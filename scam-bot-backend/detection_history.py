"""Persist one LINE text event for the dashboard without logging secrets."""
from datetime import datetime, timezone

from supabase import create_client
from supabase.client import ClientOptions

from bot_observability import error_summary, log
from config import SAFE_WORDS, SUPABASE_HISTORY_KEY, SUPABASE_URL


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
