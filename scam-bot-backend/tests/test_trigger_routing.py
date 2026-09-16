"""ตรวจการส่งเข้า LLM ด้วยคีย์เวิร์ดจาก config จริง โดยไม่อ่าน secret หรือเรียก API."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
from test_llm_validation import load_detector


class TriggerRoutingTests(unittest.TestCase):
    def setUp(self):
        self.detector = load_detector()
        # อ่านรายการคำโดยไม่รัน config.py ที่โหลด .env
        path = Path(__file__).resolve().parents[1] / "config.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SCAM_TRIGGERS" for t in node.targets
            ):
                self.detector.SCAM_TRIGGERS = ast.literal_eval(node.value)
                break
        else:
            self.fail("Missing SCAM_TRIGGERS")

    def route(self, text, score, label="spam", decision=False):
        result = {"is_scam": decision, "risk_level": "low", "reason": "test"}
        with patch.object(self.detector, "find_similarity", return_value=(score, label)), patch.object(
            self.detector, "analyze_with_llm", return_value=result
        ) as llm, patch("builtins.print"):
            actual = self.detector.analyze_message(text)
        return actual, llm

    def test_s5_reaches_llm_at_observed_score(self):
        text = "กลุ่มลงทุนรับประกันกำไร 30% ทุกวัน ไม่มีความเสี่ยง ฝาก 1,000 บาทรับคืน 1,300 บาทภายในคืนนี้ สนใจโอนเงินเข้าบัญชีผู้ดูแลกลุ่มเพื่อเริ่มลงทุนได้ทันที"
        _, llm = self.route(text, 83.68)
        llm.assert_called_once_with(text, 83.68, "spam")

    def test_s7_reaches_llm_at_observed_score(self):
        text = "ผมเป็นเจ้าหน้าที่ตำรวจ พบว่าบัญชีคุณเกี่ยวข้องกับคดีฟอกเงิน ต้องโอนเงินทั้งหมดมายังบัญชีตรวจสอบของเจ้าหน้าที่ทันที และห้ามแจ้งครอบครัวระหว่างดำเนินการ"
        _, llm = self.route(text, 81.06)
        llm.assert_called_once_with(text, 81.06, "spam")

    def test_normal_context_uses_llm_decision(self):
        for text in (
            "รายงานวันนี้ให้อธิบายความเสี่ยงของการลงทุนและยกตัวอย่างการออมเงินระยะยาว",
            "วันนี้ตำรวจมาให้ความรู้เรื่องการป้องกันมิจฉาชีพที่มหาวิทยาลัย อย่าลืมเข้าร่วม",
            "เตือนภัย อย่าเชื่อคนอ้างเป็นตำรวจให้โอนเงินเข้าบัญชีตรวจสอบและห้ามแจ้งครอบครัว",
        ):
            with self.subTest(text=text):
                result, llm = self.route(text, 81.06, "ham")
                llm.assert_called_once()
                self.assertIs(result["is_scam"], False)

    def test_all_new_keywords_route_without_forcing_warning(self):
        for keyword in ("ลงทุน", "รับประกันกำไร", "ไม่มีความเสี่ยง", "ตำรวจ", "ฟอกเงิน", "บัญชีตรวจสอบ", "ห้ามแจ้งครอบครัว"):
            with self.subTest(keyword=keyword):
                result, llm = self.route("ข้อความสำหรับทดสอบการส่งต่อเพื่อวิเคราะห์บริบท " + keyword, 80)
                llm.assert_called_once()
                self.assertIs(result["is_scam"], False)

    def test_65_percent_boundary_unchanged(self):
        for score, calls in ((64.99, 0), (65, 1)):
            with self.subTest(score=score):
                _, llm = self.route("ข้อความเกี่ยวกับการลงทุนสำหรับทดสอบการส่งต่อให้วิเคราะห์บริบท", score)
                self.assertEqual(llm.call_count, calls)

    def test_no_keyword_and_short_text_rules_unchanged(self):
        for text in ("พรุ่งนี้ประชุมงานกลุ่มที่ห้องสมุดและเตรียมสไลด์มาให้พร้อม", "ตำรวจ"):
            with self.subTest(text=text):
                result, llm = self.route(text, 84)
                llm.assert_not_called()
                self.assertIs(result["is_scam"], False)


if __name__ == "__main__":
    unittest.main()
