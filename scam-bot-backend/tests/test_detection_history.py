"""History writes use the LINE event ID and do not stop webhook processing."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_history():
    config = ModuleType("config")
    config.SUPABASE_URL = "https://example.invalid"
    config.SUPABASE_HISTORY_KEY = "offline"
    config.SAFE_WORDS = {"สวัสดี"}
    supabase = ModuleType("supabase")
    supabase.create_client = Mock()
    supabase_client = ModuleType("supabase.client")
    supabase_client.ClientOptions = lambda **kwargs: kwargs
    messaging = ModuleType("messaging")
    messaging.get_group_name = Mock(return_value=None)
    path = Path(__file__).resolve().parents[1] / "detection_history.py"
    spec = importlib.util.spec_from_file_location("history_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(path.parent), *sys.path]), patch.dict(sys.modules, {
        "config": config, "supabase": supabase, "supabase.client": supabase_client, "messaging": messaging,
    }):
        spec.loader.exec_module(module)
    return module


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.history = load_history()
        self.source_table = Mock()
        self.source_table.upsert.return_value.execute.return_value.data = [{"id": "source-uuid"}]
        self.log_table = Mock()
        self.db = Mock()
        self.db.table.side_effect = lambda name: {
            "line_sources": self.source_table, "detection_logs": self.log_table,
        }[name]
        self.history._client = self.db
        self.event = SimpleNamespace(
            source=SimpleNamespace(type="group", group_id="group-1"),
            message=SimpleNamespace(text="ฝากโอนเงินมาที่บัญชีนี้ด่วน"),
            webhook_event_id="line-event-1", timestamp=1_700_000_000_000,
        )

    def test_saves_result_once_by_line_event_id(self):
        result = {"is_scam": True, "risk_level": "high", "reason": "ขอเงินด่วน"}
        self.assertTrue(self.history.save_detection(
            self.event, result, warning_attempted=True, warning_sent=True,
        ))
        row = self.log_table.upsert.call_args.args[0]
        self.assertEqual(row["line_event_id"], "line-event-1")
        self.assertEqual(row["source_id"], "source-uuid")
        self.assertEqual(row["detection_status"], "risk_found")
        self.assertTrue(row["warning_sent"])
        self.assertEqual(self.log_table.upsert.call_args.kwargs,
                         {"on_conflict": "line_event_id", "ignore_duplicates": True})

    def test_database_failure_is_reported_without_raising(self):
        self.db.table.side_effect = RuntimeError("secret server message")
        with patch.object(self.history, "log") as log:
            self.assertFalse(self.history.save_detection(self.event, {"is_scam": False}))
        self.assertNotIn("secret server message", log.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
