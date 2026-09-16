"""จุดเริ่มต้น FastAPI: ตรวจลายเซ็น รับข้อความ วิเคราะห์ และตอบ LINE."""
# 1. นำเข้าเครื่องมือ: FastAPI รับ HTTP; โมดูลของเราใช้วิเคราะห์และตอบ LINE
import json
from uuid import uuid4
from bot_observability import log as print, trace_id
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from config import LINE_CHANNEL_SECRET
from detector import analyze_message
from messaging import reply_to_line
from event_guard import EventGuard

# 2. ประกาศแอปและตัวตรวจลายเซ็นจาก Channel Secret
app = FastAPI(title="Scam Detection AI Bot")
parser = WebhookParser(LINE_CHANNEL_SECRET)
event_guard = EventGuard()


def parse_webhook(body: bytes, signature: str | None):
    """ตรวจลายเซ็นจาก body เดิมก่อนอ่าน JSON แล้วตรวจรูปแบบที่บอทต้องใช้."""
    if not signature or not signature.strip():
        raise HTTPException(status_code=400, detail="Missing signature")
    try:
        body_text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid UTF-8 body") from None
    if not parser.signature_validator.validate(body_text, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body_text)
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise ValueError("Expected events list")
        for raw in payload["events"]:
            if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
                raise ValueError("Invalid event")
            if raw["type"] == "message":
                message = raw.get("message")
                if not isinstance(message, dict) or not isinstance(message.get("type"), str):
                    raise ValueError("Invalid message")
                if message["type"] == "text":
                    if not isinstance(message.get("text"), str):
                        raise ValueError("Invalid text")
                    for field in ("webhookEventId", "replyToken"):
                        if not isinstance(raw.get(field), str) or not raw[field].strip():
                            raise ValueError("Missing event identity or reply token")

        events = parser.parse(body_text, signature)
        # SDK อาจแปลงข้อความที่ข้อมูลไม่ครบเป็น UnknownEvent จึงตรวจ text ซ้ำก่อนใช้งาน
        for raw, event in zip(payload["events"], events):
            if raw["type"] == "message" and raw["message"]["type"] == "text":
                if not isinstance(event, MessageEvent) or not isinstance(event.message, TextMessageContent):
                    raise ValueError("Invalid text event")
        return events
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature") from None
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        # ไม่ส่ง body, token หรือรายละเอียด SDK กลับไปใน error
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from None


# 3. เส้นทางตรวจสถานะ: GET / ยืนยันว่าแอปทำงาน (ไม่ได้ทดสอบ API ภายนอก)
@app.get("/")
async def root():
    return {"status": "ok", "message": "Scam Detection LINE Bot is running!"}

# 4. รับค่า: LINE ส่ง JSON body และลายเซ็นใน HTTP header
@app.post("/webhook")
async def line_webhook(request: Request, x_line_signature: str = Header(None)):
    # อ่าน body ต้นฉบับก่อนตรวจลายเซ็น ห้ามแก้ข้อความก่อนตรวจ
    body = await request.body()
    events = parse_webhook(body, x_line_signature)

    # 5. ประมวลผลแต่ละ event; ข้ามภาพ สติกเกอร์ และ event ที่ไม่ใช่ข้อความ
    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
            claim = event_guard.claim(event.webhook_event_id)
            if claim == "duplicate":
                print("[DUPLICATE] ข้าม event เดิมที่กำลังทำหรือเคยทำแล้ว")
                continue
            if claim == "full":
                print("[BUSY] ที่เก็บ event ID เต็ม ยังไม่รับ event ใหม่")
                raise HTTPException(status_code=503, detail="Event capacity reached")
            try:
                await process_text_event(event)
            finally:
                event_guard.finish(event.webhook_event_id)
        else:
            print("[SKIP] ไม่ใช่ข้อความ Text ที่บอทรองรับ")

    # คืน 200 หลังพยายามทำครบ ไม่ใช่หลักฐานว่าทุกข้อความตรวจหรือส่งสำเร็จ
    return JSONResponse(content="OK", status_code=200)


async def process_text_event(event: MessageEvent):
    """สร้างรหัสสุ่มเฉพาะงาน ไม่ใช้ LINE user ID หรือ token เป็นรหัส log."""
    token = trace_id.set(uuid4().hex[:8])
    try:
        await _process_text_event(event)
    finally:
        trace_id.reset(token)


async def _process_text_event(event: MessageEvent):
    """วิเคราะห์และตอบหนึ่ง event; แยกไว้เพื่อให้ Webhook จัดการการกันซ้ำได้ชัดเจน."""
    user_text = event.message.text
    reply_token = event.reply_token

    print("==================== [NEW MESSAGE] ====================")
    print(f"📩 ข้อความเข้า: \"{user_text}\"")

    # ให้ thread pool รอ AI/ฐานข้อมูล เพื่อไม่บล็อกการรับคำขออื่น
    # await ยังรอผลของข้อความนี้ก่อนสร้างคำเตือน ไม่ได้ปล่อยงานทิ้งไว้เบื้องหลัง
    try:
        result = await run_in_threadpool(analyze_message, user_text)
    except Exception as error:
        # ข้อผิดพลาดที่ไม่ได้คาดไว้: ไม่ตอบในกลุ่ม และไปทำ event ถัดไป
        print(f"[CHECK ERROR] stage=analysis type={type(error).__name__}")
        return

    if result.get("status") == "error":
        print("[ACTION] ตรวจไม่ได้ ไม่ส่งคำเตือน และไม่สรุปว่าปลอดภัย")
        return

    # 6. สร้างคำเตือนและตอบด้วย reply_token ของ event นี้
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
        # การส่ง LINE ก็รอเครือข่าย จึงให้ thread pool ทำงานส่วนนี้ด้วย
        try:
            sent = await run_in_threadpool(reply_to_line, reply_token, reply_msg)
        except Exception as error:
            print(f"[SEND ERROR] stage=line_reply type={type(error).__name__}")
            return
        if sent:
            print("[ACTION] LINE API ยอมรับคำขอส่งคำเตือนแล้ว")
        else:
            print("[ACTION] ส่งคำเตือนไม่สำเร็จ ไม่ retry อัตโนมัติ")
    elif result.get("status") == "fallback":
        print("[ACTION] กฎสำรองไม่เข้าเกณฑ์เตือน แต่ LLM ตรวจไม่สำเร็จ")
    else:
        print("[ACTION] ไม่เข้าเกณฑ์แจ้งเตือน ดูขั้นตอนการตรวจจาก log ด้านบน")
