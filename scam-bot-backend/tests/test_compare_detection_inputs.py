"""ตรวจสคริปต์เปรียบเทียบแบบ offline ไม่ import detector หรืออ่านคีย์จริง."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch


class ComparisonTests(unittest.TestCase):
    def test_paired_calls_keep_inputs_context_and_errors(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "compare_detection_inputs.py"
        spec = importlib.util.spec_from_file_location("comparison_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        results = [
            {"status": "uncertain", "is_scam": False},
            {"status": "risk_found", "is_scam": True},
            {"status": "error", "is_scam": None},
        ] * 4
        analyze = Mock(side_effect=results)
        find_match = Mock(side_effect=[
            (81.0, "spam", "ตัวอย่างข้อความ"),
            (62.0, "ham", "ตัวอย่าง OCR"),
        ])
        with patch("builtins.print"):
            report = module.compare_inputs(analyze, find_match)
        self.assertEqual(find_match.call_args_list, [
            call(module.INPUTS["text"]), call(module.INPUTS["ocr"]),
        ])
        expected_calls = [
            call(module.INPUTS["text"], 81.0, "spam", matched_text="", private=True),
            call(module.INPUTS["text"], 81.0, "spam", matched_text="ตัวอย่างข้อความ", private=True),
            call(module.INPUTS["ocr"], 62.0, "ham", matched_text="", private=True),
            call(module.INPUTS["ocr"], 62.0, "ham", matched_text="ตัวอย่าง OCR", private=True),
        ] * 3
        self.assertEqual(analyze.call_args_list, expected_calls)
        self.assertEqual(report["matches"], {
            "text": {"similarity_percent": 81.0, "matched_label": "spam", "matched_text": "ตัวอย่างข้อความ"},
            "ocr": {"similarity_percent": 62.0, "matched_label": "ham", "matched_text": "ตัวอย่าง OCR"},
        })
        self.assertEqual([run["result"] for run in report["runs"]], results)
        self.assertEqual([run["repeat"] for run in report["runs"]], [1] * 4 + [2] * 4 + [3] * 4)
        self.assertEqual([run["input"] for run in report["runs"]], ["text", "text", "ocr", "ocr"] * 3)
        self.assertEqual([run["mode"] for run in report["runs"]], ["without_example", "with_example"] * 6)
        self.assertEqual(len(module.INPUTS["text"]), 110)
        self.assertEqual(len(module.INPUTS["ocr"]), 197)

    def test_no_match_keeps_both_modes_without_example(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "compare_detection_inputs.py"
        spec = importlib.util.spec_from_file_location("comparison_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        find_match = Mock(return_value=(0.0, None, ""))
        analyze = Mock(return_value={"status": "uncertain", "is_scam": False})
        with patch("builtins.print"):
            report = module.compare_inputs(analyze, find_match)
        self.assertEqual(find_match.call_count, 2)
        self.assertEqual(analyze.call_count, 12)
        for analysis_call in analyze.call_args_list:
            self.assertEqual(analysis_call.args[1:], (0.0, None))
            self.assertEqual(analysis_call.kwargs, {"matched_text": "", "private": True})
        self.assertEqual([run["mode"] for run in report["runs"]], ["without_example", "with_example"] * 6)


if __name__ == "__main__":
    unittest.main()
