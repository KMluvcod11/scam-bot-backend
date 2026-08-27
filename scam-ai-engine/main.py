import os
import json
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai

# โหลดค่าจากไฟล์ .env
load_dotenv()

# ตั้งค่า Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# สร้างแอป FastAPI
app = FastAPI(title="Scam Detector AI Engine")

# กำหนดโครงสร้างข้อมูลที่รับเข้ามา
class MessageRequest(BaseModel):
    message: str

# ใช้โมเดลเจเนอเรชันใหม่ล่าสุด (อัปเดตปี 2026)
model = genai.GenerativeModel('gemini-flash-lite-latest')

@app.get("/")
def health_check():
    return {"status": "ok", "service": "Scam Detector AI Engine with Gemini is running"}

@app.post("/api/analyze")
def analyze_message(req: MessageRequest):
    text = req.message
    print(f" ได้รับข้อความจาก Node.js: {text}")
    
    # ย้ายคำสั่งวิเคราะห์มารวมใน Prompt
    prompt = f"""
    คุณคือผู้เชี่ยวชาญด้านความปลอดภัยไซเบอร์ หน้าที่ของคุณคือวิเคราะห์ข้อความแชทภาษาไทย ว่าเป็นข้อความหลอกลวง (Scam), สแปม (Spam), หรือฟิชชิ่ง (Phishing) หรือไม่
    ให้วิเคราะห์จาก: การหลอกให้กดลิงก์, การเสนอเงินกู้, การข่มขู่, การแอบอ้างเป็นเจ้าหน้าที่, หรือการชวนเล่นพนันออนไลน์
    
    คุณต้องตอบกลับมาเป็น JSON format ที่ถูกต้องเท่านั้น ห้ามพิมพ์ข้อความอื่นนอกจาก JSON:
    {{
      "is_scam": true หรือ false,
      "risk_level": "High", "Medium", "Low", หรือ "None",
      "reason": "อธิบายเหตุผลสั้นๆ 1-2 ประโยค (ภาษาไทย)"
    }}
    
    ข้อความที่ต้องวิเคราะห์: "{text}"
    """
    
    try:
        response = model.generate_content(prompt)
        
        # คลีนข้อความเผื่อโมเดลครอบ Markdown มาให้
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        result_data = json.loads(clean_text)
        
        result_data["original_message"] = text
        print(f" ผลการวิเคราะห์จาก Gemini: {result_data}")
        return result_data

    except Exception as e:
        print(f" Error: {e}")
        return {
            "is_scam": False,
            "risk_level": "Unknown",
            "reason": "ไม่สามารถวิเคราะห์ข้อความได้ในขณะนี้",
            "original_message": text
        }