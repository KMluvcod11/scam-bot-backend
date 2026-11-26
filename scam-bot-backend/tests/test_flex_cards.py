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
                            # การ์ดเสี่ยงแสดงระดับ ("high" → สูง); สถานะอื่นห้ามมีคำระดับ
                            if status == "risk_found":
                                self.assertIn("ระดับความเสี่ยง: สูง", texts)
                            else:
                                for word in FORBIDDEN:
                                    self.assertNotIn(word, dumped)
                            for word in ("HIGH", "MEDIUM", "LOW", "100%"):
                                self.assertNotIn(word, dumped)
                            if group:
                                self.assertNotIn("footer", card["contents"])
                                self.assertNotIn("liff", dumped)
                            else:
                                button = card["contents"]["footer"]["contents"][0]
                                self.assertEqual(button["action"], {"type": "uri", "label": "ดูรายละเอียด",
                                    "uri": f"https://liff.line.me/1234567890-TestApp?case={CASE_ID}"})

    # test_warning_icon_is_vertically_centered_with_title: ไอคอนเตือนกับหัวข้อจัดกึ่งกลางแนวตั้งเสมอกัน
    def test_warning_icon_is_vertically_centered_with_title(self):
        with patch.dict(os.environ, LIVE_ENV):
            heading = flex_cards.note_heading(flex_cards.STATUS_STYLES["risk_found"])
        self.assertEqual(heading["alignItems"], "center")
        self.assertEqual([item["type"] for item in heading["contents"]], ["image", "text"])

    # test_group_never_gets_button_even_with_case_id_or_postback:ทดสอบการ์ดกลุ่มไม่มีปุ่ม แม้ส่ง case_id และอนุญาต postback
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
        self.assertIn("ระดับความเสี่ยง: กลาง", all_texts(card["contents"]))
        self.assertIn("(ระดับกลาง)", card["altText"])
        self.assertNotIn("medium", json.dumps(card).lower())
        self.assertIsNone(flex_cards.build_result_card({"status": "fallback", "is_scam": False},
                                                       source="text", quote="x", case_id=None))

    # test_risk_card_without_known_level_has_no_badge: ไม่มี risk_level หรือเป็น low ต้องไม่แสดงป้าย
    def test_risk_card_without_known_level_has_no_badge(self):
        for level in (None, "low", "critical"):
            with self.subTest(level=level):
                card = flex_cards.build_result_card(
                    {"status": "risk_found", "is_scam": True, "risk_level": level, "reason": "x"},
                    source="text", quote="x", case_id=None)
                self.assertNotIn("ระดับความเสี่ยง", json.dumps(card, ensure_ascii=False))
                FlexMessage.from_dict(card)

    # test_reason_lines_become_bullets: ทดสอบเหตุผลหลายบรรทัดถูกแสดงเป็นรายการแต่ละข้อ
    def test_reason_lines_become_bullets(self):
        card = self.card(reason="แอบอ้างเป็นธนาคาร\n• ขู่ว่าบัญชีจะถูกระงับ\n- เร่งให้ส่ง OTP")
        texts = all_texts(card["contents"])
        for item in ("แอบอ้างเป็นธนาคาร", "ขู่ว่าบัญชีจะถูกระงับ", "เร่งให้ส่ง OTP"):
            self.assertIn(item, texts)
        self.assertEqual(texts.count("●"), 3)

    # ข้อความยาว: การ์ดแสดงเฉพาะช่วงสำคัญ ตัดตรงช่องว่างเท่านั้น และชี้ไป Mini App เมื่อมีปุ่ม
    def test_long_text_shows_important_part_and_points_to_mini_app(self):
        filler = "ข้อความทั่วไปของประกาศฉบับนี้ " * 10
        long_quote = filler + "พร้อมกรอกรหัส OTP ที่ได้รับ " + filler
        with patch.dict(os.environ, LIVE_ENV):
            card = self.card(quote=long_quote)
        texts = all_texts(card["contents"])
        excerpt = texts[texts.index("ข้อความสำคัญ") + 1]
        self.assertIn("พร้อมกรอกรหัส OTP ที่ได้รับ", excerpt)
        self.assertLessEqual(len(excerpt), flex_cards.QUOTE_LIMIT)
        self.assertTrue(set(excerpt.split()) <= set(long_quote.split()) | {"…"})
        self.assertIn(flex_cards.FULL_TEXT_HINT, texts)
        self.assertIn(flex_cards.DISCLAIMER, texts)

    # test_long_text_without_mini_app_button_does_not_mention_it: ไม่มีปุ่มเปิด Mini App ต้องไม่ชวนกดดูฉบับเต็ม
    def test_long_text_without_mini_app_button_does_not_mention_it(self):
        long_quote = "กรุณาส่งรหัส OTP ด่วน " * 30
        with patch.dict(os.environ, LIVE_ENV):
            group_texts = all_texts(self.card(quote=long_quote, group=True)["contents"])
        with patch.dict(os.environ, {"MINI_LIFF_ID": "", "LINE_LOGIN_CHANNEL_ID": ""}):
            postback_texts = all_texts(self.card(quote=long_quote, allow_postback=True)["contents"])
        for texts in (group_texts, postback_texts):
            self.assertIn("ข้อความสำคัญ", texts)
            self.assertNotIn(flex_cards.FULL_TEXT_HINT, texts)

    # test_important_text_without_keyword_uses_the_beginning: ไม่พบคำค้นใช้ช่วงต้นข้อความ
    def test_important_text_without_keyword_uses_the_beginning(self):
        excerpt = flex_cards.important_text("นัดประชุมทีมที่ห้องเดิม " * 30)
        self.assertTrue(excerpt.startswith("นัดประชุมทีมที่ห้องเดิม"))
        self.assertTrue(excerpt.endswith("…"))
        self.assertLessEqual(len(excerpt), flex_cards.QUOTE_LIMIT)

    # test_unbreakable_text_shows_label_instead_of_cutting_a_word: ไม่มีช่องว่างให้ตัด แสดงป้ายแทน
    def test_unbreakable_text_shows_label_instead_of_cutting_a_word(self):
        texts = all_texts(self.card(quote="ก" * 500)["contents"])
        self.assertIn(flex_cards.LONG_QUOTE, texts)

    # test_important_text_defangs_links: ลิงก์ในช่วงที่เลือกต้องกดไม่ได้
    def test_important_text_defangs_links(self):
        quote = "กดที่ https://phish.example.com/login ทันที " + "ข้อความทั่วไป " * 30
        excerpt = flex_cards.important_text(quote)
        self.assertIn("hxxps://phish[.]example[.]com/login", excerpt)
        self.assertNotIn("https://", excerpt)

    # test_long_reasons_keep_leading_items_and_say_there_is_more: เหตุผลเกินพื้นที่ยังแสดงข้อแรก ๆ
    def test_long_reasons_keep_leading_items_and_say_there_is_more(self):
        reason = "\n".join(f"เหตุผลข้อ {index}" for index in range(8))
        with patch.dict(os.environ, LIVE_ENV):
            texts = all_texts(self.card(reason=reason)["contents"])
        self.assertIn("เหตุผลข้อ 0", texts)
        self.assertNotIn("เหตุผลข้อ 7", texts)
        self.assertIn(flex_cards.LONG_REASON, texts)
        self.assertIn(flex_cards.FULL_TEXT_HINT, texts)

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

    def test_long_content_sends_only_the_card(self):
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
                            with patch.object(self.module.requests, "post", return_value=Mock()) as post:
                                self.assertTrue(self.module.reply_to_line("token", "fallback", card=card))
                            messages = post.call_args.kwargs["json"]["messages"]
                            self.assertEqual(messages, [card])
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
            self.assertTrue(self.module.reply_to_line("token", text, card=self.card))
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
                self.module.reply_to_line("token", text)
                self.assertEqual(post.call_args.kwargs["json"]["messages"],
                                 [{"type": "text", "text": self.module.TOO_LONG_NOTICE}])

    def test_plain_fallback_redacts_phone(self):
        with patch.object(self.module.requests, "post", return_value=Mock()) as post:
            self.module.reply_to_line("token", "โทร 081-234-5678")
        self.assertNotIn("081-234-5678", json.dumps(post.call_args.kwargs["json"]))

    # test_plain_text_replies_never_carry_clickable_links: ข้อความธรรมดาที่ LINE ทำลิงก์ให้กดได้ต้องไม่มีลิงก์ที่กดได้
    # เช่น เหตุผลจาก AI ที่ยกลิงก์มา ในคำตอบส่วนตัว คำเตือนกลุ่ม ผลรูปภาพ หรือบทเรียน
    def test_plain_text_replies_never_carry_clickable_links(self):
        reason = "• เหตุผล: ให้กด https://phish.example/login หรือ www.bank.example ทันที"
        rejected = Mock()
        rejected.status_code = 400
        rejected.raise_for_status.side_effect = requests.HTTPError(response=rejected)
        cases = {
            "plain": ({}, [Mock()]),
            "card_rejected": ({"card": self.card}, [rejected, Mock()]),
        }
        for name, (options, responses) in cases.items():
            with self.subTest(path=name), patch.dict(os.environ, {"MINI_LIFF_ID": "", "LINE_LOGIN_CHANNEL_ID": ""}), \
                    patch.object(self.module.requests, "post", side_effect=responses) as post:
                self.assertTrue(self.module.reply_to_line("token", reason, **options))
                text = post.call_args.kwargs["json"]["messages"][0]["text"]
                self.assertNotIn("https://", text)
                self.assertNotIn("www.bank", text)
                self.assertIn("hxxps://phish[.]example/login", text)
                self.assertIn("www[.]bank[.]example", text)

    # test_learning_button_uri_is_not_defanged: ลิงก์ปุ่ม Mini App เป็น action ไม่ใช่ข้อความ ต้องใช้งานได้ตามเดิม
    def test_learning_button_uri_is_not_defanged(self):
        with patch.dict(os.environ, {"MINI_LIFF_ID": "1234567890-TestApp", "LINE_LOGIN_CHANNEL_ID": "1234567890"}), \
                patch.object(self.module.requests, "post", return_value=Mock()) as post:
            self.module.reply_to_line("token", "ผลตรวจ", learn_case_id=CASE_ID)
        button = post.call_args.kwargs["json"]["messages"][-1]["template"]["actions"][0]
        self.assertEqual(button["uri"], f"https://liff.line.me/1234567890-TestApp?case={CASE_ID}")

    def test_non_400_errors_do_not_resend(self):
        for status in (401, 429, 500):
            rejected = Mock(status_code=status)
            rejected.raise_for_status.side_effect = requests.HTTPError(response=rejected)
            with self.subTest(status=status), patch.object(self.module.requests, "post", return_value=rejected) as post:
                self.assertFalse(self.module.reply_to_line("token", "ผลตรวจ", card=self.card))
            self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
