import os
import json
import requests
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types
from supabase import create_client, Client
from dotenv import load_dotenv

from linebot.v3.webhook import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

load_dotenv()

app = FastAPI(title="Scam Detection AI Bot")

# 1. เชื่อมต่อระบบ
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
LINE_CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")

client = genai.Client(api_key=GEMINI_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
parser = WebhookParser(LINE_CHANNEL_SECRET)

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

# 2. ฟังก์ชันตอบกลับ LINE
def reply_to_line(reply_token: str, message_text: str):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message_text}]
    }
    try:
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
    except Exception as e:
        print(f"❌ [LINE API ERROR] ส่งข้อความไม่สำเร็จ: {e}")

# 3. ฟังก์ชันวิเคราะห์ข้อความ (Cascading Pipeline)
def analyze_message(text: str) -> dict:
    clean_text = text.strip().lower()

    # ด่าน 1: Fast Filter (คำสั้นและ Whitelist)
    if clean_text in SAFE_WORDS or len(clean_text) <= 25:
        print(f"👉 [STAGE 1: BYPASS] ข้อความสั้น/คำทั่วไป (<= 25 ตัวอักษร)")
        return {"is_scam": False}

    # แปลงเวกเตอร์
    embed_resp = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(
            task_type="retrieval_document",
            output_dimensionality=768
        )
    )
    query_vector = embed_resp.embeddings[0].values

    # ค้นหาใน Supabase ด้วย Threshold ที่เข้มขึ้น
    res = supabase.rpc(
        'match_scam',
        {'query_embedding': query_vector, 'match_threshold': 0.65, 'match_count': 1}
    ).execute()

    similarity_percent = 0.0
    matched_text = ""
    if res.data and len(res.data) > 0:
        similarity_percent = round(res.data[0]['similarity'] * 100, 2)
        matched_text = res.data[0]['thai_text']

    print(f"📊 [STAGE 2: VECTOR DB] ความคล้ายคลึง: {similarity_percent}% | แมตช์กับ: '{matched_text}'")

    has_trigger = any(kw in text for kw in SCAM_TRIGGERS)

    # ด่าน 2: กรองข้อความที่ไม่ถึงเกณฑ์ความเสี่ยง
    if similarity_percent < 70.0 and not has_trigger:
        print(f"🎯 [STAGE 2: PASS] Similarity ต่ำและไม่มีคีย์เวิร์ดเสี่ยง -> ปลอดภัย ไม่เรียก LLM")
        return {"is_scam": False}

    # กรณีฐานข้อมูลเวกเตอร์ตรงสูงมาก (>= 92%) ตัดสินทันทีโดยไม่เปลือง LLM
    if similarity_percent >= 92.0:
        print(f"🎯 [STAGE 2: MATCH] แมตช์ฐานข้อมูลระดับสูงมาก (>= 92%) -> แจ้ง Scam ทันที")
        return {
            "is_scam": True,
            "risk_level": "high",
            "reason": "ตรงกับรูปแบบข้อความมิจฉาชีพในฐานข้อมูลอย่างมีนัยสำคัญ"
        }

    # ด่าน 3: ส่ง LLM วิเคราะห์บริบทเชิงลึก
    print(f"🤖 [STAGE 3: LLM] ข้อความมีความเสี่ยงก้ำกึ่ง -> ส่งต่อให้ Gemini วิเคราะห์บริบท")
    prompt = f"""
    วิเคราะห์ข้อความต่อไปนี้อย่างรอบคอบ:
    ข้อความ: "{text}"
    
    เกณฑ์การตัดสิน:
    1. ถ้าเป็นการสนทนาทั่วไป นัดหมาย โอนเงินคืนเพื่อน ซื้อขาย หรือคุยเล่นในกลุ่ม ให้ is_scam = false, risk_level = 'low'
    2. ระบุเป็น is_scam = true เฉพาะข้อความที่เจตนาหลอกลวงชัดเจน: ชวนทำงานออนไลน์, เงินกู้นอกระบบ, เว็บพนัน, ลิงก์ฟิชชิง, เร่งโอนมัดจำจองหอพัก
    
    ตอบกลับในรูปแบบ JSON เท่านั้น:
    - "is_scam": true หรือ false
    - "risk_level": "low", "medium", หรือ "high"
    - "reason": คำอธิบายสั้นๆ ภาษาไทย
    """

    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]

    for model_name in models_to_try:
        try:
            llm_response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            parsed = json.loads(llm_response.text)
            print(f"📝 [LLM RESULT ({model_name})] is_scam={parsed.get('is_scam')} | reason={parsed.get('reason')}")
            return parsed
        except Exception as e:
            print(f"⚠️ [LLM FAILOVER] {model_name} เกิดข้อผิดพลาด ({e})")
            continue

    # หาก LLM ขัดข้องทั้งหมด ใช้เกณฑ์คะแนนเวกเตอร์สำรอง
    if similarity_percent >= 80.0:
        return {
            "is_scam": True,
            "risk_level": "medium",
            "reason": f"รูปแบบข้อความใกล้เคียงข้อความหลอกลวงในฐานข้อมูล {similarity_percent}% (ระบบสำรอง)"
        }
    return {"is_scam": False}

# 4. Webhook Routes
@app.get("/")
async def root():
    return {"status": "ok", "message": "Scam Detection LINE Bot is running!"}

@app.post("/webhook")
async def line_webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    body_text = body.decode("utf-8")

    try:
        events = parser.parse(body_text, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            user_text = event.message.text
            reply_token = event.reply_token

            print(f"\n==================== [NEW MESSAGE] ====================")
            print(f"📩 ข้อความเข้า: \"{user_text}\"")

            result = analyze_message(user_text)

            if result.get("is_scam"):
                risk_display = result.get('risk_level', 'HIGH').upper()
                reason_text = result.get('reason', 'ตรวจพบพฤติกรรมหลอกลวง')

                reply_msg = (
                    f"⚠️ [แจ้งเตือนภัยคุกคาม] ⚠️\n\n"
                    f"ข้อความนี้มีความเสี่ยงเป็นมิจฉาชีพ!\n"
                    f"• ระดับความเสี่ยง: {risk_display}\n"
                    f"• สาเหตุ: {reason_text}\n\n"
                    f"⛔ คำเตือน: อย่ากดลิงก์ หรือโอนเงินโดยเด็ดขาด"
                )
                reply_to_line(reply_token, reply_msg)
                print(f"🚀 [ACTION] แจ้งเตือนมิจฉาชีพเรียบร้อย")
            else:
                print(f"💤 [ACTION] ปลอดภัย บอทไม่ตอบแทรก")

    return JSONResponse(content="OK", status_code=200)