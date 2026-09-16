"""คะแนนสูงต้องอ่านคู่กับ label; ทดสอบ offline ไม่เรียก API."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_llm_validation import load_detector


class MatchLabelTests(unittest.TestCase):
    def setUp(self):
        self.detector = load_detector()
        self.text = "ข้อความทดสอบที่ยาวเกินยี่สิบห้าตัวอักษรเพื่อไม่ให้ถูกข้าม"
        self.detector.client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1] * 768)])

    def match(self, score, label):
        self.detector.supabase.rpc.return_value.execute.return_value = SimpleNamespace(
            data=[{"similarity": score, "label": label, "thai_text": "ตัวอย่าง"}])

    def analyze(self):
        with patch("builtins.print"):
            return self.detector.analyze_message(self.text)

    def answer(self, is_scam):
        self.detector.client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({"is_scam": is_scam, "risk_level": "high" if is_scam else "low",
                             "reason": "เหตุผลทดสอบ"}))

    def test_ham_100_percent_goes_to_llm_not_direct_warning(self):
        self.match(1.0, "ham")
        self.answer(False)
        self.assertIs(self.analyze()["is_scam"], False)
        self.detector.client.models.generate_content.assert_called_once()

    def test_ham_can_still_be_scam_when_llm_detects_risk(self):
        self.match(0.95, "ham")
        self.answer(True)
        self.assertIs(self.analyze()["is_scam"], True)
        self.detector.client.models.generate_content.assert_called_once()

    def test_spam_92_percent_keeps_direct_warning(self):
        self.match(0.92, "spam")
        self.assertIs(self.analyze()["is_scam"], True)
        self.detector.client.models.generate_content.assert_not_called()

    def test_ham_with_keyword_uses_existing_llm_gate(self):
        self.match(0.80, "ham")
        self.detector.SCAM_TRIGGERS = ["ทดสอบ"]
        self.answer(False)
        self.assertIs(self.analyze()["is_scam"], False)
        self.detector.client.models.generate_content.assert_called_once()

    def test_no_keyword_below_85_keeps_existing_gate(self):
        self.match(0.84, "ham")
        self.assertIs(self.analyze()["is_scam"], False)
        self.detector.client.models.generate_content.assert_not_called()

    def test_ham_high_score_never_warns_from_fallback(self):
        self.match(1.0, "ham")
        self.detector.client.models.generate_content.side_effect = RuntimeError("offline")
        result = self.analyze()
        self.assertEqual(result, {"status": "fallback", "is_scam": False})
        self.assertEqual(self.detector.client.models.generate_content.call_count, 2)

    def test_unknown_label_is_error_not_warning(self):
        for label in (None, "", "unknown", [], 1):
            with self.subTest(label=label):
                self.match(1.0, label)
                result = self.analyze()
                self.assertEqual(result["status"], "error")
                self.assertIsNone(result["is_scam"])

    def test_empty_match_returns_zero_and_no_label(self):
        self.detector.supabase.rpc.return_value.execute.return_value = SimpleNamespace(data=[])
        with patch("builtins.print"):
            self.assertEqual(self.detector.find_similarity(self.text), (0.0, None))

    def test_match_returns_and_logs_label(self):
        self.match(0.9, "ham")
        with patch("builtins.print") as output:
            self.assertEqual(self.detector.find_similarity(self.text), (90.0, "ham"))
        self.assertIn("label=ham", str(output.call_args_list))

    def test_unspecified_label_cannot_trigger_fallback_warning(self):
        self.detector.client.models.generate_content.side_effect = RuntimeError("offline")
        with patch("builtins.print"):
            result = self.detector.analyze_with_llm(self.text, 100)
        self.assertEqual(result, {"status": "fallback", "is_scam": False})


if __name__ == "__main__":
    unittest.main()
