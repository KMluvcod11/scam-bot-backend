"""ตรวจส่วนตัวด้วย client จำลอง: ไม่อ่านคีย์ ไม่ใช้โควตา และไม่ส่ง LINE จริง."""
import json
import os
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


def warning_kwargs(save_mock):
    """เช็กเฉพาะผลการแจ้งเตือน; แชตส่วนตัวมี case_id/image_text เพิ่มซึ่งเทสต์อื่นตรวจแยก."""
    kwargs = save_mock.call_args.kwargs
    return {key: kwargs[key] for key in ("warning_attempted", "warning_sent") if key in kwargs}


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

    def test_private_prompt_distinguishes_submitted_conversation_from_bot_help(self):
        # Checks the instructions sent to the SDK, NOT real model accuracy.
        expected = result("no_risk_found")
        self.d.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(expected))
        text = "พรุ่งนี้เข้ามาคุยเรื่องรายงานตอนสิบโมงนะครับ"
        self.assertEqual(self.d.analyze_with_llm(text, 80.33, "ham", private=True), expected)
        prompt = self.d.client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("ห้ามใช้ conversation เพียงเพราะข้อความเป็นบทสนทนา", prompt)
        self.assertIn("ไม่ใช่เพียงไม่รู้ตัวตนผู้ส่งหรือสถานที่นัดหมาย", prompt)
        self.assertIn("คำทักทายที่ตามด้วยการชักชวนเสี่ยงต้องไม่ถูกข้าม", prompt)
        self.assertTrue(prompt.rstrip().endswith(json.dumps(text, ensure_ascii=False)))
        self.assertNotIn("conversation = สนทนาทั่วไปหรือถามนอกหน้าที่", prompt)

    def test_private_prompt_limits_claims_to_text_evidence(self):
        # Verifies prompt wiring, not whether the real model follows it.
        expected = result("risk_found")
        self.d.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(expected))
        text = "ได้รับรางวัล โอนค่าธรรมเนียมภายใน 10 นาที"
        self.assertEqual(self.d.analyze_with_llm(text, 85, "spam", private=True), expected)
        prompt = self.d.client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("ห้ามฟันธงว่าเป็นรางวัลปลอม", prompt)
        self.assertIn("มีการขอค่าธรรมเนียมก่อนรับรางวัลและกำหนดเวลาเร่งให้โอน", prompt)
        self.assertIn('ไม่ตีความ "เริ่มงานได้ทันที" ว่าเร่งโอนเงิน', prompt)
        self.assertTrue(prompt.rstrip().endswith(json.dumps(text, ensure_ascii=False)))

    def test_group_prompt_distinguishes_normal_sales_from_combined_risk(self):
        # ตรวจคำสั่งที่ส่งให้ SDK ไม่ใช่ผลตัดสินของ AI จริง
        expected = result("risk_found")
        self.d.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(expected))
        text = "เสื้อตัวสุดท้าย โอนมัดจำ 300 บาทภายใน 10 นาที ทักนอกแอป ไม่รับชำระผ่านระบบ"
        self.d.analyze_with_llm(text, 85, "spam")
        prompt = self.d.client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("ซื้อขายตามปกติ", prompt)
        self.assertIn("เร่งโอนมัดจำ พร้อมชวนคุยนอกแอปและไม่รับชำระผ่านระบบ", prompt)
        self.assertIn('ไม่ใช่เพียงคำว่า "ซื้อขาย" หรือ "มัดจำ"', prompt)
        self.assertIn("แยกคำเตือนภัยหรือการยกตัวอย่าง", prompt)
        self.assertIn("ไม่ฟันธงว่ารางวัลปลอมหรือเว็บฟิชชิง", prompt)

    def test_image_and_private_prompt_do_not_invent_reward_evidence(self):
        expected = result("uncertain")
        self.d.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(expected))
        self.d.analyze_with_llm("แจกเงิน https://example.invalid", 85, "spam", private=True)
        prompt = self.d.client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("ไม่ใช่หลักฐานยืนยันว่ารางวัลปลอมหรือเว็บฟิชชิง", prompt)
        self.assertIn("ห้ามเติมการขอข้อมูลหรือโอนเงินที่ไม่มีในข้อความ", prompt)
        self.assertIn("OCR อาจอ่านคลาดเคลื่อน", prompt)

    def test_private_prompt_includes_dataset_metadata_without_another_lookup(self):
        # ตรวจข้อมูลที่ส่งให้ SDK ไม่ใช่ความแม่นยำของ AI จริง
        expected = result("uncertain")
        text = 'SECRET_OCR_TEXT\n"โอนค่าธรรมเนียมก่อนรับรางวัล"'
        generate = self.d.client.models.generate_content
        prefix = "ข้อมูลประกอบจาก dataset (JSON):\n"

        with patch.object(self.d, "find_similarity") as lookup:
            for score, label in ((78.59, "spam"), (99.2, "ham"), (0.0, None)):
                with self.subTest(score=score, label=label):
                    generate.reset_mock()
                    generate.return_value = SimpleNamespace(text=json.dumps(expected))

                    actual = self.d.analyze_with_llm(text, score, label, private=True)

                    self.assertEqual(actual, expected)
                    generate.assert_called_once()
                    prompt = generate.call_args.kwargs["contents"]
                    self.assertTrue(prompt.startswith(prefix))
                    context, _ = json.JSONDecoder().raw_decode(prompt[len(prefix):])
                    self.assertEqual(context, {
                        "similarity_percent": score, "matched_label": label,
                    })
                    self.assertIn("ความคล้าย ไม่ใช่โอกาสเป็นมิจฉาชีพ", prompt)
                    self.assertIn("ประเภทของตัวอย่าง ไม่ใช่คำตัดสินข้อความนี้", prompt)
                    self.assertIn("ห้ามตัดสินจากคะแนนหรือ label เพียงอย่างเดียว", prompt)
                    self.assertIn("ham หรือไม่พบตัวอย่าง ไม่ได้ยืนยันว่าปลอดภัย", prompt)
                    self.assertTrue(prompt.rstrip().endswith(
                        json.dumps(text, ensure_ascii=False)
                    ))

            lookup.assert_not_called()

    def test_private_failover_keeps_dataset_context_and_message_without_secret_logs(self):
        expected = result("uncertain")
        text = "SECRET_OCR_FAILOVER_TEXT"
        generate = self.d.client.models.generate_content
        generate.side_effect = [
            SimpleNamespace(text="invalid JSON"),
            SimpleNamespace(text=json.dumps(expected)),
        ]

        with patch("builtins.print") as logs:
            actual = self.d.analyze_with_llm(text, 78.59, "spam", private=True)

        self.assertEqual(actual, expected)
        self.assertEqual(generate.call_count, 2)
        prompts = [call.kwargs["contents"] for call in generate.call_args_list]
        self.assertEqual(prompts[0], prompts[1])
        context, _ = json.JSONDecoder().raw_decode(prompts[0].split("\n", 1)[1])
        self.assertEqual(context, {
            "similarity_percent": 78.59, "matched_label": "spam",
        })
        self.assertTrue(prompts[0].rstrip().endswith(json.dumps(text, ensure_ascii=False)))
        self.assertNotIn(text, str(logs.call_args_list))

    def test_group_prompt_does_not_receive_private_classification_instructions(self):
        expected = {"is_scam": False, "risk_level": "low", "reason": "เหตุผลทดสอบ"}
        self.d.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(expected))
        self.assertEqual(self.d.analyze_with_llm("นัดคุยงาน", 85, "ham"), expected)
        prompt = self.d.client.models.generate_content.call_args.kwargs["contents"]
        self.assertNotIn("ห้ามใช้ conversation", prompt)
        self.assertNotIn("ข้อมูลประกอบจาก dataset", prompt)
        self.assertNotIn('"matched_label"', prompt)

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

    async def test_ocr_debug_requires_explicit_opt_in_and_preserves_analysis_input(self):
        text = 'ข้อความทดสอบส่วนตัว\n"ลิงก์จากการ์ดพรีวิว"'
        self.module.extract_text_from_image.return_value = {"status": "ok", "text": text}
        for number, flag in enumerate((None, "0", "true", "1"), 1):
            with self.subTest(flag=flag), patch.dict(os.environ), patch("builtins.print") as logs:
                os.environ.pop("DEBUG_OCR_TEXT", None)
                if flag is not None:
                    os.environ["DEBUG_OCR_TEXT"] = flag
                event = fixtures.image_event(number)
                event["source"] = {"type": "user", "userId": "offline-user"}
                response = await self.post_events([event])
                self.assertEqual(response.status_code, 200)
                debug_lines = [str(arg) for call in logs.call_args_list for arg in call.args
                               if "[OCR DEBUG]" in str(arg)]
                if flag == "1":
                    self.assertEqual(debug_lines, ["[OCR DEBUG] text=" + json.dumps(text, ensure_ascii=False)])
                else:
                    self.assertEqual(debug_lines, [])
                    self.assertNotIn("ข้อความทดสอบส่วนตัว", str(logs.call_args_list))
                self.module.analyze_with_llm.assert_called_with(text, 87.5, "spam", private=True)

    async def test_private_log_contains_metadata_not_message(self):
        text = "สวัสดีครับ\nข้อความทดสอบ"
        self.module.analyze_message.return_value = result("conversation")
        with patch("builtins.print") as logs:
            await self.post_events([private_event(text)])
        incoming = [call for call in logs.call_args_list
                    if any("[MESSAGE] source=user" in str(arg) for arg in call.args)]
        self.assertEqual(len(incoming), 1)
        self.assertRegex(incoming[0].args[0], r"^\[trace=[0-9a-f]{8}\]$")
        self.assertEqual(incoming[0].args[1],
                         f"[MESSAGE] source=user chars={len(text)}")
        self.assertNotIn('ข้อความทดสอบ', str(logs.call_args_list))

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

    async def test_private_image_replies_and_saves_analysis_once(self):
        event = private_event()
        event["message"] = {"type": "image", "id": "1", "contentProvider": {"type": "line"}, "quoteToken": "offline"}
        response = await self.post_events([event, event])
        self.assertEqual(response.status_code, 200)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_called_once()
        self.module.analyze_with_llm.assert_called_once()
        reply = self.module.reply_to_line.call_args.args[1]
        self.assertIn("ข้อความที่อ่านได้ในรูป", reply)
        self.assertIn("ยังไม่พบสัญญาณหลอกลวงชัดเจน", reply)
        self.assertIn("ไม่รับรองว่าปลอดภัย", reply)
        self.module.save_detection.assert_called_once()
        self.assertEqual(warning_kwargs(self.module.save_detection), {
            "warning_attempted": True, "warning_sent": True,
        })

    async def test_private_image_returns_each_analysis_status(self):
        cases = (
            ("risk_found", "พบสัญญาณเสี่ยง"),
            ("no_risk_found", "ยังไม่พบสัญญาณหลอกลวงชัดเจน"),
            ("uncertain", "ยังประเมินข้อความในรูปได้ไม่ชัดเจน"),
            ("conversation", "ต้องการให้ช่วยตรวจส่วนไหน"),
        )
        for number, (status, expected) in enumerate(cases, start=1):
            with self.subTest(status=status):
                self.module.reply_to_line.reset_mock()
                self.module.save_detection.reset_mock()
                event = fixtures.image_event(number)
                event["source"] = {"type": "user", "userId": "offline-user"}
                with patch.object(self.module, "analyze_with_llm", return_value=result(status)) as analyze:
                    response = await self.post_events([event, event])
                self.assertEqual(response.status_code, 200)
                analyze.assert_called_once_with(
                    self.module.extract_text_from_image.return_value["text"],
                    87.5, "spam", private=True,
                )
                self.module.reply_to_line.assert_called_once()
                token, reply = self.module.reply_to_line.call_args.args
                self.assertEqual(token, event["replyToken"])
                self.assertIn(expected, reply)
                self.assertNotIn("ยังตรวจรูปภาพ", reply)
                self.module.save_detection.assert_called_once()
                self.assertEqual(self.module.save_detection.call_args.args[1]["status"], status)
                self.assertEqual(warning_kwargs(self.module.save_detection), {
                    "warning_attempted": True, "warning_sent": True,
                })
        self.module.analyze_message.assert_not_called()

    async def test_private_image_failures_reply_once_with_retry_or_clarity_request(self):
        cases = (
            ("get_image_content", None),
            ("get_image_content", RuntimeError("SECRET_DOWNLOAD")),
            ("extract_text_from_image", {"status": "uncertain", "text": ""}),
            ("extract_text_from_image", {"status": "error", "text": ""}),
            ("extract_text_from_image", RuntimeError("SECRET_OCR")),
            ("find_similarity", RuntimeError("SECRET_DATASET")),
            ("analyze_with_llm", {"status": "error", "is_scam": None}),
            ("analyze_with_llm", RuntimeError("SECRET_ANALYSIS")),
        )
        for number, (stage, failure) in enumerate(cases, start=1):
            with self.subTest(stage=stage, failure=failure):
                self.module.reply_to_line.reset_mock()
                self.module.save_detection.reset_mock()
                event = fixtures.image_event(number)
                event["source"] = {"type": "user", "userId": "offline-user"}
                options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                with patch.object(self.module, stage, **options), patch("builtins.print") as logs:
                    response = await self.post_events([event, event])
                self.assertEqual(response.status_code, 200)
                self.module.reply_to_line.assert_called_once()
                reply = self.module.reply_to_line.call_args.args[1]
                if isinstance(failure, dict) and failure.get("status") == "uncertain":
                    self.assertIn("รูปที่ข้อความชัดขึ้น", reply)
                else:
                    self.assertIn("ยังให้ผลประเมินไม่ได้", reply)
                self.assertNotIn("SECRET", reply)
                self.assertNotIn("SECRET", str(logs.call_args_list))
                self.module.save_detection.assert_called_once()
                saved_result = self.module.save_detection.call_args.args[1]
                self.assertEqual(saved_result["status"],
                                 "uncertain" if isinstance(failure, dict) and failure.get("status") == "uncertain" else "error")
                self.assertEqual(warning_kwargs(self.module.save_detection), {
                    "warning_attempted": True, "warning_sent": True,
                })
        self.module.analyze_message.assert_not_called()

    async def test_failed_image_send_does_not_retry_or_stop_next_text(self):
        for number, failure in enumerate((False, RuntimeError("SECRET_SEND")), start=1):
            with self.subTest(failure=failure):
                self.module.analyze_message.reset_mock()
                self.module.save_detection.reset_mock()
                event = fixtures.image_event(number * 2)
                event["source"] = {"type": "user", "userId": "offline-user"}
                events = [event, private_event("ข้อความถัดไป", number * 2 + 1)]
                with patch.object(self.module, "reply_to_line", side_effect=[failure, True]) as reply, patch("builtins.print") as logs:
                    first = await self.post_events(events)
                    duplicate = await self.post_events(events)
                self.assertEqual((first.status_code, duplicate.status_code), (200, 200))
                self.assertEqual(reply.call_count, 2)
                self.assertEqual([call.args[0] for call in reply.call_args_list], [item["replyToken"] for item in events])
                self.module.analyze_message.assert_called_once_with("ข้อความถัดไป", private=True)
                self.assertNotIn("SECRET_SEND", str(logs.call_args_list))
                self.assertEqual(self.module.save_detection.call_count, 2)
                saved = self.module.save_detection.call_args_list[0].kwargs
                self.assertEqual({key: saved[key] for key in ("warning_attempted", "warning_sent")},
                                 {"warning_attempted": True, "warning_sent": False})
                # แชตส่วนตัวเก็บข้อความ OCR และรหัสเคสไว้ให้หน้าประวัติ แม้ส่งคำตอบไม่สำเร็จ
                self.assertIn("image_text", saved)
                self.assertRegex(saved["case_id"], r"^[0-9a-f]{32}$")

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


