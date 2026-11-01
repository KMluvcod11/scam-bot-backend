"""ตรวจสคริปต์เปรียบเทียบแบบ offline ไม่ import detector หรืออ่านคีย์จริง."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch


class ComparisonTests(unittest.TestCase):
    def load_comparison(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "compare_detection_inputs.py"
        spec = importlib.util.spec_from_file_location("comparison_evaluation_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_evaluation_budget_and_paired_context(self):
        module = self.load_comparison()
        cases = json.loads(Path(module.__file__).with_name("rag_evaluation_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 12)
        expected_by_text = {case["text"]: case["expected"] for case in cases.values()}
        self.assertEqual(len(expected_by_text), 12)
        def analyze(text, score, label, **kwargs):
            status = expected_by_text[text]
            return {"status": status, "is_scam": status == "risk_found"}
        analysis = Mock(side_effect=analyze)
        retrieval = Mock(return_value=(72.0, "spam", "synthetic reference"))
        with patch("builtins.print"):
            report = module.compare_inputs(analysis, retrieval, cases=cases, repeats=1)
        self.assertEqual(retrieval.call_count, 12)
        self.assertEqual(analysis.call_count, 24)
        for index in range(0, 24, 2):
            first, second = analysis.call_args_list[index:index+2]
            self.assertEqual(first.args, second.args)
            self.assertEqual(first.kwargs, {"matched_text": "", "private": True})
            self.assertEqual(second.kwargs, {"matched_text": "synthetic reference", "private": True})
        for counts in report["summary"].values():
            self.assertEqual(counts["total"], 12)
            self.assertEqual(counts["false_alarms"], 0)
            self.assertEqual(counts["missed_risks"], 0)
            self.assertEqual(counts["uncertain"], 3)

    def test_summary_separates_abstentions_failures_and_wrong_decisions(self):
        module = self.load_comparison()
        outcomes = [
            ("no_risk_found", "risk_found", True),
            ("risk_found", "no_risk_found", False),
            ("risk_found", "uncertain", False),
            ("risk_found", "error", None),
            ("risk_found", "fallback", False),
            ("risk_found", "risk_found", False),
            ("no_risk_found", "conversation", False),
        ]
        report = {"cases": {}, "matches": {}, "runs": []}
        for index, (expected, status, is_scam) in enumerate(outcomes):
            name = str(index)
            report["cases"][name] = {"expected": expected}
            report["matches"][name] = {"matched_text": ""}
            report["runs"].append({"input": name, "mode": "with_example",
                                   "result": {"status": status, "is_scam": is_scam}})
        counts = module.summarize(report)["with_example"]
        for key in ("false_alarms", "missed_risks", "uncertain", "error", "fallback", "invalid"):
            self.assertEqual(counts[key], 1, key)
        self.assertEqual(counts["matrix"]["no_risk_found"]["no_risk_found"], 1)
        self.assertEqual(counts["no_example"], 7)

    def test_service_exceptions_preserve_other_cases_and_hide_error_text(self):
        module = self.load_comparison()
        cases = {"first": {"text": "first", "expected": "risk_found"},
                 "second": {"text": "second", "expected": "no_risk_found"}}
        retrieval = Mock(side_effect=[TimeoutError("secret-value"), (60.0, "ham", "example")])
        analysis = Mock(side_effect=[RuntimeError("secret-value"), {"status": "no_risk_found", "is_scam": False}])
        with patch("builtins.print"):
            report = module.compare_inputs(analysis, retrieval, cases=cases, repeats=1)
        self.assertEqual(len(report["runs"]), 4)
        self.assertEqual(analysis.call_count, 2)
        self.assertEqual([run["result"]["status"] for run in report["runs"]],
                         ["error", "error", "error", "no_risk_found"])
        self.assertNotIn("secret-value", json.dumps(report))

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
