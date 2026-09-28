import json
import os
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from app.core.slurm_diagnostics import SLURM_DIAGNOSTIC_COMMAND
from app.core.paths import CONFIG_DIR, PROJECTS_DIR, USER_DATA_DIR, ensure_dirs
from app.version import VERSION
from app.core.secret_storage import protect_secret, unprotect_secret, remove_secret


DEFAULT_SETTINGS = {
    "app_version": VERSION,
    "language": "en_US",
    "recent_projects": [],
    "recent_project_limit": 10,
    "default_project_dir": str(PROJECTS_DIR),
    "test_workspace_dir": str(USER_DATA_DIR / "sandbox"),
    "default_export_dir": "",
    "default_download_dir": "",
    "generated_structure_dir": "",
    "dialog_directories": {},
    "pane_ratios": {"left": 0.24, "right": 0.78, "bottom": 0.62},
    "default_remote_host": "",
    "default_remote_port": "22",
    "default_remote_root": "/home/user/vasp_projects",
    "open_last_project": True,
    "auto_save_project": True,
    "save_ssh_history": True,
    "save_password": False,
    "debug_mode": False,
    "appearance": {
        "theme": "白色专业版",
        "background_image": "",
    },
    "ai": {
        "last_provider": "DeepSeek",
        "credentials": {},
    },
    "slurm_script_name": "Svasp.sh",
    "scheduler": "Slurm",
    "submit_script": "Svasp.sh",
    "submit_init_command": "",
    "submit_use_login_shell": True,
    "submit_test_command": SLURM_DIAGNOSTIC_COMMAND,
    "potcar_root": "",
    "high_throughput": {
        "enabled": True,
        "primary_material_family": "alloy",
        "recommended_max_atoms": 300,
        "warning_max_atoms": 500,
        "hard_max_atoms": 1000,
        "max_inflight_jobs": 10,
        "server_aware_limit": True,
        "poll_interval_seconds": 15,
        "max_automatic_retries": 3,
        "stale_claim_seconds": 900,
        "slurm_automation": {
            "enabled": True,
            "max_attempts": 3,
            "auto_retry_node_failure": True,
            "auto_retry_preempted": True,
            "require_approval_for_resource_change": True,
        },
        "require_confirmation_for_expensive_jobs": True,
    },
    "mobaxterm_path": "",
    "editor_command": "",
    "ssh_terminal_command": "",
    "notepadpp_path": r"C:\Program Files\Notepad++\notepad++.exe" if sys.platform == "win32" else "",
    "servers": [],
    "slurm": {
        "partition": "",
        "job_name": "iface",
        "nodes": 1,
        "ntasks_per_node": 20,
        "time": "24:00:00",
        "vasp_version": "6.4.3",
        "vasp_bin": "",
        "run_command": "srun vasp_std",
        "batch_mode": False,
        "vasp_command": "srun vasp_std",
        "submit_command": "sbatch Svasp.sh",
        "query_command": "squeue -u {username}",
        "cancel_command": "scancel {job_id}",
    },
}


