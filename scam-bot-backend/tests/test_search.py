# หน้าที่: สคริปต์ทดลองค้นหา Supabase จากข้อความจำลอง ไม่ใช่ automated test
# การรันหรือ import ไฟล์นี้เรียก Gemini/Supabase จริง และอาจใช้โควตา

# 1. นำเข้าเครื่องมือ
import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from dotenv import load_dotenv

# 2. โหลดค่าการเชื่อมต่อและสร้าง client
load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# 3. รับค่า: แก้ test_message เพื่อเลือกข้อความทดลอง
test_message = "ยินดีด้วยครับ คุณได้รับสิทธิ์กู้เงินฉุกเฉิน 50,000 บาท ดอกเบี้ยต่ำ คลิกลิงก์เพื่อรับสิทธิ์ด่วน"

print(f"🔍 กำลังวิเคราะห์ข้อความ: '{test_message}'")

try:
    # 1. แปลงข้อความจำลองเป็น Vector
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=test_message,
        config=types.EmbedContentConfig(task_type="retrieval_document", output_dimensionality=768)
    )
    query_vector = response.embeddings[0].values

    # 2. ค้นหาข้อความที่คล้ายกันใน Supabase
    res = supabase.rpc(
        'match_scam',
        {'query_embedding': query_vector, 'match_threshold': 0.7, 'match_count': 3}
    ).execute()

    # 4. แสดงผล Top 3; similarity คือความคล้าย ไม่ใช่ accuracy
    # ข้อความ log เดิมที่ใช้คำว่า “ปลอดภัย/ความแม่นยำ” ไม่ใช่ข้อยืนยันเชิงสถิติ
    print("\n ผลการค้นหา (Top 3 ที่คล้ายที่สุด):")
    if not res.data:
        print("ปลอดภัย: ไม่พบข้อความที่คล้ายคลึงกับสแกมเมอร์ในฐานข้อมูล")
    else:
        for idx, item in enumerate(res.data):
            percent = item['similarity'] * 100
            print(f"{idx+1}. ความแม่นยำ: {percent:.2f}% | ข้อความ: {item['thai_text'][:70]}...")

except Exception as e:
    print(f"❌ เกิดข้อผิดพลาด: {e}")
