"""Offline member counts: real webhook parser with mocked LINE and database."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import requests

from test_detection_history import load_history
from test_group_join import join_event
import test_webhook_threadpool as fixtures


class MemberHistoryTests(unittest.TestCase):
    def test_valid_counts_use_existing_history_client(self):
        for count in (0, 12):
            with self.subTest(count=count):
                history = load_history()
                history._client = Mock()
                history.get_group_member_count.return_value = count
                event = SimpleNamespace(source=SimpleNamespace(type="group", group_id="group-1"))
                self.assertTrue(history.save_group_members(event))
                row = history._client.table.return_value.upsert.call_args.args[0]
                self.assertEqual(row["member_count"], count)
                self.assertNotIn("is_active", row)
                self.assertNotIn("bot_joined_at", row)

    def test_api_failure_preserves_previous_count(self):
        history = load_history()
        history._client = Mock()
        event = SimpleNamespace(source=SimpleNamespace(type="group", group_id="group-1"))
        self.assertFalse(history.save_group_members(event))
        history._client.table.assert_not_called()

    def test_join_saves_count_after_registering_group(self):
        history = load_history()
        history._client = Mock()
        history.get_group_member_count.return_value = 7
        event = SimpleNamespace(source=SimpleNamespace(type="group", group_id="group-1"), timestamp=0)
        self.assertTrue(history.save_group_join(event))
        writes = history._client.table.return_value.upsert.call_args_list
        self.assertEqual(len(writes), 2)
        self.assertTrue(writes[0].args[0]["is_active"])
        self.assertEqual(writes[1].args[0]["member_count"], 7)

    def test_database_failure_returns_false_without_secret(self):
        history = load_history()
        history.get_group_member_count.return_value = 7
        history._client = Mock()
        history._client.table.side_effect = RuntimeError("SECRET")
        event = SimpleNamespace(source=SimpleNamespace(type="group", group_id="group-1"))
        with patch.object(history, "log") as output:
            self.assertFalse(history.save_group_members(event))
        self.assertNotIn("SECRET", str(output.call_args_list))


class MemberApiTests(unittest.TestCase):
    def test_count_validation_and_timeout(self):
        # ใช้ fixture โหลด messaging โดยไม่อ่าน secret จริง
        import importlib.util
        from pathlib import Path
        import sys
        from types import ModuleType
        config = ModuleType("config")
        config.LINE_CHANNEL_ACCESS_TOKEN = "SECRET"
        path = Path(__file__).resolve().parents[1] / "messaging.py"
        spec = importlib.util.spec_from_file_location("member_messaging_test", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"config": config}):
            spec.loader.exec_module(module)
        for payload, expected in (({"count": 12}, 12), ({"count": 0}, 0),
                                  ({"count": True}, None), ({"count": -1}, None),
                                  ({"count": "12"}, None), ({}, None), ([], None)):
            with self.subTest(payload=payload), patch.object(module.requests, "get") as get:
                get.return_value.json.return_value = payload
                self.assertEqual(module.get_group_member_count("group/1"), expected)
                self.assertEqual(get.call_args.args[0], "https://api.line.me/v2/bot/group/group%2F1/members/count")
                self.assertEqual(get.call_args.kwargs["timeout"], 10)
        with patch.object(module.requests, "get", side_effect=requests.Timeout("SECRET")), patch("builtins.print") as output:
            self.assertIsNone(module.get_group_member_count("group"))
        self.assertNotIn("SECRET", str(output.call_args_list))


class MemberWebhookTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.WebhookThreadpoolTests.asyncSetUp
    asyncTearDown = fixtures.WebhookThreadpoolTests.asyncTearDown
    post_events = fixtures.WebhookThreadpoolTests.post_events

    def event(self, kind):
        event = join_event()
        event["type"] = kind
        event["webhookEventId"] = kind
        key = "joined" if kind == "memberJoined" else "left"
        event[key] = {"members": [{"type": "user", "userId": "offline-user"}]}
        return event

    async def test_member_changes_run_once_in_worker_without_detection(self):
        workers = []
        loop_thread = threading.get_ident()
        self.module.save_group_members.side_effect = lambda event: workers.append(threading.get_ident()) or True
        events = [self.event("memberJoined"), self.event("memberLeft")]
        self.assertEqual((await self.post_events(events + events)).status_code, 200)
        self.assertEqual(len(workers), 2)
        self.assertNotIn(loop_thread, workers)
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_failure_keeps_webhook_alive(self):
        self.module.save_group_members.return_value = False
        self.assertEqual((await self.post_events([self.event("memberLeft")])).status_code, 200)

    async def test_invalid_member_event_rejects_entire_batch(self):
        invalid = self.event("memberLeft")
        invalid["source"] = {"type": "group"}
        self.assertEqual((await self.post_events([self.event("memberJoined"), invalid])).status_code, 400)
        self.module.save_group_members.assert_not_called()

    async def test_room_members_are_not_saved_as_groups(self):
        event = self.event("memberJoined")
        event["source"] = {"type": "room", "roomId": "offline-room"}
        self.assertEqual((await self.post_events([event])).status_code, 200)
        self.module.save_group_members.assert_not_called()
