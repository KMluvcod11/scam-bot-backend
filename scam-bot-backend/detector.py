"""ลำดับการวิเคราะห์: กรองข้อความ → ค้นหาเวกเตอร์ → ตัดสินด้วยกฎหรือ LLM."""
# 1. นำเข้าเครื่องมือและค่าตั้งต้นจาก config.py
import json
import math
import re
from google import genai
from google.genai import types
from supabase import create_client
from supabase.client import ClientOptions
from httpx import TimeoutException
from bot_observability import log as print, timed_call
from config import (
    GEMINI_KEY, SUPABASE_URL, SUPABASE_KEY, SAFE_WORDS, SCAM_TRIGGERS,
    VECTOR_MATCH_THRESHOLD, DIRECT_SCAM_THRESHOLD, LLM_WITHOUT_TRIGGER_THRESHOLD,
)

# 2. สร้าง client สำหรับเรียก Gemini และ Supabase
# จำกัดเวลารอเครือข่ายต่อคำขอ ไม่ใช่เวลารวมทั้งข้อความ
# Gemini ใช้ ms; ปิด retry ภายใน SDK เพื่อไม่ยืดเวลารอเงียบ ๆ
client = genai.Client(api_key=GEMINI_KEY, http_options=types.HttpOptions(
    timeout=20_000, retry_options=types.HttpRetryOptions(attempts=1),
))
supabase = create_client(SUPABASE_URL, SUPABASE_KEY,
                         options=ClientOptions(postgrest_client_timeout=10))


class DetectionUnavailable(Exception):
    """ระบุขั้นตอนที่ตรวจไม่ได้ โดยไม่เก็บข้อความ error ดิบจากบริการภายนอก."""
    def __init__(self, stage: str, error_type: str):
        self.stage = stage
        self.error_type = error_type
        super().__init__(stage)


# 3. รับข้อความจาก main.py → กรอง → วิเคราะห์ → คืนผลว่าจะเตือนหรือไม่
# is_scam=False หมายถึงไม่แจ้งเตือนตามกฎ ไม่ใช่รับประกันว่าปลอดภัย
def analyze_message(text: str) -> dict:
    clean_text = text.strip().lower()

    # 3.1 ข้ามคำทั่วไป/ข้อความไม่เกิน 25 ตัวอักษรตามกฎเดิม
    # ข้อจำกัด: ความสั้นไม่ได้รับประกันความปลอดภัย
    if clean_text in SAFE_WORDS or len(clean_text) <= 25:
        print(f"👉 [STAGE 1: BYPASS] ข้อความสั้น/คำทั่วไป (<= 25 ตัวอักษร)")
        return {"is_scam": False}

    try:
        similarity_percent, matched_label = find_similarity(text)
    except DetectionUnavailable as error:
        # None = ยังตัดสินไม่ได้ ต่างจาก False ที่เป็นผลไม่แจ้งเตือนตามกฎ
        print(f"[CHECK ERROR] stage={error.stage} type={error.error_type}")
        return {"status": "error", "is_scam": None, "error_stage": error.stage}

    has_trigger = any(kw in text for kw in SCAM_TRIGGERS)

    # 3.2 เตือนจาก Vector เฉพาะเมื่อแมตช์ spam; คะแนน ham ไม่ใช่หลักฐาน Scam
    if matched_label == "spam" and similarity_percent >= DIRECT_SCAM_THRESHOLD:
        print(f"🎯 [STAGE 2: MATCH] Similarity >= {DIRECT_SCAM_THRESHOLD}% -> เข้าเกณฑ์เตือนจาก Vector ไม่เรียก LLM")
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
        print(f"🎯 [STAGE 2: PASS] มีคีย์เวิร์ดแต่ Similarity ต่ำ (< 65%) -> ไม่เข้าเกณฑ์เรียก LLM")
        return {"is_scam": False}

    # 3.5 ส่งให้ LLM เมื่อมีคำบ่งชี้และคะแนน >=65 หรือไม่มีคำบ่งชี้แต่คะแนน >=85
    print(f"🤖 [STAGE 3: LLM] เข้าข่ายเสี่ยง -> ส่งต่อให้ Gemini วิเคราะห์บริบท")

    return analyze_with_llm(text, similarity_percent, matched_label)


# 4. ค้นหาตัวอย่างใกล้เคียง: text → embedding 768 มิติ → RPC match_scam → คะแนน
# ฟังก์ชันนี้ค้นข้อมูลเท่านั้น ไม่เพิ่มข้อความใหม่ลงฐานข้อมูล
def find_similarity(text: str) -> tuple[float, str | None]:
    """คืน (คะแนน, label) ของรายการที่ใกล้ที่สุด; ไม่พบคืน (0, None)."""
    # แปลงข้อความเป็นชุดตัวเลข 768 ค่า เพื่อใช้ค้นหาความคล้าย
    try:
        embed_resp = timed_call("embedding", client.models.embed_content,
            model="gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(
                task_type="retrieval_document",
                output_dimensionality=768
            )
        )
        query_vector = embed_resp.embeddings[0].values
        if not query_vector:
            raise ValueError("Missing embedding")
    except Exception as error:
        raise DetectionUnavailable("embedding", type(error).__name__) from None

    # เรียก match_scam ในฐานข้อมูล ขอผล 1 รายการที่ผ่านเกณฑ์จาก config
    try:
        res = timed_call("vector_db", supabase.rpc(
            'match_scam',
            {
                'query_embedding': query_vector,
                'match_threshold': VECTOR_MATCH_THRESHOLD,
                'match_count': 1,
            }
        ).execute)

        # [] คือค้นสำเร็จแต่ไม่พบ; ข้อมูลผิดรูปแบบต้องไม่ถือเป็นผลค้นหา 0%
        if not isinstance(res.data, list):
            raise ValueError("Invalid search response")
        similarity_percent = 0.0
        matched_text = ""
        matched_label = None
        if res.data:
            score = res.data[0]['similarity']
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("Invalid similarity")
            similarity_percent = round(score * 100, 2)
            matched_text = res.data[0]['thai_text']
            matched_label = res.data[0].get('label')
            if matched_label not in ("ham", "spam"):
                raise ValueError("Missing or unsupported label")
            if not isinstance(matched_text, str):
                raise ValueError("Invalid matched text")
    except Exception as error:
        raise DetectionUnavailable("vector_db", type(error).__name__) from None

    print(f"📊 [STAGE 2: VECTOR DB] ความคล้ายคลึง: {similarity_percent}% | label={matched_label} | แมตช์กับ: '{matched_text}'")

    return similarity_percent, matched_label