class ImageReplyTests(unittest.TestCase):
    def setUp(self):
        self.module = fixtures.load_app()

    def test_assessed_image_preserves_reason_and_limits(self):
        for status, heading in (
            ("risk_found", "พบสัญญาณเสี่ยง"),
            ("no_risk_found", "ยังไม่พบสัญญาณหลอกลวงชัดเจน"),
        ):
            with self.subTest(status=status):
                reply = self.module.image_reply(result(status))
                self.assertIn("ข้อความที่อ่านได้ในรูป", reply)
                self.assertIn(heading, reply)
                self.assertIn("เหตุผลทดสอบ", reply)
                if status == "no_risk_found":
                    self.assertIn("ไม่รับรองว่าปลอดภัย", reply)
                else:
                    self.assertIn("ไม่ใช่การยืนยันตัวตน", reply)
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    def test_incomplete_image_results_request_context_or_retry(self):
        reply = self.module.image_reply(result("uncertain"))
        self.assertIn("เหตุผลทดสอบ", reply)
        self.assertIn("รูปที่ข้อความชัดขึ้น", reply)
        self.assertIn("ไม่ส่ง OTP หรือรหัสผ่าน", reply)
        reply = self.module.image_reply(result("conversation"))
        self.assertIn("ต้องการให้ช่วยตรวจส่วนไหน", reply)
        self.assertNotEqual(reply, self.module.PRIVATE_HELP)
        for value in ({"status": "error", "is_scam": None}, {}, {"status": "unknown"}):
            with self.subTest(value=value):
                reply = self.module.image_reply(value)
                self.assertIn("ยังให้ผลประเมินไม่ได้", reply)
                self.assertIn("ส่งใหม่", reply)

    def test_contradictory_results_do_not_produce_risk_or_clear_verdict(self):
        for status, flag in (("risk_found", False), ("no_risk_found", True), ("uncertain", True)):
            with self.subTest(status=status, flag=flag):
                reply = self.module.image_reply({**result(status), "is_scam": flag})
                self.assertIn("ยังให้ผลประเมินไม่ได้", reply)
                self.assertNotIn("⚠️ พบสัญญาณเสี่ยง", reply)
                self.assertNotIn("✅ ยังไม่พบสัญญาณ", reply)


if __name__ == "__main__":
    unittest.main()
