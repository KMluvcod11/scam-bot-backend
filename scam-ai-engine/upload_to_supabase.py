# หน้าที่: เตรียมฐานตัวอย่างจาก CSV โดยสร้าง embedding และเขียนลง Supabase
# เรียก main() หรือรันไฟล์จึงเขียนฐานข้อมูล; import อย่างเดียวไม่เริ่มงาน

# 1. นำเข้าเครื่องมือ
import pandas as pd
from google import genai
from google.genai import types
from supabase import create_client
import time
import os
import argparse
import math
from pathlib import Path
from dotenv import load_dotenv

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

# รับ client อย่างชัดเจน ไม่พึ่ง client ที่สร้างเมื่อ import
def get_embedding(text, client):
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

def main(argv=None):
    """อ่าน CSV → เลือกแถวใหม่ → embedding → insert; คืน exit code."""
    parser = argparse.ArgumentParser(description='Upload new CSV texts to Supabase')
    parser.add_argument('--limit', type=int, help='Maximum new rows to upload this run')
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error('--limit must be positive')
    load_dotenv(Path(__file__).with_name('.env'))
    try:
        client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'), http_options=types.HttpOptions(
            timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))
        key = os.getenv('SUPABASE_HISTORY_KEY') or os.getenv('SUPABASE_KEY')
        db = create_client(os.getenv('SUPABASE_URL'), key)
        df = pd.read_csv(Path(__file__).with_name('linebot_1000word.csv'), encoding='utf-8-sig')
        df_remaining = select_new_rows(df, db)
    except Exception as error:
        print(f"หยุด: ตรวจ CSV/ข้อมูลเดิมไม่สำเร็จ type={type(error).__name__}")
        return 1

    if df_remaining.empty:
        print('ไม่มีข้อความใหม่ที่ต้องอัปโหลด')
        return 0
    print(f'CSV {len(df)} แถว / ข้อความใหม่ {len(df_remaining)} แถว')
    if args.limit is not None:
        df_remaining = df_remaining.head(args.limit)
    print(f'รอบนี้อัปโหลดไม่เกิน {len(df_remaining)} แถว', flush=True)

    # รันครั้งละหนึ่ง process; ถ้าเขียนไม่สำเร็จต้องตรวจฐานก่อนรันซ้ำ
    batch_size = 50
    records = []
    uploaded = 0
    for index, row in df_remaining.iterrows():
        try:
            text = str(row['thai_text'])
            embedding = get_embedding(text, client)
            records.append({'label': str(row['label']), 'thai_text': text, 'embedding': embedding})
            time.sleep(4)
        except Exception as error:
            print(f'หยุด: embedding แถว CSV {index+1} type={type(error).__name__}; ยังไม่บันทึกชุดค้าง {len(records)} แถว')
            return 1

        if len(records) >= batch_size or index == df_remaining.index[-1]:
            try:
                db.table('scam_dataset').insert(records).execute()
                uploaded += len(records)
                print(f'อัปโหลดรอบนี้ {uploaded}/{len(df_remaining)} แถว', flush=True)
                records = []
            except Exception as error:
                print(f'หยุด: insert type={type(error).__name__}; ต้องตรวจฐานก่อนรันซ้ำ ไม่ retry อัตโนมัติ')
                return 1
    print(f'เสร็จเฉพาะรอบนี้: {uploaded} แถว')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
