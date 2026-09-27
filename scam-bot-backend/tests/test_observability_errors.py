"""Offline logging checks: no credentials or live API calls."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "bot_observability.py"
if not MODULE_PATH.exists():
    MODULE_PATH = ROOT.parent / "bot_observability.py"
SPEC = importlib.util.spec_from_file_location("observability_under_test", MODULE_PATH)
observability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observability)


class ObservabilityErrorTests(unittest.TestCase):
    def test_api_error_has_safe_fields_and_preserves_exception(self):
        error = RuntimeError("SECRET_MESSAGE")
        error.code = 503
        error.status = "UNAVAILABLE"
        error.details = {"api_key": "SECRET_KEY"}
        token = observability.trace_id.set("test1234")
        try:
            with patch.object(observability, "monotonic", side_effect=[10, 29.66]), patch("builtins.print") as output:
                with self.assertRaises(RuntimeError) as caught:
                    observability.timed_call("llm:test", Mock(side_effect=error))
            self.assertIs(caught.exception, error)
            logged = " ".join(str(arg) for arg in output.call_args.args)
            self.assertIn("trace=test1234", logged)
            self.assertIn("elapsed=19.66s type=RuntimeError code=503 status=UNAVAILABLE", logged)
            self.assertNotIn("SECRET", logged)
        finally:
            observability.trace_id.reset(token)

    def test_untrusted_fields_are_omitted(self):
        for code, status in [("503 SECRET", "UNAVAILABLE\nSECRET"),
                             (True, {"SECRET": "value"}), (9999, ["UNAVAILABLE"])]:
            with self.subTest(code=code):
                error = RuntimeError("SECRET")
                error.code, error.status = code, status
                self.assertEqual(observability.error_summary(error), "type=RuntimeError")

    def test_error_without_sdk_fields_still_works(self):
        self.assertEqual(observability.error_summary(TimeoutError("SECRET")), "type=TimeoutError")

    def test_success_has_no_extra_log_and_keeps_result(self):
        operation = Mock(return_value={"ok": True})
        with patch("builtins.print") as output:
            result = observability.timed_call("llm:test", operation, "text", private=True)
        self.assertEqual(result, {"ok": True})
        operation.assert_called_once_with("text", private=True)
        output.assert_not_called()


if __name__ == "__main__":
    unittest.main()
