import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from app.core.config_manager import ConfigManager, DEFAULT_SETTINGS
from app.ui import file_dialogs


class DialogDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = ConfigManager.__new__(ConfigManager)
        self.manager.path = self.root / "settings.json"
        self.manager.data = deepcopy(DEFAULT_SETTINGS)
        self.manager.data["user_marker"] = {"keep": [1, 2, 3]}

    def folder(self, name):
        path = self.root / name
        path.mkdir(parents=True)
        return path

    def test_restart_keeps_separate_import_export_and_unrelated_settings(self):
        source = self.folder("source")
        output = self.folder("output")
        self.manager.remember_dialog_path("structure_import", source / "POSCAR")
        self.manager.remember_dialog_path("structure_export", output / "model.cif")

        restored = ConfigManager.__new__(ConfigManager)
        restored.path = self.manager.path
        restored.data = restored.load()
        self.assertEqual(restored.get_dialog_directory("structure_import"), str(source))
        self.assertEqual(restored.get_dialog_directory("structure_export"), str(output))
        self.assertEqual(restored.data["user_marker"], {"keep": [1, 2, 3]})
        self.assertEqual(restored.data["default_export_dir"], "")

    def test_cancel_and_blank_do_not_change_saved_config(self):
        chosen = self.folder("chosen")
        self.manager.remember_dialog_path("download", chosen, is_directory=True)
        before = self.manager.path.read_bytes()
        for value in (None, "", "   "):
            self.assertFalse(self.manager.remember_dialog_path("download", value, is_directory=True))
        with patch.object(file_dialogs.filedialog, "asksaveasfilename", return_value=""):
            self.assertEqual(file_dialogs.asksaveasfilename(self.manager, "download"), "")
        self.assertEqual(self.manager.path.read_bytes(), before)

    def test_deleted_folder_falls_back_to_nearest_surviving_ancestor(self):
        parent = self.folder("exports")
        removed = self.folder("exports/deleted")
        self.manager.remember_dialog_path("structure_export", removed, is_directory=True)
        removed.rmdir()
        self.assertEqual(self.manager.get_dialog_directory("structure_export"), str(parent))

    def test_corrupt_or_unavailable_history_uses_valid_fallback(self):
        fallback = self.folder("fallback")
        self.manager.data["dialog_directories"] = {"download": "\0bad-path"}
        self.assertEqual(self.manager.get_dialog_directory("download", fallback), str(fallback))
        self.manager.data["dialog_directories"] = ["old-invalid-setting"]
        self.assertEqual(self.manager.get_dialog_directory("download", fallback), str(fallback))
        self.manager.remember_dialog_path("download", fallback, is_directory=True)
        self.assertEqual(json.loads(self.manager.path.read_text(encoding="utf-8"))["dialog_directories"]["download"], str(fallback))

    def test_new_output_folder_is_remembered_without_creating_it(self):
        parent = self.folder("future-output")
        intended = parent / "new-calculation"
        self.assertTrue(self.manager.remember_dialog_path("pdos_export", intended, is_directory=True))
        self.assertFalse(intended.exists())
        self.assertEqual(self.manager.data["dialog_directories"]["pdos_export"], str(intended))
        self.assertEqual(self.manager.get_dialog_directory("pdos_export"), str(parent))
        intended.mkdir()
        self.assertEqual(self.manager.get_dialog_directory("pdos_export"), str(intended))

    def test_incomplete_typed_paths_do_not_replace_last_output_folder(self):
        output = self.folder("valid-output")
        self.manager.remember_dialog_path("pdos_export", output, is_directory=True)
        for value in ("partial", "./relative-output", "\0invalid"):
            self.assertFalse(self.manager.remember_dialog_path("pdos_export", value, is_directory=True))
        self.assertEqual(self.manager.get_dialog_directory("pdos_export"), str(output))

    def test_save_dialog_uses_history_retains_filename_and_records_new_selection(self):
        first = self.folder("first")
        second = self.folder("second")
        self.manager.remember_dialog_path("structure_export", first, is_directory=True)
        with patch.object(file_dialogs.filedialog, "asksaveasfilename", return_value=str(second / "result.cif")) as dialog:
            result = file_dialogs.asksaveasfilename(
                self.manager, "structure_export", initialdir=str(self.root), initialfile="result.cif", title="导出结构"
            )
        self.assertEqual(dialog.call_args.kwargs["initialdir"], str(first))
        self.assertEqual(dialog.call_args.kwargs["initialfile"], "result.cif")
        self.assertEqual(result, str(second / "result.cif"))
        self.assertEqual(self.manager.get_dialog_directory("structure_export"), str(second))

    def test_multiselect_and_directory_selection_store_correct_folder(self):
        selected = self.folder("batch")
        paths = (str(selected / "A.cif"), str(selected / "B.cif"))
        with patch.object(file_dialogs.filedialog, "askopenfilenames", return_value=paths):
            self.assertEqual(file_dialogs.askopenfilenames(self.manager, "structure_import"), paths)
        with patch.object(file_dialogs.filedialog, "askdirectory", return_value=str(selected)):
            self.assertEqual(file_dialogs.askdirectory(self.manager, "download"), str(selected))
        self.assertEqual(self.manager.get_dialog_directory("structure_import"), str(selected))
        self.assertEqual(self.manager.get_dialog_directory("download"), str(selected))


if __name__ == "__main__":
    unittest.main()
