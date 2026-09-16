"""จำลอง timeout และงานซ้อนกัน ไม่ใช้ API จริงหรืออ่านคีย์."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from test_llm_validation import load_detector
from test_webhook_threadpool import load_app


class TimeoutTests(unittest.TestCase):
    def setUp(self):
        self.detector = load_detector()

    def test_embedding_timeout_stops_before_database(self):
        d = self.detector
        d.client.models.embed_content.side_effect = httpx.ReadTimeout("secret")
        with patch("builtins.print") as output:
            result = d.analyze_message("ข้อความยาวสำหรับการทดสอบระบบหมดเวลา" * 2)
        self.assertEqual(result, {"status": "error", "is_scam": None, "error_stage": "embedding"})
        d.supabase.rpc.assert_not_called()
        self.assertNotIn("secret", str(output.call_args_list))
        self.assertIn("stage=embedding", str(output.call_args_list))

    def test_database_timeout_stops_before_llm(self):
        d = self.detector
        d.client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1])])
        d.supabase.rpc.return_value.execute.side_effect = httpx.ReadTimeout("secret")
        with patch("builtins.print"):
            result = d.analyze_message("ข้อความยาวสำหรับการทดสอบระบบหมดเวลา" * 2)
        self.assertEqual(result["error_stage"], "vector_db")
        self.assertIsNone(result["is_scam"])
        d.client.models.generate_content.assert_not_called()

    def test_llm_timeout_does_not_warn_using_fallback(self):
        d = self.detector
        for error in (httpx.ReadTimeout("secret"), TimeoutError("secret")):
            d.client.models.generate_content.reset_mock()
            d.client.models.generate_content.side_effect = error
            with patch("builtins.print"):
                result = d.analyze_with_llm("ทดสอบ", 91, "spam")
            self.assertEqual(result, {"status": "error", "is_scam": None, "error_stage": "llm"})
            self.assertEqual(d.client.models.generate_content.call_count, 1)

    def test_only_errors_add_timing_logs_without_raw_exception(self):
        timed_call = self.detector.timed_call
        with patch("builtins.print") as output:
            self.assertEqual(timed_call("test", lambda: 42), 42)
            output.assert_not_called()
            with self.assertRaises(ValueError):
                timed_call("test", lambda: (_ for _ in ()).throw(ValueError("secret")))
        logs = str(output.call_args_list)
        for expected in ("[ERROR]", "elapsed="):
            self.assertIn(expected, logs)
        self.assertNotIn("[START]", logs)
        self.assertNotIn("[END]", logs)
        self.assertNotIn("secret", logs)


class TraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_events_keep_trace_in_worker_and_reset(self):
        app = load_app()
        trace_id = app.trace_id
        import threading
        barrier = threading.Barrier(2)
        seen = {}

        def analyze(text):
            seen[text] = trace_id.get()
            barrier.wait(timeout=3)
            self.assertEqual(trace_id.get(), seen[text])
            return {"status": "error", "is_scam": None}

        app.analyze_message.side_effect = analyze
        def event(text):
            return SimpleNamespace(message=SimpleNamespace(text=text), reply_token="secret-token")
        with patch("builtins.print") as output:
            await asyncio.gather(app.process_text_event(event("first")), app.process_text_event(event("second")))
        self.assertEqual(len(set(seen.values())), 2)
        self.assertNotIn("-", seen.values())
        for value in seen.values():
            self.assertEqual(len(value), 8)
            self.assertIn(f"[trace={value}]", str(output.call_args_list))
        self.assertNotIn("[START]", str(output.call_args_list))
        self.assertNotIn("[END]", str(output.call_args_list))
        self.assertEqual(trace_id.get(), "-")
        app.reply_to_line.assert_not_called()
        self.assertNotIn("secret-token", str(output.call_args_list))


if __name__ == "__main__":
    unittest.main()
