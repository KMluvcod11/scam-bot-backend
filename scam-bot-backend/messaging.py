"""ส่งคำเตือนกลับ LINE และรายงานว่าส่งสำเร็จหรือไม่."""
# 1. นำเข้า HTTP client และ token จาก config
import requests
from bot_observability import log as print, timed_call
from config import LINE_CHANNEL_ACCESS_TOKEN


# 2. รับค่า: reply_token ของ event และ message_text ที่ต้องการตอบ
# คืนค่า bool: True = LINE API ยอมรับ; False = HTTP/เครือข่ายผิดพลาด
def reply_to_line(reply_token: str, message_text: str) -> bool:
    # 2.1 ประกาศปลายทาง header ยืนยันตัวตน และ JSON payload
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message_text}]
    }
    # 2.2 ส่งคำตอบโดยมี timeout; ไม่มีการ retry อัตโนมัติในฟังก์ชันนี้
    try:
        res = timed_call("line_reply", requests.post, url, headers=headers, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except requests.RequestException as e:
        # บันทึกชนิดข้อผิดพลาด ไม่พิมพ์ข้อมูลคำขอหรือ token ที่อาจอยู่ใน exception
        print(f"[SEND ERROR] stage=line_reply type={type(e).__name__}")
        return False
