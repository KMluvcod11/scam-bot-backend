"""ทดสอบการ์ดผลตรวจ Flex Message แบบออฟไลน์ ไม่เรียก LINE จริง."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unicodedata
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


STATUSES = {"risk_found": ("พบสัญญาณเสี่ยง", "alert", "คำเตือน"),
            "uncertain": ("ควรตรวจเพิ่ม", "inspect", "คำแนะนำ"),
            "no_risk_found": ("ยังไม่พบสัญญาณเสี่ยง", "calm", "คำแนะนำ")}
FORBIDDEN = ("ระดับความเสี่ยง", "HIGH", "MEDIUM", "LOW", "สูง", "ปานกลาง", "ต่ำ", "100%")


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


class ResultCardTests(unittest.TestCase):
    def card(self, status="risk_found", reason="อ้างสิทธิ์คืนเงิน", **kwargs):
        result = {"status": status, "is_scam": status == "risk_found", "risk_level": "high",
                  "reason": reason}
        options = {"source": "text", "quote": "คุณได้รับสิทธิ์คืนเงินค่าไฟ", "case_id": CASE_ID}
        options.update(kwargs)
        return flex_cards.build_result_card(result, **options)

    def test_matrix_private_group_text_image_every_status(self):
        with patch.dict(os.environ, LIVE_ENV):
            for status, (title, pose, note) in STATUSES.items():
                for source, kicker in (("text", "ผลตรวจข้อความ"), ("image", "ผลตรวจข้อความจากรูปภาพ")):
                    for group in (False, True):
                        with self.subTest(status=status, source=source, group=group):
                            card = self.card(status, source=source, group=group,
                                             case_id=None if group else CASE_ID)
                            texts = all_texts(card["contents"])
                            dumped = json.dumps(card, ensure_ascii=False)
                            # ลำดับ 4 ส่วน: ผลตรวจ → ข้อความที่พบ → เหตุผล → คำเตือน/คำแนะนำ
                            order = [texts.index(kicker), texts.index(title), texts.index("ข้อความที่พบ"),
                                     texts.index("เหตุผล"),
                                     next(i for i, t in enumerate(texts) if t.endswith(note))]
                            self.assertEqual(order, sorted(order))
                            self.assertIn("“คุณได้รับสิทธิ์คืนเงินค่าไฟ”", texts)
                            self.assertIn("อ้างสิทธิ์คืนเงิน", texts)
                            self.assertIn(flex_cards.DISCLAIMER, texts)
                            self.assertEqual(card["contents"]["header"]["backgroundColor"],
                                             flex_cards.STATUS_STYLES[status]["header"])
                            self.assertIn(f"https://mini.example/mascot/{pose}.png", dumped)
                            for word in FORBIDDEN:
                                self.assertNotIn(word, dumped)
                            if group:
                                self.assertNotIn("footer", card["contents"])
                                self.assertNotIn("liff", dumped)
                            else:
                                button = card["contents"]["footer"]["contents"][0]
                                self.assertEqual(button["action"], {"type": "uri", "label": "ดูรายละเอียด",
                                    "uri": f"https://liff.line.me/1234567890-TestApp?case={CASE_ID}"})

    def test_group_never_gets_button_even_with_case_id_or_postback(self):
        with patch.dict(os.environ, LIVE_ENV):
            card = self.card(group=True, allow_postback=True)
        self.assertNotIn("footer", card["contents"])

    def test_status_designs_differ_and_only_risk_is_pink_warning(self):
        notes = {}
        for status in STATUSES:
            body = self.card(status)["contents"]["body"]["contents"]
            notes[status] = body[4]["backgroundColor"]
        self.assertEqual(notes["risk_found"], "#FDECEE")
        self.assertEqual(len(set(notes.values())), 3)

    def test_group_fallback_warning_uses_risk_card(self):
        card = flex_cards.build_result_card({"status": "fallback", "is_scam": True, "risk_level": "medium",
                                             "reason": "ใกล้เคียง 85% (ระบบสำรอง)"},
                                            source="text", quote="x", case_id=None, group=True)
        self.assertIn("พบสัญญาณเสี่ยง", all_texts(card["contents"]))
        self.assertNotIn("medium", json.dumps(card).lower())
        self.assertIsNone(flex_cards.build_result_card({"status": "fallback", "is_scam": False},
                                                       source="text", quote="x", case_id=None))

    def test_reason_lines_become_bullets(self):
        card = self.card(reason="แอบอ้างเป็นธนาคาร\n• ขู่ว่าบัญชีจะถูกระงับ\n- เร่งให้ส่ง OTP")
        texts = all_texts(card["contents"])
        for item in ("แอบอ้างเป็นธนาคาร", "ขู่ว่าบัญชีจะถูกระงับ", "เร่งให้ส่ง OTP"):
            self.assertIn(item, texts)
        self.assertEqual(texts.count("●"), 3)

    def test_long_thai_text_is_cut_safely_and_warning_kept(self):
        long_quote = "บัญชีของคุณจะถูกระงับ กรุณาส่งรหัส OTP ภายในห้านาทีเพื่อยืนยันตัวตน " * 10
        long_reason = "แอบอ้างเป็นเจ้าหน้าที่ธนาคารและเร่งให้ผู้รับเปิดเผยข้อมูลสำคัญ" * 20
        with patch.dict(os.environ, LIVE_ENV):
            for group in (False, True):
                card = self.card(quote=long_quote, reason=long_reason, group=group)
                texts = all_texts(card["contents"])
                quote = next(t for t in texts if t.startswith("“"))
                self.assertLessEqual(len(quote), flex_cards.QUOTE_LIMIT + 3)
                self.assertTrue(quote.endswith("…”"))
                reason = next(t for t in texts if t.startswith("แอบอ้าง"))
                self.assertLessEqual(len(reason), flex_cards.REASON_LIMIT + 1)
                self.assertIn(flex_cards.STATUS_STYLES["risk_found"]["advice"], texts)
                self.assertIn(flex_cards.DISCLAIMER, texts)
                self.assertFalse(any(node.get("maxLines") for node in walk(card)))
                self.assertLessEqual(len(card["altText"]), 400)
                self.assertLess(len(json.dumps(card).encode()), 30000)

    def test_shorten_never_orphans_thai_marks_or_leading_vowels(self):
        text = "เที่ยวไม่จ่ายเงินแน่นอนไม่ใช่"  # ไม่มีช่องว่าง บังคับตัดกลางคำ
        for limit in range(1, len(text)):
            with self.subTest(limit=limit):
                cut = flex_cards.shorten(text, limit)[:-1]
                rest = text[len(cut):]
                self.assertFalse(rest and unicodedata.category(rest[0]) == "Mn")
                self.assertFalse(cut and cut[-1] in flex_cards.THAI_LEADING_VOWELS)

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
        self.assertTrue(all(len(text) <= 410 for text in all_texts(card["contents"])))


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
