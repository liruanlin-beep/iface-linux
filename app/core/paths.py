import os
import shutil
from pathlib import Path
import sys


APP_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP_DIR.parent
if os.environ.get("IFACE_DATA_DIR"):
    USER_DATA_DIR = Path(os.environ["IFACE_DATA_DIR"]).expanduser().resolve()
elif sys.platform.startswith("linux"):
    data_home = Path(os.environ.get("XDG_DATA_HOME", "")).expanduser()
    if not data_home.is_absolute():
        data_home = Path.home() / ".local" / "share"
    USER_DATA_DIR = data_home / "iface" / "2.0"
elif getattr(sys, "frozen", False):
    USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "iface" / "2.0"
else:
    USER_DATA_DIR = ROOT_DIR
CONFIG_DIR = USER_DATA_DIR / "config"
PROJECTS_DIR = USER_DATA_DIR / "projects"
OUTPUTS_DIR = USER_DATA_DIR / "outputs"
DATABASE_DIR = USER_DATA_DIR / "database"
LOGS_DIR = USER_DATA_DIR / "logs"
TRANSLATIONS_DIR = APP_DIR / "resources" / "translations"
TEMPLATES_DIR = APP_DIR / "resources" / "templates"
APP_ICON = APP_DIR / "resources" / "iface.ico"


def ensure_dirs():
    for path in (CONFIG_DIR, PROJECTS_DIR, OUTPUTS_DIR, DATABASE_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _migrate_legacy_install_data()


def _migrate_legacy_install_data():
    """Move first-run data away from the selectable installation directory."""
    if (sys.platform != "win32" or os.environ.get("IFACE_DATA_DIR")
            or not getattr(sys, "frozen", False) or USER_DATA_DIR == ROOT_DIR):
        return
    for name, target in (("config", CONFIG_DIR), ("projects", PROJECTS_DIR), ("outputs", OUTPUTS_DIR)):
        legacy = ROOT_DIR / name
        if not legacy.is_dir() or any(target.iterdir()):
            continue
        try:
            shutil.copytree(legacy, target, dirs_exist_ok=True)
        except OSError:
            # Read-only or partially copied legacy data must not prevent startup.
            pass
