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
    messaging.get_group_member_count = Mock(return_value=None)
    messaging.get_sender_display_name = Mock(return_value="ผู้ทดสอบ")
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
        self.assertEqual(row["message_text"], self.event.message.text)
        self.assertEqual(row["message_preview"], self.event.message.text[:160])
        self.assertEqual(row["detection_status"], "risk_found")
        self.assertTrue(row["warning_sent"])
        self.assertEqual(self.log_table.upsert.call_args.kwargs,
                         {"on_conflict": "line_event_id", "ignore_duplicates": True})

    def test_database_failure_is_reported_without_raising(self):
        self.db.table.side_effect = RuntimeError("secret server message")
        with patch.object(self.history, "log") as log:
            self.assertFalse(self.history.save_detection(self.event, {"is_scam": False}))
        self.assertNotIn("secret server message", log.call_args.args[0])
        self.assertIn("stage=line_sources", log.call_args.args[0])

    def test_failure_identifies_table_and_safe_postgrest_code(self):
        for table in ("line_sources", "detection_logs"):
            with self.subTest(table=table):
                error = RuntimeError("SECRET_MESSAGE")
                error.code = "42501"
                error.details = "SECRET_DETAILS"
                target = self.source_table if table == "line_sources" else self.log_table
                target.upsert.return_value.execute.side_effect = error
                with patch.object(self.history, "log") as log:
                    self.assertFalse(self.history.save_detection(self.event, {"is_scam": False}))
                recorded = log.call_args.args[0]
                self.assertIn(f"stage={table}", recorded)
                self.assertIn("code=42501", recorded)
                self.assertNotIn("SECRET", recorded)
                target.upsert.return_value.execute.side_effect = None

    def test_saves_sender_id_and_display_name(self):
        self.event.source.user_id = "U123456"
        self.assertTrue(self.history.save_detection(self.event, {"is_scam": False}))
        row = self.log_table.upsert.call_args.args[0]
        self.assertEqual(row["sender_user_id"], "U123456")
        self.assertEqual(row["sender_display_name"], "ผู้ทดสอบ")


    def test_image_without_text_saves_marker_and_assessment_without_raw_content(self):
        self.event.message = SimpleNamespace(type="image", id="SECRET_IMAGE_ID")
        result = {
            "status": "risk_found", "is_scam": True, "risk_level": "high",
            "reason": "พบการขอให้โอนเงินก่อนรับรางวัล",
            "ocr_text": "SECRET_OCR_TEXT", "image_bytes": b"SECRET_IMAGE_BYTES",
        }

        self.assertTrue(self.history.save_detection(
            self.event, result, warning_attempted=True, warning_sent=True,
        ))

        row = self.log_table.upsert.call_args.args[0]
        self.assertEqual(row["message_text"], "[รูปภาพ]")
        self.assertEqual(row["message_preview"], "[รูปภาพ]")
        self.assertEqual(row["line_event_id"], self.event.webhook_event_id)
        self.assertEqual(row["source_type"], "group")
        self.assertEqual(row["received_at"], "2023-11-14T22:13:20+00:00")
        self.assertEqual(row["detection_status"], "risk_found")
        self.assertEqual(row["risk_level"], "high")
        self.assertEqual(row["reason"], result["reason"])
        self.assertNotIn("SECRET", repr(row))
        self.assertEqual(self.log_table.upsert.call_args.kwargs, {
            "on_conflict": "line_event_id", "ignore_duplicates": True,
        })

    def test_image_status_and_reply_outcomes_preserve_history_constraints(self):
        self.event.message = SimpleNamespace(type="image", id="offline-image")
        cases = (
            ("risk_found", True, True, True),
            ("no_risk_found", False, True, True),
            ("uncertain", False, False, None),
            ("error", None, False, None),
            ("risk_found", True, True, False),
        )
        for status, flag, attempted, sent in cases:
            with self.subTest(status=status, attempted=attempted, sent=sent):
                result = {
                    "status": status, "is_scam": flag,
                    "error_stage": "analysis" if status == "error" else None,
                }
                self.assertTrue(self.history.save_detection(
                    self.event, result,
                    warning_attempted=attempted, warning_sent=sent,
                ))
                row = self.log_table.upsert.call_args.args[0]
                self.assertEqual(row["detection_status"], status)
                self.assertIs(row["is_scam"], flag)
                self.assertIs(row["warning_attempted"], attempted)
                self.assertIs(row["warning_sent"], sent)
                self.assertEqual(row["error_stage"], result["error_stage"])
                self.assertEqual(row["message_text"], "[รูปภาพ]")


if __name__ == "__main__":
    unittest.main()
