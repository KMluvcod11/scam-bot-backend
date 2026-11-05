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
from linebot.v3.messaging import FlexMessage

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
            "uncertain": ("ยังประเมินไม่ได้", "inspect", "คำแนะนำ"),
            "no_risk_found": ("ยังไม่พบสัญญาณเสี่ยง", "calm", "คำแนะนำ")}
FORBIDDEN = ("ระดับความเสี่ยง", "HIGH", "MEDIUM", "LOW", "สูง", "ปานกลาง", "ต่ำ", "100%")


# walk: ไล่ dict ทุกระดับในการ์ด รวมรายการซ้อน เพื่อให้ tests ตรวจองค์ประกอบ Flex ได้
def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


class ResultCardTests(unittest.TestCase):
    # card: สร้างการ์ดจากผลตรวจจำลอง โดยเปิดให้แต่ละ test เปลี่ยนสถานะ เหตุผล และตัวเลือก
    def card(self, status="risk_found", reason="อ้างสิทธิ์คืนเงิน", **kwargs):
        result = {"status": status, "is_scam": status == "risk_found", "risk_level": "high",
                  "reason": reason}
        options = {"source": "text", "quote": "คุณได้รับสิทธิ์คืนเงินค่าไฟ", "case_id": CASE_ID}
        options.update(kwargs)
        return flex_cards.build_result_card(result, **options)

    # test_matrix_private_group_text_image_every_status: ทดสอบการ์ดทุกสถานะทั้งข้อความ/รูปและแชตส่วนตัว/กลุ่ม ว่าจัดเนื้อหา สี และปุ่มถูกต้อง
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
                            parsed = FlexMessage.from_dict(card)
                            self.assertEqual(parsed.contents.type, "bubble")
                            self.assertLessEqual(len(json.dumps(card["contents"], ensure_ascii=False).encode("utf-8")), 30000)
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

    # test_group_never_gets_button_even_with_case_id_or_postback: ทดสอบการ์ดกลุ่มไม่มีปุ่ม แม้ส่ง case_id และอนุญาต postback
    def test_group_never_gets_button_even_with_case_id_or_postback(self):
        with patch.dict(os.environ, LIVE_ENV):
            card = self.card(group=True, allow_postback=True)
        self.assertNotIn("footer", card["contents"])

    # test_status_designs_differ_and_only_risk_is_pink_warning: ทดสอบรูปแบบแต่ละสถานะแตกต่างกันและใช้กรอบเตือนสีชมพูเฉพาะผลเสี่ยง
    def test_status_designs_differ_and_only_risk_is_pink_warning(self):
        notes = {}
        for status in STATUSES:
            body = self.card(status)["contents"]["body"]["contents"]
            notes[status] = body[5]["backgroundColor"]
        self.assertEqual(notes["risk_found"], "#FFE3E9")
        self.assertEqual(len(set(notes.values())), 3)

    # test_group_fallback_warning_uses_risk_card: ทดสอบกฎสำรองที่เตือนในกลุ่มใช้การ์ดเสี่ยง ส่วน fallback ที่ไม่เตือนไม่สร้างการ์ด
    def test_group_fallback_warning_uses_risk_card(self):
        card = flex_cards.build_result_card({"status": "fallback", "is_scam": True, "risk_level": "medium",
                                             "reason": "ใกล้เคียง 85% (ระบบสำรอง)"},
                                            source="text", quote="x", case_id=None, group=True)
        self.assertIn("พบสัญญาณเสี่ยง", all_texts(card["contents"]))
        self.assertNotIn("medium", json.dumps(card).lower())
        self.assertIsNone(flex_cards.build_result_card({"status": "fallback", "is_scam": False},
                                                       source="text", quote="x", case_id=None))

    # test_reason_lines_become_bullets: ทดสอบเหตุผลหลายบรรทัดถูกแสดงเป็นรายการแต่ละข้อ
    def test_reason_lines_become_bullets(self):
        card = self.card(reason="แอบอ้างเป็นธนาคาร\n• ขู่ว่าบัญชีจะถูกระงับ\n- เร่งให้ส่ง OTP")
        texts = all_texts(card["contents"])
        for item in ("แอบอ้างเป็นธนาคาร", "ขู่ว่าบัญชีจะถูกระงับ", "เร่งให้ส่ง OTP"):
            self.assertIn(item, texts)
        self.assertEqual(texts.count("●"), 3)

    # ไม่ตัดคำไทยใน preview; ส่งฉบับเต็มแทนเมื่อเนื้อหาเกินพื้นที่การ์ด
    def test_long_thai_text_moves_to_continuation_and_warning_kept(self):
        long_quote = "บัญชีของคุณจะถูกระงับ กรุณาส่งรหัส OTP ภายในห้านาทีเพื่อยืนยันตัวตน " * 10
        long_reason = "แอบอ้างเป็นเจ้าหน้าที่ธนาคารและเร่งให้ผู้รับเปิดเผยข้อมูลสำคัญ" * 20
        with patch.dict(os.environ, LIVE_ENV):
            for group in (False, True):
                card = self.card(quote=long_quote, reason=long_reason, group=group)
                texts = all_texts(card["contents"])
                self.assertIn(flex_cards.LONG_QUOTE, texts)
                self.assertIn(flex_cards.LONG_REASON, texts)
                continuation = flex_cards.build_result_continuation(
                    {"status": "risk_found", "reason": long_reason}, source="text", quote=long_quote)
                self.assertIn(long_quote, continuation)
                self.assertIn(long_reason, continuation)
                self.assertIn(flex_cards.STATUS_STYLES["risk_found"]["advice"], texts)
                self.assertIn(flex_cards.DISCLAIMER, texts)
                self.assertFalse(any(node.get("maxLines") for node in walk(card)))
                self.assertLessEqual(len(card["altText"]), 400)
                self.assertLess(len(json.dumps(card).encode()), 30000)

    # test_shorten_never_orphans_thai_marks_or_leading_vowels: ทดสอบจุดตัดไม่ทำให้วรรณยุกต์หรือสระไทยแยกจากอักษรที่เกี่ยวข้อง
    def test_shorten_never_orphans_thai_marks_or_leading_vowels(self):
        text = "เที่ยวไม่จ่ายเงินแน่นอนไม่ใช่"  # ไม่มีช่องว่าง บังคับตัดกลางคำ
        for limit in range(1, len(text)):
            with self.subTest(limit=limit):
                cut = flex_cards.shorten(text, limit)[:-1]
                rest = text[len(cut):]
                self.assertFalse(rest and unicodedata.category(rest[0]) == "Mn")
                self.assertFalse(cut and cut[-1] in flex_cards.THAI_LEADING_VOWELS)

    # test_without_mini_settings_card_still_builds_without_image_or_uri: ทดสอบยังสร้างการ์ดได้เมื่อไม่ได้ตั้งค่า Mini App โดยไม่ใส่รูปหรือลิงก์ที่ใช้ไม่ได้
    def test_without_mini_settings_card_still_builds_without_image_or_uri(self):
        with patch.dict(os.environ, {"MINI_LIFF_ID": "", "LINE_LOGIN_CHANNEL_ID": "", "MINI_WEB_ORIGIN": ""}):
            card = self.card()
            self.assertNotIn("mascot", json.dumps(card))
            self.assertNotIn("footer", card["contents"])
            with_postback = self.card(allow_postback=True)
        button = with_postback["contents"]["footer"]["contents"][0]
        self.assertEqual(button["action"]["type"], "postback")
        self.assertEqual(button["action"]["data"], f"learn:{CASE_ID}")

    # test_phone_is_redacted_in_quote_reason_and_alt_text: การ์ดกลุ่ม/ส่วนตัวต้องไม่แสดงเบอร์ที่ประวัติปกปิดแล้ว
    def test_phone_is_redacted_in_quote_reason_and_alt_text(self):
        for group in (False, True):
            with self.subTest(group=group):
                card = self.card(quote="ติดต่อกลับ เบอร์ 081-234-5678 ด่วน",
                                 reason="ให้โทร +66 81 234 5678 เพื่อยืนยัน", group=group)
                dumped = json.dumps(card, ensure_ascii=False)
                self.assertNotIn("081-234-5678", dumped)
                self.assertNotIn("81 234 5678", dumped)
                self.assertEqual(dumped.count("[ปกปิดเบอร์โทร]"), 2)  # ข้อความ + เหตุผล; altText มีเฉพาะสถานะ

    def test_short_content_needs_no_continuation(self):
        self.assertEqual(flex_cards.build_result_continuation(
            {"status": "no_risk_found", "reason": "เป็นการนัดหมาย"}, source="text", quote="นัดพรุ่งนี้"), "")

    def test_all_reason_items_are_preserved_and_result_not_mutated(self):
        result = {"status": "uncertain", "risk_level": "medium", "reason": "\n".join(
            f"เหตุผลข้อ {index}" for index in range(8))}
        before = dict(result)
        text = flex_cards.build_result_continuation(result, source="image", quote="ข้อความ")
        self.assertIn("ผลตรวจข้อความจากรูปภาพ", text)
        for index in range(8):
            self.assertIn(f"เหตุผลข้อ {index}", text)
        self.assertEqual(result, before)
        self.assertNotIn("medium", text)

    # test_unknown_status_returns_none: ทดสอบสถานะที่ไม่รองรับคืน None แทนการสร้างการ์ดผิดชนิด
    def test_unknown_status_returns_none(self):
        for status in ("error", "conversation", None):
            with self.subTest(status=status):
                self.assertIsNone(flex_cards.build_result_card(
                    {"status": status}, source="text", quote="x", case_id=None))

    # test_alt_text_and_reason_are_within_line_limits: ทดสอบ altText และข้อความเหตุผลในการ์ดไม่เกินความยาวที่กำหนด
    def test_alt_text_and_reason_are_within_line_limits(self):
        with patch.dict(os.environ, LIVE_ENV):
            card = flex_cards.build_result_card({"status": "risk_found", "reason": "ร" * 2000},
                                                source="text", quote="x" * 2000, case_id=CASE_ID)
        self.assertLessEqual(len(card["altText"]), 400)
        self.assertTrue(all(len(text) <= 410 for text in all_texts(card["contents"])))


