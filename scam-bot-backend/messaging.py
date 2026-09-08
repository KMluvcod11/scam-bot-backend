"""ส่งคำเตือนกลับ LINE และรายงานว่าส่งสำเร็จหรือไม่."""
import requests
from config import LINE_CHANNEL_ACCESS_TOKEN


# 2. ฟังก์ชันตอบกลับ LINE
def reply_to_line(reply_token: str, message_text: str) -> bool:
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
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"❌ [LINE API ERROR] ส่งข้อความไม่สำเร็จ: {e}")
        return False
