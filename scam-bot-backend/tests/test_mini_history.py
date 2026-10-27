"""ทดสอบอ่าน/ลบประวัติ Mini App ด้วย Supabase จำลอง ไม่แตะฐานข้อมูลจริง."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini_history  # noqa: E402

DASHED = "0f8f2b7c-1d2e-4f30-9a1b-2c3d4e5f6a7b"
HEX = DASHED.replace("-", "")


def fake_client(rows):
    """client จำลองที่ทุกเมธอดคืนตัวเอง และ execute() คืน rows ที่กำหนด."""
    query = MagicMock()
    for name in ("table", "select", "eq", "in_", "order", "limit", "delete"):
        getattr(query, name).return_value = query
    query.execute.return_value = MagicMock(data=rows)
    return query


def row(**overrides):
    base = {"id": DASHED, "message_text": "ส่ง OTP มา  ด่วน", "detection_status": "risk_found",
            "reason": "ขอ OTP", "received_at": "2026-10-23T08:00:00+00:00"}
    base.update(overrides)
    return base


class MiniHistoryTests(unittest.TestCase):
    def use(self, client):
        return patch.object(mini_history, "get_client", return_value=client)

    def test_list_filters_owner_private_three_statuses_newest_first_limit_50(self):
        client = fake_client([row()])
        with self.use(client):
            mini_history.list_cases("U1")
        client.table.assert_called_with("detection_logs")
        client.eq.assert_any_call("sender_user_id", "U1")
        client.eq.assert_any_call("source_type", "user")
        client.in_.assert_called_with("detection_status", ["risk_found", "uncertain", "no_risk_found"])
        client.order.assert_called_with("received_at", desc=True)
        client.limit.assert_called_with(50)

    def test_list_converts_dashed_uuid_to_hex_and_shortens_title(self):
        long_text = "ก  " * 80
        with self.use(fake_client([row(message_text=long_text)])):
            items = mini_history.list_cases("U1")
        self.assertEqual(items, [{
            "id": HEX, "title": " ".join(long_text.split())[:60], "category": "message",
            "receivedAt": "2026-10-23T08:00:00+00:00", "status": "risk_found",
        }])
        self.assertNotIn("message", items[0])

    def test_list_category_is_link_when_message_has_url(self):
        rows = [row(message_text="กดรับเงินที่ https://bit.ly/abc"),
                row(message_text="เข้า WWW.example.com ด่วน"),
                row(message_text="โอนค่ามัดจำมาก่อนนะ")]
        with self.use(fake_client(rows)):
            items = mini_history.list_cases("U1")
        self.assertEqual([item["category"] for item in items], ["link", "link", "message"])

    def test_get_case_category_is_link_when_message_has_url(self):
        with self.use(fake_client([row(message_text="ยืนยันบัญชีที่ http://fake-bank.co")])):
            detail = mini_history.get_case(HEX, "U1")
        self.assertEqual(detail["category"], "link")

    def test_list_empty_history_returns_empty_list(self):
        with self.use(fake_client([])):
            self.assertEqual(mini_history.list_cases("U1"), [])

    def test_get_case_rebuilds_detail_and_falls_back_for_null_reason(self):
        client = fake_client([row(reason=None, message_text="[รูปภาพ]", detection_status="uncertain")])
        with self.use(client):
            detail = mini_history.get_case(HEX, "U1")
        client.eq.assert_any_call("id", DASHED)
        client.eq.assert_any_call("sender_user_id", "U1")
        self.assertEqual(detail["id"], HEX)
        self.assertEqual(detail["status"], "uncertain")
        self.assertEqual(detail["reason"], "ไม่มีเหตุผลเพิ่มเติมจากผลตรวจ")
        self.assertEqual(detail["message"], "[รูปภาพ]")
        self.assertTrue(detail["nextSteps"])
        self.assertTrue(detail["warningPoints"])

    def test_get_case_bad_hex_returns_none_without_query(self):
        client = fake_client([row()])
        with self.use(client):
            for bad in ("xyz", "a" * 31, DASHED, "g" * 32, ""):
                self.assertIsNone(mini_history.get_case(bad, "U1"))
        client.execute.assert_not_called()

    def test_get_case_other_owner_returns_none(self):
        with self.use(fake_client([])):
            self.assertIsNone(mini_history.get_case(HEX, "someone-else"))

    def test_delete_all_targets_owner_private_rows_only(self):
        # ลบทุกสถานะ แต่นับเฉพาะที่ผู้ใช้เห็นในหน้าประวัติ (คำทักทาย/error ไม่นับ)
        client = fake_client([row(), row(detection_status="uncertain"), row(detection_status="conversation"),
                              row(detection_status="error")])
        with self.use(client):
            self.assertEqual(mini_history.delete_all("U1"), 2)
        client.delete.assert_called_once()
        client.eq.assert_any_call("sender_user_id", "U1")
        client.eq.assert_any_call("source_type", "user")
        client.in_.assert_not_called()

    def test_supabase_error_becomes_history_unavailable_without_message(self):
        client = fake_client([])
        client.execute.side_effect = RuntimeError("SECRET")
        with self.use(client):
            for call in (lambda: mini_history.list_cases("U1"),
                         lambda: mini_history.get_case(HEX, "U1"),
                         lambda: mini_history.delete_all("U1")):
                with self.assertRaises(mini_history.HistoryUnavailable) as caught:
                    call()
                self.assertNotIn("SECRET", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
