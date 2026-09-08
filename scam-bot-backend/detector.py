"""ลำดับการวิเคราะห์: กรองข้อความ → ค้นหาเวกเตอร์ → ตัดสินด้วยกฎหรือ LLM."""
import json
from google import genai
from google.genai import types
from supabase import create_client
from config import (
    GEMINI_KEY, SUPABASE_URL, SUPABASE_KEY, SAFE_WORDS, SCAM_TRIGGERS,
    VECTOR_MATCH_THRESHOLD, DIRECT_SCAM_THRESHOLD, LLM_WITHOUT_TRIGGER_THRESHOLD,
)

client = genai.Client(api_key=GEMINI_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# 3. ฟังก์ชันวิเคราะห์ข้อความ (Cascading Pipeline)
def analyze_message(text: str) -> dict:
    clean_text = text.strip().lower()

    # ด่าน 1: Fast Filter (คำสั้นและ Whitelist)
    if clean_text in SAFE_WORDS or len(clean_text) <= 25:
        print(f"👉 [STAGE 1: BYPASS] ข้อความสั้น/คำทั่วไป (<= 25 ตัวอักษร)")
        return {"is_scam": False}

    similarity_percent = find_similarity(text)

    has_trigger = any(kw in text for kw in SCAM_TRIGGERS)

    # 1. ถ้าตรงกับฐานข้อมูลเป๊ะๆ 92% ขึ้นไป -> ตัดเป็น Scam ทันที
    if similarity_percent >= DIRECT_SCAM_THRESHOLD:
        print(f"🎯 [STAGE 2: MATCH] แมตช์ฐานข้อมูลระดับสูงมาก (>= 92%) -> แจ้ง Scam ทันที")
        return {
            "is_scam": True,
            "risk_level": "high",
            "reason": "ตรงกับรูปแบบข้อความมิจฉาชีพในฐานข้อมูลอย่างมีนัยสำคัญ"
        }

    # 2. ถ้าไม่มีคีย์เวิร์ด ให้ส่ง LLM เฉพาะกรณีที่คล้ายฐานข้อมูลมาก
    if not has_trigger and similarity_percent < LLM_WITHOUT_TRIGGER_THRESHOLD:
        print(f"🎯 [STAGE 2: PASS] ไม่พบคีย์เวิร์ดและ Similarity ต่ำกว่า {LLM_WITHOUT_TRIGGER_THRESHOLD}% ({similarity_percent}%) -> ไม่เรียก LLM")
        return {"is_scam": False}

    # 3. มีคีย์เวิร์ดเสี่ยง แต่ความคล้ายคลึงต่ำกว่า 65% -> ปลอดภัย
    if similarity_percent < 65.0:
        print(f"🎯 [STAGE 2: PASS] มีคีย์เวิร์ดแต่ Similarity ต่ำ (< 65%) -> ปลอดภัย ไม่เรียก LLM")
        return {"is_scam": False}

    # 4. มีคีย์เวิร์ดเสี่ยง หรือ Similarity สูงมาก -> ส่ง LLM วิเคราะห์บริบท
    print(f"🤖 [STAGE 3: LLM] เข้าข่ายเสี่ยง -> ส่งต่อให้ Gemini วิเคราะห์บริบท")

    return analyze_with_llm(text, similarity_percent)


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


def analyze_with_llm(text: str, similarity_percent: float) -> dict:
    """ลองโมเดลตามลำดับ; ใช้กฎสำรองเมื่อทุกโมเดลล้มเหลว."""
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
