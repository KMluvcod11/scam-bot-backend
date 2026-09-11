"""ค่าตั้งต้นและกฎที่ใช้ร่วมกันในบอท."""
# 1. นำเข้าเครื่องมืออ่านไฟล์และ environment variables
from pathlib import Path
import os
from dotenv import load_dotenv

# 2. อ่าน .env ที่อยู่ข้างไฟล์นี้; environment ที่ตั้งไว้แล้วมีลำดับก่อน
load_dotenv(Path(__file__).with_name(".env"))


# 3. รับค่าการเชื่อมต่อ: เก็บ secret ใน .env ไม่เขียนค่าจริงใน source code
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
LINE_CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")

# 4. ตรวจค่าที่จำเป็นก่อนเริ่มแอป; error แสดงเฉพาะชื่อ ไม่แสดง secret
REQUIRED_ENVIRONMENT_VARIABLES = {
    "GEMINI_API_KEY": GEMINI_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "CHANNEL_SECRET": LINE_CHANNEL_SECRET,
    "CHANNEL_ACCESS_TOKEN": LINE_CHANNEL_ACCESS_TOKEN,
}
missing_environment_variables = [
    name for name, value in REQUIRED_ENVIRONMENT_VARIABLES.items() if not value
]
if missing_environment_variables:
    raise RuntimeError(
        "Missing required environment variables: "
        + ", ".join(missing_environment_variables)
    )

# 5. เกณฑ์: RPC ใช้คะแนน 0–1 ส่วนการตัดสินใน Python ใช้ 0–100
# ตัวเลขเหล่านี้เป็นเกณฑ์การทำงาน ไม่ใช่ค่าความแม่นยำที่วัดแล้ว
VECTOR_MATCH_THRESHOLD = 0.65
DIRECT_SCAM_THRESHOLD = 92.0
LLM_WITHOUT_TRIGGER_THRESHOLD = 85.0


# 6. คำที่ข้ามการวิเคราะห์เมื่อเทียบตรงกันหลัง strip/lower
SAFE_WORDS = {
    "สวัสดี", "สวัสดีครับ", "สวัสดีค่ะ", "ดีครับ", "ดีค่ะ",
    "หวัดดี", "ฮัลโหล", "hi", "hello", "ok", "โอเค", "555",
    "คับ", "ครับ", "ค่ะ", "โอนแล้ว", "โอนแล้วนะ", "โอนไปแล้วนะ",
    "กินข้าวยัง", "ถึงไหนแล้ว", "เค", "ขอบคุณ", "ขอบคุณครับ", "ขอบคุณค่ะ"
}

# 7. คำบ่งชี้: ใช้ร่วมกับ similarity เพื่อเลือกว่าจะเรียก LLM หรือไม่
SCAM_TRIGGERS = [
    "อนุมัติ", "ดอกเบี้ย", "กู้", "รับเงิน", "รายได้", "โอนมัดจำ",
    "ลิงก์", "เครดิต", "พัสดุ", "คลิก", "ภารกิจ", "ออเดอร์", "แอดไลน์", "ดาวน์"
]