# load_messaging: โหลด messaging ด้วย token จำลองสำหรับทดสอบ payload การส่งการ์ด
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
    # setUp: เตรียมโมดูล messaging จำลองและการ์ดสั้นสำหรับทดสอบส่ง LINE
    def setUp(self):
        self.module = load_messaging()
        self.card = {"type": "flex", "altText": "ผล", "contents": {"type": "bubble"}}

    # test_card_is_sent_alone_instead_of_text_and_button: ทดสอบส่ง Flex เพียงรายการเดียวเมื่อมีการ์ด ไม่ส่งข้อความหรือปุ่มซ้ำ
    def test_card_is_sent_alone_instead_of_text_and_button(self):
        with patch.object(self.module.requests, "post", return_value=Mock()) as post:
            self.assertTrue(self.module.reply_to_line("token", "ผลตรวจ", card=self.card, learn_case_id=CASE_ID))
        self.assertEqual(post.call_args.kwargs["json"]["messages"], [self.card])

    # test_rejected_card_falls_back_to_plain_text_once: ทดสอบ LINE ปฏิเสธการ์ดด้วย 400 แล้วส่งข้อความธรรมดาแทนเพียงครั้งเดียว
    def test_rejected_card_falls_back_to_plain_text_once(self):
        rejected = Mock()
        rejected.status_code = 400
        rejected.raise_for_status.side_effect = requests.HTTPError(response=rejected)
        with patch.dict(os.environ, {"MINI_LIFF_ID": "", "LINE_LOGIN_CHANNEL_ID": ""}), \
                patch.object(self.module.requests, "post", side_effect=[rejected, Mock()]) as post:
            self.assertTrue(self.module.reply_to_line("token", "ผลตรวจ", card=self.card))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["messages"], [{"type": "text", "text": "ผลตรวจ"}])

    # test_network_failure_with_card_does_not_retry: ทดสอบส่งการ์ดเจอปัญหาเครือข่ายแล้วไม่ส่งซ้ำโดยอัตโนมัติ
    def test_network_failure_with_card_does_not_retry(self):
        with patch.object(self.module.requests, "post", side_effect=requests.ConnectionError("SECRET")) as post:
            self.assertFalse(self.module.reply_to_line("token", "ผลตรวจ", card=self.card))
        self.assertEqual(post.call_count, 1)

    def test_long_payload_matrix_keeps_content_and_privacy(self):
        quote = "ข้อความที่พบ กรุณาตรวจสอบก่อนทำตาม เบอร์ 081-234-5678\n" * 160
        reason = "ตรวจบริบทและผู้ส่งเพิ่มเติม\n" * 22
        with patch.dict(os.environ, LIVE_ENV):
            for status in STATUSES:
                for source in ("text", "image"):
                    for group in (False, True):
                        with self.subTest(status=status, source=source, group=group):
                            result = {"status": status, "reason": reason, "risk_level": "high"}
                            card = flex_cards.build_result_card(result, source=source, quote=quote,
                                case_id=None if group else CASE_ID, group=group)
                            continuation = flex_cards.build_result_continuation(result, source=source, quote=quote)
                            with patch.object(self.module.requests, "post", return_value=Mock()) as post:
                                self.assertTrue(self.module.reply_to_line("token", "fallback", card=card,
                                    continuation=continuation))
                            messages = post.call_args.kwargs["json"]["messages"]
                            self.assertEqual(messages[0], card)
                            self.assertGreater(len(messages), 1)
                            self.assertLessEqual(len(messages), 5)
                            self.assertEqual("".join(m["text"] for m in messages[1:]), continuation)
                            for message in messages[1:]:
                                self.assertLessEqual(len(message["text"].encode("utf-16-le")) // 2, 5000)
                            dumped = json.dumps(messages, ensure_ascii=False)
                            self.assertNotIn("081-234-5678", dumped)
                            self.assertNotIn("high", dumped)
                            if group:
                                self.assertNotIn("liff.line.me", dumped)
                                self.assertNotIn("postback", dumped)

    def test_long_card_rejection_falls_back_to_complete_redacted_text(self):
        rejected = Mock(status_code=400)
        rejected.raise_for_status.side_effect = requests.HTTPError(response=rejected)
        text = "ตรวจสอบ 081-234-5678 ก่อนทำตาม\n" * 250
        with patch.object(self.module.requests, "post", side_effect=[rejected, Mock()]) as post:
            self.assertTrue(self.module.reply_to_line("token", "ผลตรวจ", card=self.card, continuation=text))
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual("".join(m["text"] for m in messages), self.module.redact_phone(text))
        self.assertEqual(post.call_count, 2)

    def test_utf16_limits_preserve_emoji_and_thai_words(self):
        text = ("เที่ยวไม่จ่ายเงินแน่นอนไม่ใช่ 👨‍👩‍👧‍👦 👍🏽\n" * 300)
        messages = self.module.text_messages(text)
        self.assertIsNotNone(messages)
        self.assertEqual("".join(m["text"] for m in messages), text)
        for message in messages:
            self.assertLessEqual(len(message["text"].encode("utf-16-le")) // 2, 5000)
        for message in messages[:-1]:
            self.assertTrue(message["text"][-1].isspace() or
                            text[text.index(message["text"]) + len(message["text"])].isspace())

    def test_impossible_payload_is_explicit_not_silently_truncated(self):
        for text in ("ก" * 5001, "คำเตือน " * 4000):
            with self.subTest(length=len(text)), patch.object(self.module.requests, "post", return_value=Mock()) as post:
                self.module.reply_to_line("token", text, card=self.card, continuation=text)
                self.assertEqual(post.call_args.kwargs["json"]["messages"],
                                 [self.card, {"type": "text", "text": self.module.TOO_LONG_NOTICE}])

    def test_plain_fallback_redacts_phone(self):
        with patch.object(self.module.requests, "post", return_value=Mock()) as post:
            self.module.reply_to_line("token", "โทร 081-234-5678")
        self.assertNotIn("081-234-5678", json.dumps(post.call_args.kwargs["json"]))

    def test_five_text_chunks_replace_card_without_losing_content(self):
        text = "ข้อความครบ " * 2100
        with patch.object(self.module.requests, "post", return_value=Mock()) as post:
            self.assertTrue(self.module.reply_to_line("token", "ผลตรวจ", card=self.card, continuation=text))
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(len(messages), 5)
        self.assertTrue(all(m["type"] == "text" for m in messages))
        self.assertEqual("".join(m["text"] for m in messages), text)

    def test_non_400_errors_do_not_resend(self):
        for status in (401, 429, 500):
            rejected = Mock(status_code=status)
            rejected.raise_for_status.side_effect = requests.HTTPError(response=rejected)
            with self.subTest(status=status), patch.object(self.module.requests, "post", return_value=rejected) as post:
                self.assertFalse(self.module.reply_to_line("token", "ผลตรวจ", card=self.card,
                    continuation="เหตุผลฉบับเต็ม " * 500))
            self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
