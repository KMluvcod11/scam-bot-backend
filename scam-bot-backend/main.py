"""จุดเริ่มต้น FastAPI: ตรวจลายเซ็น รับข้อความ วิเคราะห์ และตอบ LINE."""
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from config import LINE_CHANNEL_SECRET
from detector import analyze_message
from messaging import reply_to_line

app = FastAPI(title="Scam Detection AI Bot")
parser = WebhookParser(LINE_CHANNEL_SECRET)


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
                if reply_to_line(reply_token, reply_msg):
                    print("[ACTION] แจ้งเตือนมิจฉาชีพเรียบร้อย")
            else:
                print(f"💤 [ACTION] ปลอดภัย บอทไม่ตอบแทรก")

    return JSONResponse(content="OK", status_code=200)
