"""ทดสอบการตรวจ URL และ cache ในเครื่อง ไม่อ่านคีย์หรือเรียกบริการภายนอก."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


class URLValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "url_checker.py"
        spec = importlib.util.spec_from_file_location("url_checker_under_test", path)
        cls.checker = importlib.util.module_from_spec(spec)
        config = ModuleType("config")
        config.SAFE_BROWSING_API_KEY = "offline-test-key"
        with patch.dict(sys.modules, {"config": config}):
            spec.loader.exec_module(cls.checker)

    def setUp(self):
        self.checker._url_cache.clear()
        self.addCleanup(self.checker._url_cache.clear)
        self.now = 100.0
        self.enterContext(patch.object(
            self.checker, "monotonic", side_effect=lambda: self.now,
        ))
        self.enterContext(patch.object(
            self.checker.requests, "get",
            side_effect=AssertionError("External HTTP is forbidden in offline tests"),
        ))

    def test_http_https_paths_queries_and_ports(self):
        cases = (
            "http://example.com",
            "https://example.com/page?item=123&language=th",
            "https://example.com:8443/path",
            "https://[2001:db8::1]:443/path",
            "https://example.com/?next=https%3A%2F%2Fexample.org%2F",
        )
        for url in cases:
            with self.subTest(url=url):
                self.assertEqual(self.checker.validate_url(url), url)

    def test_trims_outer_spaces_and_removes_only_fragment(self):
        self.assertEqual(
            self.checker.validate_url("  HTTPS://Example.COM/page?q=%23value#section  "),
            "https://Example.COM/page?q=%23value",
        )

    def test_rejects_nonstring_empty_and_missing_host(self):
        for url in (None, False, 123, [], {}, b"https://example.com", "", "   ",
                    "example.com", "/page", "https://", "https:///page", "https://?q=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    def test_rejects_non_http_schemes(self):
        for url in ("file:///etc/hosts", "ftp://example.com/file", "javascript:alert(1)",
                    "data:text/html,hello", "mailto:test@example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    def test_rejects_credentials_instead_of_forwarding_them(self):
        for url in ("https://user:password@example.com", "https://user@example.com",
                    "https://:password@example.com", "https://user%40name@example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    def test_rejects_bad_ports_and_broken_ipv6(self):
        for url in ("https://example.com:0", "https://example.com:-1",
                    "https://example.com:65536", "https://example.com:abc",
                    "https://[2001:db8::1/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    def test_rejects_embedded_whitespace_and_backslashes(self):
        for url in ("https://exa mple.com", "https://example.com/a\tb",
                    "https://example.com/a\nb", "https://example.com/a\rb",
                    "https://example.com/\\path", "https://example.com/\u00a0path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    def test_rejects_raw_control_characters(self):
        for character in ("\x00", "\x01", "\x1b", "\x7f"):
            for url in (character + "https://example.com", "https://example.com/a" + character + "b"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.checker.validate_url(url)

    def test_url_length_boundary(self):
        prefix = "https://example.com/"
        url = prefix + "a" * (4096 - len(prefix))
        self.assertEqual(self.checker.validate_url(url), url)
        with self.assertRaises(ValueError):
            self.checker.validate_url(url + "a")

    def test_validation_does_not_resolve_dns_or_connect_to_destination(self):
        with patch("socket.getaddrinfo") as resolve, patch("socket.create_connection") as connect:
            self.assertEqual(self.checker.validate_url("https://example.com/page"),
                             "https://example.com/page")
        resolve.assert_not_called()
        connect.assert_not_called()


    def test_parser_combines_and_deduplicates_reported_threats(self):
        report = {
            "cacheDuration": "300s",
            "threats": [
                {"url": "https://example.com/", "threatTypes": ["SOCIAL_ENGINEERING", "MALWARE"]},
                {"url": "https://example.com/page", "threatTypes": ["MALWARE"]},
            ],
        }
        result, seconds = self.checker.parse_safe_browsing_response(report)
        self.assertEqual(result, {
            "status": "matched", "threat_types": ["MALWARE", "SOCIAL_ENGINEERING"],
        })
        self.assertEqual(seconds, 300.0)

    def test_parser_no_match_accepts_empty_or_omitted_threats(self):
        for report in ({"cacheDuration": "60s", "threats": []}, {"cacheDuration": "60s"}):
            with self.subTest(report=report):
                result, seconds = self.checker.parse_safe_browsing_response(report)
                self.assertEqual(result, {"status": "not_found", "threat_types": []})
                self.assertEqual(seconds, 60.0)

    def test_parser_accepts_zero_and_fractional_cache_duration(self):
        for duration, expected in (("0s", 0.0), ("1.5s", 1.5), ("0.000000001s", 1e-9)):
            with self.subTest(duration=duration):
                _, seconds = self.checker.parse_safe_browsing_response({"cacheDuration": duration})
                self.assertEqual(seconds, expected)

    def test_parser_rejects_nonobject_responses(self):
        for report in (None, [], "{}", False, 123):
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.checker.parse_safe_browsing_response(report)

    def test_parser_rejects_missing_invalid_or_infinite_duration(self):
        durations = (None, 300, True, "", "300", "-1s", "1m", "NaNs", "infs",
                     "1e3s", "1.1234567890s", " 300s", "9" * 400 + "s")
        for duration in durations:
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.checker.parse_safe_browsing_response({"cacheDuration": duration})
        with self.assertRaises(ValueError):
            self.checker.parse_safe_browsing_response({"threats": []})

    def test_parser_rejects_malformed_threats_instead_of_returning_no_match(self):
        valid = {"url": "https://example.com/", "threatTypes": ["MALWARE"]}
        invalid_lists = (None, {}, "MALWARE", False, 123)
        invalid_entries = (None, [], "MALWARE", {},
                           {**valid, "url": None}, {**valid, "url": "   "},
                           {**valid, "threatTypes": None}, {**valid, "threatTypes": []},
                           {**valid, "threatTypes": "MALWARE"},
                           {**valid, "threatTypes": [None]},
                           {**valid, "threatTypes": ["malware"]},
                           {**valid, "threatTypes": ["MALWARE\n"]},
                           {**valid, "threatTypes": ["A" * 101]})
        for threats in (*invalid_lists, *[[entry] for entry in invalid_entries]):
            with self.subTest(threats=threats), self.assertRaises(ValueError):
                self.checker.parse_safe_browsing_response({
                    "cacheDuration": "300s", "threats": threats,
                })

    def test_parser_does_not_return_partial_result_when_an_entry_is_invalid(self):
        report = {
            "cacheDuration": "300s",
            "threats": [
                {"url": "https://example.com/", "threatTypes": ["MALWARE"]},
                {"url": "https://example.org/", "threatTypes": []},
            ],
        }
        with self.assertRaises(ValueError):
            self.checker.parse_safe_browsing_response(report)


    def test_request_returns_matched_report_and_uses_fixed_google_endpoint(self):
        with patch.object(self.checker.requests, "get") as get:
            response = get.return_value.__enter__.return_value
            response.status_code = 200
            response.json.return_value = {
                "cacheDuration": "300s",
                "threats": [{"url": "https://example.com/", "threatTypes": ["MALWARE"]}],
            }

            result, seconds = self.checker._request_safe_browsing(
                " https://example.com/page?q=1#section "
            )

            self.assertEqual(result, {"status": "matched", "threat_types": ["MALWARE"]})
            self.assertEqual(seconds, 300.0)
            get.assert_called_once_with(
                "https://safebrowsing.googleapis.com/v5/urls:search",
                params={"key": "offline-test-key", "urls": "https://example.com/page?q=1"},
                timeout=(5, 10), allow_redirects=False,
            )
            response.json.assert_called_once()
            get.return_value.__exit__.assert_called_once()

    def test_request_returns_no_match_with_cache_duration(self):
        with patch.object(self.checker.requests, "get") as get:
            response = get.return_value.__enter__.return_value
            response.status_code = 200
            response.json.return_value = {"cacheDuration": "60s", "threats": []}
            self.assertEqual(self.checker._request_safe_browsing("https://example.com"), (
                {"status": "not_found", "threat_types": []}, 60.0,
            ))
            get.assert_called_once()

    def test_request_missing_key_does_not_call_api(self):
        for key in (None, ""):
            with self.subTest(key=key):
                with patch.object(self.checker, "SAFE_BROWSING_API_KEY", key), patch.object(self.checker.requests, "get") as get:
                    with self.assertRaises(ValueError):
                        self.checker._request_safe_browsing("https://example.com")
                    get.assert_not_called()

    def test_request_invalid_url_does_not_call_api(self):
        for url in ("file:///etc/hosts", "https://user:secret@example.com", "https://example.com/a\x00b"):
            with self.subTest(url=url), patch.object(self.checker.requests, "get") as get:
                with self.assertRaises(ValueError):
                    self.checker._request_safe_browsing(url)
                get.assert_not_called()

    def test_request_rejects_http_errors_and_redirects_without_parsing_body(self):
        for status in (301, 302, 400, 401, 403, 429, 500, 503):
            with self.subTest(status=status), patch.object(self.checker.requests, "get") as get:
                response = get.return_value.__enter__.return_value
                response.status_code = status
                with self.assertRaises(ValueError) as raised:
                    self.checker._request_safe_browsing("https://example.com")
                self.assertIn(str(status), str(raised.exception))
                self.assertNotIn("offline-test-key", str(raised.exception))
                response.json.assert_not_called()
                get.assert_called_once()
                get.return_value.__exit__.assert_called_once()

    def test_request_propagates_transport_errors_without_retry_or_logging_secrets(self):
        for error_type in (self.checker.requests.Timeout, self.checker.requests.ConnectionError):
            with self.subTest(error=error_type.__name__):
                with patch.object(self.checker.requests, "get", side_effect=error_type("SECRET_REQUEST")) as get, patch("builtins.print") as logs:
                    with self.assertRaises(error_type):
                        self.checker._request_safe_browsing("https://example.com")
                    get.assert_called_once()
                    self.assertNotIn("SECRET_REQUEST", str(logs.call_args_list))

    def test_request_rejects_invalid_json_or_malformed_report(self):
        cases = (ValueError("invalid JSON"), None, [], {},
                 {"cacheDuration": "300s", "threats": None})
        for report in cases:
            with self.subTest(report=report), patch.object(self.checker.requests, "get") as get:
                response = get.return_value.__enter__.return_value
                response.status_code = 200
                if isinstance(report, Exception):
                    response.json.side_effect = report
                else:
                    response.json.return_value = report
                with self.assertRaises(ValueError):
                    self.checker._request_safe_browsing("https://example.com")
                response.json.assert_called_once()
                get.return_value.__exit__.assert_called_once()


    def test_check_caches_matched_and_no_match_by_normalized_url(self):
        reports = (
            {"status": "matched", "threat_types": ["MALWARE"]},
            {"status": "not_found", "threat_types": []},
        )
        for report in reports:
            with self.subTest(status=report["status"]):
                self.checker._url_cache.clear()
                with patch.object(self.checker, "_request_safe_browsing",
                                  return_value=(report, 60.0)) as request:
                    first = self.checker.check_url(" https://example.com/page#one ")
                    second = self.checker.check_url("https://example.com/page#two")
                    self.assertEqual(first, report)
                    self.assertEqual(second, report)
                    request.assert_called_once_with("https://example.com/page")

    def test_check_returns_independent_copies_of_cached_result(self):
        expected = {"status": "matched", "threat_types": ["MALWARE"]}
        report = {"status": "matched", "threat_types": ["MALWARE"]}
        with patch.object(self.checker, "_request_safe_browsing",
                          return_value=(report, 60.0)) as request:
            first = self.checker.check_url("https://example.com")
            first["status"] = "CHANGED"
            first["threat_types"].append("CHANGED")
            second = self.checker.check_url("https://example.com")
            self.assertEqual(second, expected)
            second["threat_types"].clear()
            self.assertEqual(self.checker.check_url("https://example.com"), expected)
            request.assert_called_once()

    def test_check_refreshes_cache_at_exact_expiry(self):
        matched = {"status": "matched", "threat_types": ["MALWARE"]}
        no_match = {"status": "not_found", "threat_types": []}
        for duration in (60.0, 0.5):
            with self.subTest(duration=duration):
                self.checker._url_cache.clear()
                self.now = 100.0
                with patch.object(self.checker, "_request_safe_browsing",
                                  side_effect=[(matched, duration), (no_match, duration)]) as request:
                    self.assertEqual(self.checker.check_url("https://example.com"), matched)
                    self.now = 100.0 + duration / 2
                    self.assertEqual(self.checker.check_url("https://example.com"), matched)
                    self.assertEqual(request.call_count, 1)
                    self.now = 100.0 + duration
                    self.assertEqual(self.checker.check_url("https://example.com"), no_match)
                    self.assertEqual(request.call_count, 2)

    def test_check_does_not_cache_zero_duration(self):
        report = {"status": "not_found", "threat_types": []}
        with patch.object(self.checker, "_request_safe_browsing",
                          return_value=(report, 0.0)) as request:
            self.assertEqual(self.checker.check_url("https://example.com"), report)
            self.assertEqual(self.checker.check_url("https://example.com"), report)
            self.assertEqual(request.call_count, 2)
            self.assertFalse(self.checker._url_cache)

    def test_check_invalid_url_returns_error_without_request(self):
        urls = (None, "file:///secret", "https://user:secret@example.com")
        with patch.object(self.checker, "_request_safe_browsing") as request, patch("builtins.print"):
            for url in urls:
                with self.subTest(url=url):
                    self.assertEqual(self.checker.check_url(url), {
                        "status": "error", "threat_types": [],
                    })
            request.assert_not_called()
            self.assertFalse(self.checker._url_cache)

    def test_check_failures_return_error_without_cache_or_secret_logs(self):
        errors = (
            ValueError("SECRET_REPORT"),
            self.checker.requests.Timeout("SECRET_KEY"),
            self.checker.requests.ConnectionError("SECRET_URL"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with patch.object(self.checker, "_request_safe_browsing",
                                  side_effect=error) as request, patch("builtins.print") as logs:
                    for _ in range(2):
                        self.assertEqual(self.checker.check_url("https://example.com"), {
                            "status": "error", "threat_types": [],
                        })
                    self.assertEqual(request.call_count, 2)
                    self.assertFalse(self.checker._url_cache)
                    self.assertNotIn("SECRET", str(logs.call_args_list))

    def test_check_missing_key_returns_error_without_http(self):
        with patch.object(self.checker, "SAFE_BROWSING_API_KEY", ""), patch("builtins.print"):
            self.assertEqual(self.checker.check_url("https://example.com"), {
                "status": "error", "threat_types": [],
            })
            self.checker.requests.get.assert_not_called()
            self.assertFalse(self.checker._url_cache)

    def test_check_removes_expired_entries_and_retains_live_results(self):
        report = {"status": "not_found", "threat_types": []}
        with patch.object(self.checker, "_request_safe_browsing",
                          side_effect=[(report, 5.0), (report, 60.0), (report, 60.0)]) as request:
            self.checker.check_url("https://expired.example")
            self.checker.check_url("https://live.example")
            self.now = 105.0
            self.checker.check_url("https://new.example")
            self.assertNotIn("https://expired.example", self.checker._url_cache)
            self.assertEqual(self.checker.check_url("https://live.example"), report)
            self.assertEqual(request.call_count, 3)

    def test_check_evicts_oldest_entry_at_cache_capacity(self):
        report = {"status": "not_found", "threat_types": []}
        with patch.object(self.checker, "_URL_CACHE_MAX_ENTRIES", 2):
            with patch.object(self.checker, "_request_safe_browsing",
                              return_value=(report, 60.0)) as request:
                for host in ("one", "two", "three"):
                    self.checker.check_url(f"https://{host}.example")
                self.assertEqual(len(self.checker._url_cache), 2)
                self.assertEqual(self.checker.check_url("https://two.example"), report)
                self.assertEqual(request.call_count, 3)
                self.assertEqual(self.checker.check_url("https://one.example"), report)
                self.assertEqual(request.call_count, 4)
                self.assertEqual(len(self.checker._url_cache), 2)

    def test_check_releases_cache_lock_before_request(self):
        report = {"status": "not_found", "threat_types": []}

        def request(url):
            self.assertFalse(self.checker._url_cache_lock.locked())
            return report, 60.0

        with patch.object(self.checker, "_request_safe_browsing", side_effect=request):
            self.assertEqual(self.checker.check_url("https://example.com"), report)

    def test_check_expired_result_is_not_reused_when_request_fails(self):
        matched = {"status": "matched", "threat_types": ["MALWARE"]}
        no_match = {"status": "not_found", "threat_types": []}
        responses = [(matched, 5.0), self.checker.requests.Timeout("SECRET_URL"), (no_match, 60.0)]
        with patch.object(self.checker, "_request_safe_browsing",
                          side_effect=responses) as request, patch("builtins.print") as logs:
            self.assertEqual(self.checker.check_url("https://example.com"), matched)
            self.now = 105.0
            self.assertEqual(self.checker.check_url("https://example.com"), {
                "status": "error", "threat_types": [],
            })
            self.assertEqual(self.checker.check_url("https://example.com"), no_match)
            self.assertEqual(request.call_count, 3)
            self.assertNotIn("SECRET", str(logs.call_args_list))


if __name__ == "__main__":
    unittest.main()
