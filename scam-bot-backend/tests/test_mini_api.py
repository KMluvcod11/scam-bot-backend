"""ตรวจ API ของ Mini App ผ่าน HTTP ในเครื่อง; จำลอง LINE/AI/ประวัติทั้งหมด ไม่อ่าน .env."""
import os
import time
import unittest
from unittest.mock import Mock, patch

import requests
import test_webhook_threadpool as fixtures


class FakeHistory:
    """แทน mini_history: เก็บเคสในหน่วยความจำ และบันทึกว่าถูกถามด้วยเจ้าของคนไหน."""

    def __init__(self, unavailable):
        self.cases, self.calls, self.unavailable, self.broken = {}, [], unavailable, False

    def add(self, case_id, owner, message="ส่ง OTP มา"):
        self.cases[case_id] = (owner, {
            "id": case_id, "title": message, "category": "message", "message": message,
            "receivedAt": "2026-10-23T08:00:00+00:00", "status": "risk_found",
            "reason": "เหตุผลทดสอบ", "lessonId": "otp", "nextSteps": ["หยุดก่อน"],
            "warningPoints": [{"icon": "user", "title": "พบคำว่า OTP", "description": "x"}]})

    def _check(self, name, owner):
        self.calls.append((name, owner))
        if self.broken:
            raise self.unavailable()

    def list_cases(self, owner, limit=50):
        self._check("list", owner)
        keys = ("id", "title", "category", "receivedAt", "status")
        return [{key: detail[key] for key in keys}
                for case_owner, detail in self.cases.values() if case_owner == owner][:limit]

    def get_case(self, case_id, owner):
        self._check("get", owner)
        case = self.cases.get(case_id)
        return dict(case[1]) if case and case[0] == owner else None

    def delete_all(self, owner):
        self._check("delete", owner)
        mine = [key for key, (case_owner, _) in self.cases.items() if case_owner == owner]
        for key in mine:
            del self.cases[key]
        return len(mine)


class MiniApiTests(unittest.IsolatedAsyncioTestCase):
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
        history_module = self.module.mini_history
        self.history = FakeHistory(history_module.HistoryUnavailable)
        for name in ("list_cases", "get_case", "delete_all"):
            patcher = patch.object(history_module, name, getattr(self.history, name))
            patcher.start()
            self.addCleanup(patcher.stop)

    asyncTearDown = fixtures.WebhookThreadpoolTests.asyncTearDown

    def auth(self, token="test-id-token"):
        return {"Authorization": f"Bearer {token}"}

    def create_case(self, text="ส่ง OTP มา", number=1, owner="offline-user"):
        case_id = f"{number:032x}"
        self.history.add(case_id, owner, text)
        return case_id

    async def read_case(self, case_id, token="test-id-token", **kwargs):
        return await self.http.get(f"/api/mini/cases/{case_id}", headers=self.auth(token), **kwargs)

    async def test_reads_exact_original_case_from_history_without_ai(self):
        first = self.create_case("ส่ง OTP มา", 1)
        self.create_case("รับประกันกำไร ไม่มีความเสี่ยง", 2)
        response = await self.read_case(first)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], first)
        self.assertEqual(data["message"], "ส่ง OTP มา")
        self.assertNotIn("offline-user", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.history.calls, [("get", "offline-user")])
        self.verify.assert_called_with("https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": "test-id-token", "client_id": "1234567890"},
            timeout=10, allow_redirects=False)
        self.module.analyze_message.assert_not_called()

    async def test_case_other_owner_unknown_and_malformed_all_404_same_body(self):
        case_id = self.create_case()
        self.identity["sub"] = "another-user"
        wrong_owner = await self.read_case(case_id)
        self.identity["sub"] = "offline-user"
        unknown = await self.read_case("f" * 32)
        malformed = await self.read_case("not-a-case")
        for response in (wrong_owner, unknown, malformed):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), wrong_owner.json())
            self.assertNotIn("OTP", response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_query_user_id_cannot_override_verified_owner(self):
        case_id = self.create_case()
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
        case_id = self.create_case()
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
        case_id = self.create_case()
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

    async def test_cors_allows_delete_from_configured_origin(self):
        response = await self.http.options("/api/mini/history", headers={
            "Origin": "https://mini.example", "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization"})
        self.assertEqual(response.status_code, 200)

    async def test_history_lists_only_verified_owner_cases(self):
        self.create_case("ของฉัน", 1)
        self.create_case("ของคนอื่น", 2, owner="another-user")
        response = await self.http.get("/api/mini/history", headers=self.auth(),
                                       params={"user_id": "another-user"})
        self.assertEqual(response.status_code, 200)
        cases = response.json()["cases"]
        self.assertEqual([item["title"] for item in cases], ["ของฉัน"])
        self.assertNotIn("message", cases[0])
        self.assertEqual(self.history.calls, [("list", "offline-user")])
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_history_empty_returns_empty_list(self):
        response = await self.http.get("/api/mini/history", headers=self.auth())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"cases": []})

    async def test_delete_removes_verified_owner_and_is_repeatable(self):
        for number in (1, 2, 3):
            self.create_case(number=number)
        self.create_case(number=4, owner="another-user")
        first = await self.http.delete("/api/mini/history", headers=self.auth())
        second = await self.http.delete("/api/mini/history", headers=self.auth())
        self.assertEqual((first.status_code, first.json()), (200, {"deleted": 3}))
        self.assertEqual((second.status_code, second.json()), (200, {"deleted": 0}))
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertEqual(len(self.history.cases), 1)

    async def test_all_endpoints_401_without_token_and_never_touch_history(self):
        for method, path in (("get", "/api/mini/history"), ("delete", "/api/mini/history"),
                             ("get", "/api/mini/cases/" + "a" * 32)):
            response = await getattr(self.http, method)(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.history.calls, [])

    async def test_history_unavailable_is_503_without_raw_error(self):
        self.history.broken = True
        for method, path in (("get", "/api/mini/history"), ("delete", "/api/mini/history"),
                             ("get", "/api/mini/cases/" + "a" * 32)):
            response = await getattr(self.http, method)(path, headers=self.auth())
            self.assertEqual(response.status_code, 503)
            self.assertIn("ระบบประวัติขัดข้อง", response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_url_contains_only_random_case_and_validated_liff_id(self):
        case_id = "a" * 32
        self.assertEqual(self.api.get_mini_case_url(case_id), f"https://liff.line.me/1234567890-TestApp?case={case_id}")
        self.assertIsNone(self.api.get_mini_case_url("invalid"))
        for value in ("", "123-abc?token=SECRET", "https://attacker.invalid"):
            with patch.dict(os.environ, {"MINI_LIFF_ID": value}):
                self.assertIsNone(self.api.get_mini_case_url(case_id))


if __name__ == "__main__":
    unittest.main()
