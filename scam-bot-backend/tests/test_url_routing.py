"""ตรวจทางเดิน URL ในกลุ่มและส่วนตัว โดยไม่เรียก Google, Gemini หรือ Supabase จริง."""
import unittest
from unittest.mock import call, patch

from test_llm_validation import load_detector


class URLRoutingTests(unittest.TestCase):
    # setUp: เตรียม detector และผลจำลองของ URL เวกเตอร์ และ LLM เพื่อทดสอบลำดับการตรวจ
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

    # test_greetings_without_urls_keep_existing_bypass: ทดสอบคำทักทายที่ไม่มี URL ยังข้ามบริการตามกฎเดิม
    def test_greetings_without_urls_keep_existing_bypass(self):
        self.assertEqual(self.detector.analyze_message("กินข้าวยัง"), {"is_scam": False})
        self.assertEqual(
            self.detector.analyze_message("สวัสดี", private=True)["status"],
            "conversation",
        )
        self.check.assert_not_called()
        self.vector.assert_not_called()
        self.llm.assert_not_called()

    # test_short_group_message_with_www_link_is_checked_not_bypassed: ข้อความสั้นในกลุ่มที่มีลิงก์ www. ต้องตรวจลิงก์และบริบท
    def test_short_group_message_with_www_link_is_checked_not_bypassed(self):
        self.check.return_value = {"status": "not_found", "threat_types": []}
        text = "ดูที่ www.evil-bank.example"
        self.assertEqual(self.detector.analyze_message(text), self.normal_result)
        self.check.assert_called_once_with("http://www.evil-bank.example")
        self.vector.assert_called_once_with(text)
        self.llm.assert_called_once()

    # test_long_text_without_urls_keeps_existing_analysis: ทดสอบข้อความยาวไม่มี URL ใช้เวกเตอร์และ LLM โดยไม่เรียกตรวจลิงก์
    def test_long_text_without_urls_keeps_existing_analysis(self):
        text = "พรุ่งนี้ประชุมงานกลุ่มที่ห้องสมุดและเตรียมสไลด์มาให้พร้อม"
        self.assertEqual(self.detector.analyze_message(text), self.normal_result)
        self.check.assert_not_called()
        self.vector.assert_called_once_with(text)
        self.llm.assert_called_once_with(text, 0.0, None, matched_text="")

    # test_matched_short_url_warns_before_group_bypass_or_vector: ทดสอบ URL สั้นที่พบภัยเตือนก่อนกฎข้ามข้อความกลุ่มและก่อนค้นเวกเตอร์
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

    # test_not_found_short_url_continues_context_analysis_in_both_chats: ทดสอบลิงก์สั้นไม่พบภัยยังวิเคราะห์บริบททั้งกลุ่มและส่วนตัว
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

    # test_not_found_does_not_override_text_risk: ทดสอบไม่พบ URL ในรายการภัยไม่ได้ลบความเสี่ยงที่พบจากข้อความ
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

    # test_check_error_continues_to_ai_and_says_link_unchecked: Safe Browsing เสียไม่ทำให้ตรวจทั้งข้อความไม่ได้
    # แต่ต้องวิเคราะห์ต่อด้วย AI พร้อมบอกว่ายังไม่ได้ตรวจลิงก์ (ไม่แปลงเป็นผลว่าลิงก์ปลอดภัย)
    def test_check_error_continues_to_ai_and_says_link_unchecked(self):
        self.check.return_value = {"status": "error", "threat_types": []}
        for private in (False, True):
            with self.subTest(private=private):
                self.llm.reset_mock()
                result = self.detector.analyze_message("https://a.test", private=private)
                self.assertEqual(result, self.normal_result)
                self.assertIs(self.llm.call_args.kwargs.get("url_unchecked"), True)

    # test_successful_check_does_not_flag_link_unchecked: ตรวจลิงก์สำเร็จแล้วไม่ต้องบอก AI ว่ายังไม่ได้ตรวจ
    def test_successful_check_does_not_flag_link_unchecked(self):
        self.check.return_value = {"status": "not_found", "threat_types": []}
        self.detector.analyze_message("https://a.test", private=True)
        self.assertFalse(self.llm.call_args.kwargs.get("url_unchecked", False))

    # test_error_on_first_url_does_not_hide_later_matched_url: ทดสอบลิงก์แรกตรวจพลาดแต่ลิงก์ถัดไปพบภัยยังแจ้งเตือน
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

    # test_exactly_three_unique_urls_can_continue_text_analysis: ทดสอบสาม URL ไม่ซ้ำตรวจครบแล้ววิเคราะห์ข้อความต่อได้
    def test_exactly_three_unique_urls_can_continue_text_analysis(self):
        text = "https://a.test https://b.test https://c.test https://a.test"
        self.assertEqual(self.detector.analyze_message(text), self.normal_result)
        self.assertEqual(self.check.call_args_list, [
            call("https://a.test"), call("https://b.test"), call("https://c.test"),
        ])
        self.vector.assert_called_once_with(text)

    # test_more_than_three_urls_is_uncertain_without_checking_fourth: ทดสอบเกินสาม URL คืน uncertain โดยไม่ตรวจลิงก์ที่สี่หรือเรียก LLM
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

    # test_matched_url_still_warns_when_message_exceeds_limit: ทดสอบพบภัยในลิงก์ที่ตรวจแล้วต้องเตือนแม้ข้อความมีลิงก์เกินจำนวนที่รองรับ
    def test_matched_url_still_warns_when_message_exceeds_limit(self):
        self.check.return_value = {"status": "matched", "threat_types": ["MALWARE"]}
        result = self.detector.analyze_message(
            "https://a.test https://b.test https://c.test https://d.test",
        )
        self.assertEqual(result["status"], "risk_found")
        self.assertIs(result["is_scam"], True)
        self.check.assert_called_once_with("https://a.test")

    # test_url_query_is_not_written_to_timing_logs: ทดสอบ log จับเวลาไม่เผย URL หรือ query ที่มีข้อมูลลับ
    def test_url_query_is_not_written_to_timing_logs(self):
        self.check.return_value = {"status": "error", "threat_types": []}
        self.detector.analyze_message("https://a.test/?token=SECRET_URL_QUERY", private=True)
        logs = str(self.logs.call_args_list)
        self.assertNotIn("SECRET_URL_QUERY", logs)
        self.assertNotIn("https://a.test", logs)
        self.assertIn("stage=safe_browsing", logs)
