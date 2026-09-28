import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReleasePathsTests(unittest.TestCase):
    def run_isolated(self, directory, code):
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=dict(os.environ, IFACE_DATA_DIR=str(directory)),
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
        return json.loads(result.stdout)

    def test_override_contains_all_state_and_removes_machine_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            values = self.run_isolated(directory,
                "import json; from app.core.config_manager import ConfigManager; "
                "from app.core.paths import CONFIG_DIR, PROJECTS_DIR, DATABASE_DIR; "
                "c=ConfigManager(); print(json.dumps([str(CONFIG_DIR), str(PROJECTS_DIR), "
                "str(DATABASE_DIR), c.data['default_project_dir'], c.data['potcar_root'], c.data['default_remote_host']]))")
            for path in values[:4]:
                self.assertTrue(Path(path).is_relative_to(Path(directory)))
            self.assertEqual(values[4:], ["", ""])

    def test_existing_user_settings_survive_new_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.mkdir()
            (config / "settings.json").write_text(json.dumps({
                "default_project_dir": "X:/user-projects",
                "potcar_root": "X:/licensed-potentials",
                "default_remote_host": "research.example",
            }), encoding="utf-8")
            values = self.run_isolated(directory,
                "import json; from app.core.config_manager import ConfigManager; "
                "c=ConfigManager(); print(json.dumps([c.data['default_project_dir'], "
                "c.data['potcar_root'], c.data['default_remote_host']]))")
            self.assertEqual(values, ["X:/user-projects", "X:/licensed-potentials", "research.example"])
