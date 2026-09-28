import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core import platform_utils, secret_storage
from app.main import main, enable_windows_dpi_awareness


class LinuxPathsTests(unittest.TestCase):
    def load_paths(self, environment):
        source = Path(__file__).resolve().parents[1] / "app" / "core" / "paths.py"
        spec = importlib.util.spec_from_file_location("isolated_paths", source)
        module = importlib.util.module_from_spec(spec)
        environment = {"HOME": str(Path.home()), "USERPROFILE": str(Path.home()), **environment}
        with patch.dict(os.environ, environment, clear=True), patch.object(sys, "platform", "linux"):
            spec.loader.exec_module(module)
        return module

    def test_linux_state_uses_xdg_without_writing_into_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.load_paths({"XDG_DATA_HOME": temporary})
            paths.ensure_dirs()
            self.assertEqual(paths.USER_DATA_DIR, Path(temporary) / "iface" / "2.0")
            self.assertTrue(paths.CONFIG_DIR.is_dir())
            self.assertTrue(paths.TEMPLATES_DIR.is_dir())
            self.assertFalse(paths.CONFIG_DIR.is_relative_to(paths.APP_DIR))

    def test_data_override_preserves_isolated_workspaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.load_paths({"IFACE_DATA_DIR": temporary, "XDG_DATA_HOME": "ignored"})
            self.assertEqual(paths.USER_DATA_DIR, Path(temporary).resolve())

    def test_relative_xdg_value_uses_home_default(self):
        paths = self.load_paths({"XDG_DATA_HOME": "relative-path"})
        self.assertEqual(paths.USER_DATA_DIR, Path.home() / ".local" / "share" / "iface" / "2.0")


class PlatformOpeningTests(unittest.TestCase):
    def test_linux_opener_passes_a_literal_path_without_shell(self):
        path = Path("folder with spaces;echo no")
        with patch.object(sys, "platform", "linux"), patch.object(platform_utils.subprocess, "Popen") as launch:
            platform_utils.open_path(path)
        launch.assert_called_once_with(["xdg-open", str(path.resolve())], shell=False)

    def test_configured_editor_preserves_quoted_arguments(self):
        with patch.object(platform_utils.subprocess, "Popen") as launch:
            platform_utils.open_editor("INCAR", 'editor --title "iface inputs"')
        launch.assert_called_once_with(["editor", "--title", "iface inputs", str(Path("INCAR").resolve())], shell=False)

    def test_visual_editor_and_system_association_fallback(self):
        with patch.dict(os.environ, {"VISUAL": "visual-editor", "EDITOR": "other-editor"}, clear=True), \
                patch.object(platform_utils.subprocess, "Popen") as launch:
            platform_utils.open_editor("INCAR")
        self.assertEqual(launch.call_args.args[0][0], "visual-editor")
        with patch.dict(os.environ, {}, clear=True), patch.object(platform_utils, "open_path") as fallback:
            platform_utils.open_editor("INCAR")
        fallback.assert_called_once_with("INCAR")

    def test_windows_file_association_is_preserved(self):
        with patch.object(sys, "platform", "win32"), patch.object(os, "startfile", create=True) as start:
            platform_utils.open_path("INCAR")
        start.assert_called_once_with(str(Path("INCAR").resolve()))

    def test_ssh_terminal_uses_literal_destination_and_no_shell(self):
        with patch.object(platform_utils.subprocess, "Popen") as launch:
            platform_utils.open_ssh_terminal("compute.example", "researcher", 2222, "gnome-terminal")
        launch.assert_called_once_with(
            ["gnome-terminal", "--", "ssh", "-p", "2222", "--", "researcher@compute.example"], shell=False)


