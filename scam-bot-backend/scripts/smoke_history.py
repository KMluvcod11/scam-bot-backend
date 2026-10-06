"""Write one clearly labelled synthetic record; requires only Supabase credentials."""
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from dotenv import load_dotenv
from pathlib import Path

def main():
    import sys
    backend = Path(__file__).resolve().parents[1]
    load_dotenv(backend / '.env')
    key = os.getenv('SUPABASE_HISTORY_KEY')
    if not key or key.startswith('replace-with-'):
        raise SystemExit('SUPABASE_HISTORY_KEY is missing')
    os.environ.setdefault('SUPABASE_KEY', key)
    for name in ('GEMINI_API_KEY', 'CHANNEL_SECRET', 'CHANNEL_ACCESS_TOKEN'):
        os.environ.setdefault(name, 'unused-in-supabase-smoke-test')
    sys.path.insert(0, str(backend))
    from detection_history import _history_client, save_detection

    event_id = "backend-smoke-test-" + uuid4().hex
    event = SimpleNamespace(
        source=SimpleNamespace(type="group", group_id="backend-smoke-test-group"),
        message=SimpleNamespace(text="[TEST] Synthetic backend history record; no LINE or AI call."),
        webhook_event_id=event_id,
        timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
    )
    result = {"is_scam": True, "risk_level": "high",
              "reason": "Synthetic result to verify database persistence only."}
    if not save_detection(event, result):
        raise SystemExit("Database write failed; see sanitized HISTORY ERROR above.")
    if not save_detection(event, result):
        raise SystemExit("Duplicate-write check failed.")
    try:
        response = (_history_client().table("detection_logs")
                    .select("id,line_event_id,detection_status")
                    .eq("line_event_id", event_id).execute())
    except Exception as error:
        raise SystemExit("Readback failed: " + type(error).__name__) from None
    if len(response.data) != 1:
        raise SystemExit("Expected exactly one stored row.")
    print("PASS: persisted one synthetic row; duplicate event did not add a row.")
    print("Record ID:", response.data[0]["id"])


if __name__ == "__main__":
    main()
