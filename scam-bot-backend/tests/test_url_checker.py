"""ทดสอบการดึงและตรวจ URL และ cache ในเครื่อง ไม่อ่านคีย์หรือเรียกบริการภายนอก."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


class URLValidationTests(unittest.TestCase):
    # setUpClass: โหลด url_checker ด้วย config จำลองพร้อม decoder สำหรับใช้ร่วมกันทั้งชุดทดสอบ
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "url_checker.py"
        spec = importlib.util.spec_from_file_location("url_checker_under_test", path)
        cls.checker = importlib.util.module_from_spec(spec)
        config = ModuleType("config")
        config.SAFE_BROWSING_API_KEY = "offline-test-key"
        with patch.dict(sys.modules, {"config": config}), patch.object(
            sys, "path", [str(path.parent), *sys.path],
        ):
            cls.protocol = importlib.import_module("safe_browsing_proto")
            spec.loader.exec_module(cls.checker)

    # setUp: ล้าง cache และจำลองนาฬิกากับเครือข่ายก่อนแต่ละกรณีตรวจลิงก์
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

    # test_extract_returns_empty_list_without_http_urls: ทดสอบข้อความที่ไม่มี HTTP/HTTPS คืนรายการลิงก์ว่าง
    def test_extract_returns_empty_list_without_http_urls(self):
        self.assertEqual(
            self.checker.extract_urls("ข้อความทั่วไป www.example.com ftp://example.com"),
            [],
        )

    # test_extract_preserves_protocol_case_path_query_and_fragment: ทดสอบดึงลิงก์โดยคงตัวพิมพ์ path query และ fragment ตามข้อความเดิม
    def test_extract_preserves_protocol_case_path_query_and_fragment(self):
        self.assertEqual(
            self.checker.extract_urls(
                "ดู http://example.com/Page และ HTTPS://Example.org/Path?q=Ab#Section"
            ),
            ["http://example.com/Page", "HTTPS://Example.org/Path?q=Ab#Section"],
        )

    # test_extract_deduplicates_urls_preserving_order: ทดสอบตัดลิงก์ซ้ำโดยรักษาลำดับแรกที่พบ
    def test_extract_deduplicates_urls_preserving_order(self):
        self.assertEqual(
            self.checker.extract_urls(
                "https://example.org/b https://example.com/a https://example.org/b"
            ),
            ["https://example.org/b", "https://example.com/a"],
        )

    # test_extract_stops_at_whitespace_angle_brackets_and_quotes: ทดสอบจบ URL เมื่อพบช่องว่าง วงเล็บแหลม หรือเครื่องหมายคำพูด
    def test_extract_stops_at_whitespace_angle_brackets_and_quotes(self):
        self.assertEqual(
            self.checker.extract_urls(
                'ลิงก์ <https://example.com/a> "http://example.org/b"\n'
                '“https://example.net/c”\thttps://example.edu/d จบ'
            ),
            [
                "https://example.com/a", "http://example.org/b",
                "https://example.net/c", "https://example.edu/d",
            ],
        )

    # test_extract_rejects_nonstring_input: ทดสอบ extract_urls ปฏิเสธ input ที่ไม่ใช่ข้อความ
    def test_extract_rejects_nonstring_input(self):
        for value in (None, False, 123, [], {}, b"https://example.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.checker.extract_urls(value)

    # test_http_https_paths_queries_and_ports: ทดสอบ validate_url รับ HTTP/HTTPS พร้อม path query และ port ที่ถูกต้อง
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

    # test_trims_outer_spaces_and_removes_only_fragment: ทดสอบตัดช่องว่างรอบ URL และ fragment โดยยังเก็บ query ไว้
    def test_trims_outer_spaces_and_removes_only_fragment(self):
        self.assertEqual(
            self.checker.validate_url("  HTTPS://Example.COM/page?q=%23value#section  "),
            "https://Example.COM/page?q=%23value",
        )

    # test_rejects_nonstring_empty_and_missing_host: ทดสอบปฏิเสธ URL ที่ไม่ใช่ข้อความ ว่าง หรือไม่มี host
    def test_rejects_nonstring_empty_and_missing_host(self):
        for url in (None, False, 123, [], {}, b"https://example.com", "", "   ",
                    "example.com", "/page", "https://", "https:///page", "https://?q=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    # test_rejects_non_http_schemes: ทดสอบไม่รับ URL ที่ใช้ protocol นอก HTTP/HTTPS
    def test_rejects_non_http_schemes(self):
        for url in ("file:///etc/hosts", "ftp://example.com/file", "javascript:alert(1)",
                    "data:text/html,hello", "mailto:test@example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    # test_rejects_credentials_instead_of_forwarding_them: ทดสอบ URL ที่ฝังชื่อผู้ใช้หรือรหัสผ่านถูกปฏิเสธก่อนส่งต่อ
    def test_rejects_credentials_instead_of_forwarding_them(self):
        for url in ("https://user:password@example.com", "https://user@example.com",
                    "https://:password@example.com", "https://user%40name@example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    # test_rejects_bad_ports_and_broken_ipv6: ทดสอบปฏิเสธ port ที่ผิดและรูปแบบ IPv6 ที่ไม่สมบูรณ์
    def test_rejects_bad_ports_and_broken_ipv6(self):
        for url in ("https://example.com:0", "https://example.com:-1",
                    "https://example.com:65536", "https://example.com:abc",
                    "https://[2001:db8::1/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    # test_rejects_embedded_whitespace_and_backslashes: ทดสอบไม่รับ URL ที่มีช่องว่างภายในหรือ backslash
    def test_rejects_embedded_whitespace_and_backslashes(self):
        for url in ("https://exa mple.com", "https://example.com/a\tb",
                    "https://example.com/a\nb", "https://example.com/a\rb",
                    "https://example.com/\\path", "https://example.com/\u00a0path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.checker.validate_url(url)

    # test_rejects_raw_control_characters: ทดสอบปฏิเสธอักขระควบคุมดิบใน URL
    def test_rejects_raw_control_characters(self):
        for character in ("\x00", "\x01", "\x1b", "\x7f"):
            for url in (character + "https://example.com", "https://example.com/a" + character + "b"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.checker.validate_url(url)

    # test_url_length_boundary: ทดสอบขอบเขตความยาว URL ที่ยอมรับและเมื่อเกิน
    def test_url_length_boundary(self):
        prefix = "https://example.com/"
        url = prefix + "a" * (4096 - len(prefix))
        self.assertEqual(self.checker.validate_url(url), url)
        with self.assertRaises(ValueError):
            self.checker.validate_url(url + "a")

    # test_validation_does_not_resolve_dns_or_connect_to_destination: ทดสอบ validate_url ตรวจรูปแบบอย่างเดียว ไม่ค้น DNS หรือเชื่อมต่อเว็บปลายทาง
    def test_validation_does_not_resolve_dns_or_connect_to_destination(self):
        with patch("socket.getaddrinfo") as resolve, patch("socket.create_connection") as connect:
            self.assertEqual(self.checker.validate_url("https://example.com/page"),
                             "https://example.com/page")
        resolve.assert_not_called()
        connect.assert_not_called()


    # test_parser_combines_and_deduplicates_reported_threats: ทดสอบรวมประเภทภัยคุกคามจากรายงานและตัดค่าซ้ำ
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

    # test_parser_no_match_accepts_empty_or_omitted_threats: ทดสอบ threats ว่างหรือไม่ระบุแปลเป็น not_found เมื่อข้อมูลอื่นถูกต้อง
    def test_parser_no_match_accepts_empty_or_omitted_threats(self):
        for report in ({"cacheDuration": "60s", "threats": []}, {"cacheDuration": "60s"}):
            with self.subTest(report=report):
                result, seconds = self.checker.parse_safe_browsing_response(report)
                self.assertEqual(result, {"status": "not_found", "threat_types": []})
                self.assertEqual(seconds, 60.0)

    # test_parser_accepts_zero_and_fractional_cache_duration: ทดสอบอ่านอายุ cache ที่เป็นศูนย์และเศษวินาทีได้
    def test_parser_accepts_zero_and_fractional_cache_duration(self):
        for duration, expected in (("0s", 0.0), ("1.5s", 1.5), ("0.000000001s", 1e-9)):
            with self.subTest(duration=duration):
                _, seconds = self.checker.parse_safe_browsing_response({"cacheDuration": duration})
                self.assertEqual(seconds, expected)

    # test_parser_rejects_nonobject_responses: ทดสอบ parser ปฏิเสธ response ที่ไม่ใช่ object
    def test_parser_rejects_nonobject_responses(self):
        for report in (None, [], "{}", False, 123):
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.checker.parse_safe_browsing_response(report)

    # test_parser_rejects_missing_invalid_or_infinite_duration: ทดสอบไม่รับอายุ cache ที่หาย ผิดรูปแบบ หรือไม่เป็นจำนวนจำกัด
    def test_parser_rejects_missing_invalid_or_infinite_duration(self):
        durations = (None, 300, True, "", "300", "-1s", "1m", "NaNs", "infs",
                     "1e3s", "1.1234567890s", " 300s", "9" * 400 + "s")
        for duration in durations:
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.checker.parse_safe_browsing_response({"cacheDuration": duration})
        with self.assertRaises(ValueError):
            self.checker.parse_safe_browsing_response({"threats": []})

    # test_parser_rejects_malformed_threats_instead_of_returning_no_match: ทดสอบ threats ผิดรูปแบบต้องแจ้ง error ไม่แปลงเป็นไม่พบภัย
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

    # test_parser_does_not_return_partial_result_when_an_entry_is_invalid: ทดสอบรายการภัยผิดเพียงส่วนเดียวทำให้ปฏิเสธทั้งผล ไม่ใช้ผลที่อ่านได้บางส่วน
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


    # test_request_returns_matched_report_and_uses_fixed_google_endpoint: ทดสอบคำขอ Safe Browsing ใช้ endpoint Google ที่กำหนดและคืนรายงาน matched
    def test_request_returns_matched_report_and_uses_fixed_google_endpoint(self):
        with patch.object(self.checker.requests, "get") as get:
            response = get.return_value.__enter__.return_value
            response.status_code = 200
            message = self.protocol.SearchUrlsResponse()
            message.cache_duration.seconds = 300
            message.threats.add(url="https://example.com/", threat_types=[1])
            response.content = message.SerializeToString()
            response.json.side_effect = AssertionError("Successful V5 replies are Protobuf")

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
            response.json.assert_not_called()
            get.return_value.__exit__.assert_called_once()

    # test_request_returns_no_match_with_cache_duration: ทดสอบคำขอ Safe Browsing คืน not_found พร้อมอายุ cache
    def test_request_returns_no_match_with_cache_duration(self):
        with patch.object(self.checker.requests, "get") as get:
            response = get.return_value.__enter__.return_value
            response.status_code = 200
            # ไบนารีอิสระ: field 2 เป็น Duration ซึ่งมี seconds = 60
            response.content = b"\x12\x02\x08\x3c"
            self.assertEqual(self.checker._request_safe_browsing("https://example.com"), (
                {"status": "not_found", "threat_types": []}, 60.0,
            ))
            get.assert_called_once()

    # test_request_missing_key_does_not_call_api: ทดสอบไม่ตั้ง API key แล้วหยุดก่อนเรียก Safe Browsing
    def test_request_missing_key_does_not_call_api(self):
        for key in (None, ""):
            with self.subTest(key=key):
                with patch.object(self.checker, "SAFE_BROWSING_API_KEY", key), patch.object(self.checker.requests, "get") as get:
                    with self.assertRaises(ValueError):
                        self.checker._request_safe_browsing("https://example.com")
                    get.assert_not_called()

    # test_request_invalid_url_does_not_call_api: ทดสอบ URL ผิดรูปแบบไม่ถูกส่งไป Safe Browsing
    def test_request_invalid_url_does_not_call_api(self):
        for url in ("file:///etc/hosts", "https://user:secret@example.com", "https://example.com/a\x00b"):
            with self.subTest(url=url), patch.object(self.checker.requests, "get") as get:
                with self.assertRaises(ValueError):
                    self.checker._request_safe_browsing(url)
                get.assert_not_called()

    # test_request_rejects_http_errors_and_redirects_without_parsing_body: ทดสอบ HTTP error หรือ redirect ถูกปฏิเสธก่อนอ่านรายงาน และไม่เผย key
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

    # test_request_propagates_transport_errors_without_retry_or_logging_secrets: ทดสอบ error เครือข่ายถูกส่งต่อโดยไม่ retry หรือ log ข้อความลับ
    def test_request_propagates_transport_errors_without_retry_or_logging_secrets(self):
        for error_type in (self.checker.requests.Timeout, self.checker.requests.ConnectionError):
            with self.subTest(error=error_type.__name__):
                with patch.object(self.checker.requests, "get", side_effect=error_type("SECRET_REQUEST")) as get, patch("builtins.print") as logs:
                    with self.assertRaises(error_type):
                        self.checker._request_safe_browsing("https://example.com")
                    get.assert_called_once()
                    self.assertNotIn("SECRET_REQUEST", str(logs.call_args_list))

    # test_request_rejects_invalid_protobuf_or_malformed_report: ทดสอบ protobuf หรือรายงานเสียถูกปฏิเสธและปิด response หลังใช้งาน
    def test_request_rejects_invalid_protobuf_or_malformed_report(self):
        missing_url = self.protocol.SearchUrlsResponse()
        missing_url.cache_duration.seconds = 60
        missing_url.threats.add(threat_types=[1])
        missing_types = self.protocol.SearchUrlsResponse()
        missing_types.cache_duration.seconds = 60
        missing_types.threats.add(url="https://example.com/")
        invalid_duration = self.protocol.SearchUrlsResponse()
        invalid_duration.cache_duration.seconds = -1
        invalid_nanos = self.protocol.SearchUrlsResponse()
        invalid_nanos.cache_duration.nanos = 1_000_000_000
        cases = (
            b"\x80", b"\x12\x02\x08", b"", b"<html>SECRET_RESPONSE</html>",
            b'{"cacheDuration":"60s"}', missing_url.SerializeToString(),
            missing_types.SerializeToString(), invalid_duration.SerializeToString(),
            invalid_nanos.SerializeToString(),
        )
        for data in cases:
            with self.subTest(data=data), patch.object(self.checker.requests, "get") as get:
                response = get.return_value.__enter__.return_value
                response.status_code = 200
                response.content = data
                with self.assertRaises(ValueError):
                    self.checker._request_safe_browsing("https://example.com")
                response.json.assert_not_called()
                get.return_value.__exit__.assert_called_once()

    # test_decoder_maps_all_public_v5_threat_types: ทดสอบแปลงประเภทภัยคุกคามสาธารณะของ Safe Browsing v5 ครบตามค่าจำลอง
    def test_decoder_maps_all_public_v5_threat_types(self):
        message = self.protocol.SearchUrlsResponse()
        message.cache_duration.seconds = 1
        message.cache_duration.nanos = 500_000_000
        message.threats.add(url="https://example.com/", threat_types=[1, 2, 3, 4])
        self.assertEqual(self.protocol.decode_safe_browsing_response(message.SerializeToString()), {
            "cacheDuration": "1.500s",
            "threats": [{
                "url": "https://example.com/",
                "threatTypes": [
                    "MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                    "POTENTIALLY_HARMFUL_APPLICATION",
                ],
            }],
        })

    # test_decoder_rejects_nonbytes_instead_of_treating_them_as_no_match: ทดสอบ decoder ไม่รับข้อมูลที่ไม่ใช่ bytes และไม่ตีความเป็นไม่พบภัย
    def test_decoder_rejects_nonbytes_instead_of_treating_them_as_no_match(self):
        for data in (None, False, 123, [], {}, "", bytearray()):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.protocol.decode_safe_browsing_response(data)

    # test_decoder_ignores_unknown_wire_fields_and_keeps_cache_duration: ทดสอบข้าม protobuf field ที่ไม่รู้จักโดยยังอ่านอายุ cache ได้
    def test_decoder_ignores_unknown_wire_fields_and_keeps_cache_duration(self):
        self.assertEqual(
            self.protocol.decode_safe_browsing_response(b"\x12\x02\x08\x3c\x98\x06\x01"),
            {"cacheDuration": "60s"},
        )

    # test_unknown_or_unspecified_wire_threat_type_is_error_and_not_cached: ทดสอบประเภทภัยที่ไม่รู้จักหรือไม่ได้ระบุเป็น error และไม่ถูก cache
    def test_unknown_or_unspecified_wire_threat_type_is_error_and_not_cached(self):
        for threat_type in (0, 99):
            with self.subTest(threat_type=threat_type), patch.object(self.checker.requests, "get") as get:
                message = self.protocol.SearchUrlsResponse()
                message.cache_duration.seconds = 60
                message.threats.add(url="https://example.com/", threat_types=[threat_type])
                response = get.return_value.__enter__.return_value
                response.status_code = 200
                response.content = message.SerializeToString()
                with patch("builtins.print") as logs:
                    for _ in range(2):
                        self.assertEqual(self.checker.check_url("https://example.com/"), {
                            "status": "error", "threat_types": [],
                        })
                self.assertEqual(get.call_count, 2)
                self.assertEqual(self.checker._url_cache, {})
                self.assertNotIn("offline-test-key", str(logs.call_args_list))


    # test_check_caches_matched_and_no_match_by_normalized_url: ทดสอบเก็บทั้ง matched/not_found ใน cache ด้วย URL ที่ปรับรูปแบบแล้ว
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

    # test_check_returns_independent_copies_of_cached_result: ทดสอบคืนสำเนาผล cache เพื่อไม่ให้ผู้เรียกแก้ข้อมูลที่เก็บไว้
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

    # test_check_refreshes_cache_at_exact_expiry: ทดสอบเมื่อถึงเวลาหมดอายุพอดีต้องเรียกตรวจใหม่
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

    # test_check_does_not_cache_zero_duration: ทดสอบผลที่มีอายุ cache ศูนย์ไม่ถูกใช้ซ้ำ
    def test_check_does_not_cache_zero_duration(self):
        report = {"status": "not_found", "threat_types": []}
        with patch.object(self.checker, "_request_safe_browsing",
                          return_value=(report, 0.0)) as request:
            self.assertEqual(self.checker.check_url("https://example.com"), report)
            self.assertEqual(self.checker.check_url("https://example.com"), report)
            self.assertEqual(request.call_count, 2)
            self.assertFalse(self.checker._url_cache)

    # test_check_invalid_url_returns_error_without_request: ทดสอบ check_url รับ URL เสียแล้วคืน error โดยไม่ส่งคำขอหรือเก็บ cache
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

    # test_check_failures_return_error_without_cache_or_secret_logs: ทดสอบตรวจลิงก์ล้มเหลวคืน error โดยไม่ cache และไม่เผยรายละเอียดลับ
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

    # test_check_missing_key_returns_error_without_http: ทดสอบ check_url ไม่มี key คืน error โดยไม่ส่ง HTTP
    def test_check_missing_key_returns_error_without_http(self):
        with patch.object(self.checker, "SAFE_BROWSING_API_KEY", ""), patch("builtins.print"):
            self.assertEqual(self.checker.check_url("https://example.com"), {
                "status": "error", "threat_types": [],
            })
            self.checker.requests.get.assert_not_called()
            self.assertFalse(self.checker._url_cache)

    # test_check_removes_expired_entries_and_retains_live_results: ทดสอบล้าง cache ที่หมดอายุโดยยังเก็บผลที่ใช้ได้
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

    # test_check_evicts_oldest_entry_at_cache_capacity: ทดสอบ cache เต็มแล้วนำรายการเก่าสุดออกเพื่อรับรายการใหม่
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

    # test_check_releases_cache_lock_before_request: ทดสอบปล่อย lock ของ cache ก่อนเรียกเครือข่ายเพื่อไม่ล็อกงานอื่นระหว่างรอ
    def test_check_releases_cache_lock_before_request(self):
        report = {"status": "not_found", "threat_types": []}

        # request: จำลองคำขอ Safe Browsing โดยยืนยันว่าไม่ได้ถือ lock ของ cache ระหว่างเรียก
        def request(url):
            self.assertFalse(self.checker._url_cache_lock.locked())
            return report, 60.0

        with patch.object(self.checker, "_request_safe_browsing", side_effect=request):
            self.assertEqual(self.checker.check_url("https://example.com"), report)

    # test_check_expired_result_is_not_reused_when_request_fails: ทดสอบตรวจใหม่ล้มเหลวไม่ย้อนใช้ผล cache ที่หมดอายุ
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
