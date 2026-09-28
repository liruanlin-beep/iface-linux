#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'HELP'
Install the full iface 4.0 Linux desktop application for the current user.

Usage: bash install.sh [--python COMMAND] [--venv PATH] [--no-desktop]
                       [--install-system-deps]

Ubuntu 24.04 system dependencies:
  sudo apt-get update
  sudo apt-get install python3.12 python3.12-venv python3-tk xdg-utils openssh-client \
    gnome-keyring dbus-x11 fonts-dejavu-core libx11-6 libxext6 libxrender1

--install-system-deps runs these apt commands through sudo.
Python packages are always installed into a user-owned virtual environment.
The default environment is $XDG_DATA_HOME/iface/4.0/venv, or
$HOME/.local/share/iface/4.0/venv when XDG_DATA_HOME is unset or relative.
--no-desktop skips creation of the per-user Applications menu launcher.
HELP
}

python_command=python3
venv_path=''
desktop=1
system_deps=0
while (($#)); do
    case "$1" in
        --python|--venv)
            (($# >= 2)) || { printf 'Missing value for %s\n' "$1" >&2; exit 2; }
            if [[ "$1" == --python ]]; then python_command="$2"; else venv_path="$2"; fi
            shift 2 ;;
        --no-desktop) desktop=0; shift ;;
        --install-system-deps) system_deps=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ "$(uname -s)" == Linux ]] || { printf 'Run this installer on Linux.\n' >&2; exit 1; }
((EUID != 0)) || { printf 'Run as your normal desktop user, not root.\n' >&2; exit 1; }
if ((system_deps)); then
    sudo apt-get update
    sudo apt-get install -y python3.12 python3.12-venv python3-tk xdg-utils openssh-client \
        gnome-keyring dbus-x11 fonts-dejavu-core libx11-6 libxext6 libxrender1
fi

"$python_command" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("iface needs Python 3.12 or later. Use --python /path/to/python3.12.")
try:
    import tkinter
    import venv
except ImportError as error:
    raise SystemExit("Install python3-tk and python3.12-venv before continuing.") from error
PY

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
[[ "$data_home" == /* ]] || data_home="$HOME/.local/share"
venv_path="${venv_path:-$data_home/iface/4.0/venv}"
venv_path="$("$python_command" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$venv_path")"
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
[[ -f "$source_dir/pyproject.toml" ]] || { printf 'Keep install.sh inside the extracted source package.\n' >&2; exit 1; }

if [[ -e "$venv_path" && ! -f "$venv_path/pyvenv.cfg" ]]; then
    printf 'The selected environment path exists and is not a Python virtual environment: %s\n' "$venv_path" >&2
    exit 1
fi
if [[ ! -f "$venv_path/pyvenv.cfg" ]]; then
    "$python_command" -m venv "$venv_path"
fi
"$venv_path/bin/python" -c 'import sys; assert sys.version_info >= (3, 12), "The existing virtual environment needs Python 3.12 or later."'
"$venv_path/bin/python" -m pip install --upgrade pip
"$venv_path/bin/python" -m pip install "$source_dir"

if ((desktop)); then
    "$venv_path/bin/python" - "$venv_path" "$data_home" <<'PY'
from importlib.resources import files
from pathlib import Path
import sys
from PIL import Image

venv_path, data_home = map(Path, sys.argv[1:])
launcher = data_home / "applications" / "iface.desktop"
launcher.parent.mkdir(parents=True, exist_ok=True)
icon = data_home / "icons" / "hicolor" / "256x256" / "apps" / "iface.png"
icon.parent.mkdir(parents=True, exist_ok=True)
with Image.open(str(files("app").joinpath("resources", "iface.ico"))) as source:
    source.convert("RGBA").save(icon)

def desktop_quote(value):
    value = str(value).replace("%", "%%")
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value + '"'

executable = venv_path / "bin" / "iface"
launcher.write_text(
    "[Desktop Entry]\nType=Application\nName=iface\n"
    "Comment=Interface and surface modeling with the full iface desktop workflow\n"
    f"Exec={desktop_quote(executable)}\nTryExec={executable}\nIcon={icon}\n"
    "Terminal=false\nCategories=Science;Education;\nStartupNotify=true\n",
    encoding="utf-8",
)
print(f"Applications menu launcher: {launcher}")
PY
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$data_home/applications" || true
    fi
fi
printf '\nInstalled iface 4.0. Start it with:\n  %q\n' "$venv_path/bin/iface"
