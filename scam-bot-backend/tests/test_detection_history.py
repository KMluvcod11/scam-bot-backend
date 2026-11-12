"""History writes use the LINE event ID and do not stop webhook processing."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


# load_history: โหลดโมดูลประวัติด้วย config, Supabase และ messaging จำลอง เพื่อไม่แตะคีย์หรือบริการจริง
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
    # setUp: เตรียมตาราง line_sources/detection_logs และ event จำลองสำหรับตรวจข้อมูลที่ถูกบันทึก
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

    # test_saves_result_once_by_line_event_id: ทดสอบบันทึกข้อความและผลตรวจด้วย upsert ที่กันซ้ำตาม LINE event ID
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

    # test_database_failure_is_reported_without_raising: ทดสอบบันทึกประวัติล้มเหลวคืน False พร้อม log ขั้นตอน โดยไม่ส่ง exception ออกไป
    def test_database_failure_is_reported_without_raising(self):
        self.db.table.side_effect = RuntimeError("secret server message")
        with patch.object(self.history, "log") as log:
            self.assertFalse(self.history.save_detection(self.event, {"is_scam": False}))
        self.assertNotIn("secret server message", log.call_args.args[0])
        self.assertIn("stage=line_sources", log.call_args.args[0])

    # test_failure_identifies_table_and_safe_postgrest_code: ทดสอบ log ระบุตารางและรหัส PostgREST ที่อนุญาต แต่ไม่เผยรายละเอียดลับ
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

    # test_saves_sender_id_and_display_name: ทดสอบข้อมูลประวัติมีรหัสและชื่อผู้ส่งที่ได้จากตัวจำลอง LINE
    def test_saves_sender_id_and_display_name(self):
        self.event.source.user_id = "U123456"
        self.assertTrue(self.history.save_detection(self.event, {"is_scam": False}))
        row = self.log_table.upsert.call_args.args[0]
        self.assertEqual(row["sender_user_id"], "U123456")
        self.assertEqual(row["sender_display_name"], "ผู้ทดสอบ")

    # save_from: บันทึกข้อความจากผู้ส่ง/แชตที่กำหนด แล้วคืนชื่อที่ถูกบันทึก
    def save_from(self, user_id, group_id="group-1"):
        self.event.source.user_id = user_id
        self.event.source.group_id = group_id
        self.assertTrue(self.history.save_detection(self.event, {"is_scam": False}))
        return self.log_table.upsert.call_args.args[0]["sender_display_name"]

    # test_sender_name_is_cached_per_chat_and_user: คนเดิมในแชตเดิมไม่ต้องเรียก LINE ทุกข้อความ
    def test_sender_name_is_cached_per_chat_and_user(self):
        lookup = self.history.get_sender_display_name
        self.assertEqual(self.save_from("U1"), "ผู้ทดสอบ")
        self.assertEqual(self.save_from("U1"), "ผู้ทดสอบ")
        self.assertEqual(lookup.call_count, 1)
        self.save_from("U2")              # คนอื่นในกลุ่มเดิม
        self.save_from("U1", "group-2")   # คนเดิมแต่คนละกลุ่ม (ชื่อในกลุ่มอาจต่างกัน)
        self.assertEqual(lookup.call_count, 3)

    # test_sender_name_cache_expires_and_unknown_names_retry_sooner: ชื่อเปลี่ยนได้ และอ่านไม่ได้ชั่วคราวควรลองใหม่เร็วกว่า
    def test_sender_name_cache_expires_and_unknown_names_retry_sooner(self):
        lookup = self.history.get_sender_display_name
        now = [1000.0]
        with patch.object(self.history, "monotonic", lambda: now[0]):
            self.save_from("U1")
            now[0] += self.history.SENDER_NAME_TTL_SECONDS - 1
            self.save_from("U1")
            self.assertEqual(lookup.call_count, 1)
            now[0] += 2
            self.save_from("U1")
            self.assertEqual(lookup.call_count, 2)

            lookup.reset_mock()
            lookup.return_value = None
            self.assertIsNone(self.save_from("U9"))
            now[0] += self.history.UNKNOWN_SENDER_TTL_SECONDS - 1
            self.save_from("U9")
            self.assertEqual(lookup.call_count, 1)
            now[0] += 2
            self.save_from("U9")
            self.assertEqual(lookup.call_count, 2)

    # test_sender_name_cache_is_bounded: กลุ่มใหญ่มากต้องไม่ทำให้ RAM โตไม่จำกัด
    def test_sender_name_cache_is_bounded(self):
        with patch.object(self.history, "SENDER_NAME_CACHE_MAX_ENTRIES", 2):
            for user_id in ("U1", "U2", "U3"):
                self.save_from(user_id)
            self.assertLessEqual(len(self.history._sender_names), 2)
            self.history.get_sender_display_name.reset_mock()
            self.save_from("U3")  # คนล่าสุดยังอยู่ใน cache
            self.history.get_sender_display_name.assert_not_called()


    # test_save_detection_uses_case_id_as_row_id: ทดสอบแปลง case_id เป็น UUID ของแถวประวัติพร้อมรักษาการกัน event ซ้ำ
    def test_save_detection_uses_case_id_as_row_id(self):
        case_hex = "0f8f2b7c1d2e4f309a1b2c3d4e5f6a7b"
        self.assertTrue(self.history.save_detection(self.event, {"is_scam": False}, case_id=case_hex))
        row = self.log_table.upsert.call_args.args[0]
        self.assertEqual(row["id"], "0f8f2b7c-1d2e-4f30-9a1b-2c3d4e5f6a7b")
        self.assertEqual(self.log_table.upsert.call_args.kwargs,
                         {"on_conflict": "line_event_id", "ignore_duplicates": True})

    # test_without_case_id_row_has_no_id_so_database_generates_it: ทดสอบไม่ส่ง id ในแถวเมื่อไม่ได้ระบุ case_id เพื่อให้ฐานข้อมูลสร้างเอง
    def test_without_case_id_row_has_no_id_so_database_generates_it(self):
        self.history.save_detection(self.event, {"is_scam": False})
        self.assertNotIn("id", self.log_table.upsert.call_args.args[0])

    # test_save_detection_image_prefix_and_fallback: ทดสอบข้อความ OCR ที่บันทึกมีคำนำหน้ารูปภาพ และไม่มี OCR ก็เก็บเครื่องหมายรูปภาพ
    def test_save_detection_image_prefix_and_fallback(self):
        self.event.message = SimpleNamespace(type="image", id="img")
        self.history.save_detection(self.event, {"status": "risk_found", "is_scam": True},
                                    image_text="  โอนเงินด่วน  ")
        row = self.log_table.upsert.call_args.args[0]
        self.assertEqual(row["message_text"], "[รูปภาพ] โอนเงินด่วน")
        self.assertEqual(row["message_preview"], "[รูปภาพ] โอนเงินด่วน")
        self.history.save_detection(self.event, {"status": "risk_found", "is_scam": True}, image_text="   ")
        self.assertEqual(self.log_table.upsert.call_args.args[0]["message_text"], "[รูปภาพ]")

    # test_image_without_text_saves_marker_and_assessment_without_raw_content: ทดสอบประวัติรูปที่ไม่มีข้อความเก็บเพียงเครื่องหมายและผลตรวจ ไม่เก็บเนื้อหารูปดิบ
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

    # test_image_status_and_reply_outcomes_preserve_history_constraints: ทดสอบบันทึกสถานะรูปและผลส่งคำตอบตรงกับเงื่อนไขประวัติแต่ละกรณี
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
