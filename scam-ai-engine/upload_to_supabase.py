# หน้าที่: เตรียมฐานตัวอย่างจาก CSV โดยสร้าง embedding และเขียนลง Supabase
# การรันหรือ import ไฟล์นี้มีผลเขียนฐานข้อมูลจริง ไม่ใช่ส่วนรับ webhook

# 1. นำเข้าเครื่องมือ
import pandas as pd
from google import genai
from google.genai import types
from supabase import create_client, Client
import time
import os
import sys
import argparse
import math
from pathlib import Path
from dotenv import load_dotenv

# 2. รับค่าการเชื่อมต่อจาก environment และสร้าง client
parser = argparse.ArgumentParser(description='Upload new CSV texts to Supabase')
parser.add_argument('--limit', type=int, help='Maximum new rows to upload this run')
args = parser.parse_args()
if args.limit is not None and args.limit <= 0:
    parser.error('--limit must be positive')
load_dotenv(Path(__file__).with_name('.env'))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_HISTORY_KEY") or os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(
    timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# อ่านทุกหน้า ไม่ใช้จำนวนแถวเดิมเป็นตำแหน่งใน CSV
def select_new_rows(df, db):
    if not {'thai_text', 'label'}.issubset(df.columns):
        raise ValueError('Missing CSV columns')
    if df[['thai_text', 'label']].isna().any().any():
        raise ValueError('Empty CSV values')
    if not df['label'].isin(['ham', 'spam']).all() or not df['thai_text'].str.strip().astype(bool).all():
        raise ValueError('Invalid CSV values')
    if (df.groupby('thai_text')['label'].nunique() > 1).any():
        raise ValueError('Conflicting CSV labels')
    # ponytail: read labels/text into memory; use indexed lookups if dataset outgrows memory.
    existing = {}
    offset = 0
    total = None
    while True:
        res = db.table('scam_dataset').select('id,thai_text,label', count='exact').order('id').range(offset, offset + 499).execute()
        if res.count is None or (total is not None and total != res.count):
            raise ValueError('Database changed or count unavailable')
        total = res.count
        if not res.data:
            if offset != total:
                raise ValueError('Incomplete database read')
            break
        for row in res.data:
            existing.setdefault(row['thai_text'], set()).add(row['label'])
        offset += len(res.data)
        if offset == total:
            break
        if offset > total:
            raise ValueError('Invalid database count')
    for row in df.itertuples():
        if row.thai_text in existing and existing[row.thai_text] != {row.label}:
            raise ValueError('Existing text has conflicting label; review before upload')
    return df.loc[~df['thai_text'].isin(existing)].drop_duplicates('thai_text')

# 3. ตรวจข้อมูลเดิมก่อนสร้าง embedding; อ่านไม่สำเร็จต้องหยุด
try:
    df = pd.read_csv(Path(__file__).with_name('linebot_1000word.csv'), encoding='utf-8-sig')
    df_remaining = select_new_rows(df, supabase)
except Exception as e:
    print(f"หยุด: ตรวจ CSV/ข้อมูลเดิมไม่สำเร็จ type={type(e).__name__}")
    sys.exit(1)

total_rows = len(df)

if df_remaining.empty:
    print("ไม่มีข้อความใหม่ที่ต้องอัปโหลด")
    sys.exit(0)

print(f"CSV {total_rows} แถว / ข้อความใหม่ {len(df_remaining)} แถว")
if args.limit is not None:
    df_remaining = df_remaining.head(args.limit)
print(f"รอบนี้อัปโหลดไม่เกิน {len(df_remaining)} แถว", flush=True)

# 6. ฟังก์ชันแปลงข้อความ: รับ text → คืนรายการตัวเลขเวกเตอร์ 768 มิติ
def get_embedding(text):
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(
            task_type="retrieval_document",
            output_dimensionality=768
        )
    )
    values = response.embeddings[0].values
    if len(values) != 768 or not all(math.isfinite(v) for v in values):
        raise ValueError('Invalid embedding')
    return values

# 7. ประกาศขนาด batch และพื้นที่พักข้อมูลก่อน insert
batch_size = 50
records = []

# 8. ประมวลผลทีละแถว: embedding → สะสม → insert เมื่อครบ batch
# Run only one uploader at a time. Stop on ambiguous writes; inspect before rerunning.
uploaded = 0
for i, row in df_remaining.iterrows():
    text = str(row['thai_text'])
    label = str(row['label'])

    try:
        embedding = get_embedding(text)
        records.append({'label': label, 'thai_text': text, 'embedding': embedding})
        time.sleep(4)
    except Exception as e:
        print(f"หยุด: embedding แถว CSV {i+1} type={type(e).__name__}; ยังไม่บันทึกชุดค้าง {len(records)} แถว")
        sys.exit(1)

    # 4. เมื่อสะสมครบ 50 แถว หรือถึงแถวสุดท้าย ให้อัปโหลดขึ้น Supabase ตามปกติ
    if len(records) >= batch_size or i == df_remaining.index[-1]:
        try:
            supabase.table('scam_dataset').insert(records).execute()
            uploaded += len(records)
            print(f"อัปโหลดรอบนี้ {uploaded}/{len(df_remaining)} แถว", flush=True)
            records = []
        except Exception as e:
            print(f"หยุด: insert type={type(e).__name__}; ต้องตรวจฐานก่อนรันซ้ำ ไม่ retry อัตโนมัติ")
            sys.exit(1)

print(f"เสร็จเฉพาะรอบนี้: {uploaded} แถว")
