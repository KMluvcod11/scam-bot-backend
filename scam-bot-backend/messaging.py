"""ส่งคำเตือนกลับ LINE และรายงานว่าส่งสำเร็จหรือไม่."""
# 1. นำเข้า HTTP client และ token จาก config
import requests
from urllib.parse import quote
from bot_observability import log as print, timed_call
from config import LINE_CHANNEL_ACCESS_TOKEN


def get_group_member_count(group_id: str) -> int | None:
    """ดึงจำนวนสมาชิกที่ไม่รวมบอต; ถ้าดึงไม่ได้คืน None เพื่อรักษาค่าเดิม."""
    try:
        response = requests.get(
            f"https://api.line.me/v2/bot/group/{quote(group_id, safe='')}/members/count",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid member count response")
        count = data.get("count")
        if type(count) is not int or count < 0:
            raise ValueError("Invalid member count")
        return count
    except (requests.RequestException, ValueError) as error:
        print(f"[GROUP ERROR] stage=line_member_count type={type(error).__name__}")
        return None


def get_group_name(group_id: str) -> str | None:
    """อ่านชื่อกลุ่มจาก LINE; ล้มเหลวคืน None ไม่พิมพ์ token/ชื่อกลุ่มใน log."""
    try:
        response = requests.get(
            f"https://api.line.me/v2/bot/group/{quote(group_id, safe='')}/summary",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("groupName"), str) or not data["groupName"].strip():
            raise ValueError("Invalid group summary")
        return data["groupName"]
    except (requests.RequestException, ValueError) as error:
        print(f"[GROUP ERROR] stage=line_summary type={type(error).__name__}")
        return None


# 2. รับค่า: reply_token ของ event และ message_text ที่ต้องการตอบ
# คืนค่า bool: True = LINE API ยอมรับ; False = HTTP/เครือข่ายผิดพลาด
def reply_to_line(reply_token: str, message_text: str, *, learn_case_id: str | None = None) -> bool:
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
    if learn_case_id:
        # ปุ่มส่งเพียงรหัสสุ่ม ไม่ฝังข้อความที่ตรวจหรือ user ID ใน postback
        payload["messages"].append({
            "type": "template",
            "altText": "เรียนรู้จากข้อความนี้ (ปุ่มมีอายุ 15 นาที)",
            "template": {
                "type": "buttons",
                "text": "เรียนรู้จากผลตรวจด้านบน\nปุ่มมีอายุ 15 นาที หรือจนกว่าบอตจะรีสตาร์ต",
                "actions": [{
                    "type": "postback", "label": "เรียนรู้จากเคสนี้",
                    "data": f"learn:{learn_case_id}",
                    "displayText": "เรียนรู้จากข้อความนี้",
                }],
            },
        })
    # 2.2 ส่งคำตอบโดยมี timeout; ไม่มีการ retry อัตโนมัติในฟังก์ชันนี้
    try:
        res = timed_call("line_reply", requests.post, url, headers=headers, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except requests.RequestException as e:
        # บันทึกชนิดข้อผิดพลาด ไม่พิมพ์ข้อมูลคำขอหรือ token ที่อาจอยู่ใน exception
        print(f"[SEND ERROR] stage=line_reply type={type(e).__name__}")
        return False
