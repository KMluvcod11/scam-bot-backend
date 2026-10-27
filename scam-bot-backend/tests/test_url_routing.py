"""ตรวจทางเดิน URL ในกลุ่มและส่วนตัว โดยไม่เรียก Google, Gemini หรือ Supabase จริง."""
import unittest
from unittest.mock import call, patch

from test_llm_validation import load_detector


class URLRoutingTests(unittest.TestCase):
    def setUp(self):
        self.detector = load_detector()
        self.check = self.detector.check_url
        self.normal_result = {
            "status": "no_risk_found", "is_scam": False,
            "risk_level": "low", "reason": "เหตุผลจำลองจากข้อความ",
        }
        self.vector = self.enterContext(patch.object(
            self.detector, "find_similarity", return_value=(0.0, None, ""),
        ))
        self.llm = self.enterContext(patch.object(
            self.detector, "analyze_with_llm", return_value=self.normal_result,
        ))
        self.logs = self.enterContext(patch("builtins.print"))

    def test_greetings_without_urls_keep_existing_bypass(self):
        self.assertEqual(self.detector.analyze_message("กินข้าวยัง"), {"is_scam": False})
        self.assertEqual(
            self.detector.analyze_message("สวัสดี", private=True)["status"],
            "conversation",
        )
        self.check.assert_not_called()
        self.vector.assert_not_called()
        self.llm.assert_not_called()

    def test_long_text_without_urls_keeps_existing_analysis(self):
        text = "พรุ่งนี้ประชุมงานกลุ่มที่ห้องสมุดและเตรียมสไลด์มาให้พร้อม"
        self.assertEqual(self.detector.analyze_message(text), self.normal_result)
        self.check.assert_not_called()
        self.vector.assert_called_once_with(text)
        self.llm.assert_called_once_with(text, 0.0, None, matched_text="")

    def test_matched_short_url_warns_before_group_bypass_or_vector(self):
        self.check.return_value = {"status": "matched", "threat_types": ["MALWARE"]}
        for private in (False, True):
            with self.subTest(private=private):
                self.check.reset_mock()
                result = self.detector.analyze_message("https://a.test", private=private)
                self.assertEqual(result["status"], "risk_found")
                self.assertIs(result["is_scam"], True)
                self.assertEqual(result["risk_level"], "high")
                self.assertIn("Google Safe Browsing", result["reason"])
                self.check.assert_called_once_with("https://a.test")
        self.vector.assert_not_called()
        self.llm.assert_not_called()

    def test_not_found_short_url_continues_context_analysis_in_both_chats(self):
        text = "https://a.test"
        for private in (False, True):
            with self.subTest(private=private):
                self.check.reset_mock()
                self.vector.reset_mock()
                self.llm.reset_mock()
                self.assertEqual(
                    self.detector.analyze_message(text, private=private), self.normal_result,
                )
                self.check.assert_called_once_with(text)
                self.vector.assert_called_once_with(text)
                options = {"matched_text": ""}
                if private:
                    options["private"] = True
                self.llm.assert_called_once_with(text, 0.0, None, **options)

    def test_not_found_does_not_override_text_risk(self):
        expected = {
            "status": "risk_found", "is_scam": True,
            "risk_level": "high", "reason": "เหตุผลจำลองจากข้อความ",
        }
        self.llm.return_value = expected
        self.assertEqual(
            self.detector.analyze_message("ส่งข้อมูลมาตามลิงก์ https://a.test", private=True),
            expected,
        )

    def test_check_error_does_not_become_no_risk_result(self):
        self.check.return_value = {"status": "error", "threat_types": []}
        for private in (False, True):
            with self.subTest(private=private):
                result = self.detector.analyze_message("https://a.test", private=private)
                self.assertEqual(result, {
                    "status": "error", "is_scam": None, "error_stage": "safe_browsing",
                })
        self.vector.assert_not_called()
        self.llm.assert_not_called()

    def test_error_on_first_url_does_not_hide_later_matched_url(self):
        self.check.side_effect = [
            {"status": "error", "threat_types": []},
            {"status": "matched", "threat_types": ["SOCIAL_ENGINEERING"]},
        ]
        result = self.detector.analyze_message("https://a.test https://b.test")
        self.assertEqual(result["status"], "risk_found")
        self.assertIs(result["is_scam"], True)
        self.assertEqual(self.check.call_args_list, [call("https://a.test"), call("https://b.test")])
        self.vector.assert_not_called()

    def test_exactly_three_unique_urls_can_continue_text_analysis(self):
        text = "https://a.test https://b.test https://c.test https://a.test"
        self.assertEqual(self.detector.analyze_message(text), self.normal_result)
        self.assertEqual(self.check.call_args_list, [
            call("https://a.test"), call("https://b.test"), call("https://c.test"),
        ])
        self.vector.assert_called_once_with(text)

    def test_more_than_three_urls_is_uncertain_without_checking_fourth(self):
        text = "https://a.test https://b.test https://c.test https://d.test"
        for private in (False, True):
            with self.subTest(private=private):
                self.check.reset_mock()
                result = self.detector.analyze_message(text, private=private)
                self.assertEqual(result["status"], "uncertain")
                self.assertIs(result["is_scam"], False)
                self.assertIn("3", result["reason"])
                self.assertEqual(self.check.call_args_list, [
                    call("https://a.test"), call("https://b.test"), call("https://c.test"),
                ])
        self.vector.assert_not_called()
        self.llm.assert_not_called()

    def test_matched_url_still_warns_when_message_exceeds_limit(self):
        self.check.return_value = {"status": "matched", "threat_types": ["MALWARE"]}
        result = self.detector.analyze_message(
            "https://a.test https://b.test https://c.test https://d.test",
        )
        self.assertEqual(result["status"], "risk_found")
        self.assertIs(result["is_scam"], True)
        self.check.assert_called_once_with("https://a.test")

    def test_url_query_is_not_written_to_timing_logs(self):
        self.check.return_value = {"status": "error", "threat_types": []}
        self.detector.analyze_message("https://a.test/?token=SECRET_URL_QUERY", private=True)
        logs = str(self.logs.call_args_list)
        self.assertNotIn("SECRET_URL_QUERY", logs)
        self.assertNotIn("https://a.test", logs)
        self.assertIn("stage=safe_browsing", logs)
