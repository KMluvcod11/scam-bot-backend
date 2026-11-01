"""ทดสอบดาวน์โหลดรูปด้วยข้อมูลจำลอง ไม่อ่านคีย์หรือเรียก LINE จริง."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

import requests


class ImageContentTests(unittest.TestCase):
    # setUp: เตรียม messaging และ HTTP response รูปจำลอง พร้อมดัก log โดยไม่อ่าน token จริง
    def setUp(self):
        config = ModuleType("config")
        config.LINE_CHANNEL_ACCESS_TOKEN = "offline-token"

        path = Path(__file__).resolve().parents[1] / "messaging.py"
        spec = importlib.util.spec_from_file_location(
            "image_messaging_test", path
        )
        self.messaging = importlib.util.module_from_spec(spec)

        with patch.object(sys, "path", [str(path.parent), *sys.path]):
            with patch.dict(sys.modules, {"config": config}):
                spec.loader.exec_module(self.messaging)

        self.get = self.enterContext(
            patch.object(self.messaging.requests, "get")
        )
        self.logs = self.enterContext(
            patch.object(self.messaging, "print")
        )

        self.response = self.get.return_value.__enter__.return_value
        self.response.status_code = 200
        self.response.headers = {
            "Content-Type": "Image/JPEG; charset=binary"
        }
        self.response.iter_content.return_value = [b"one", b"two"]

    # test_download_returns_bytes_and_mime_type: ทดสอบดาวน์โหลดรูปคืน bytes และ MIME พร้อม URL, timeout และ header ที่คาดไว้
    def test_download_returns_bytes_and_mime_type(self):
        result = self.messaging.get_image_content("1/2")

        self.assertEqual(result, (b"onetwo", "image/jpeg"))
        self.get.assert_called_once_with(
            "https://api-data.line.me/v2/bot/message/1%2F2/content",
            headers={"Authorization": "Bearer offline-token"},
            timeout=(5, 10),
            stream=True,
            allow_redirects=False,
        )

    # test_invalid_id_does_not_request_line: ทดสอบรหัสรูปผิดรูปแบบไม่ส่งคำขอไป LINE
    def test_invalid_id_does_not_request_line(self):
        for message_id in (None, "", "   ", 123):
            with self.subTest(message_id=message_id):
                result = self.messaging.get_image_content(message_id)
                self.assertIsNone(result)

        self.get.assert_not_called()

    # test_unsupported_mime_type_does_not_read_body: ทดสอบ MIME ที่ไม่รองรับถูกปฏิเสธก่อนอ่านเนื้อหารูป
    def test_unsupported_mime_type_does_not_read_body(self):
        for mime_type in ("text/html", "application/octet-stream", ""):
            with self.subTest(mime_type=mime_type):
                self.response.headers = {"Content-Type": mime_type}
                result = self.messaging.get_image_content("1")
                self.assertIsNone(result)

        self.response.iter_content.assert_not_called()

    # test_redirect_is_rejected: ทดสอบดาวน์โหลดรูปไม่ติดตาม redirect และไม่อ่าน body ของปลายทางใหม่
    def test_redirect_is_rejected(self):
        self.response.status_code = 302

        result = self.messaging.get_image_content("1")

        self.assertIsNone(result)
        self.response.iter_content.assert_not_called()

    # test_empty_content_returns_none: ทดสอบรูปที่ไม่มีเนื้อหาคืน None
    def test_empty_content_returns_none(self):
        self.response.iter_content.return_value = [b""]

        result = self.messaging.get_image_content("1")

        self.assertIsNone(result)

    # test_size_limit_accepts_exact_limit_and_rejects_overflow: ทดสอบรับรูปที่ขนาดพอดีขีดจำกัดและปฏิเสธเมื่อเกิน
    def test_size_limit_accepts_exact_limit_and_rejects_overflow(self):
        self.assertEqual(
            self.messaging.MAX_IMAGE_BYTES, 5 * 1024 * 1024
        )

        with patch.object(self.messaging, "MAX_IMAGE_BYTES", 4):
            self.response.iter_content.return_value = [b"12", b"34"]
            result = self.messaging.get_image_content("1")
            self.assertEqual(result, (b"1234", "image/jpeg"))

            self.response.iter_content.return_value = [b"12", b"345"]
            result = self.messaging.get_image_content("1")
            self.assertIsNone(result)

    # test_http_error_and_timeout_do_not_log_secrets: ทดสอบดาวน์โหลดเจอ HTTP error/timeout คืน None และไม่เผยรายละเอียดลับใน log
    def test_http_error_and_timeout_do_not_log_secrets(self):
        self.response.raise_for_status.side_effect = (
            requests.HTTPError("SECRET_HTTP")
        )
        self.assertIsNone(self.messaging.get_image_content("1"))

        self.get.side_effect = requests.Timeout("SECRET_TIMEOUT")
        self.assertIsNone(self.messaging.get_image_content("1"))

        self.assertNotIn("SECRET", str(self.logs.call_args_list))


if __name__ == "__main__":
    unittest.main()