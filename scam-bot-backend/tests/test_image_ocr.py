"""ทดสอบอ่านข้อความในรูปด้วย Gemini จำลอง ไม่อ่านคีย์หรือเรียกบริการจริง."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from google.genai import types as sdk_types

import test_llm_validation as fixtures


class ImageOCRTests(unittest.TestCase):
    def setUp(self):
        self.detector = fixtures.load_detector()
        # ใช้ชนิดข้อมูล SDK จริง เพื่อตรวจชื่อพารามิเตอร์ด้วย แต่ client ยังจำลอง
        self.detector.types = sdk_types
        self.generate = self.detector.client.models.generate_content
        self.logs = self.enterContext(patch.object(self.detector, "print"))
        self.image_bytes = b"offline-image"
        self.set_response({"readable": True, "text": "ข้อความทดสอบ"})

    def tearDown(self):
        # OCR ขั้นนี้ยังไม่ต้องสร้าง embedding หรือค้น dataset
        self.detector.client.models.embed_content.assert_not_called()
        self.detector.supabase.rpc.assert_not_called()

    def set_response(self, data, finish_reason=sdk_types.FinishReason.STOP):
        self.generate.return_value = SimpleNamespace(
            text=json.dumps(data, ensure_ascii=False),
            candidates=[SimpleNamespace(finish_reason=finish_reason)],
        )

    def read_image(self, mime_type="image/jpeg"):
        self.generate.reset_mock()
        result = self.detector.extract_text_from_image(
            self.image_bytes, mime_type
        )
        # ป้องกัน test ผ่านเพราะพังตั้งแต่สร้าง config ก่อนถึงคำตอบจำลอง
        self.generate.assert_called_once()
        return result

    def test_readable_image_sends_bytes_and_returns_text_without_logging_it(self):
        text = "  SECRET_OCR_TEXT\nโอนค่าประกันก่อนเริ่มงาน  "
        self.set_response({"readable": True, "text": text})

        result = self.read_image()

        self.assertEqual(result, {"status": "ok", "text": text.strip()})
        arguments = self.generate.call_args.kwargs
        self.assertEqual(len(arguments["contents"]), 1)
        image = arguments["contents"][0].inline_data
        self.assertEqual(image.data, self.image_bytes)
        self.assertEqual(image.mime_type, "image/jpeg")
        config = arguments["config"]
        self.assertEqual(config.system_instruction, self.detector.IMAGE_TEXT_PROMPT)
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertGreater(config.max_output_tokens, 0)
        self.assertLessEqual(config.max_output_tokens, 4096)
        self.assertIsNone(config.tools)
        self.assertNotIn("SECRET_OCR_TEXT", str(self.logs.call_args_list))

    def test_download_supported_mime_types_are_passed_to_gemini(self):
        for mime_type in ("image/jpeg", "image/png", "image/webp"):
            with self.subTest(mime_type=mime_type):
                result = self.read_image(mime_type)
                self.assertEqual(result["status"], "ok")
                image = self.generate.call_args.kwargs["contents"][0].inline_data
                self.assertEqual(image.mime_type, mime_type)

    def test_invalid_image_bytes_do_not_call_gemini(self):
        for image_bytes in (None, b"", "not-bytes", 123, bytearray(b"image")):
            with self.subTest(image_bytes=image_bytes):
                result = self.detector.extract_text_from_image(
                    image_bytes, "image/jpeg"
                )
                self.assertEqual(result, {"status": "error", "text": ""})

        self.generate.assert_not_called()

    def test_unsupported_mime_types_do_not_call_gemini(self):
        for mime_type in (None, "", "text/html", "image/gif"):
            with self.subTest(mime_type=mime_type):
                result = self.detector.extract_text_from_image(
                    self.image_bytes, mime_type
                )
                self.assertEqual(result, {"status": "error", "text": ""})

        self.generate.assert_not_called()

    def test_unreadable_or_blank_text_is_uncertain(self):
        cases = [
            {"readable": False, "text": ""},
            {"readable": False, "text": "ข้อความที่อ่านได้บางส่วน"},
            {"readable": True, "text": ""},
            {"readable": True, "text": " \n\t "},
        ]
        for data in cases:
            with self.subTest(data=data):
                self.set_response(data)
                self.assertEqual(
                    self.read_image(), {"status": "uncertain", "text": ""}
                )

    def test_invalid_json_is_error_without_logging_response(self):
        for text in ("", "SECRET_INVALID_JSON", "{unclosed"):
            with self.subTest(text=text):
                self.generate.return_value.text = text
                self.assertEqual(
                    self.read_image(), {"status": "error", "text": ""}
                )

        self.assertNotIn("SECRET_INVALID_JSON", str(self.logs.call_args_list))

    def test_non_object_json_is_rejected(self):
        for data in (None, [], "ข้อความ", 123, True):
            with self.subTest(data=data):
                self.set_response(data)
                self.assertEqual(
                    self.read_image(), {"status": "error", "text": ""}
                )

    def test_readable_flag_must_be_boolean(self):
        cases = [{"text": "ข้อความ"}]
        cases.extend(
            {"readable": flag, "text": "ข้อความ"}
            for flag in (None, 0, 1, "true", "false")
        )
        for data in cases:
            with self.subTest(data=data):
                self.set_response(data)
                self.assertEqual(
                    self.read_image(), {"status": "error", "text": ""}
                )

    def test_text_must_be_present_and_a_string(self):
        cases = [{"readable": True}]
        cases.extend(
            {"readable": True, "text": text}
            for text in (None, 123, [], {}, True)
        )
        for data in cases:
            with self.subTest(data=data):
                self.set_response(data)
                self.assertEqual(
                    self.read_image(), {"status": "error", "text": ""}
                )

    def test_text_length_limit_accepts_boundary_and_rejects_overflow(self):
        text = "ก" * 5000
        self.set_response({"readable": True, "text": text})
        self.assertEqual(self.read_image(), {"status": "ok", "text": text})

        self.set_response({"readable": True, "text": text + "ก"})
        self.assertEqual(self.read_image(), {"status": "error", "text": ""})

    def test_incomplete_or_blocked_response_is_error(self):
        for reason in (
            sdk_types.FinishReason.MAX_TOKENS,
            sdk_types.FinishReason.SAFETY,
            None,
        ):
            with self.subTest(reason=reason):
                self.set_response(
                    {"readable": True, "text": "ข้อความที่ดูเหมือนอ่านสำเร็จ"},
                    finish_reason=reason,
                )
                self.assertEqual(
                    self.read_image(), {"status": "error", "text": ""}
                )

    def test_missing_response_or_candidates_is_error(self):
        responses = [
            None,
            SimpleNamespace(text="SECRET_RESPONSE", candidates=None),
            SimpleNamespace(text="SECRET_RESPONSE", candidates=[]),
        ]
        for response in responses:
            with self.subTest(response=response):
                self.generate.return_value = response
                self.assertEqual(
                    self.read_image(), {"status": "error", "text": ""}
                )

        self.assertNotIn("SECRET_RESPONSE", str(self.logs.call_args_list))

    def test_api_failure_returns_error_without_retry_or_secret_logs(self):
        for error in (
            TimeoutError("SECRET_TIMEOUT"),
            RuntimeError("SECRET_SERVER"),
        ):
            with self.subTest(error=type(error).__name__):
                self.generate.side_effect = error
                self.assertEqual(
                    self.read_image(), {"status": "error", "text": ""}
                )

        self.assertNotIn("SECRET_", str(self.logs.call_args_list))


if __name__ == "__main__":
    unittest.main()
