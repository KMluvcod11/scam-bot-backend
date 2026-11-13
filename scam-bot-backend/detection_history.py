"""Persist one LINE text event for the dashboard without logging secrets."""
from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
import uuid

from supabase import create_client
from supabase.client import ClientOptions

from bot_observability import error_summary, log
from config import SAFE_WORDS, SUPABASE_HISTORY_KEY, SUPABASE_URL
from messaging import get_group_name, get_group_member_count, get_sender_display_name
# ย้ายไป privacy.py ให้การ์ด LINE ใช้ร่วมได้; import ไว้ตรงนี้ให้โค้ด/เทสต์เดิมเรียก detection_history.redact_phone ได้
from privacy import redact_phone  # noqa: F401


_client = None

# ชื่อผู้ส่งเปลี่ยนไม่บ่อย จึงจำไว้แทนการเรียก LINE ทุกข้อความ (ลดเวลาและ rate limit ในกลุ่มที่คึกคัก)
# อ่านชื่อไม่ได้ (None) จำสั้นกว่า เผื่อเป็นปัญหาชั่วคราว; cache อยู่ใน process เดียว หายเมื่อ restart
SENDER_NAME_TTL_SECONDS = 6 * 60 * 60
UNKNOWN_SENDER_TTL_SECONDS = 10 * 60
SENDER_NAME_CACHE_MAX_ENTRIES = 1000
_sender_names = OrderedDict()
_sender_names_lock = Lock()


# _sender_name: หาชื่อผู้ส่ง: ใช้ cache ก่อน ถ้าไม่มีหรือหมดอายุค่อยถาม LINE
def _sender_name(kind, source_id, user_id):
    """คืนชื่อผู้ส่งจาก cache หรือถาม LINE เมื่อยังไม่มี/หมดอายุ; คืน None เมื่ออ่านไม่ได้."""
    key = (kind, source_id, user_id)
    with _sender_names_lock:
        cached = _sender_names.get(key)
        if cached is not None and cached[0] > monotonic():
            return cached[1]
    # เรียก LINE นอก lock เพื่อไม่ให้งานอื่นรอ network
    name = get_sender_display_name(kind, source_id, user_id)
    ttl = SENDER_NAME_TTL_SECONDS if name is not None else UNKNOWN_SENDER_TTL_SECONDS
    with _sender_names_lock:
        _sender_names.pop(key, None)
        _sender_names[key] = (monotonic() + ttl, name)
        while len(_sender_names) > SENDER_NAME_CACHE_MAX_ENTRIES:
            _sender_names.popitem(last=False)  # ทิ้งรายการที่ถูกเพิ่มนานที่สุด
    return name


# _history_client: สร้างและเก็บ client เขียนประวัติไว้ใช้ซ้ำ โดยกำหนด timeout ของ PostgREST สิบวินาที
def _history_client():
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_HISTORY_KEY,
                                options=ClientOptions(postgrest_client_timeout=10))
    return _client


# _source: อ่านชนิดแชตจาก event แล้วคืนคู่ชนิดและรหัส user/group/room ที่ตรงกัน
def _source(event):
    source = event.source
    kind = source.type
    attribute = {"group": "group_id", "room": "room_id", "user": "user_id"}[kind]
    return kind, getattr(source, attribute, None)


# _status: แปลงผลตรวจเป็นสถานะที่บันทึกได้ โดยแยก error, uncertain และข้อความกลุ่มที่ข้ามการตรวจ
def _status(result, text, kind):
    if result.get("status") == "error" or result.get("is_scam") is None:
        return "error"
    if result.get("status") in {"conversation", "no_risk_found", "risk_found", "uncertain"}:
        return result["status"]
    if result.get("status") == "fallback" and result.get("is_scam") is False:
        return "uncertain"
    if result.get("is_scam") is True:
        return "risk_found"
    if kind != "user" and (text.strip().lower() in SAFE_WORDS or len(text.strip()) <= 25):
        return "bypassed"
    return "no_risk_found"


