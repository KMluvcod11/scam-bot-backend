"""ทดสอบคำตอบ LLM แบบ offline: ใช้ client จำลอง ไม่อ่าน .env และไม่เชื่อม API."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import google


def load_detector():
    """แทนที่ dependency ตอน import เพื่อไม่สร้าง client จริงหรืออ่าน secret."""
    config = ModuleType("config")
    for name, value in {
        "GEMINI_KEY": "test", "SUPABASE_URL": "test", "SUPABASE_KEY": "test",
        "SAFE_WORDS": set(), "SCAM_TRIGGERS": [],
        "VECTOR_MATCH_THRESHOLD": 0.65, "DIRECT_SCAM_THRESHOLD": 92.0,
        "SAFE_BROWSING_API_KEY": "offline-test-key",
    }.items():
        setattr(config, name, value)
    genai = ModuleType("google.genai")
    genai.Client = Mock(return_value=Mock())
    genai.types = SimpleNamespace(
        HttpOptions=lambda **kw: kw, HttpRetryOptions=lambda **kw: kw,
        GenerateContentConfig=lambda **kw: kw, EmbedContentConfig=lambda **kw: kw,
    )
    supabase = ModuleType("supabase")
    supabase.create_client = Mock(return_value=Mock())
    supabase_client = ModuleType("supabase.client")
    supabase_client.ClientOptions = lambda **kw: kw
    path = Path(__file__).resolve().parents[1] / "detector.py"
    url_spec = importlib.util.spec_from_file_location(
        "url_checker_under_test", path.with_name("url_checker.py"),
    )
    url_checker = importlib.util.module_from_spec(url_spec)
    spec = importlib.util.spec_from_file_location("detector_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "config": config, "google.genai": genai,
        "supabase": supabase, "supabase.client": supabase_client,
    }), patch.object(google, "genai", genai, create=True), patch.object(
        sys, "path", [str(path.parent), *sys.path],
    ):
        url_spec.loader.exec_module(url_checker)
        # ใช้ตัวดึงลิงก์จริง แต่แทนการตรวจ Google เพื่อไม่ออกเครือข่ายใน tests
        url_checker.check_url = Mock(return_value={"status": "not_found", "threat_types": []})
        with patch.dict(sys.modules, {"url_checker": url_checker}):
            spec.loader.exec_module(module)
    return module


class LLMValidationTests(unittest.TestCase):
    # setUp: เตรียม detector จำลองและผล LLM ที่ถูกต้องเป็นฐานสำหรับทดสอบ validation
    def setUp(self):
        self.detector = load_detector()
        self.valid = {"is_scam": False, "risk_level": "low", "reason": "ข้อความทั่วไป"}

    # test_valid_boolean_and_all_risk_levels: ทดสอบรับ boolean และระดับความเสี่ยงทั้งสามค่าที่ถูกต้องจาก LLM
    def test_valid_boolean_and_all_risk_levels(self):
        for flag in (True, False):
            for level in ("low", "medium", "high"):
                with self.subTest(flag=flag, level=level):
                    value = {**self.valid, "is_scam": flag, "risk_level": level}
                    self.assertEqual(self.detector.validate_llm_result(value), value)

    # test_reject_non_objects: ทดสอบปฏิเสธผล LLM ที่ไม่ใช่ JSON object
    def test_reject_non_objects(self):
        for value in (None, [], "false", False, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.detector.validate_llm_result(value)

    # test_reject_missing_fields: ทดสอบปฏิเสธผล LLM ที่ขาดฟิลด์บังคับ
    def test_reject_missing_fields(self):
        for key in self.valid:
            value = dict(self.valid)
            del value[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.detector.validate_llm_result(value)

    # test_reject_wrong_field_types_and_values: ทดสอบปฏิเสธชนิดหรือค่าของฟิลด์ LLM ที่ไม่ตรงสัญญาข้อมูล
    def test_reject_wrong_field_types_and_values(self):
        invalid = {
            "is_scam": ["false", "true", 0, 1, None, []],
            "risk_level": [None, [], 1, "HIGH", "critical", ""],
            "reason": [None, [], 1, "", "   "],
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.detector.validate_llm_result({**self.valid, key: value})

    # run_responses: กำหนดลำดับคำตอบโมเดลจำลองแล้วรันวิเคราะห์ เพื่อให้ตรวจผลและจำนวนครั้งที่ลองโมเดล
    def run_responses(self, responses, score=85):
        generate = self.detector.client.models.generate_content
        generate.side_effect = [SimpleNamespace(text=text) for text in responses]
        with patch("builtins.print"):
            result = self.detector.analyze_with_llm("ข้อความทดสอบ", score, "spam")
        return result, generate

    # test_unchecked_link_is_stated_in_prompt_only_when_flagged: AI ต้องรู้ว่าลิงก์ยังไม่ได้ตรวจ จะได้ไม่สรุปว่าปลอดภัย
    def test_unchecked_link_is_stated_in_prompt_only_when_flagged(self):
        generate = self.detector.client.models.generate_content
        for flagged in (True, False):
            with self.subTest(flagged=flagged):
                generate.reset_mock()
                generate.side_effect = [SimpleNamespace(text=json.dumps(self.valid))]
                with patch("builtins.print"):
                    self.detector.analyze_with_llm("ดูที่ https://a.test", 0.0, None, url_unchecked=flagged)
                prompt = generate.call_args.kwargs["contents"]
                if flagged:
                    self.assertIn('"url_safety_check": "unavailable"', prompt)
                else:
                    self.assertNotIn("url_safety_check", prompt)

    # test_valid_false_does_not_trigger_failover: ทดสอบ is_scam=False ที่ถูกต้องไม่ถูกเข้าใจว่าโมเดลล้มเหลว
    def test_valid_false_does_not_trigger_failover(self):
        result, generate = self.run_responses([json.dumps(self.valid)])
        self.assertIs(result["is_scam"], False)
        self.assertEqual(generate.call_count, 1)

    # test_bad_response_tries_next_model: ทดสอบคำตอบผิดรูปแบบทำให้ลองโมเดลถัดไปตามลำดับ
    def test_bad_response_tries_next_model(self):
        for bad in ("not json", "null", "[]", None,
                    json.dumps({**self.valid, "is_scam": "false"}),
                    json.dumps({**self.valid, "risk_level": None})):
            with self.subTest(bad=bad):
                self.setUp()
                result, generate = self.run_responses([bad, json.dumps(self.valid)])
                self.assertEqual(result, self.valid)
                self.assertEqual(
                    [call.kwargs["model"] for call in generate.call_args_list],
                    ["gemini-3.5-flash-lite", "gemini-3.6-flash"],
                )

    # test_both_invalid_keep_existing_fallback_boundary: ทดสอบคำตอบเสียทั้งสองโมเดลใช้เกณฑ์กฎสำรองที่ขอบเขตคะแนนเดิม
    def test_both_invalid_keep_existing_fallback_boundary(self):
        for score, expected in ((79.99, False), (80.0, True), (90.0, True)):
            with self.subTest(score=score):
                self.setUp()
                result, generate = self.run_responses(["null", "{}"], score)
                self.assertIs(result["is_scam"], expected)
                self.assertEqual(result["status"], "fallback")
                self.assertEqual(generate.call_count, 2)
                if expected:
                    self.assertEqual(result["risk_level"], "medium")

    # test_reason_length_boundary: ทดสอบความยาวเหตุผลที่ขอบเขตสูงสุดและเมื่อยาวเกิน
    def test_reason_length_boundary(self):
        for size, accepted in ((499, True), (500, True), (501, False)):
            with self.subTest(size=size):
                value = {**self.valid, "reason": ("ab" * 251)[:size]}
                if accepted:
                    self.assertEqual(self.detector.validate_llm_result(value), value)
                else:
                    with self.assertRaises(ValueError):
                        self.detector.validate_llm_result(value)

    # test_identical_run_boundary: ทดสอบขอบเขตจำนวนอักขระซ้ำติดกันที่ทำให้เหตุผลไม่ผ่าน
    def test_identical_run_boundary(self):
        for character in ("0", "ก", "!", " ", "\n"):
            for size in (19, 20, 21):
                with self.subTest(character=character, size=size):
                    value = {**self.valid, "reason": "start" + character * size + "end"}
                    if size < 20:
                        self.assertEqual(self.detector.validate_llm_result(value), value)
                    else:
                        with self.assertRaises(ValueError):
                            self.detector.validate_llm_result(value)

    # test_normal_thai_reason_with_numbers_is_unchanged: ทดสอบเหตุผลภาษาไทยปกติที่มีตัวเลขไม่ถูกแก้หรือปฏิเสธ
    def test_normal_thai_reason_with_numbers_is_unchanged(self):
        value = {**self.valid, "reason": "ชักชวนทำงานรายได้ 1,500 บาท แต่ให้โอนค่าประกัน 300 บาทก่อนเริ่มงาน"}
        self.assertEqual(self.detector.validate_llm_result(value), value)

    # test_garbled_reason_tries_second_model_without_logging_garbage: ทดสอบเหตุผลเสียทำให้ลองโมเดลที่สองโดยไม่พิมพ์เนื้อหาที่เสียลง log
    def test_garbled_reason_tries_second_model_without_logging_garbage(self):
        for reason in ("เข้าข่ายหลอกลวง" + "0" * 2000, "ab" * 251, "เลข" + "0" * 20):
            with self.subTest(length=len(reason)):
                self.detector.client.models.generate_content.reset_mock(side_effect=True)
                bad = {"is_scam": True, "risk_level": "high", "reason": reason}
                self.detector.client.models.generate_content.side_effect = [
                    SimpleNamespace(text=json.dumps(bad)),
                    SimpleNamespace(text=json.dumps(self.valid)),
                ]
                with patch("builtins.print") as output:
                    result = self.detector.analyze_with_llm("ทดสอบ", 89.79)
                self.assertEqual(result, self.valid)
                self.assertEqual(self.detector.client.models.generate_content.call_count, 2)
                log = " ".join(str(call) for call in output.call_args_list)
                self.assertNotIn(reason, log)
                self.assertIn("LLM FAILOVER", log)

    # test_both_garbled_reasons_use_existing_fallback: ทดสอบเหตุผลเสียทั้งสองโมเดลใช้กฎสำรองโดยไม่คัดลอกเหตุผลเสียมาแสดง
    def test_both_garbled_reasons_use_existing_fallback(self):
        bad = json.dumps({**self.valid, "reason": "0" * 2000})
        for score, expected in ((79.99, False), (80.0, True)):
            with self.subTest(score=score):
                result, _ = self.run_responses([bad, bad], score)
                self.assertEqual(result["status"], "fallback")
                self.assertIs(result["is_scam"], expected)
                self.assertNotIn("0" * 20, result.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
