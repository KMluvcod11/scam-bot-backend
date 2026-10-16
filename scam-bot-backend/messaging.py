"""ส่งคำเตือนกลับ LINE และรายงานว่าส่งสำเร็จหรือไม่."""
# 1. นำเข้า HTTP client และ token จาก config
import requests
from urllib.parse import quote
from bot_observability import log as print, timed_call
from config import LINE_CHANNEL_ACCESS_TOKEN

# จำกัดขนาดดาวน์โหลดของโปรเจกต์ไว้ที่ 5 MiB
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

def get_image_content(message_id: str) -> tuple[bytes, str] | None:
    """ดาวน์โหลดรูปไว้ในหน่วยความจำ; คืนข้อมูลรูปกับชนิดไฟล์ หรือ None."""
    try:
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("Missing image message_id")

        url = (
            "https://api-data.line.me/v2/bot/message"
            "/"f"{quote(message_id, safe='')}/content"
        )

        with requests.get(
            url,
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout = (5, 10),
            stream=True,
            allow_redirects=False,
        )as response:
            response.raise_for_status()

            if response.status_code != 200:
                raise ValueError("Unexpected contentstatus")

            main_type =(
                response.headers.get("Content-Type", "")
                .split(";")[0]
                .strip()
                .lower()
            )
            if main_type not in ("image/jpeg", "image/png", "image/webp"):
                raise ValueError("Unsupported image type")

            image_bytes = bytearray()

            for chunk in response.iter_content(chunk_size=64 * 1024):
                if len(image_bytes) + len(chunk) > MAX_IMAGE_BYTES:
                    raise ValueError("Image exceeds size limit")
                image_bytes.extend(chunk)

            if not image_bytes:
                raise ValueError("Empty image content")

            return bytes(image_bytes), main_type

    except (requests.RequestException, ValueError) as error:
        print(f"[IMAGE ERROR] stage=line_content type={type(error).__name__}")
        return None



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


def get_sender_display_name(kind: str, source_id: str, user_id: str) -> str | None:
    """อ่านชื่อผู้ส่งจาก LINE; คืน None เมื่อ LINE ไม่อนุญาตหรืออ่านไม่สำเร็จ."""
    if kind == "group":
        path = f"group/{quote(source_id, safe='')}/member/{quote(user_id, safe='')}"
    elif kind == "room":
        path = f"room/{quote(source_id, safe='')}/member/{quote(user_id, safe='')}"
    elif kind == "user":
        path = f"profile/{quote(user_id, safe='')}"
    else:
        return None
    try:
        response = requests.get(
            f"https://api.line.me/v2/bot/{path}",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=3,
        )
        response.raise_for_status()
        name = response.json().get("displayName")
        return name.strip() if isinstance(name, str) and name.strip() else None
    except (requests.RequestException, ValueError, AttributeError) as error:
        print(f"[PROFILE ERROR] type={type(error).__name__}")
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
