"""ตรวจสคริปต์เปรียบเทียบแบบ offline ไม่ import detector หรืออ่านคีย์จริง."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch


class ComparisonTests(unittest.TestCase):
    def test_six_calls_keep_inputs_context_and_errors(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "compare_detection_inputs.py"
        spec = importlib.util.spec_from_file_location("comparison_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        results = [
            {"status": "uncertain", "is_scam": False},
            {"status": "risk_found", "is_scam": True},
            {"status": "error", "is_scam": None},
        ] * 2
        analyze = Mock(side_effect=results)
        with patch("builtins.print"):
            report = module.compare_inputs(analyze)
        expected_calls = [call(text, 80.85, "spam", private=True)
                          for _ in range(3) for text in module.INPUTS.values()]
        self.assertEqual(analyze.call_args_list, expected_calls)
        self.assertEqual([run["result"] for run in report["runs"]], results)
        self.assertEqual([run["repeat"] for run in report["runs"]], [1, 1, 2, 2, 3, 3])
        self.assertEqual(len(module.INPUTS["text"]), 110)
        self.assertEqual(len(module.INPUTS["ocr"]), 197)


if __name__ == "__main__":
    unittest.main()
