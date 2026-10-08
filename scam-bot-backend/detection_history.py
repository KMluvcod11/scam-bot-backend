"""Persist one LINE text event for the dashboard without logging secrets."""
from datetime import datetime, timezone

from supabase import create_client
from supabase.client import ClientOptions

from bot_observability import error_summary, log
from config import SAFE_WORDS, SUPABASE_HISTORY_KEY, SUPABASE_URL
from messaging import get_group_name, get_group_member_count


_client = None


def _history_client():
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_HISTORY_KEY,
                                options=ClientOptions(postgrest_client_timeout=10))
    return _client


def _source(event):
    source = event.source
    kind = source.type
    attribute = {"group": "group_id", "room": "room_id", "user": "user_id"}[kind]
    return kind, getattr(source, attribute, None)


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


def save_detection(event, result, *, warning_attempted=False, warning_sent=None):
    """Insert once by LINE event ID. Never update an earlier result on redelivery."""
    kind, line_source_id = _source(event)
    if not line_source_id:
        log("[HISTORY ERROR] stage=source missing_id")
        return False

    try:
        db = _history_client()
        source_response = db.table("line_sources").upsert({
            "line_source_id": line_source_id,
            "source_type": kind,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="line_source_id").execute()
        source_id = source_response.data[0]["id"]
        text = event.message.text
        status = _status(result, text, kind)
        row = {
            "line_event_id": event.webhook_event_id,
            "source_id": source_id,
            "source_type": kind,
            "message_text": text,
            "message_preview": text[:160],
            "received_at": datetime.fromtimestamp(event.timestamp / 1000, timezone.utc).isoformat(),
            "detection_status": status,
            "is_scam": None if status == "error" else result.get("is_scam"),
            "risk_level": result.get("risk_level"),
            "reason": result.get("reason"),
            "decision_method": "fallback" if result.get("status") == "fallback" else "unknown",
            "warning_attempted": warning_attempted,
            "warning_sent": warning_sent,
            "error_stage": result.get("error_stage"),
        }
        db.table("detection_logs").upsert(
            row, on_conflict="line_event_id", ignore_duplicates=True,
        ).execute()
        return True
    except Exception as error:
        log(f"[HISTORY ERROR] stage=database {error_summary(error)}")
        return False