class LinuxSecretsTests(unittest.TestCase):
    def setUp(self):
        self.entries = {}
        self.backend = Mock()
        self.backend.set_password.side_effect = lambda service, reference, value: self.entries.__setitem__((service, reference), value)
        self.backend.get_password.side_effect = lambda service, reference: self.entries.get((service, reference))
        self.backend.delete_password.side_effect = lambda service, reference: self.entries.pop((service, reference))

    def test_linux_secret_round_trip_writes_only_keyring_reference_to_config(self):
        from copy import deepcopy
        from app.core.config_manager import ConfigManager, DEFAULT_SETTINGS

        with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "platform", "linux"), \
                patch.object(secret_storage, "_linux_keyring", return_value=self.backend):
            manager = ConfigManager.__new__(ConfigManager)
            manager.path = Path(temporary) / "settings.json"
            manager.data = deepcopy(DEFAULT_SETTINGS)
            manager.save_ai_credentials("DeepSeek", "deepseek-chat", "test-private-api-key")
            raw = manager.path.read_text(encoding="utf-8")
            reference = json.loads(raw)["ai"]["credentials"]["DeepSeek"]["protected_key"]
            self.assertTrue(reference.startswith("keyring:secret-service:"))
            self.assertNotIn("test-private-api-key", raw)
            self.assertEqual(manager.load_ai_credentials()["api_key"], "test-private-api-key")
            manager.save_ai_credentials("DeepSeek", "deepseek-chat", "replacement-test-key")
            self.assertEqual(len(self.entries), 1)
            self.assertEqual(manager.load_ai_credentials()["api_key"], "replacement-test-key")
            manager.remove_ai_credentials("DeepSeek")
            self.assertEqual(self.entries, {})
            self.assertEqual(manager.load_ai_credentials()["api_key"], "")

    def test_failed_config_save_removes_new_secret_and_keeps_previous(self):
        from copy import deepcopy
        from app.core.config_manager import ConfigManager, DEFAULT_SETTINGS

        with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "platform", "linux"), \
                patch.object(secret_storage, "_linux_keyring", return_value=self.backend):
            manager = ConfigManager.__new__(ConfigManager)
            manager.path = Path(temporary) / "settings.json"
            manager.data = deepcopy(DEFAULT_SETTINGS)
            manager.save_ai_credentials("DeepSeek", "deepseek-chat", "previous-test-key")
            with patch.object(manager, "save", side_effect=OSError("read-only")), self.assertRaises(OSError):
                manager.save_ai_credentials("DeepSeek", "deepseek-chat", "new-test-key")
            self.assertEqual(len(self.entries), 1)
            self.assertEqual(manager.load_ai_credentials()["api_key"], "previous-test-key")

    def test_remove_missing_keyring_entry_is_idempotent(self):
        with patch.object(sys, "platform", "linux"), patch.object(secret_storage, "_linux_keyring", return_value=self.backend):
            reference = secret_storage.protect_secret("temporary")
            secret_storage.remove_secret(reference)
            secret_storage.remove_secret(reference)
        self.assertEqual(self.entries, {})

    def test_missing_or_locked_keyring_never_falls_back_to_plaintext(self):
        with patch.object(sys, "platform", "linux"), \
                patch.object(secret_storage, "_linux_keyring", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                secret_storage.protect_secret("private")
        self.backend.set_password.side_effect = RuntimeError("locked")
        with patch.object(sys, "platform", "linux"), patch.object(secret_storage, "_linux_keyring", return_value=self.backend):
            with self.assertRaisesRegex(OSError, "could not save"):
                secret_storage.protect_secret("private")

    def test_native_secret_service_is_selected_explicitly(self):
        backend = Mock(priority=5)
        factory = Mock(return_value=backend)
        with patch.object(sys, "platform", "linux"), patch.dict(sys.modules, {
                "keyring.backends.SecretService": SimpleNamespace(Keyring=factory)}):
            self.assertIs(secret_storage._linux_keyring(), backend)
        factory.assert_called_once_with()

    def test_missing_and_invalid_references_are_reported(self):
        with patch.object(sys, "platform", "linux"), patch.object(secret_storage, "_linux_keyring", return_value=self.backend):
            with self.assertRaisesRegex(OSError, "missing"):
                secret_storage.unprotect_secret("keyring:secret-service:" + "a" * 32)
            with self.assertRaises(ValueError):
                secret_storage.unprotect_secret("keyring:secret-service:invalid")
            with self.assertRaisesRegex(OSError, "Windows"):
                secret_storage.unprotect_secret("dpapi:AA==")


class ApplicationEntryPointTests(unittest.TestCase):
    def test_callable_main_preserves_self_test_argument(self):
        run = Mock(return_value=7)
        with patch.dict(sys.modules, {"app.core.release_self_test": SimpleNamespace(run_release_self_test=run)}):
            self.assertEqual(main(["--self-test", "report.json"]), 7)
        run.assert_called_once_with("report.json")

    def test_callable_main_opens_full_original_gui(self):
        run = Mock()
        with patch.dict(sys.modules, {"app.ui.main_window": SimpleNamespace(main=run)}):
            self.assertEqual(main([]), 0)
        run.assert_called_once_with()

    def test_linux_dpi_setup_does_not_call_windows_libraries(self):
        import ctypes
        with patch.object(sys, "platform", "linux"), patch.object(ctypes, "windll", create=True) as dll:
            enable_windows_dpi_awareness()
        self.assertEqual(dll.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
