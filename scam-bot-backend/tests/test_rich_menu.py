"""จำลองปุ่ม Rich Menu และขั้นตอนติดตั้ง ไม่เรียก LINE/AI/ฐานข้อมูลจริง."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_webhook_threadpool as fixtures
from test_private_chat import private_event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rich_menu_setup as setup


def menu_event(number=1, source_type="user"):
    event = private_event(number=number)
    event.pop("message")
    event["type"] = "postback"
    event["postback"] = {"data": "menu:check"}
    if source_type != "user":
        event["source"] = {"type": source_type, f"{source_type}Id": "offline-source"}
    return event


class RichMenuWebhookTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.WebhookThreadpoolTests.asyncSetUp
    asyncTearDown = fixtures.WebhookThreadpoolTests.asyncTearDown
    post_events = fixtures.WebhookThreadpoolTests.post_events

    async def test_menu_check_replies_without_analysis_history_or_case(self):
        response = await self.post_events([menu_event()])
        self.assertEqual(response.status_code, 200)
        reply = self.module.reply_to_line.call_args.args[1]
        self.assertIn("วางและส่งในแชตนี้", reply)
        self.assertIn("อย่าส่งรหัสผ่านหรือ OTP", reply)
        self.module.analyze_message.assert_not_called()
        self.module.extract_text_from_image.assert_not_called()
        self.module.save_detection.assert_not_called()
        self.assertEqual(len(self.module.lesson_store._cases), 0)

    async def test_duplicate_click_is_replied_once(self):
        event = menu_event()
        await self.post_events([event, event])
        self.module.reply_to_line.assert_called_once()

    async def test_group_room_and_invalid_signature_do_not_reply(self):
        for kind in ("group", "room"):
            response = await self.post_events([menu_event(source_type=kind)])
            self.assertEqual(response.status_code, 200)
        response = await self.post_events([menu_event()], valid_signature=False)
        self.assertEqual(response.status_code, 400)
        self.module.reply_to_line.assert_not_called()

    async def test_send_failure_does_not_stop_next_menu_click(self):
        self.module.reply_to_line.side_effect = [RuntimeError("INTERNAL_SECRET"), True]
        with patch("builtins.print") as output:
            await self.post_events([menu_event(1), menu_event(2)])
        self.assertEqual(self.module.reply_to_line.call_count, 2)
        self.assertNotIn("INTERNAL_SECRET", str(output.call_args_list))


class RichMenuSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "deployment.local.json"
        self.definition = setup.build_rich_menu("1234567890-TestApp")

    def test_image_dimensions_and_tap_areas_match_liff_routes(self):
        image = setup.validate_menu_image(setup.IMAGE_PATH)
        self.assertLessEqual(len(image), 1_000_000)
        areas = self.definition["areas"]
        self.assertEqual([area["bounds"]["x"] for area in areas], [0, 1000, 1740])
        self.assertEqual(sum(area["bounds"]["width"] for area in areas), 2500)
        self.assertTrue(all(area["bounds"]["height"] == 843 for area in areas))
        self.assertEqual(areas[0]["action"]["data"], "menu:check")
        self.assertEqual(areas[1]["action"]["uri"], "https://liff.line.me/1234567890-TestApp/lessons")
        self.assertEqual(areas[2]["action"]["uri"], "https://liff.line.me/1234567890-TestApp/help")
        for invalid in ("", "123-app?secret=1", "https://bad.invalid", None):
            with self.assertRaises(ValueError):
                setup.build_rich_menu(invalid)

    def test_publish_keeps_backup_and_uploads_before_activation(self):
        calls = []

        def request(method, path, token, **kwargs):
            calls.append((method, path))
            if path == "/v2/bot/richmenu":
                return {"richMenuId": "richmenu-new"}
            if path == "/v2/bot/user/all/richmenu/richmenu-new":
                state = json.loads(self.state_path.read_text())
                self.assertEqual(state["previous_menu_id"], "richmenu-old")
                self.assertEqual(state["phase"], "created")
            return {}

        with patch.object(setup, "get_default_menu", side_effect=["richmenu-old", "richmenu-new"]), \
                patch.object(setup, "line_call", side_effect=request):
            result = setup.publish_menu("offline-token", self.definition, state_path=self.state_path)
        self.assertEqual(result["status"], "active")
        self.assertTrue(calls[-2][1].endswith("/content"))
        self.assertEqual(calls[-1][1], "/v2/bot/user/all/richmenu/richmenu-new")
        self.assertNotIn("offline-token", self.state_path.read_text())
        with patch.object(setup, "get_default_menu", return_value="richmenu-new"), patch.object(setup, "line_call") as line:
            self.assertEqual(setup.publish_menu("offline-token", self.definition, state_path=self.state_path)["status"], "already_active")
            line.assert_not_called()

    def test_failed_upload_never_activates_new_menu(self):
        with patch.object(setup, "get_default_menu", return_value="richmenu-old"), \
                patch.object(setup, "line_call", side_effect=[{}, {"richMenuId": "richmenu-new"}, RuntimeError("upload failed")]) as line:
            with self.assertRaises(RuntimeError):
                setup.publish_menu("offline-token", self.definition, state_path=self.state_path)
        self.assertEqual(line.call_count, 3)
        self.assertEqual(json.loads(self.state_path.read_text())["phase"], "created")

    def test_restore_refuses_to_overwrite_menu_changed_elsewhere(self):
        setup.write_state(self.state_path, {"new_menu_id": "richmenu-new", "previous_menu_id": "richmenu-old"})
        with patch.object(setup, "get_default_menu", return_value="richmenu-another"), patch.object(setup, "line_call") as line:
            with self.assertRaises(RuntimeError):
                setup.restore_menu("offline-token", self.state_path)
            line.assert_not_called()

    def test_restore_without_previous_api_default_removes_only_default_link(self):
        setup.write_state(self.state_path, {"new_menu_id": "richmenu-new", "previous_menu_id": None})
        with patch.object(setup, "get_default_menu", side_effect=["richmenu-new", None]), patch.object(setup, "line_call") as line:
            setup.restore_menu("offline-token", self.state_path)
            line.assert_called_once_with("DELETE", "/v2/bot/user/all/richmenu", "offline-token")
        self.assertEqual(json.loads(self.state_path.read_text())["phase"], "restored")

    def test_publish_requires_apply_before_config_or_network(self):
        with patch.object(sys, "argv", ["rich_menu_setup.py", "publish"]), \
                patch.object(setup, "load_dotenv") as environment, patch.object(setup, "line_call") as line, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                setup.main()
            environment.assert_not_called()
            line.assert_not_called()


if __name__ == "__main__":
    unittest.main()
