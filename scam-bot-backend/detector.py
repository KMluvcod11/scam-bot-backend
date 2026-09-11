"""ลำดับการวิเคราะห์: กรองข้อความ → ค้นหาเวกเตอร์ → ตัดสินด้วยกฎหรือ LLM."""
# 1. นำเข้า SDK และค่าตั้งต้น
import json
from google import genai
from google.genai import types
from supabase import create_client
from config import (
    GEMINI_KEY, SUPABASE_URL, SUPABASE_KEY, SAFE_WORDS, SCAM_TRIGGERS,
    VECTOR_MATCH_THRESHOLD, DIRECT_SCAM_THRESHOLD, LLM_WITHOUT_TRIGGER_THRESHOLD,
)

# 2. สร้าง client สำหรับเรียก Gemini และ Supabase
client = genai.Client(api_key=GEMINI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# 3. ฟังก์ชันหลัก: รับ text (str) → คืน dict; is_scam=False หมายถึงไม่แจ้งเตือนตามกฎ
# อ่านฟังก์ชันนี้ก่อน แล้วตามไป find_similarity และ analyze_with_llm
def analyze_message(text: str) -> dict:
    clean_text = text.strip().lower()

    # 3.1 ข้ามคำทั่วไป/ข้อความไม่เกิน 25 ตัวอักษรตามกฎเดิม
    # ข้อจำกัด: ความสั้นไม่ได้รับประกันความปลอดภัย
    if clean_text in SAFE_WORDS or len(clean_text) <= 25:
        print(f"👉 [STAGE 1: BYPASS] ข้อความสั้น/คำทั่วไป (<= 25 ตัวอักษร)")
        return {"is_scam": False}

    similarity_percent = find_similarity(text)

    has_trigger = any(kw in text for kw in SCAM_TRIGGERS)

    # 3.2 คะแนนตั้งแต่ 92%: แจ้งเตือนทันทีตามกฎ (คล้ายมาก ไม่ได้แปลว่าตรงเป๊ะ)
    if similarity_percent >= DIRECT_SCAM_THRESHOLD:
        print(f"🎯 [STAGE 2: MATCH] แมตช์ฐานข้อมูลระดับสูงมาก (>= 92%) -> แจ้ง Scam ทันที")
        return {
            "is_scam": True,
            "risk_level": "high",
            "reason": "ตรงกับรูปแบบข้อความมิจฉาชีพในฐานข้อมูลอย่างมีนัยสำคัญ"
        }

    # 3.3 ไม่มี keyword และคะแนนต่ำกว่า 85%: ไม่เรียก LLM
    if not has_trigger and similarity_percent < LLM_WITHOUT_TRIGGER_THRESHOLD:
        print(f"🎯 [STAGE 2: PASS] ไม่พบคีย์เวิร์ดและ Similarity ต่ำกว่า {LLM_WITHOUT_TRIGGER_THRESHOLD}% ({similarity_percent}%) -> ไม่เรียก LLM")
        return {"is_scam": False}

    # 3.4 คะแนนต่ำกว่า 65%: ไม่แจ้งเตือนตามกฎเดิม
    if similarity_percent < 65.0:
        print(f"🎯 [STAGE 2: PASS] มีคีย์เวิร์ดแต่ Similarity ต่ำ (< 65%) -> ปลอดภัย ไม่เรียก LLM")
        return {"is_scam": False}

    # 3.5 กรณีที่เหลือ: มี keyword กับคะแนน >=65 หรือไม่มี keyword กับคะแนน >=85
    print(f"🤖 [STAGE 3: LLM] เข้าข่ายเสี่ยง -> ส่งต่อให้ Gemini วิเคราะห์บริบท")

    return analyze_with_llm(text, similarity_percent)


# 4. ค้นหาตัวอย่างใกล้เคียง: text → embedding 768 มิติ → RPC match_scam → คะแนน
# ฟังก์ชันนี้ค้นข้อมูลเท่านั้น ไม่เพิ่มข้อความใหม่ลงฐานข้อมูล
def find_similarity(text: str) -> float:
    """สร้าง embedding และคืนคะแนนความคล้ายคลึง (ไม่พบผลคืน 0)."""
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
        {
            'query_embedding': query_vector,
            'match_threshold': VECTOR_MATCH_THRESHOLD,
            'match_count': 1,
        }
    ).execute()

    similarity_percent = 0.0
    matched_text = ""
    if res.data and len(res.data) > 0:
        similarity_percent = round(res.data[0]['similarity'] * 100, 2)
        matched_text = res.data[0]['thai_text']

    print(f"📊 [STAGE 2: VECTOR DB] ความคล้ายคลึง: {similarity_percent}% | แมตช์กับ: '{matched_text}'")

    return similarity_percent


# 5. วิเคราะห์บริบท: text และคะแนน → ลอง LLM ตามลำดับ → คืนผล JSON ที่แปลงเป็น dict
def analyze_with_llm(text: str, similarity_percent: float) -> dict:
    """ลองโมเดลตามลำดับ; ใช้กฎสำรองเมื่อทุกโมเดลล้มเหลว."""
    # 5.1 ประกาศ prompt: ระบุข้อความ เกณฑ์ และฟิลด์ผลลัพธ์ที่ต้องการ
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

    # 5.2 ลองโมเดลถัดไปเมื่อการเรียกหรือการอ่าน JSON ของโมเดลก่อนหน้าล้มเหลว
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

    # 5.3 ทุกโมเดลล้มเหลว: >=80 เตือน medium; ต่ำกว่านั้นไม่เตือนตามกฎเดิม
    if similarity_percent >= 80.0:
        return {
            "is_scam": True,
            "risk_level": "medium",
            "reason": f"รูปแบบข้อความใกล้เคียงข้อความหลอกลวงในฐานข้อมูล {similarity_percent}% (ระบบสำรอง)"
        }
    return {"is_scam": False}