class ConfigManager:
    def __init__(self):
        ensure_dirs()
        self.path = CONFIG_DIR / "settings.json"
        self.data = self.load()

    def load(self):
        if not self.path.exists():
            self.save(DEFAULT_SETTINGS)
            return deepcopy(DEFAULT_SETTINGS)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        merged = deepcopy(DEFAULT_SETTINGS)
        self._deep_update(merged, data)
        if self._migrate_submit_defaults(merged):
            self.path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return merged

    def save(self, data=None):
        if data is not None:
            self.data = data
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_recent_project(self, path):
        items = [p for p in self.data.get("recent_projects", []) if p != str(path)]
        items.insert(0, str(path))
        self.data["recent_projects"] = items[:10]
        self.save()

    @staticmethod
    def _dialog_path(value):
        """Reject incomplete typed input instead of resolving it against the app folder."""
        if value is None or not str(value).strip():
            return None
        try:
            candidate = Path(os.path.expandvars(str(value).strip())).expanduser()
            if not candidate.is_absolute() or "\0" in str(candidate):
                return None
            if os.name == "nt" and any(
                any(char in '<>:"|?*' for char in part) or Path(part).is_reserved()
                for part in candidate.parts[1:]
            ):
                return None
            return candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    @staticmethod
    def _existing_directory(value):
        """Return a usable folder, walking up if a remembered folder was removed."""
        candidate = ConfigManager._dialog_path(value)
        if candidate is None:
            return None
        try:
            if candidate.is_file():
                candidate = candidate.parent
            while not candidate.is_dir():
                parent = candidate.parent
                if parent == candidate:
                    return None
                candidate = parent
            return str(candidate)
        except (OSError, RuntimeError, ValueError):
            return None

    def get_dialog_directory(self, purpose, fallback=None):
        """Restore a last-used folder without changing current project/task defaults."""
        directories = self.data.get("dialog_directories", {})
        remembered = directories.get(str(purpose).strip()) if isinstance(directories, dict) else None
        default_key = {
            "structure_export": "default_export_dir",
            "postprocessing_export": "default_export_dir",
            "download": "default_download_dir",
            "project": "default_project_dir",
            "potcar": "potcar_root",
        }.get(str(purpose).strip())
        for value in (remembered, fallback, self.data.get(default_key, ""), Path.home()):
            directory = self._existing_directory(value)
            if directory:
                return directory
        return None

    def remember_dialog_path(self, purpose, path, is_directory=False):
        """Persist a successful choice; cancellation never changes stored folders."""
        purpose = str(purpose or "").strip()
        if not purpose or path is None or not str(path).strip():
            return False
        selected = self._dialog_path(path)
        if selected is None:
            return False
        if not is_directory:
            selected = selected.parent
        if selected.is_file() or not self._existing_directory(selected):
            return False
        # Keep the intended output folder even before it is created. Native
        # dialogs resolve it to a surviving ancestor through get_dialog_directory.
        directory = str(selected)
        directories = self.data.get("dialog_directories")
        if not isinstance(directories, dict):
            directories = {}
            self.data["dialog_directories"] = directories
        if directories.get(purpose) != directory:
            directories[purpose] = directory
            self.save()
        return True

    def load_ai_credentials(self, provider=None):
        ai = self.data.setdefault("ai", deepcopy(DEFAULT_SETTINGS["ai"]))
        chosen = "DeepSeek"
        entry = ai.setdefault("credentials", {}).get(chosen, {})
        protected_key = str(entry.get("protected_key") or "")
        return {
            "provider": chosen,
            "model": str(entry.get("model") or ""),
            "api_key": unprotect_secret(protected_key) if protected_key else "",
            "saved_at": str(entry.get("saved_at") or ""),
        }

    def save_ai_credentials(self, provider, model, api_key):
        provider = str(provider or "").strip()
        api_key = str(api_key or "").strip()
        if provider != "DeepSeek":
            raise ValueError("iface Agent supports the DeepSeek API only.")
        if not api_key:
            raise ValueError("The API key must not be empty.")
        ai = self.data.setdefault("ai", deepcopy(DEFAULT_SETTINGS["ai"]))
        credentials = ai.setdefault("credentials", {})
        previous = credentials.get(provider)
        protected_key = protect_secret(api_key)
        ai["last_provider"] = provider
        credentials[provider] = {
            "model": str(model or "").strip(),
            "protected_key": protected_key,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            self.save()
        except Exception:
            if previous is None:
                credentials.pop(provider, None)
            else:
                credentials[provider] = previous
            remove_secret(protected_key)
            raise
        if previous:
            remove_secret(previous.get("protected_key", ""))

    def remove_ai_credentials(self, provider):
        ai = self.data.setdefault("ai", deepcopy(DEFAULT_SETTINGS["ai"]))
        credentials = ai.setdefault("credentials", {})
        previous = credentials.get("DeepSeek", {})
        remove_secret(previous.get("protected_key", ""))
        credentials.pop("DeepSeek", None)
        ai["last_provider"] = "DeepSeek"
        self.save()

    @staticmethod
    def _deep_update(target, source):
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                ConfigManager._deep_update(target[key], value)
            else:
                target[key] = value

    @staticmethod
    def _migrate_submit_defaults(data):
        changed = False
        appearance = data.setdefault("appearance", {})
        if appearance.get("theme") != "白色专业版":
            appearance["theme"] = "白色专业版"
            changed = True
        if data.get("submit_script") in ("", "slurm.sh"):
            data["submit_script"] = "Svasp.sh"
            changed = True
        if data.get("slurm_script_name") in ("", "slurm.sh"):
            data["slurm_script_name"] = "Svasp.sh"
            changed = True
        slurm = data.setdefault("slurm", {})
        if slurm.get("submit_command") in ("", "sbatch slurm.sh"):
            slurm["submit_command"] = "sbatch Svasp.sh"
            changed = True
        if slurm.get("job_name") in (None, "", "gjn"):
            slurm["job_name"] = "iface"
            changed = True
        if slurm.get("ntasks_per_node") in (None, "", 32):
            slurm["ntasks_per_node"] = 20
            changed = True
        if slurm.get("vasp_bin") in (
            "/home/dell/Software/vasp.6.3.2/bin",
            "/home/dell/Software/vasp.6.3.2/bin/",
        ):
            # 不把第一版集群上的固定路径带入另一台服务器。
            slurm["vasp_bin"] = ""
            changed = True
        if slurm.get("run_command") in ("", "mpirun -np $NP vasp_std"):
            slurm["run_command"] = "srun vasp_std"
            changed = True
        if slurm.get("vasp_command") in ("", "mpirun -np $NP vasp_std"):
            slurm["vasp_command"] = "srun vasp_std"
            changed = True
        if slurm.get("vasp_version") in (None, ""):
            slurm["vasp_version"] = "6.4.3"
            changed = True
        if data.get("submit_test_command") in (
            "",
            "echo SHELL=$SHELL && whoami && pwd && command -v sbatch && sbatch --version",
            "command -v sbatch && sbatch --version",
        ):
            data["submit_test_command"] = SLURM_DIAGNOSTIC_COMMAND
            changed = True
        slurm.setdefault("batch_mode", False)
        return changed
