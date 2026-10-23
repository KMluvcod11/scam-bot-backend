"""ทดสอบการ์ดผลตรวจ Flex Message แบบออฟไลน์ ไม่เรียก LINE จริง."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import flex_cards  # noqa: E402

LIVE_ENV = {"MINI_LIFF_ID": "1234567890-TestApp", "LINE_LOGIN_CHANNEL_ID": "1234567890",
            "MINI_WEB_ORIGIN": "https://mini.example"}
CASE_ID = "a" * 32


def all_texts(node):
    """ดึงข้อความทุกตัวในการ์ดมาต่อกัน เพื่อเช็กเนื้อหาโดยไม่ผูกกับโครงสร้างละเอียด."""
    if isinstance(node, dict):
        own = [node["text"]] if node.get("type") == "text" else []
        return own + [text for value in node.values() for text in all_texts(value)]
    if isinstance(node, list):
        return [text for item in node for text in all_texts(item)]
    return []


class ResultCardTests(unittest.TestCase):
    def card(self, status="risk_found", **kwargs):
        result = {"status": status, "is_scam": status == "risk_found", "reason": "อ้างสิทธิ์คืนเงิน"}
        options = {"source": "text", "quote": "คุณได้รับสิทธิ์คืนเงินค่าไฟ", "case_id": CASE_ID}
        options.update(kwargs)
        return flex_cards.build_result_card(result, **options)

    def test_each_status_has_title_mascot_and_detail_button(self):
        expected = {"risk_found": ("พบสัญญาณเสี่ยง", "alert"), "uncertain": ("ควรตรวจเพิ่ม", "inspect"),
                    "no_risk_found": ("ยังไม่พบสัญญาณเสี่ยง", "calm")}
        with patch.dict(os.environ, LIVE_ENV):
            for status, (title, pose) in expected.items():
                with self.subTest(status=status):
                    card = self.card(status)
                    self.assertEqual(card["type"], "flex")
                    self.assertIn(title, card["altText"])
                    texts = all_texts(card["contents"])
                    self.assertIn(title, texts)
                    self.assertIn("ตรวจจากข้อความ", texts)
                    body = json.dumps(card, ensure_ascii=False)
                    self.assertIn(f"https://mini.example/mascot/{pose}.png", body)
                    button = card["contents"]["footer"]["contents"][0]
                    self.assertEqual(button["action"], {"type": "uri", "label": "ดูรายละเอียด",
                        "uri": f"https://liff.line.me/1234567890-TestApp?case={CASE_ID}"})

    def test_quote_is_shortened_and_image_source_is_labelled(self):
        with patch.dict(os.environ, LIVE_ENV):
            card = self.card(source="image", quote="ก" * 200)
        texts = all_texts(card["contents"])
        self.assertIn("ตรวจจากรูปภาพ", texts)
        quote = next(text for text in texts if text.startswith("ข้อความในรูป:"))
        self.assertLessEqual(len(quote), 80)
        self.assertTrue(quote.endswith("…”"))

    def test_without_mini_settings_card_still_builds_without_image_or_uri(self):
        with patch.dict(os.environ, {"MINI_LIFF_ID": "", "LINE_LOGIN_CHANNEL_ID": "", "MINI_WEB_ORIGIN": ""}):
            card = self.card()
            self.assertNotIn("mascot", json.dumps(card))
            self.assertNotIn("footer", card["contents"])
            with_postback = self.card(allow_postback=True)
        button = with_postback["contents"]["footer"]["contents"][0]
        self.assertEqual(button["action"]["type"], "postback")
        self.assertEqual(button["action"]["data"], f"learn:{CASE_ID}")

    def test_unknown_status_returns_none(self):
        for status in ("error", "conversation", None):
            with self.subTest(status=status):
                self.assertIsNone(flex_cards.build_result_card(
                    {"status": status}, source="text", quote="x", case_id=None))

    def test_alt_text_and_reason_are_within_line_limits(self):
        with patch.dict(os.environ, LIVE_ENV):
            card = flex_cards.build_result_card({"status": "risk_found", "reason": "ร" * 2000},
                                                source="text", quote="x" * 2000, case_id=CASE_ID)
        self.assertLessEqual(len(card["altText"]), 400)
        self.assertTrue(all(len(text) <= 300 for text in all_texts(card["contents"])))


def load_messaging():
    config = ModuleType("config")
    config.LINE_CHANNEL_ACCESS_TOKEN = "offline-token"
    path = ROOT / "messaging.py"
    spec = importlib.util.spec_from_file_location("messaging_card_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"config": config}):
        spec.loader.exec_module(module)
    return module


class CardReplyTests(unittest.TestCase):
    def setUp(self):
        self.module = load_messaging()
        self.card = {"type": "flex", "altText": "ผล", "contents": {"type": "bubble"}}

    def test_card_is_sent_alone_instead_of_text_and_button(self):
        with patch.object(self.module.requests, "post", return_value=Mock()) as post:
            self.assertTrue(self.module.reply_to_line("token", "ผลตรวจ", card=self.card, learn_case_id=CASE_ID))
        self.assertEqual(post.call_args.kwargs["json"]["messages"], [self.card])

    def test_rejected_card_falls_back_to_plain_text_once(self):
        rejected = Mock()
        rejected.status_code = 400
        rejected.raise_for_status.side_effect = requests.HTTPError(response=rejected)
        with patch.dict(os.environ, {"MINI_LIFF_ID": "", "LINE_LOGIN_CHANNEL_ID": ""}), \
                patch.object(self.module.requests, "post", side_effect=[rejected, Mock()]) as post:
            self.assertTrue(self.module.reply_to_line("token", "ผลตรวจ", card=self.card))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["messages"], [{"type": "text", "text": "ผลตรวจ"}])

    def test_network_failure_with_card_does_not_retry(self):
        with patch.object(self.module.requests, "post", side_effect=requests.ConnectionError("SECRET")) as post:
            self.assertFalse(self.module.reply_to_line("token", "ผลตรวจ", card=self.card))
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
