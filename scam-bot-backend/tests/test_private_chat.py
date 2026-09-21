"""ตรวจส่วนตัวด้วย client จำลอง: ไม่อ่านคีย์ ไม่ใช้โควตา และไม่ส่ง LINE จริง."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_webhook_threadpool as fixtures
from test_llm_validation import load_detector


def private_event(text="ส่ง OTP มา", number=1):
    event = fixtures.text_event(text, number)
    event["source"] = {"type": "user", "userId": "offline-user"}
    return event


def result(status):
    return {"status": status, "is_scam": status == "risk_found",
            "risk_level": "medium" if status == "risk_found" else "low", "reason": "เหตุผลทดสอบ"}


class PrivateDetectionTests(unittest.TestCase):
    def setUp(self):
        self.d = load_detector()
        self.logs = patch("builtins.print")
        self.logs.start()
        self.addCleanup(self.logs.stop)

    def test_exact_greetings_skip_external_services(self):
        with patch.object(self.d, "find_similarity") as vector, patch.object(self.d, "analyze_with_llm") as llm:
            for text in ("สวัสดี", " สวัสดีครับ ", "HI", "ขอบคุณ", "โอเค", "วิธีใช้งาน"):
                self.assertEqual(self.d.analyze_message(text, private=True)["status"], "conversation")
            vector.assert_not_called()
            llm.assert_not_called()

    def test_short_url_low_and_high_scores_always_get_context_check(self):
        for text in ("ส่ง OTP มา", "https://example.invalid", "สวัสดี โอนค่าประกันก่อน", "กินข้าวยัง"):
            for score, label in ((0, None), (64, "spam"), (99, "spam"), (99, "ham")):
                with self.subTest(text=text, score=score), patch.object(self.d, "find_similarity", return_value=(score, label)), patch.object(self.d, "analyze_with_llm", return_value=result("uncertain")) as llm:
                    self.assertEqual(self.d.analyze_message(text, private=True)["status"], "uncertain")
                    llm.assert_called_once_with(text, score, label, private=True)

    def test_all_private_statuses_validated(self):
        for status in ("conversation", "no_risk_found", "risk_found", "uncertain"):
            expected = result(status)
            self.d.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(expected))
            self.assertEqual(self.d.analyze_with_llm("ทดสอบ", 99, "spam", private=True), expected)

    def test_bad_status_and_contradiction_fail_closed(self):
        for bad in ({k: v for k, v in result("no_risk_found").items() if k != "status"},
                    result("safe"), {**result("risk_found"), "is_scam": False},
                    {**result("uncertain"), "is_scam": True}):
            self.d.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(bad))
            actual = self.d.analyze_with_llm("ทดสอบ", 99, "spam", private=True)
            self.assertEqual(actual["status"], "error")
            self.assertIsNone(actual["is_scam"])

    def test_missing_status_retries_next_model(self):
        self.d.client.models.generate_content.side_effect = [
            SimpleNamespace(text='{}'), SimpleNamespace(text=json.dumps(result("uncertain"))),
        ]
        self.assertEqual(self.d.analyze_with_llm("ทดสอบ", 0, private=True), result("uncertain"))
        self.assertEqual(self.d.client.models.generate_content.call_count, 2)

    def test_private_vector_error_is_not_a_negative_result(self):
        with patch.object(self.d, "find_similarity", side_effect=self.d.DetectionUnavailable("vector_db", "TimeoutError")):
            actual = self.d.analyze_message("ส่ง OTP มา", private=True)
        self.assertEqual(actual["status"], "error")
        self.assertIsNone(actual["is_scam"])

    def test_private_timeout_has_no_score_fallback(self):
        self.d.client.models.generate_content.side_effect = TimeoutError("SECRET")
        self.assertEqual(self.d.analyze_with_llm("ทดสอบ", 99, "spam", private=True)["status"], "error")
        self.assertEqual(self.d.client.models.generate_content.call_count, 1)


class PrivateWebhookTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.WebhookThreadpoolTests.asyncSetUp
    asyncTearDown = fixtures.WebhookThreadpoolTests.asyncTearDown
    post_events = fixtures.WebhookThreadpoolTests.post_events

    async def test_private_incoming_text_logged_with_trace_on_one_line(self):
        text = "สวัสดีครับ\nข้อความทดสอบ"
        self.module.analyze_message.return_value = result("conversation")
        with patch("builtins.print") as logs:
            await self.post_events([private_event(text)])
        incoming = [call for call in logs.call_args_list
                    if any("📩 ข้อความเข้า:" in str(arg) for arg in call.args)]
        self.assertEqual(len(incoming), 1)
        self.assertRegex(incoming[0].args[0], r"^\[trace=[0-9a-f]{8}\]$")
        self.assertEqual(incoming[0].args[1],
                         f"📩 ข้อความเข้า: {json.dumps(text, ensure_ascii=False)}")

    async def test_private_replies_for_each_result(self):
        for number, (status, expected) in enumerate((
            ("conversation", "ส่งข้อความที่สงสัย"), ("risk_found", "พบสัญญาณเสี่ยง"),
            ("no_risk_found", "ไม่รับรองว่าปลอดภัย"), ("uncertain", "ข้อความเดียว"),
            ("error", "ตรวจข้อความนี้ไม่สำเร็จ"), ("fallback", "ตรวจข้อความนี้ไม่สำเร็จ"),
        ), 1):
            self.module.analyze_message.return_value = result(status)
            response = await self.post_events([private_event(number=number)])
            self.assertEqual(response.status_code, 200)
            self.module.analyze_message.assert_called_with("ส่ง OTP มา", private=True)
            self.assertIn(expected, self.module.reply_to_line.call_args.args[1])

    async def test_unknown_legacy_result_does_not_claim_checked(self):
        self.module.analyze_message.return_value = {"is_scam": False}
        await self.post_events([private_event()])
        self.assertEqual(self.module.reply_to_line.call_args.args[1], self.module.PRIVATE_ERROR)

    async def test_thanks_is_brief(self):
        self.module.analyze_message.return_value = result("conversation")
        await self.post_events([private_event("ขอบคุณ")])
        self.assertIn("ยินดีครับ", self.module.reply_to_line.call_args.args[1])

    async def test_exception_replies_and_next_event_continues(self):
        self.module.analyze_message.side_effect = [RuntimeError("SECRET"), result("no_risk_found")]
        with patch("builtins.print") as logs:
            response = await self.post_events([private_event(number=1), private_event(number=2)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module.reply_to_line.call_count, 2)
        self.assertIn("ตรวจข้อความนี้ไม่สำเร็จ", self.module.reply_to_line.call_args_list[0].args[1])
        self.assertNotIn("SECRET", str(logs.call_args_list))

    async def test_private_image_replies_once_without_analysis(self):
        event = private_event()
        event["message"] = {"type": "image", "id": "1", "contentProvider": {"type": "line"}, "quoteToken": "offline"}
        response = await self.post_events([event, event])
        self.assertEqual(response.status_code, 200)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_called_once()
        self.assertIn("ยังตรวจรูปภาพ", self.module.reply_to_line.call_args.args[1])

    async def test_private_image_requires_identity_before_work(self):
        event = private_event()
        event["message"] = {"type": "image", "id": "1", "contentProvider": {"type": "line"}, "quoteToken": "offline"}
        event.pop("webhookEventId")
        response = await self.post_events([event])
        self.assertEqual(response.status_code, 400)
        self.module.reply_to_line.assert_not_called()

    async def test_bad_signature_cannot_trigger_private_analysis(self):
        response = await self.post_events([private_event()], valid_signature=False)
        self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()

    async def test_same_private_event_only_replies_once(self):
        self.module.analyze_message.return_value = result("no_risk_found")
        await self.post_events([private_event(), private_event()])
        self.module.analyze_message.assert_called_once()
        self.module.reply_to_line.assert_called_once()

    async def test_mixed_group_and_private_preserve_modes(self):
        self.module.analyze_message.side_effect = [{"is_scam": False}, result("no_risk_found")]
        await self.post_events([fixtures.text_event(number=1), private_event(number=2)])
        calls = self.module.analyze_message.call_args_list
        self.assertEqual(calls[0].kwargs, {})
        self.assertEqual(calls[1].kwargs, {"private": True})
        self.module.reply_to_line.assert_called_once()
        self.assertEqual(self.module.reply_to_line.call_args.args[0], "reply-2")

    async def test_private_reply_exception_does_not_stop_next_event(self):
        self.module.analyze_message.return_value = result("no_risk_found")
        self.module.reply_to_line.side_effect = [RuntimeError("SECRET"), True]
        response = await self.post_events([private_event(number=1), private_event(number=2)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module.reply_to_line.call_count, 2)


if __name__ == "__main__":
    unittest.main()
