#!/usr/bin/env bash
# Install without root, global Python changes, or a graphical desktop.
set -euo pipefail
source_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
data_base="${XDG_DATA_HOME:-$HOME/.local/share}"
case "$data_base" in
    /*) ;;
    *) data_base="$HOME/.local/share" ;;
esac
environment="${IFACE_VENV:-$data_base/iface/terminal-3.0}"
python_bin="${PYTHON:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.10 or newer is required.' >&2
    exit 1
fi
"$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required.")'
if [[ ! -x "$environment/bin/python" ]]; then
    "$python_bin" -m venv "$environment"
fi
if [[ "${1:-}" == "--structures" ]]; then
    "$environment/bin/python" -m pip install "$source_dir[structures]"
elif [[ $# -eq 0 ]]; then
    "$environment/bin/python" -m pip install "$source_dir"
else
    printf '%s\n' 'Usage: bash install.sh [--structures]' >&2
    exit 2
fi
"$environment/bin/iface" --version
printf '\nInstalled successfully. Start with:\n  "%s/bin/iface"\n\n' "$environment"
printf 'Optional PATH setup for this shell:\n  export PATH="%s/bin:$PATH"\n' "$environment"
