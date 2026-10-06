"""Leave handling without real LINE or database calls."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from test_detection_history import load_history
from test_group_join import join_event
import test_webhook_threadpool as webhook_tests


def leave_event():
    event = join_event()
    event.update(type='leave', webhookEventId='leave-1')
    del event['replyToken']  # LINE leave events cannot be replied to.
    return event


class LeaveWebhookTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = webhook_tests.WebhookThreadpoolTests.asyncSetUp
    asyncTearDown = webhook_tests.WebhookThreadpoolTests.asyncTearDown
    post_events = webhook_tests.WebhookThreadpoolTests.post_events

    async def test_leave_runs_in_worker_and_duplicate_is_skipped(self):
        workers = []
        loop_thread = threading.get_ident()
        self.module.save_group_leave.side_effect = lambda event: workers.append(threading.get_ident()) or True
        for _ in range(2):
            self.assertEqual((await self.post_events([leave_event()])).status_code, 200)
        self.assertEqual(len(workers), 1)
        self.assertNotEqual(workers[0], loop_thread)
        self.module.save_group_leave.assert_called_once()
        self.module.save_group_join.assert_not_called()
        self.module.save_detection.assert_not_called()
        self.module.analyze_message.assert_not_called()
        self.module.reply_to_line.assert_not_called()

    async def test_invalid_leave_rejects_whole_batch_before_write(self):
        self.assertEqual((await self.post_events([leave_event()], False)).status_code, 400)
        for field, value in [('source', {}), ('source', {'type': 'group', 'groupId': ''}),
                             ('timestamp', True), ('timestamp', -1), ('webhookEventId', '')]:
            with self.subTest(field=field):
                invalid = leave_event()
                invalid[field] = value
                self.assertEqual((await self.post_events([join_event(), invalid])).status_code, 400)
        self.module.save_group_leave.assert_not_called()
        self.module.save_group_join.assert_not_called()

    async def test_database_failure_returns_200(self):
        self.module.save_group_leave.return_value = False
        self.assertEqual((await self.post_events([leave_event()])).status_code, 200)

    async def test_room_leave_does_not_change_group(self):
        event = leave_event()
        event['source'] = {'type': 'room', 'roomId': 'room-1'}
        self.assertEqual((await self.post_events([event])).status_code, 200)
        self.module.save_group_leave.assert_not_called()


class LeaveHistoryTests(unittest.TestCase):
    def setUp(self):
        self.history = load_history()
        self.db = Mock()
        self.history._client = self.db
        self.query = self.db.table.return_value.update.return_value
        self.query.eq.return_value = self.query
        self.query.execute.return_value.data = [{'id': 'same-id'}]
        self.event = SimpleNamespace(source=SimpleNamespace(type='group', group_id='group-1'), timestamp=1700000000000)

    def test_leave_updates_only_status_and_join_reuses_identity(self):
        with patch('builtins.print'):
            self.assertTrue(self.history.save_group_leave(self.event))
            self.history.get_group_name.assert_not_called()
            self.db.table.assert_called_once_with('line_sources')
            self.db.table.return_value.update.assert_called_once_with({'is_active': False})
            self.query.eq.assert_any_call('line_source_id', 'group-1')
            self.query.eq.assert_any_call('source_type', 'group')
            self.assertTrue(self.history.save_group_join(self.event))
        row = self.db.table.return_value.upsert.call_args.args[0]
        self.assertEqual(row['line_source_id'], 'group-1')
        self.assertTrue(row['is_active'])
        self.assertEqual(self.db.table.return_value.upsert.call_args.kwargs, {'on_conflict': 'line_source_id'})
        self.db.table.return_value.delete.assert_not_called()
        self.assertTrue(all(call.args == ('line_sources',) for call in self.db.table.call_args_list))

    def test_no_row_and_database_error_are_not_success(self):
        self.query.execute.return_value.data = []
        with patch('builtins.print'):
            self.assertFalse(self.history.save_group_leave(self.event))
        self.query.execute.side_effect = RuntimeError('SECRET')
        with patch('builtins.print') as logs:
            self.assertFalse(self.history.save_group_leave(self.event))
        self.assertNotIn('SECRET', str(logs.call_args_list))

    def test_delayed_message_history_does_not_set_group_active(self):
        self.db.table.return_value.upsert.return_value.execute.return_value.data = [{'id': 'same-id'}]
        self.event.message = SimpleNamespace(text='สวัสดี')
        self.event.webhook_event_id = 'message-1'
        with patch('builtins.print'):
            self.assertTrue(self.history.save_detection(self.event, {'is_scam': False}))
        source_row = self.db.table.return_value.upsert.call_args_list[0].args[0]
        self.assertNotIn('is_active', source_row)
