"""จำลองบริการล่มและข้อมูลเสีย โดยไม่อ่านคีย์หรือเรียก API จริง."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_llm_validation import load_detector


class DetectionErrorTests(unittest.TestCase):
    def setUp(self):
        self.detector = load_detector()
        self.text = "ข้อความสำหรับทดสอบความผิดพลาดที่ยาวเกินยี่สิบห้าตัวอักษร"
        self.detector.client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1] * 768)],
        )

    def analyze(self):
        with patch("builtins.print") as output:
            result = self.detector.analyze_message(self.text)
        return result, " ".join(str(call) for call in output.call_args_list)

    def test_embedding_failure_is_unknown_and_does_not_query_database(self):
        self.detector.client.models.embed_content.side_effect = TimeoutError("SECRET_TEST")
        result, log = self.analyze()
        self.assertEqual(result, {"status": "error", "is_scam": None, "error_stage": "embedding"})
        self.detector.supabase.rpc.assert_not_called()
        self.assertIn("TimeoutError", log)
        self.assertNotIn("SECRET_TEST", log)

    def test_missing_embedding_is_unknown(self):
        self.detector.client.models.embed_content.return_value = SimpleNamespace(embeddings=[])
        result, _ = self.analyze()
        self.assertEqual(result["error_stage"], "embedding")
        self.assertIsNone(result["is_scam"])

    def test_database_failure_is_unknown_and_does_not_call_llm(self):
        self.detector.supabase.rpc.return_value.execute.side_effect = RuntimeError("SECRET_TEST")
        result, log = self.analyze()
        self.assertEqual(result["error_stage"], "vector_db")
        self.assertIsNone(result["is_scam"])
        self.detector.client.models.generate_content.assert_not_called()
        self.assertNotIn("SECRET_TEST", log)

    def test_empty_search_is_not_a_service_failure(self):
        self.detector.supabase.rpc.return_value.execute.return_value = SimpleNamespace(data=[])
        result, _ = self.analyze()
        self.assertIs(result["is_scam"], False)
        self.assertNotEqual(result.get("status"), "error")

    def test_invalid_search_results_are_not_safe_results(self):
        for data in (None, {}, [{}], [{"similarity": float("nan"), "thai_text": "test"}],
                     [{"similarity": "0.9", "thai_text": "test"}]):
            with self.subTest(data=data):
                self.detector.supabase.rpc.return_value.execute.return_value = SimpleNamespace(data=data)
                result, _ = self.analyze()
                self.assertEqual(result["error_stage"], "vector_db")
                self.assertIsNone(result["is_scam"])

    def test_successful_search_keeps_direct_warning(self):
        self.detector.supabase.rpc.return_value.execute.return_value = SimpleNamespace(
            data=[{"similarity": 0.93, "thai_text": "test", "label": "spam"}],
        )
        result, _ = self.analyze()
        self.assertIs(result["is_scam"], True)
        self.assertEqual(result["risk_level"], "high")

    def test_llm_exceptions_keep_fallback_without_leaking_error_details(self):
        self.detector.client.models.generate_content.side_effect = RuntimeError("SECRET_TEST")
        for score, expected in ((79.99, False), (80, True)):
            with self.subTest(score=score), patch("builtins.print") as output:
                result = self.detector.analyze_with_llm(self.text, score, "spam")
                self.assertEqual(result["status"], "fallback")
                self.assertIs(result["is_scam"], expected)
                log = " ".join(str(call) for call in output.call_args_list)
                self.assertIn("stage=llm", log)
                self.assertNotIn("SECRET_TEST", log)


if __name__ == "__main__":
    unittest.main()
