"""ตรวจการอ่านเคสผ่าน HTTP ในเครื่อง; จำลอง LINE/AI/ประวัติทั้งหมด ไม่อ่าน .env."""
import os
import time
import unittest
from unittest.mock import Mock, patch

import requests
import test_webhook_threadpool as fixtures
from test_private_chat import private_event, result


class MiniApiTests(unittest.IsolatedAsyncioTestCase):
    post_events = fixtures.WebhookThreadpoolTests.post_events

    async def asyncSetUp(self):
        self.environment = patch.dict(os.environ, {
            "MINI_LIFF_ID": "1234567890-TestApp", "LINE_LOGIN_CHANNEL_ID": "1234567890",
            "MINI_WEB_ORIGIN": "https://mini.example",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        await fixtures.WebhookThreadpoolTests.asyncSetUp(self)
        import mini_api
        self.api = mini_api
        self.identity = {"sub": "offline-user", "aud": "1234567890", "iss": "https://access.line.me",
                         "exp": time.time() + 3600}
        self.verify_response = Mock(status_code=200)
        self.verify_response.json.return_value = self.identity
        self.verification = patch.object(self.api.requests, "post", return_value=self.verify_response)
        self.verify = self.verification.start()
        self.addCleanup(self.verification.stop)

    asyncTearDown = fixtures.WebhookThreadpoolTests.asyncTearDown

    async def create_case(self, text="ส่ง OTP มา", number=1):
        self.module.analyze_message.return_value = result("risk_found")
        response = await self.post_events([private_event(text, number)])
        self.assertEqual(response.status_code, 200)
        return self.module.reply_to_line.call_args.kwargs["learn_case_id"]

    async def read_case(self, case_id, token="test-id-token", **kwargs):
        return await self.http.get(f"/api/mini/cases/{case_id}",
                                   headers={"Authorization": f"Bearer {token}"}, **kwargs)

    async def test_reads_exact_original_case_after_new_message_without_ai_or_database(self):
        first = await self.create_case("ส่ง OTP มา", 1)
        await self.create_case("รับประกันกำไร ไม่มีความเสี่ยง", 2)
        self.module.analyze_message.reset_mock()
        self.module.save_detection.reset_mock()
        response = await self.read_case(first)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], first)
        self.assertEqual(data["message"], "ส่ง OTP มา")
        self.assertEqual(data["reason"], result("risk_found")["reason"])
        self.assertEqual(data["receivedAt"], "1970-01-01T00:00:00+00:00")
        self.assertEqual(data["lessonId"], "otp")
        self.assertNotIn("offline-user", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.verify.assert_called_with("https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": "test-id-token", "client_id": "1234567890"},
            timeout=10, allow_redirects=False)
        self.module.analyze_message.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_wrong_owner_unknown_expired_and_restart_are_indistinguishable(self):
        now = [0]
        self.module.lesson_store = self.module.LessonStore(clock=lambda: now[0])
        case_id = await self.create_case()
        self.identity["sub"] = "another-user"
        wrong_owner = await self.read_case(case_id)
        self.identity["sub"] = "offline-user"
        unknown = await self.read_case("f" * 32)
        now[0] = 900
        expired = await self.read_case(case_id)
        self.module.lesson_store = self.module.LessonStore()
        restarted = await self.read_case(case_id)
        for response in (wrong_owner, unknown, expired, restarted):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), wrong_owner.json())
            self.assertNotIn("OTP", response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_query_user_id_cannot_override_verified_owner(self):
        case_id = await self.create_case()
        self.identity["sub"] = "another-user"
        response = await self.read_case(case_id, params={"user_id": "offline-user"})
        self.assertEqual(response.status_code, 404)

    async def test_missing_or_malformed_authorization_does_not_call_line(self):
        for value in ("", "Basic test", "Bearer ", "Bearer has spaces", "Bearer " + "x" * 8193):
            response = await self.http.get("/api/mini/cases/" + "a" * 32, headers={"Authorization": value})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.verify.assert_not_called()

    async def test_line_rejection_expired_wrong_channel_and_invalid_identity_never_release_case(self):
        case_id = await self.create_case()
        for changes in ({"aud": "different-channel"}, {"iss": "https://attacker.invalid"},
                        {"sub": ""}, {"exp": 0}, {"exp": "9999999999"}, {"exp": float("nan")}):
            with self.subTest(changes=changes):
                self.verify_response.json.return_value = {**self.identity, **changes}
                response = await self.read_case(case_id)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("OTP", response.text)
        for code in (400, 401, 403):
            self.verify_response.status_code = code
            self.assertEqual((await self.read_case(case_id)).status_code, 401)

    async def test_line_failure_and_bad_json_do_not_leak_errors(self):
        case_id = await self.create_case()
        for error in (requests.Timeout("SECRET_TOKEN"), requests.ConnectionError("SECRET_TOKEN")):
            self.verify.side_effect = error
            response = await self.read_case(case_id)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("SECRET_TOKEN", response.text)
        self.verify.side_effect = None
        for code in (429, 500, 302):
            self.verify_response.status_code = code
            self.assertEqual((await self.read_case(case_id)).status_code, 503)
        self.verify_response.status_code = 200
        self.verify_response.json.side_effect = ValueError("SECRET_TOKEN")
        self.assertEqual((await self.read_case(case_id)).status_code, 503)
        self.verify_response.json.side_effect = None
        self.verify_response.json.return_value = []
        self.assertEqual((await self.read_case(case_id)).status_code, 503)

    async def test_missing_server_setting_fails_closed(self):
        with patch.dict(os.environ, {"LINE_LOGIN_CHANNEL_ID": ""}):
            self.assertEqual((await self.read_case("a" * 32)).status_code, 503)
        self.verify.assert_not_called()

    async def test_cors_allows_only_configured_origin(self):
        for origin, expected in (("https://mini.example", 200), ("https://attacker.invalid", 400)):
            response = await self.http.options("/api/mini/cases/" + "a" * 32, headers={
                "Origin": origin, "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            })
            self.assertEqual(response.status_code, expected)
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin if expected == 200 else None)

    async def test_store_copies_detail_and_preserves_legacy_lesson(self):
        case_id = await self.create_case()
        detail = self.module.lesson_store.get_detail(case_id, "offline-user")
        detail["warningPoints"][0]["title"] = "changed"
        self.assertNotEqual(self.module.lesson_store.get_detail(case_id, "offline-user")["warningPoints"][0]["title"], "changed")
        self.assertIn("OTP", self.module.lesson_store.get(case_id, "offline-user"))

    async def test_url_contains_only_random_case_and_validated_liff_id(self):
        case_id = await self.create_case()
        self.assertEqual(self.api.get_mini_case_url(case_id), f"https://liff.line.me/1234567890-TestApp?case={case_id}")
        self.assertIsNone(self.api.get_mini_case_url("invalid"))
        for value in ("", "123-abc?token=SECRET", "https://attacker.invalid"):
            with patch.dict(os.environ, {"MINI_LIFF_ID": value}):
                self.assertIsNone(self.api.get_mini_case_url(case_id))


if __name__ == "__main__":
    unittest.main()
