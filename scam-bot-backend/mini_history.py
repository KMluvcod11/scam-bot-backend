"""อ่านและลบประวัติการตรวจของเจ้าของจาก detection_logs ให้ Mini App (ไม่เรียก AI).

owner คือ sub ที่ verify_line_owner() ยืนยันกับ LINE แล้วเท่านั้น
"""
import re
import uuid

from learning import build_case_detail, case_category

TABLE = "detection_logs"
VISIBLE_STATUSES = ["risk_found", "uncertain", "no_risk_found"]
COLUMNS = "id,message_text,detection_status,reason,received_at"


class HistoryUnavailable(Exception):  # noqa: N818 — ชื่อสื่อความหมายตามที่ mini_api ใช้
    """Supabase ขัดข้อง; ไม่เก็บข้อความ error ดิบเพราะอาจมีข้อมูลระบบ."""


def get_client():
    # import ตอนใช้ เพื่อไม่ให้การ import โมดูลนี้ต้องโหลด config/LINE ทั้งชุด
    from detection_history import _history_client
    return _history_client()


def _run(build_query):
    """รัน query แล้วคืน data; ทุก error กลายเป็น HistoryUnavailable."""
    try:
        return build_query(get_client()).execute().data or []
    except Exception:
        raise HistoryUnavailable() from None


def _owner_rows(client, owner):
    """เงื่อนไขร่วม: แถวของเจ้าของ เฉพาะแชตส่วนตัว และ 3 สถานะที่แสดงได้."""
    return (client.table(TABLE).select(COLUMNS)
            .eq("sender_user_id", owner).eq("source_type", "user")
            .in_("detection_status", VISIBLE_STATUSES))


def _short_title(text):
    return " ".join(str(text).split())[:60]


def list_cases(owner: str, limit: int = 50) -> list[dict]:
    rows = _run(lambda client: _owner_rows(client, owner)
                .order("received_at", desc=True).limit(limit))
    return [{
        "id": uuid.UUID(str(item["id"])).hex,
        "title": _short_title(item["message_text"]),
        "category": case_category(item["message_text"]),
        "receivedAt": item["received_at"],
        "status": item["detection_status"],
    } for item in rows]


def get_case(case_hex: str, owner: str) -> dict | None:
    # รับเฉพาะ 32 ตัวฐานสิบหก แบบที่อยู่ในลิงก์ รหัสผิดรูปแบบไม่ต้องถามฐานข้อมูล
    if not isinstance(case_hex, str) or not re.fullmatch(r"[0-9a-f]{32}", case_hex):
        return None
    row_id = str(uuid.UUID(case_hex))
    rows = _run(lambda client: _owner_rows(client, owner).eq("id", row_id).limit(1))
    if not rows:
        return None
    item = rows[0]
    result = {"status": item["detection_status"], "reason": item.get("reason")}
    detail = build_case_detail(item["message_text"], result, item["received_at"])
    return {**detail, "id": case_hex}


def delete_all(owner: str) -> int:
    # ลบทุกสถานะของเจ้าของในแชตส่วนตัว (รวมคำทักทาย/error) แต่ไม่แตะข้อความในกลุ่ม
    rows = _run(lambda client: client.table(TABLE).delete()
                .eq("sender_user_id", owner).eq("source_type", "user"))
    # นับเฉพาะสถานะที่ผู้ใช้เห็นในหน้าประวัติ ให้ตัวเลข "ลบแล้ว X รายการ" ตรงกับที่เห็น
    return sum(1 for item in rows if item.get("detection_status") in VISIBLE_STATUSES)
