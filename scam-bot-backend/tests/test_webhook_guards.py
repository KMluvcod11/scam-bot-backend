"""ทดสอบกันซ้ำ ลายเซ็น และ payload เสีย โดยส่ง HTTP ในเครื่องเท่านั้น."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import threading
import unittest
from unittest.mock import patch

import test_webhook_threadpool as fixtures


class EventGuardTests(unittest.TestCase):
    def setUp(self):
        guard_type = type(fixtures.load_app().event_guard)
        self.now = 0.0
        self.guard = guard_type(ttl_seconds=10, max_entries=2, clock=lambda: self.now)

    def test_active_and_completed_ids_are_duplicates(self):
        self.assertEqual(self.guard.claim("a"), "new")
        self.assertEqual(self.guard.claim("a"), "duplicate")
        self.guard.finish("a")
        self.assertEqual(self.guard.claim("a"), "duplicate")

    def test_completed_id_expires_but_active_id_does_not(self):
        self.guard.claim("done")
        self.guard.finish("done")
        self.guard.claim("active")
        self.now = 11
        self.assertEqual(self.guard.claim("done"), "new")
        self.assertEqual(self.guard.claim("active"), "duplicate")

    def test_capacity_is_bounded_without_evicting_live_ids(self):
        self.guard.claim("a")
        self.guard.finish("a")
        self.guard.claim("b")
        self.assertEqual(self.guard.claim("c"), "full")
        self.assertEqual(self.guard.claim("a"), "duplicate")
        self.now = 11
        self.assertEqual(self.guard.claim("c"), "new")

    def test_parallel_claims_have_one_owner(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.guard.claim, ["same"] * 30))
        self.assertEqual(results.count("new"), 1)
        self.assertEqual(results.count("duplicate"), 29)


class WebhookGuardTests(unittest.IsolatedAsyncioTestCase):
    # ใช้ตัวช่วยเดิม แต่ไม่สืบทอด test เดิมมารันซ้ำ
    asyncSetUp = fixtures.WebhookThreadpoolTests.asyncSetUp
    asyncTearDown = fixtures.WebhookThreadpoolTests.asyncTearDown
    post_events = fixtures.WebhookThreadpoolTests.post_events

    async def post_raw(self, body, signature="auto"):
        if signature == "auto":
            signature = base64.b64encode(hmac.new(
                b"offline-test-secret", body, hashlib.sha256,
            ).digest()).decode()
        headers = {"Content-Type": "application/json"}
        if signature is not None:
            headers["X-Line-Signature"] = signature
        return await self.http.post("/webhook", content=body, headers=headers)

    async def test_missing_or_empty_signature_returns_400(self):
        for signature in (None, "", "   "):
            with self.subTest(signature=signature):
                response = await self.post_raw(b'{"events": []}', signature)
                self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()

    async def test_bad_utf8_and_bad_json_return_400(self):
        for body in (b"\xff", b"", b"not-json", b'{"events":'):
            with self.subTest(body=body):
                response = await self.post_raw(body)
                self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()

    async def test_invalid_payload_shapes_return_400(self):
        for value in (None, [], 5, {}, {"events": None}, {"events": {}},
                      {"events": [None]}, {"events": [1]}, {"events": [{}]},
                      {"events": [{"type": "message", "message": None}]}):
            with self.subTest(value=value):
                response = await self.post_raw(json.dumps(value).encode())
                self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()

    async def test_text_missing_fields_returns_400_before_any_work(self):
        mutations = [
            lambda e: e.pop("webhookEventId"),
            lambda e: e.update(webhookEventId=""),
            lambda e: e.update(webhookEventId=3),
            lambda e: e.pop("replyToken"),
            lambda e: e["message"].update(text=None),
            lambda e: e["message"].update(text=123),
            lambda e: e["message"].pop("quoteToken"),
        ]
        for mutate in mutations:
            event = fixtures.text_event(number=2)
            mutate(event)
            response = await self.post_events([fixtures.text_event(), event])
            self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()

    async def test_invalid_signature_does_not_reserve_id(self):
        event = fixtures.text_event()
        response = await self.post_events([event], valid_signature=False)
        self.assertEqual(response.status_code, 400)
        response = await self.post_events([event])
        self.assertEqual(response.status_code, 200)
        self.module.analyze_message.assert_called_once()

    async def test_changed_body_rejects_original_signature(self):
        original = json.dumps({"events": [fixtures.text_event("original")]}).encode()
        signature = base64.b64encode(hmac.new(
            b"offline-test-secret", original, hashlib.sha256,
        ).digest()).decode()
        response = await self.post_raw(original.replace(b"original", b"modified"), signature)
        self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()

    async def test_repeated_delivery_only_analyzes_and_replies_once(self):
        self.module.analyze_message.return_value = {
            "is_scam": True, "risk_level": "high", "reason": "test",
        }
        event = fixtures.text_event()
        self.assertEqual((await self.post_events([event, event])).status_code, 200)
        event["deliveryContext"]["isRedelivery"] = True
        self.assertEqual((await self.post_events([event])).status_code, 200)
        self.module.analyze_message.assert_called_once()
        self.module.reply_to_line.assert_called_once()

    async def test_first_seen_redelivery_and_same_text_new_id_are_processed(self):
        first = fixtures.text_event(number=1)
        first["deliveryContext"]["isRedelivery"] = True
        response = await self.post_events([first, fixtures.text_event(number=2)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module.analyze_message.call_count, 2)

    async def test_concurrent_duplicate_does_not_start_second_analysis(self):
        started, release = threading.Event(), threading.Event()

        def slow_analysis(text):
            started.set()
            if not release.wait(3):
                raise TimeoutError("test worker not released")
            return {"is_scam": False}

        self.module.analyze_message.side_effect = slow_analysis
        task = asyncio.create_task(self.post_events([fixtures.text_event()]))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(started.is_set())
            response = await asyncio.wait_for(self.post_events([fixtures.text_event()]), 1)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(task.done())
            self.module.analyze_message.assert_called_once()
        finally:
            release.set()
            await asyncio.wait_for(task, 5)

    async def test_failed_analysis_and_send_are_not_retried(self):
        self.module.analyze_message.side_effect = [
            RuntimeError("test"), {"is_scam": True, "risk_level": "high", "reason": "test"},
        ]
        self.module.reply_to_line.return_value = False
        events = [fixtures.text_event(number=1), fixtures.text_event(number=2)]
        for _ in range(2):
            self.assertEqual((await self.post_events(events)).status_code, 200)
        self.assertEqual(self.module.analyze_message.call_count, 2)
        self.module.reply_to_line.assert_called_once()

    async def test_full_cache_returns_503_without_processing_new_event(self):
        self.module.event_guard.max_entries = 1
        self.assertEqual((await self.post_events([fixtures.text_event(number=1)])).status_code, 200)
        self.assertEqual((await self.post_events([fixtures.text_event(number=2)])).status_code, 503)
        self.module.analyze_message.assert_called_once()

    async def test_normal_nonwarning_log_does_not_claim_safety(self):
        with patch("builtins.print") as output:
            await self.post_events([fixtures.text_event()])
        log = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("ไม่เข้าเกณฑ์แจ้งเตือน", log)
        self.assertNotIn("ปลอดภัย", log)


if __name__ == "__main__":
    unittest.main()