# save_group_join: บอตถูกเชิญเข้ากลุ่ม: บันทึกกลุ่ม ชื่อกลุ่ม และจำนวนสมาชิก
def save_group_join(event):
    """เก็บกลุ่มก่อนดึงชื่อ; ไม่สร้าง detection_logs เพราะ join ไม่ใช่ข้อความ."""
    try:
        kind, group_id = _source(event)
        if kind != "group" or not group_id:
            return False
        db = _history_client()
        db.table("line_sources").upsert({
            "line_source_id": group_id,
            "source_type": "group",
            "is_active": True,
            "bot_joined_at": datetime.fromtimestamp(event.timestamp / 1000, timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="line_source_id").execute()
        name = get_group_name(group_id)
        if name is not None:
            db.table("line_sources").update({"display_name": name}).eq("line_source_id", group_id).execute()
        save_group_members(event)
        # หากดึงชื่อไม่ได้ ไม่ส่ง null ไปทับชื่อเดิม
        log(f"[GROUP JOIN] saved=true name_loaded={str(name is not None).lower()}")
        return True
    except Exception as error:
        log(f"[GROUP ERROR] stage=join type={type(error).__name__}")
        return False


# save_group_members: มีคนเข้า/ออกกลุ่ม: อัปเดตจำนวนสมาชิกล่าสุดจาก LINE
def save_group_members(event):
    """บันทึกจำนวนล่าสุดจาก LINE โดยไม่บวก/ลบซ้ำจาก webhook ที่ส่งซ้ำ."""
    try:
        kind, group_id = _source(event)
        if kind != "group" or not group_id:
            return False
        count = get_group_member_count(group_id)
        if count is None:
            return False
        _history_client().table("line_sources").upsert({
            "line_source_id": group_id,
            "source_type": "group",
            "member_count": count,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="line_source_id").execute()
        return True
    except Exception as error:
        log(f"[GROUP ERROR] stage=members type={type(error).__name__}")
        return False


# sync_missing_group_members: เติมจำนวนสมาชิกให้กลุ่มเก่าที่ยังไม่มีค่า (รันจาก scripts/sync_group_members.py)
def sync_missing_group_members():
    """เติมจำนวนสมาชิกของกลุ่มเดิมที่ยังเป็น null; ไม่แก้ประวัติข้อความ."""
    db = _history_client()
    rows = (db.table("line_sources")
            .select("id,line_source_id")
            .eq("source_type", "group")
            .eq("is_active", True)
            .is_("member_count", "null")
            .execute().data or [])
    updated = 0
    for row in rows:
        count = get_group_member_count(row["line_source_id"])
        if count is None:
            continue
        try:
            response = (db.table("line_sources")
                        .update({"member_count": count})
                        .eq("id", row["id"])
                        .is_("member_count", "null")
                        .execute())
            updated += bool(response.data)
        except Exception as error:
            log(f"[GROUP ERROR] stage=sync_members type={type(error).__name__}")
    return {"missing": len(rows), "updated": updated}


# save_group_leave: บอตออกจากกลุ่ม: ซ่อนกลุ่มจาก Dashboard แต่ไม่ลบประวัติ
def save_group_leave(event):
    """ซ่อนกลุ่มที่บอตออก โดยไม่ลบกลุ่ม ชื่อ หรือประวัติการตรวจ."""
    try:
        kind, group_id = _source(event)
        if kind != "group" or not group_id:
            return False
        response = (_history_client().table("line_sources")
                    .update({"is_active": False})
                    .eq("line_source_id", group_id).eq("source_type", "group")
                    .execute())
        saved = bool(response.data)
        log(f"[GROUP LEAVE] saved={str(saved).lower()}")
        return saved
    except Exception as error:
        log(f"[GROUP ERROR] stage=leave type={type(error).__name__}")
        return False

# save_detection: รับ event และผลตรวจ ปกปิดเบอร์ที่มีคำกำกับ แล้วบันทึกครั้งเดียวต่อ event; คืน False เมื่อบันทึกไม่สำเร็จ
def save_detection(event, result, *, warning_attempted=False, warning_sent=None,
                   case_id=None, image_text=None):
    """Insert once by LINE event ID. Never update an earlier result on redelivery.

    case_id: รหัส 32 ตัวที่อยู่ในลิงก์การ์ด ใช้เป็น id ของแถวให้ Mini App เปิดเคสนี้ได้
    image_text: ข้อความ OCR ของรูป (ส่งมาเฉพาะแชตส่วนตัว)
    """
    kind, line_source_id = _source(event)
    if not line_source_id:
        log("[HISTORY ERROR] stage=source missing_id")
        return False

    stage = "client"
    try:
        db = _history_client()
        stage = "line_sources"
        source_response = db.table("line_sources").upsert({
            "line_source_id": line_source_id,
            "source_type": kind,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="line_source_id").execute()
        source_id = source_response.data[0]["id"]
        if getattr(event.message, "type", None) == "image":
            ocr = " ".join(image_text.split()) if isinstance(image_text, str) else ""
            text = f"[รูปภาพ] {ocr}" if ocr else "[รูปภาพ]"
        else:
            text = event.message.text
            
        status = _status(result, text, kind)
        stored_text = redact_phone(text)
        stored_reason = redact_phone(result.get("reason"))
        sender_user_id = getattr(event.source, "user_id", None)
        sender_display_name = (_sender_name(kind, line_source_id, sender_user_id)
                               if sender_user_id else None)
        row = {
            "line_event_id": event.webhook_event_id,
            "source_id": source_id,
            "source_type": kind,
            "sender_user_id": sender_user_id,
            "sender_display_name": sender_display_name,
            "message_text": stored_text,
            "message_preview": stored_text[:160],
            "received_at": datetime.fromtimestamp(event.timestamp / 1000, timezone.utc).isoformat(),
            "detection_status": status,
            "is_scam": None if status == "error" else result.get("is_scam"),
            "risk_level": result.get("risk_level"),
            "reason": stored_reason,
            "decision_method": "fallback" if result.get("status") == "fallback" else "unknown",
            "warning_attempted": warning_attempted,
            "warning_sent": warning_sent,
            "error_stage": result.get("error_stage"),
        }
        if case_id:
            row["id"] = str(uuid.UUID(case_id))
        stage = "detection_logs"
        db.table("detection_logs").upsert(
            row, on_conflict="line_event_id", ignore_duplicates=True,
        ).execute()
        return True
    except Exception as error:
        log(f"[HISTORY ERROR] stage={stage} {error_summary(error)}")
        return False
