"""Offline join checks: real webhook parser, mocked LINE and database."""
import importlib.util
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import requests
from test_detection_history import load_history
import test_webhook_threadpool as webhook_tests


def join_event():
    return {
        'type': 'join', 'timestamp': 1700000000000, 'mode': 'active',
        'webhookEventId': 'join-1', 'replyToken': 'unused',
        'deliveryContext': {'isRedelivery': False},
        'source': {'type': 'group', 'groupId': 'private-group-id'},
    }


class JoinWebhookTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = webhook_tests.WebhookThreadpoolTests.asyncSetUp
    asyncTearDown = webhook_tests.WebhookThreadpoolTests.asyncTearDown
    post_events = webhook_tests.WebhookThreadpoolTests.post_events

    async def test_join_runs_in_worker_without_analysis_or_reply(self):
        loop_thread = threading.get_ident()
        workers = []
        self.module.save_group_join.side_effect = lambda event: workers.append(threading.get_ident()) or True
        self.assertEqual((await self.post_events([join_event()])).status_code, 200)
        self.assertNotEqual(workers, [loop_thread])
        self.module.save_group_join.assert_called_once()
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()
        self.module.save_detection.assert_not_called()

    async def test_duplicate_join_is_skipped(self):
        await self.post_events([join_event()])
        await self.post_events([join_event()])
        self.module.save_group_join.assert_called_once()

    async def test_save_failure_keeps_webhook_alive(self):
        self.module.save_group_join.return_value = False
        self.assertEqual((await self.post_events([join_event()])).status_code, 200)

    async def test_bad_signature_and_invalid_join_do_not_write(self):
        self.assertEqual((await self.post_events([join_event()], False)).status_code, 400)
        for field, value in [('source', {}), ('source', {'type': 'group'}), ('timestamp', -1), ('timestamp', True), ('timestamp', 'now'), ('webhookEventId', '')]:
            with self.subTest(field=field, value=value):
                invalid = join_event()
                invalid[field] = value
                self.assertEqual((await self.post_events([join_event(), invalid])).status_code, 400)
        self.module.save_group_join.assert_not_called()

    async def test_room_join_is_not_registered_as_group(self):
        event = join_event()
        event['source'] = {'type': 'room', 'roomId': 'room-1'}
        self.assertEqual((await self.post_events([event])).status_code, 200)
        self.module.save_group_join.assert_not_called()


class JoinHistoryTests(unittest.TestCase):
    def test_save_before_lookup_and_preserve_name_on_lookup_failure(self):
        for name in ('Test group', None):
            with self.subTest(name=name):
                history = load_history()
                db = Mock()
                history._client = db
                event = SimpleNamespace(source=SimpleNamespace(type='group', group_id='group-1'), timestamp=1700000000000)
                def lookup(group_id):
                    db.table.return_value.upsert.return_value.execute.assert_called_once()
                    return name
                history.get_group_name.side_effect = lookup
                with patch('builtins.print'):
                    self.assertTrue(history.save_group_join(event))
                row = db.table.return_value.upsert.call_args.args[0]
                self.assertEqual(row['bot_joined_at'], '2023-11-14T22:13:20+00:00')
                self.assertNotIn('display_name', row)
                self.assertTrue(row['is_active'])
                self.assertTrue(all(call.args == ('line_sources',) for call in db.table.call_args_list))
                if name:
                    db.table.return_value.update.assert_called_once_with({'display_name': name})
                else:
                    db.table.return_value.update.assert_not_called()

    def test_database_error_returns_false_without_secret(self):
        history = load_history()
        history._client = Mock()
        history._client.table.side_effect = RuntimeError('SECRET')
        event = SimpleNamespace(source=SimpleNamespace(type='group', group_id='group-1'), timestamp=0)
        with patch('builtins.print') as logs:
            self.assertFalse(history.save_group_join(event))
        history.get_group_name.assert_not_called()
        self.assertNotIn('SECRET', str(logs.call_args_list))


class GroupNameTests(unittest.TestCase):
    def test_line_name_response_and_failures(self):
        config = ModuleType('config')
        config.LINE_CHANNEL_ACCESS_TOKEN = 'SECRET'
        path = Path(__file__).resolve().parents[1] / 'messaging.py'
        spec = importlib.util.spec_from_file_location('group_messaging_test', path)
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', [str(path.parent), *sys.path]), patch.dict(sys.modules, {'config': config}):
            spec.loader.exec_module(module)
        for payload, expected in [({'groupName': 'Test'}, 'Test'), ({}, None), ([], None), ({'groupName': ''}, None)]:
            with self.subTest(payload=payload), patch.object(module.requests, 'get') as get, patch('builtins.print'):
                get.return_value.json.return_value = payload
                self.assertEqual(module.get_group_name('group/1'), expected)
                self.assertEqual(get.call_args.args[0], 'https://api.line.me/v2/bot/group/group%2F1/summary')
                self.assertEqual(get.call_args.kwargs['timeout'], 10)
        with patch.object(module.requests, 'get', side_effect=requests.Timeout('SECRET')), patch('builtins.print') as logs:
            self.assertIsNone(module.get_group_name('group-1'))
        self.assertNotIn('SECRET', str(logs.call_args_list))
