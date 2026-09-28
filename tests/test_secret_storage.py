import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app.core.config_manager import ConfigManager, DEFAULT_SETTINGS


@unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is required")
class SecretStorageTests(unittest.TestCase):
    def test_ai_key_round_trip_is_encrypted_at_rest(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ConfigManager.__new__(ConfigManager)
            manager.path = Path(temp) / "settings.json"
            manager.data = deepcopy(DEFAULT_SETTINGS)
            secret = "sk-iface-test-secret"

            manager.save_ai_credentials("DeepSeek", "deepseek-chat", secret)
            raw = manager.path.read_text(encoding="utf-8")
            stored = json.loads(raw)["ai"]["credentials"]["DeepSeek"]

            self.assertNotIn(secret, raw)
            self.assertTrue(stored["protected_key"].startswith("dpapi:"))
            self.assertEqual(
                manager.load_ai_credentials("DeepSeek")["api_key"],
                secret,
            )

            manager.remove_ai_credentials("DeepSeek")
            self.assertEqual(
                manager.load_ai_credentials("DeepSeek")["api_key"],
                "",
            )