# เกณฑ์รูปแบบเหตุผล ไม่ใช่เกณฑ์ตัดสิน Scam; len() นับตามอักขระ Unicode ของ Python
MAX_REASON_LENGTH = 500
MAX_IDENTICAL_RUN = 20

# 5. ตรวจชนิดและค่าของคำตอบ AI ก่อนใช้ ไม่ใช่ตรวจความถูกต้องของการตัดสิน
def validate_llm_result(result: object) -> dict:
    """รับ JSON ที่แปลงแล้ว; คืน dict เดิมเมื่อถูกต้อง หรือยก ValueError เพื่อลองโมเดลถัดไป."""
    if not isinstance(result, dict):
        raise ValueError("LLM response must be a JSON object")
    # ต้องเป็น True/False จริง ไม่รับข้อความ "false" หรือเลข 0/1
    if type(result.get("is_scam")) is not bool:
        raise ValueError("LLM is_scam must be a boolean")
    risk_level = result.get("risk_level")
    if not isinstance(risk_level, str) or risk_level not in ("low", "medium", "high"):
        raise ValueError("LLM risk_level must be low, medium, or high")
    reason = result.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("LLM reason must be a non-empty string")
    # ปฏิเสธทั้งคำตอบ ไม่ตัดทิ้งบางส่วน เพราะเหตุผลที่เสียอาจทำให้ความหมายผิด
    if len(reason) > MAX_REASON_LENGTH:
        raise ValueError("LLM reason is too long")
    # เช่น เลข 0 ติดกัน 20 ตัว; ตรวจทั้งตัวเลข ตัวอักษร และช่องว่าง
    if re.search(r"(.)\1{" + str(MAX_IDENTICAL_RUN - 1) + r",}", reason, re.DOTALL):
        raise ValueError("LLM reason contains excessive repeated characters")
    return result


# 6. ส่งข้อความให้ LLM วิเคราะห์ → ตรวจคำตอบ → คืนผลให้ main.py
def analyze_with_llm(text: str, similarity_percent: float, matched_label: str | None = None) -> dict:
    """ลองโมเดลตามลำดับ; ใช้กฎสำรองเมื่อทุกโมเดลล้มเหลว."""
    # 6.1 เตรียมคำสั่งให้ AI: ข้อความที่ตรวจ เกณฑ์ และรูปแบบคำตอบ
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

    # 6.2 ลองโมเดลถัดไปเมื่อเรียก API ไม่สำเร็จ, JSON เสีย หรือฟิลด์ผิดรูปแบบ
    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]

    for model_name in models_to_try:
        try:
            llm_response = timed_call(f"llm:{model_name}", client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            # แปลง JSON เป็น dict แล้วตรวจว่าฟิลด์ครบและมีค่าที่ใช้งานได้
            parsed = validate_llm_result(json.loads(llm_response.text))
            print(f"📝 [LLM RESULT ({model_name})] is_scam={parsed.get('is_scam')} | reason={parsed.get('reason')}")
            return parsed
        except (TimeoutException, TimeoutError) as error:
            # หมดเวลา = ตรวจไม่ได้ ไม่ใช้คะแนนสำรองมาตัดสินแทน
            print(f"[CHECK ERROR] stage=llm type={type(error).__name__}")
            return {"status": "error", "is_scam": None, "error_stage": "llm"}
        except Exception as e:
            # ไม่พิมพ์ exception ดิบ เพราะอาจมี URL, คีย์ หรือข้อมูลคำขอ
            print(f"[LLM FAILOVER] stage=llm model={model_name} type={type(e).__name__}")
            continue

    # 6.3 ทุกโมเดลล้มเหลว: เตือน medium เฉพาะ spam >=80; ham ไม่ใช้คะแนนเตือน
    print("[FALLBACK] stage=llm ใช้กฎสำรองจากคะแนนฐานข้อมูล ไม่ใช่ผลยืนยันจาก LLM")
    if matched_label == "spam" and similarity_percent >= 80.0:
        return {
            "status": "fallback",
            "is_scam": True,
            "risk_level": "medium",
            "reason": f"รูปแบบข้อความใกล้เคียงข้อความหลอกลวงในฐานข้อมูล {similarity_percent}% (ระบบสำรอง)"
        }
    return {"status": "fallback", "is_scam": False}
