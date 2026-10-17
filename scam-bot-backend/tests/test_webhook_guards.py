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

    def test_batch_is_atomic_when_capacity_is_full(self):
        self.assertIsNone(self.guard.claim_batch(["a", "b", "c"]))
        self.assertEqual(self.guard.claim_batch(["a", "a", "b"]),
                         ["new", "duplicate", "new"])
        self.assertEqual(self.guard.claim("c"), "full")


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
        self.module.save_detection.assert_called_once()

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

    async def test_full_batch_does_not_reserve_earlier_event(self):
        self.module.event_guard.max_entries = 1
        response = await self.post_events([fixtures.text_event(number=1), fixtures.text_event(number=2)])
        self.assertEqual(response.status_code, 503)
        self.module.analyze_message.assert_not_called()
        self.assertEqual((await self.post_events([fixtures.text_event(number=1)])).status_code, 200)
        self.module.analyze_message.assert_called_once()

    async def test_normal_nonwarning_log_does_not_claim_safety(self):
        with patch("builtins.print") as output:
            await self.post_events([fixtures.text_event()])
        log = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("ไม่เข้าเกณฑ์แจ้งเตือน", log)
        self.assertNotIn("ปลอดภัย", log)

    async def test_group_image_is_routed_without_analysis(self):
        event = fixtures.text_event()
        event["message"] = {
            "type": "image",
            "id" : "1",
            "contentProvider": {"type": "line"},
            "quoteToken": "offline",
        }
        with patch.object(
            self.module,
            "process_text_event",
            wraps=self.module.process_text_event,
        ) as process_text:
            response = await self.post_events([event,event])
            
        self.assertEqual(response.status_code, 200)
        process_text.assert_awaited_once()

        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_group_image_rejects_invalid_identity_before_work(self):
        for field in ("id","webhookEventId", "replyToken"):
            for value in (None, ""," ", 123):
                with self.subTest(field=field, value=value):
                    event = fixtures.text_event()
                    event["message"] = {
                        "type": "image",
                        "id" : "1",
                        "contentProvider": {"type": "line"},
                        "quoteToken": "offline",
                    }
                    target = event["message"] if field == "id" else event
                    if value is None:
                        target.pop(field)
                    else:
                        target[field] = value
                    response = await self.post_events([event])
                    self.assertEqual(response.status_code, 400)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_image_download_runs_once_in_worker_thread(self):
        request_thread = threading.get_ident()
        download_threads = []

        def download(message_id):
            download_threads.append(threading.get_ident())
            return b"offline-image", "image/jpeg"

        self.module.get_image_content.side_effect = download
        event = fixtures.image_event()

        response = await self.post_events([event, event])

        self.assertEqual(response.status_code, 200)
        self.module.get_image_content.assert_called_once_with("1")
        self.assertEqual(len(download_threads), 1)
        self.assertNotEqual(download_threads[0], request_thread)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_failed_image_download_keeps_next_text_working(self):
        self.module.get_image_content.return_value = None

        response = await self.post_events([
            fixtures.image_event(),
            fixtures.text_event("ข้อความถัดไป", number=2),
        ])

        self.assertEqual(response.status_code, 200)
        self.module.get_image_content.assert_called_once_with("1")
        self.module.analyze_message.assert_called_once_with("ข้อความถัดไป")
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_called_once()

    async def test_image_download_exception_keeps_next_text_working(self):
        self.module.get_image_content.side_effect = RuntimeError(
            "SECRET_IMAGE"
        )

        with patch("builtins.print") as logs:
            response = await self.post_events([
                fixtures.image_event(),
                fixtures.text_event("ข้อความถัดไป", number=2),
            ])

        self.assertEqual(response.status_code, 200)
        self.module.get_image_content.assert_called_once_with("1")
        self.module.analyze_message.assert_called_once_with("ข้อความถัดไป")
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_called_once()
        self.assertNotIn("SECRET_IMAGE", str(logs.call_args_list))


    async def test_image_analysis_runs_once_after_dataset_in_worker_without_content_logs(self):
        request_thread = threading.get_ident()
        stages = []
        image_bytes = b"SECRET_IMAGE_DATA"

        def download(message_id):
            stages.append(("download", threading.get_ident()))
            return image_bytes, "image/png"

        def read_image(data, mime_type):
            stages.append(("ocr", threading.get_ident()))
            return {"status": "ok", "text": "SECRET_OCR_TEXT"}

        def match_dataset(text):
            stages.append(("dataset", threading.get_ident()))
            return 87.5, "spam"

        def analyze_image(text, similarity_percent, matched_label, *, private):
            stages.append(("analysis", threading.get_ident()))
            return {
                "status": "risk_found", "is_scam": True,
                "risk_level": "high", "reason": "SECRET_IMAGE_REASON",
            }

        self.module.get_image_content.side_effect = download
        self.module.extract_text_from_image.side_effect = read_image
        self.module.find_similarity.side_effect = match_dataset
        self.module.analyze_with_llm.side_effect = analyze_image
        event = fixtures.image_event()

        with patch("builtins.print") as logs:
            response = await self.post_events([event, event])

        self.assertEqual(response.status_code, 200)
        self.module.get_image_content.assert_called_once_with("1")
        self.module.extract_text_from_image.assert_called_once_with(
            image_bytes, "image/png"
        )
        self.module.find_similarity.assert_called_once_with("SECRET_OCR_TEXT")
        self.module.analyze_with_llm.assert_called_once_with(
            "SECRET_OCR_TEXT", 87.5, "spam", private=True
        )
        self.assertEqual(
            [stage for stage, _ in stages], ["download", "ocr", "dataset", "analysis"]
        )
        for stage, thread_id in stages:
            with self.subTest(stage=stage):
                self.assertNotEqual(thread_id, request_thread)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_called_once()
        self.assertIn("พบสัญญาณเสี่ยง", self.module.reply_to_line.call_args.args[1])
        self.module.save_detection.assert_not_called()
        self.assertIn("status=ok", str(logs.call_args_list))
        self.assertIn("chars=15", str(logs.call_args_list))
        self.assertIn("similarity=87.50%", str(logs.call_args_list))
        self.assertIn("label=spam", str(logs.call_args_list))
        self.assertIn("[IMAGE RESULT]", str(logs.call_args_list))
        self.assertIn("status=risk_found", str(logs.call_args_list))
        self.assertIn("stage=image_analysis", str(logs.call_args_list))
        self.assertNotIn("SECRET_IMAGE_DATA", str(logs.call_args_list))
        self.assertNotIn("SECRET_OCR_TEXT", str(logs.call_args_list))
        self.assertNotIn("SECRET_IMAGE_REASON", str(logs.call_args_list))

    async def test_failed_download_does_not_call_ocr(self):
        failures = (None, RuntimeError("SECRET_DOWNLOAD"))
        for number, error in enumerate(failures, start=1):
            with self.subTest(error=type(error).__name__):
                self.module.get_image_content.reset_mock()
                self.module.get_image_content.return_value = None
                self.module.get_image_content.side_effect = error

                with patch("builtins.print") as logs:
                    response = await self.post_events([
                        fixtures.image_event(number=number)
                    ])

                self.assertEqual(response.status_code, 200)
                self.module.get_image_content.assert_called_once_with(str(number))
                self.module.extract_text_from_image.assert_not_called()
                self.module.find_similarity.assert_not_called()
                self.module.analyze_with_llm.assert_not_called()
                self.assertNotIn("SECRET_DOWNLOAD", str(logs.call_args_list))

        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_uncertain_or_failed_ocr_is_not_treated_as_a_risk_assessment(self):
        for number, status in enumerate(("uncertain", "error"), start=1):
            with self.subTest(status=status):
                self.module.extract_text_from_image.reset_mock()
                self.module.extract_text_from_image.return_value = {
                    "status": status,
                    "text": "",
                }

                with patch("builtins.print") as logs:
                    response = await self.post_events([
                        fixtures.image_event(number=number)
                    ])

                self.assertEqual(response.status_code, 200)
                self.module.extract_text_from_image.assert_called_once_with(
                    b"offline-image", "image/jpeg"
                )
                self.assertIn(f"status={status}", str(logs.call_args_list))
                self.assertIn("chars=0", str(logs.call_args_list))
                self.module.find_similarity.assert_not_called()
                self.module.analyze_with_llm.assert_not_called()

        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_ocr_exception_keeps_next_text_working_without_secret_logs(self):
        self.module.extract_text_from_image.side_effect = RuntimeError(
            "SECRET_OCR_ERROR"
        )

        with patch("builtins.print") as logs:
            response = await self.post_events([
                fixtures.image_event(),
                fixtures.text_event("ข้อความถัดไป", number=2),
            ])

        self.assertEqual(response.status_code, 200)
        self.module.get_image_content.assert_called_once_with("1")
        self.module.extract_text_from_image.assert_called_once_with(
            b"offline-image", "image/jpeg"
        )
        self.module.analyze_message.assert_called_once_with("ข้อความถัดไป")
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_called_once()
        self.assertIn("status=error", str(logs.call_args_list))
        self.assertIn("chars=0", str(logs.call_args_list))
        self.assertNotIn("SECRET_OCR_ERROR", str(logs.call_args_list))
        self.module.find_similarity.assert_not_called()
        self.module.analyze_with_llm.assert_not_called()

    async def test_private_image_runs_analysis_once_and_replies_once_without_history(self):
        event = fixtures.image_event()
        event["source"] = {"type": "user", "userId": "U-private"}

        response = await self.post_events([event, event])

        self.assertEqual(response.status_code, 200)
        self.module.extract_text_from_image.assert_called_once_with(
            b"offline-image", "image/jpeg"
        )
        self.module.find_similarity.assert_called_once_with(
            self.module.extract_text_from_image.return_value["text"]
        )
        self.module.analyze_with_llm.assert_called_once_with(
            self.module.extract_text_from_image.return_value["text"],
            87.5, "spam", private=True,
        )
        self.module.reply_to_line.assert_called_once()
        self.module.analyze_message.assert_not_called()
        self.module.save_detection.assert_not_called()


    async def test_image_miss_ham_or_high_spam_match_still_gets_context_analysis(self):
        matches = ((0.0, None), (96.0, "ham"), (99.9, "spam"))
        for number, result in enumerate(matches, start=1):
            with self.subTest(result=result):
                self.module.find_similarity.reset_mock()
                self.module.analyze_with_llm.reset_mock()
                self.module.find_similarity.return_value = result

                with patch("builtins.print") as logs:
                    response = await self.post_events([
                        fixtures.image_event(number=number)
                    ])

                self.assertEqual(response.status_code, 200)
                self.module.find_similarity.assert_called_once_with(
                    self.module.extract_text_from_image.return_value["text"]
                )
                self.module.analyze_with_llm.assert_called_once_with(
                    self.module.extract_text_from_image.return_value["text"],
                    result[0], result[1], private=True,
                )
                self.assertIn(f"similarity={result[0]:.2f}%", str(logs.call_args_list))
                self.assertIn(f"label={result[1]}", str(logs.call_args_list))

        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_dataset_exception_keeps_next_text_working_without_secret_logs(self):
        self.module.extract_text_from_image.return_value = {
            "status": "ok", "text": "SECRET_LOOKUP_TEXT"
        }
        self.module.find_similarity.side_effect = RuntimeError("SECRET_DATASET_ERROR")

        with patch("builtins.print") as logs:
            response = await self.post_events([
                fixtures.image_event(),
                fixtures.text_event("ข้อความถัดไป", number=2),
            ])

        self.assertEqual(response.status_code, 200)
        self.module.get_image_content.assert_called_once_with("1")
        self.module.extract_text_from_image.assert_called_once_with(
            b"offline-image", "image/jpeg"
        )
        self.module.find_similarity.assert_called_once_with("SECRET_LOOKUP_TEXT")
        self.module.analyze_with_llm.assert_not_called()
        self.module.analyze_message.assert_called_once_with("ข้อความถัดไป")
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_called_once()
        self.assertIn("[IMAGE MATCH ERROR]", str(logs.call_args_list))
        self.assertIn("type=RuntimeError", str(logs.call_args_list))
        self.assertNotIn("SECRET_LOOKUP_TEXT", str(logs.call_args_list))
        self.assertNotIn("SECRET_DATASET_ERROR", str(logs.call_args_list))


    async def test_group_image_only_warns_for_risk_and_does_not_log_reason(self):
        statuses = ("risk_found", "no_risk_found", "uncertain", "error")
        for number, status in enumerate(statuses, start=1):
            with self.subTest(status=status):
                self.module.analyze_with_llm.reset_mock()
                self.module.analyze_with_llm.return_value = {
                    "status": status,
                    "is_scam": None if status == "error" else status == "risk_found",
                    "risk_level": "low", "reason": "SECRET_IMAGE_REASON",
                }

                with patch("builtins.print") as logs:
                    response = await self.post_events([
                        fixtures.image_event(number=number)
                    ])

                self.assertEqual(response.status_code, 200)
                self.module.analyze_with_llm.assert_called_once_with(
                    self.module.extract_text_from_image.return_value["text"],
                    87.5, "spam", private=True,
                )
                self.assertIn("[IMAGE RESULT]", str(logs.call_args_list))
                self.assertIn(f"status={status}", str(logs.call_args_list))
                self.assertNotIn("SECRET_IMAGE_REASON", str(logs.call_args_list))

        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_called_once()
        self.assertEqual(self.module.reply_to_line.call_args.args[0], "reply-1")
        self.module.save_detection.assert_not_called()

    async def test_image_analysis_exception_keeps_next_text_without_secret_logs(self):
        self.module.analyze_with_llm.side_effect = RuntimeError("SECRET_IMAGE_ANALYSIS_ERROR")

        with patch("builtins.print") as logs:
            response = await self.post_events([
                fixtures.image_event(),
                fixtures.text_event("ข้อความถัดไป", number=2),
            ])

        self.assertEqual(response.status_code, 200)
        self.module.find_similarity.assert_called_once()
        self.module.analyze_with_llm.assert_called_once_with(
            self.module.extract_text_from_image.return_value["text"],
            87.5, "spam", private=True,
        )
        self.module.analyze_message.assert_called_once_with("ข้อความถัดไป")
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_called_once()
        self.assertIn("[IMAGE ANALYSIS ERROR]", str(logs.call_args_list))
        self.assertIn("type=RuntimeError", str(logs.call_args_list))
        self.assertIn("status=error", str(logs.call_args_list))
        self.assertNotIn("SECRET_IMAGE_ANALYSIS_ERROR", str(logs.call_args_list))


    async def test_group_and_room_without_readable_text_skip_lookup_analysis_and_reply(self):
        number = 0
        for source in ("group", "room"):
            for status in ("uncertain", "error"):
                number += 1
                with self.subTest(source=source, status=status):
                    self.module.extract_text_from_image.reset_mock()
                    self.module.extract_text_from_image.return_value = {"status": status, "text": ""}
                    event = fixtures.image_event(number)
                    event["source"] = {"type": source, source + "Id": "offline-chat", "userId": "offline-user"}
                    with patch("builtins.print") as logs:
                        response = await self.post_events([event, event])
                    self.assertEqual(response.status_code, 200)
                    self.module.extract_text_from_image.assert_called_once()
                    self.assertNotIn("[EVENT ERROR]", str(logs.call_args_list))
        self.module.find_similarity.assert_not_called()
        self.module.analyze_with_llm.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_room_image_warns_once_only_for_consistent_risk_result(self):
        for number, flag in enumerate((True, False, None), start=1):
            with self.subTest(is_scam=flag):
                self.module.reply_to_line.reset_mock()
                self.module.analyze_with_llm.return_value = {
                    "status": "risk_found", "is_scam": flag,
                    "risk_level": "high", "reason": "เหตุผลทดสอบ",
                }
                event = fixtures.image_event(number)
                event["source"] = {"type": "room", "roomId": "offline-room", "userId": "offline-user"}
                response = await self.post_events([event, event])
                self.assertEqual(response.status_code, 200)
                if flag is True:
                    self.module.reply_to_line.assert_called_once()
                    self.assertIn("พบสัญญาณเสี่ยง", self.module.reply_to_line.call_args.args[1])
                else:
                    self.module.reply_to_line.assert_not_called()


if __name__ == "__main__":
    unittest.main()
