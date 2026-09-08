"""ค่าตั้งต้นและกฎที่ใช้ร่วมกันในบอท."""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))



# 1. เชื่อมต่อระบบ
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
LINE_CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")

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

VECTOR_MATCH_THRESHOLD = 0.65
DIRECT_SCAM_THRESHOLD = 92.0
LLM_WITHOUT_TRIGGER_THRESHOLD = 85.0



SAFE_WORDS = {
    "สวัสดี", "สวัสดีครับ", "สวัสดีค่ะ", "ดีครับ", "ดีค่ะ", 
    "หวัดดี", "ฮัลโหล", "hi", "hello", "ok", "โอเค", "555", 
    "คับ", "ครับ", "ค่ะ", "โอนแล้ว", "โอนแล้วนะ", "โอนไปแล้วนะ",
    "กินข้าวยัง", "ถึงไหนแล้ว", "เค", "ขอบคุณ", "ขอบคุณครับ", "ขอบคุณค่ะ"
}

SCAM_TRIGGERS = [
    "อนุมัติ", "ดอกเบี้ย", "กู้", "รับเงิน", "รายได้", "โอนมัดจำ", 
    "ลิงก์", "เครดิต", "พัสดุ", "คลิก", "ภารกิจ", "ออเดอร์", "แอดไลน์", "ดาวน์"
]
