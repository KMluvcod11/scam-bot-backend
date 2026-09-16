"""ทดสอบ Webhook ในเครื่อง: ใช้ FastAPI/LINE parser จริง แต่จำลอง AI และการส่ง LINE."""
import asyncio
import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import threading
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import httpx
# โหลด framework ก่อน patch sys.modules เพื่อให้ parser และ main ใช้ class ชุดเดียวกัน
import fastapi
import fastapi.concurrency
import linebot.v3.webhook
import linebot.v3.webhooks


def load_app():
    # แทน config/detector/messaging ก่อน import: ไม่อ่าน .env หรือเรียกบริการจริง
    config = ModuleType("config")
    config.LINE_CHANNEL_SECRET = "offline-test-secret"
    detector = ModuleType("detector")
    detector.analyze_message = Mock(return_value={"is_scam": False})
    messaging = ModuleType("messaging")
    messaging.reply_to_line = Mock(return_value=True)
    path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("webhook_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(path.parent), *sys.path]), patch.dict(sys.modules, {
        "config": config, "detector": detector, "messaging": messaging,
    }):
        spec.loader.exec_module(module)
    return module


def text_event(text="ข้อความทดสอบ", number=1):
    return {
        "type": "message", "timestamp": 0, "mode": "active",
        "webhookEventId": f"event-{number}",
        "deliveryContext": {"isRedelivery": False},
        "source": {"type": "user", "userId": "offline-user"},
        "replyToken": f"reply-{number}",
        "message": {"type": "text", "id": str(number), "text": text,
                    "quoteToken": "offline-quote"},
    }


class WebhookThreadpoolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = load_app()
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.module.app), base_url="http://test",
        )
        # ไม่ให้ข้อความ log ทำให้ผลทดสอบอ่านยาก
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)

    async def asyncTearDown(self):
        await self.http.aclose()

    async def post_events(self, events, valid_signature=True):
        body = json.dumps({"destination": "offline-bot", "events": events}).encode()
        signature = base64.b64encode(hmac.new(
            b"offline-test-secret", body, hashlib.sha256,
        ).digest()).decode()
        return await self.http.post("/webhook", content=body, headers={
            "Content-Type": "application/json",
            "X-Line-Signature": signature if valid_signature else "invalid",
        })

    async def test_safe_message_returns_200_without_reply(self):
        response = await self.post_events([text_event()])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), "OK")
        self.module.analyze_message.assert_called_once_with("ข้อความทดสอบ")
        self.module.reply_to_line.assert_not_called()

    async def test_scam_reply_runs_after_analysis_in_worker_threads(self):
        order = []
        loop_thread = threading.get_ident()

        def analyze(text):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            order.append("analyze")
            return {"is_scam": True, "risk_level": "high", "reason": "เหตุผลทดสอบ"}

        def reply(token, message):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            self.assertEqual(token, "reply-1")
            self.assertIn("HIGH", message)
            self.assertIn("เหตุผลทดสอบ", message)
            order.append("reply")
            return True

        self.module.analyze_message.side_effect = analyze
        self.module.reply_to_line.side_effect = reply
        response = await self.post_events([text_event()])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order, ["analyze", "reply"])

    async def test_health_responds_while_analysis_or_reply_is_waiting(self):
        # จำลองเครือข่ายที่ยังไม่ตอบ แล้วตรวจว่าคำขอ GET / ยังทำงานได้
        for stage in ("analysis", "reply"):
            with self.subTest(stage=stage):
                started, release = threading.Event(), threading.Event()
                scam = {"is_scam": True, "risk_level": "high", "reason": "test"}

                def slow_call(*args):
                    started.set()
                    if not release.wait(timeout=3):
                        raise TimeoutError("test worker was not released")
                    return scam if stage == "analysis" else True

                self.module.analyze_message.side_effect = slow_call if stage == "analysis" else None
                self.module.analyze_message.return_value = scam
                self.module.reply_to_line.side_effect = slow_call if stage == "reply" else None
                task = asyncio.create_task(self.post_events([text_event(number=1 if stage == "analysis" else 2)]))
                try:
                    for _ in range(100):
                        if started.is_set():
                            break
                        await asyncio.sleep(0.01)
                    self.assertTrue(started.is_set())
                    self.assertFalse(task.done())
                    health = await asyncio.wait_for(self.http.get("/"), timeout=1)
                    self.assertEqual(health.status_code, 200)
                    self.assertFalse(task.done())
                finally:
                    release.set()
                    response = await asyncio.wait_for(task, timeout=5)
                self.assertEqual(response.status_code, 200)

    async def test_multiple_events_keep_original_order(self):
        response = await self.post_events([text_event("first", 1), text_event("second", 2)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [call.args[0] for call in self.module.analyze_message.call_args_list],
            ["first", "second"],
        )

    async def test_non_text_and_empty_events_are_skipped(self):
        event = text_event()
        event["message"] = {"type": "image", "id": "1", "contentProvider": {"type": "line"}}
        for events in ([], [event]):
            response = await self.post_events(events)
            self.assertEqual(response.status_code, 200)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()

    async def test_invalid_signature_still_returns_400(self):
        response = await self.post_events([text_event()], valid_signature=False)
        self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()

    async def test_failed_reply_preserves_existing_200_behavior(self):
        self.module.analyze_message.return_value = {
            "is_scam": True, "risk_level": "medium", "reason": "test",
        }
        self.module.reply_to_line.return_value = False
        response = await self.post_events([text_event()])
        self.assertEqual(response.status_code, 200)
        self.module.reply_to_line.assert_called_once()

    async def test_detection_error_stays_silent_and_next_event_is_processed(self):
        self.module.analyze_message.side_effect = [
            {"status": "error", "is_scam": None, "error_stage": "embedding"},
            {"is_scam": True, "risk_level": "high", "reason": "test"},
        ]
        response = await self.post_events([text_event("first", 1), text_event("second", 2)])
        self.assertEqual(response.status_code, 200)
        self.module.reply_to_line.assert_called_once()
        self.assertEqual(self.module.reply_to_line.call_args.args[0], "reply-2")

    async def test_unexpected_analysis_error_does_not_stop_next_event(self):
        self.module.analyze_message.side_effect = [
            RuntimeError("SECRET_TEST"), {"is_scam": False},
        ]
        with patch("builtins.print") as output:
            response = await self.post_events([text_event("first", 1), text_event("second", 2)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module.analyze_message.call_count, 2)
        self.module.reply_to_line.assert_not_called()
        log = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("stage=analysis", log)
        self.assertNotIn("SECRET_TEST", log)

    async def test_fallback_not_warning_is_not_logged_as_safe(self):
        self.module.analyze_message.return_value = {"status": "fallback", "is_scam": False}
        with patch("builtins.print") as output:
            response = await self.post_events([text_event()])
        self.assertEqual(response.status_code, 200)
        self.module.reply_to_line.assert_not_called()
        log = " ".join(str(call) for call in output.call_args_list)
        self.assertNotIn("ปลอดภัย", log)
        self.assertIn("กฎสำรอง", log)

    async def test_fallback_warning_still_sends(self):
        self.module.analyze_message.return_value = {
            "status": "fallback", "is_scam": True, "risk_level": "medium", "reason": "test",
        }
        response = await self.post_events([text_event()])
        self.assertEqual(response.status_code, 200)
        self.module.reply_to_line.assert_called_once()

    async def test_reply_exception_does_not_stop_next_event(self):
        self.module.analyze_message.return_value = {
            "is_scam": True, "risk_level": "high", "reason": "test",
        }
        self.module.reply_to_line.side_effect = [RuntimeError("SECRET_TEST"), True]
        with patch("builtins.print") as output:
            response = await self.post_events([text_event("first", 1), text_event("second", 2)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module.reply_to_line.call_count, 2)
        log = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("stage=line_reply", log)
        self.assertNotIn("SECRET_TEST", log)


if __name__ == "__main__":
    unittest.main()
