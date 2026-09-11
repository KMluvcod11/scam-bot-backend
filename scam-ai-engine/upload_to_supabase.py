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
from dotenv import load_dotenv

# 2. รับค่าการเชื่อมต่อจาก environment และสร้าง client
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 3. อ่านจำนวนแถวเพื่อเลือกจุดเริ่มทำต่อ
# ข้อจำกัดเดิม: จำนวนแถวไม่ยืนยันว่าเป็นข้อมูลชุดเดียวกันหรือเรียงลำดับตรง CSV
try:
    res = supabase.table("scam_dataset").select("id", count="exact").limit(1).execute()
    uploaded_count = res.count if res.count is not None else 0
except Exception as e:
    print(f"ไม่สามารถตรวจสอบข้อมูลใน Supabase ได้: {e}")
    uploaded_count = 0

# 4. อ่านข้อมูลจาก CSV: ต้องมีคอลัมน์ thai_text และ label
df = pd.read_csv('master_thai_dataset.csv', encoding='utf-8-sig')
total_rows = len(df)

if uploaded_count >= total_rows:
    print("🎉 ข้อมูลทั้งหมดถูกอัปโหลดครบถ้วนแล้ว ไม่ต้องทำอะไรเพิ่ม!")
    sys.exit(0)

print(f"📊 ข้อมูลใน Supabase มีแล้ว: {uploaded_count} แถว")
print(f"🚀 กำลังเริ่มทำต่อจาก CSV แถวที่: {uploaded_count + 1}...")

# 5. เลือกแถวที่เหลือด้วยจำนวนข้อมูลเดิม
df_remaining = df.iloc[uploaded_count:]

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
    return response.embeddings[0].values

# 7. ประกาศขนาด batch และพื้นที่พักข้อมูลก่อน insert
batch_size = 50
records = []

# 8. ประมวลผลทีละแถว: embedding → สะสม → insert เมื่อครบ batch
# ข้อจำกัดเดิม: retry บางกรณีไม่มีจำนวนครั้งสูงสุด และ insert ซ้ำอาจเกิดข้อมูลซ้ำ
for i, row in df_remaining.iterrows():
    text = str(row['thai_text'])
    label = str(row['label'])

    while True:
        try:
            embedding = get_embedding(text)
            records.append({
                "label": label,
                "thai_text": text,
                "embedding": embedding
            })

            # 📌 ปรับเป็น 4 วินาที เพื่อรักษาสปีดไม่ให้เกิน 15 ครั้ง/นาที
            time.sleep(4)
            break

        except Exception as e:
            # 3. ถ้าโควตา 429 เต็ม ให้เซฟข้อมูลที่ค้างอยู่แล้วหยุดโปรแกรม
            if "429" in str(e):
                print(f"\n⚠️ โควตา API ของคีย์นี้เต็มแล้ว! (ติดที่แถว {i+1})")
                if records:
                    print("💾 กำลังบันทึกข้อมูลที่ทำเสร็จแล้วขึ้น Supabase...")
                    try:
                        supabase.table('scam_dataset').insert(records).execute()
                        print(f"✅ บันทึกข้อมูลที่ค้างอยู่สำเร็จ!")
                    except Exception as insert_e:
                        print(f"❌ บันทึกไม่สำเร็จ: {insert_e}")

                print("\n🛑 สคริปต์หยุดทำงานชั่วคราว:")
                print("👉 กรุณาไปเปลี่ยน GEMINI_API_KEY (ใช้อีเมลอื่น) ในไฟล์ .env")
                print("👉 จากนั้นเซฟไฟล์ .env แล้วกดรันสคริปต์นี้ใหม่อีกครั้ง ระบบจะทำต่ออัตโนมัติ!")
                sys.exit(0)

            else:
                print(f"❌ Error แถวที่ {i+1}: {e} (ลองใหม่ใน 5 วิ)")
                time.sleep(5)

    # 4. เมื่อสะสมครบ 50 แถว หรือถึงแถวสุดท้าย ให้อัปโหลดขึ้น Supabase ตามปกติ
    if len(records) >= batch_size or i == df.index[-1]:
        while True:
            try:
                supabase.table('scam_dataset').insert(records).execute()
                print(f"✅ อัปโหลดสำเร็จถึงแถวที่ {i+1} / {total_rows}")
                records = []
                break
            except Exception as e:
                print(f"❌ Supabase Insert Error: {e} (กำลังพยายามใหม่ใน 5 วิ)")
                time.sleep(5)

print("\n🎉 นำเข้าข้อมูลสู่ Supabase ทั้งหมดสำเร็จ 100%!")
