"""ทดสอบการตรวจค่าตั้งต้นใน config.py แบบออฟไลน์ ไม่อ่าน .env จริง."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
REQUIRED = {
    "GEMINI_API_KEY": "offline", "SUPABASE_URL": "offline", "SUPABASE_KEY": "offline",
    "CHANNEL_SECRET": "offline", "CHANNEL_ACCESS_TOKEN": "offline",
    "SAFE_BROWSING_API_KEY": "offline",
}


def load_config(environment):
    """โหลด config.py ใหม่ด้วย environment ที่กำหนด และปิด load_dotenv เพื่อไม่ให้ .env จริงเติมค่า."""
    spec = importlib.util.spec_from_file_location("config_under_test", CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, environment, clear=True), patch("dotenv.load_dotenv"):
        spec.loader.exec_module(module)
    return module


class ConfigTests(unittest.TestCase):
    # ข้อความที่มีลิงก์เป็นช่องทางหลักของมิจฉาชีพ ไม่มีคีย์ = ตรวจลิงก์ไม่ได้เลย จึงต้องหยุดตั้งแต่เริ่มบอต
    def test_missing_safe_browsing_key_stops_startup_without_showing_secrets(self):
        environment = {name: value for name, value in REQUIRED.items() if name != "SAFE_BROWSING_API_KEY"}
        with self.assertRaises(RuntimeError) as raised:
            load_config(environment)
        self.assertIn("SAFE_BROWSING_API_KEY", str(raised.exception))
        self.assertNotIn("offline", str(raised.exception))

    def test_all_required_values_load(self):
        config = load_config(REQUIRED)
        self.assertEqual(config.SAFE_BROWSING_API_KEY, "offline")


if __name__ == "__main__":
    unittest.main()
