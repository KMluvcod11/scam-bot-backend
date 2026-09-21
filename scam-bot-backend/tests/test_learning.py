"""ทดสอบปุ่ม/เจ้าของ/หมดอายุ ผ่าน webhook จริงในเครื่อง ไม่เรียกบริการภายนอก."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import test_webhook_threadpool as fixtures
from test_private_chat import private_event, result


def postback(case_id, number=10, owner="offline-user"):
    event = private_event(number=number)
    event.pop("message")
    event["type"] = "postback"
    event["source"]["userId"] = owner
    event["postback"] = {"data": f"learn:{case_id}"}
    return event


class LearningTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.WebhookThreadpoolTests.asyncSetUp
    asyncTearDown = fixtures.WebhookThreadpoolTests.asyncTearDown
    post_events = fixtures.WebhookThreadpoolTests.post_events

    async def create_case(self, text="ส่ง OTP มา", number=1, status="risk_found"):
        self.module.analyze_message.return_value = result(status)
        response = await self.post_events([private_event(text, number)])
        self.assertEqual(response.status_code, 200)
        return self.module.reply_to_line.call_args.kwargs["learn_case_id"]

    async def test_button_reads_original_case_not_latest_without_ai(self):
        first = await self.create_case("ส่ง OTP มา", 1)
        second = await self.create_case("รับประกันกำไร ไม่มีความเสี่ยง", 2)
        self.assertNotEqual(first, second)
        self.module.analyze_message.reset_mock()
        await self.post_events([postback(first)])
        lesson = self.module.reply_to_line.call_args.args[1]
        self.assertIn("OTP", lesson)
        self.assertNotIn("รับประกันกำไร", lesson)
        self.module.analyze_message.assert_not_called()

    async def test_owner_mismatch_unknown_and_expired_do_not_disclose(self):
        now = [0]
        self.module.lesson_store = self.module.LessonStore(clock=lambda: now[0])
        case_id = await self.create_case()
        await self.post_events([postback(case_id, 10, "another-user")])
        denied = self.module.reply_to_line.call_args.args[1]
        self.assertNotIn("OTP", denied)
        await self.post_events([postback("f" * 32, 11)])
        self.assertEqual(self.module.reply_to_line.call_args.args[1], denied)
        now[0] = 900
        await self.post_events([postback(case_id, 12)])
        self.assertEqual(self.module.reply_to_line.call_args.args[1], denied)
        self.assertEqual(len(self.module.lesson_store._cases), 0)

    async def test_duplicate_click_is_handled_once(self):
        case_id = await self.create_case()
        self.module.reply_to_line.reset_mock()
        await self.post_events([postback(case_id), postback(case_id)])
        self.module.reply_to_line.assert_called_once()

    async def test_signature_and_required_fields_checked_before_learning(self):
        case_id = await self.create_case()
        self.module.reply_to_line.reset_mock()
        response = await self.post_events([postback(case_id)], valid_signature=False)
        self.assertEqual(response.status_code, 400)
        for field in ("webhookEventId", "replyToken"):
            event = postback(case_id)
            event.pop(field)
            self.assertEqual((await self.post_events([event])).status_code, 400)
        event = postback(case_id)
        event["source"].pop("userId")
        self.assertEqual((await self.post_events([event])).status_code, 400)
        event = postback(case_id)
        event["postback"]["data"] = ["invalid"]
        self.assertEqual((await self.post_events([event])).status_code, 400)
        self.module.reply_to_line.assert_not_called()

    async def test_group_and_room_cannot_open_private_lesson(self):
        case_id = await self.create_case()
        self.module.reply_to_line.reset_mock()
        self.module.analyze_message.reset_mock()
        for number, kind in enumerate(("group", "room"), 10):
            event = postback(case_id, number)
            event["source"] = {"type": kind, f"{kind}Id": "offline", "userId": "offline-user"}
            self.assertEqual((await self.post_events([event])).status_code, 200)
        self.module.reply_to_line.assert_not_called()
        self.module.analyze_message.assert_not_called()

    async def test_no_button_for_conversation_errors_or_inconsistent_result(self):
        for number, status in enumerate(("conversation", "error", "fallback"), 1):
            self.module.analyze_message.return_value = result(status)
            await self.post_events([private_event(number=number)])
            self.assertEqual(self.module.reply_to_line.call_args.kwargs, {})
        self.module.analyze_message.return_value = {**result("risk_found"), "is_scam": False}
        await self.post_events([private_event(number=5)])
        self.assertEqual(self.module.reply_to_line.call_args.kwargs, {})
        self.assertEqual(len(self.module.lesson_store._cases), 0)

    async def test_negative_and_uncertain_reply_without_button_or_stored_lesson(self):
        for number, status in enumerate(("no_risk_found", "uncertain"), 1):
            text = "คำเตือน: อย่าส่ง OTP ให้ใคร"
            self.module.analyze_message.return_value = result(status)
            response = await self.post_events([private_event(text, number)])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.module.reply_to_line.call_args.kwargs, {})
            self.assertEqual(self.module.reply_to_line.call_args.args[1],
                             self.module.private_reply(result(status), text))
        self.assertEqual(len(self.module.lesson_store._cases), 0)

    async def test_group_warning_stays_text_only(self):
        self.module.analyze_message.return_value = result("risk_found")
        await self.post_events([fixtures.text_event()])
        self.assertEqual(self.module.reply_to_line.call_args.kwargs, {})
        self.assertEqual(len(self.module.lesson_store._cases), 0)

    async def test_store_full_or_learning_error_preserves_detection_reply(self):
        self.module.lesson_store = self.module.LessonStore(max_entries=1)
        first = await self.create_case()
        await self.post_events([private_event(number=2)])
        self.assertEqual(self.module.reply_to_line.call_args.kwargs, {})
        self.assertIn("พบสัญญาณเสี่ยง", self.module.reply_to_line.call_args.args[1])
        self.assertIsNotNone(self.module.lesson_store.get(first, "offline-user"))
        with patch.object(self.module, "build_lesson", side_effect=ValueError("SECRET")):
            await self.post_events([private_event(number=3)])
        self.assertIn("พบสัญญาณเสี่ยง", self.module.reply_to_line.call_args.args[1])

    async def test_missing_owner_never_creates_case(self):
        event = private_event()
        event["source"].pop("userId")
        self.module.analyze_message.return_value = result("risk_found")
        response = await self.post_events([event])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module.reply_to_line.call_args.kwargs, {})
        self.assertEqual(len(self.module.lesson_store._cases), 0)

    async def test_restart_invalidates_old_button(self):
        case_id = await self.create_case()
        self.module.lesson_store = self.module.LessonStore()
        await self.post_events([postback(case_id)])
        self.assertIn("ไม่สามารถเปิดบทเรียน", self.module.reply_to_line.call_args.args[1])

    async def test_send_failure_does_not_stop_following_click(self):
        case_id = await self.create_case()
        self.module.reply_to_line.reset_mock()
        self.module.reply_to_line.side_effect = [RuntimeError("SECRET"), True]
        response = await self.post_events([postback(case_id, 10), postback(case_id, 11)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module.reply_to_line.call_count, 2)


class LearningPayloadTests(unittest.TestCase):
    def test_template_payload_limits_and_no_private_data_in_action(self):
        config = ModuleType("config")
        config.LINE_CHANNEL_ACCESS_TOKEN = "offline-token"
        path = Path(__file__).resolve().parents[1] / "messaging.py"
        spec = importlib.util.spec_from_file_location("messaging_under_test", path)
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", [str(path.parent), *sys.path]), patch.dict(sys.modules, {"config": config}):
            spec.loader.exec_module(module)
        with patch.object(module.requests, "post", return_value=Mock()) as post:
            self.assertTrue(module.reply_to_line("offline-reply", "ผลตรวจ", learn_case_id="a" * 32))
            payload = post.call_args.kwargs["json"]
            self.assertEqual(len(payload["messages"]), 2)
            template = payload["messages"][1]["template"]
            self.assertLessEqual(len(template["text"]), 160)
            action = template["actions"][0]
            self.assertLessEqual(len(action["label"]), 20)
            self.assertEqual(action["data"], "learn:" + "a" * 32)
            self.assertEqual(action["type"], "postback")
            self.assertNotIn("text", action)
            module.reply_to_line("offline-reply", "ผลตรวจ")
            self.assertEqual(post.call_args.kwargs["json"]["messages"], [{"type": "text", "text": "ผลตรวจ"}])


if __name__ == "__main__":
    unittest.main()
