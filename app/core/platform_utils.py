"""Desktop file opening without platform-specific shell commands."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


UI_FONT = "DejaVu Sans" if sys.platform.startswith("linux") else "Segoe UI"
MONO_FONT = "DejaVu Sans Mono" if sys.platform.startswith("linux") else "Consolas"


def open_ssh_terminal(host, username, port=22, terminal=None):
    """Open the same remote SSH session in a native Linux terminal."""
    host, username = str(host).strip(), str(username).strip()
    if not host or any(character.isspace() or character == "\0" for character in host + username):
        raise ValueError("Enter a valid SSH host and username.")
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535.")
    command = terminal or os.environ.get("TERMINAL")
    if command:
        argv = shlex.split(command) if isinstance(command, str) else list(command)
    else:
        executable = next((shutil.which(name) for name in (
            "x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"
        ) if shutil.which(name)), None)
        argv = [executable] if executable else []
    if not argv:
        raise OSError("No terminal emulator was found. Configure an SSH terminal command or install one.")
    name = Path(argv[0]).name
    flag = "--" if name in ("gnome-terminal", "kgx", "ptyxis") else "--execute" if name == "xfce4-terminal" else "-e"
    if argv[-1] not in ("--", "-e", "--execute", "-x"):
        argv.append(flag)
    destination = f"{username}@{host}" if username else host
    return subprocess.Popen(argv + ["ssh", "-p", str(port), "--", destination], shell=False)


def open_path(path):
    """Open a file or folder with the user's desktop application."""
    target = str(Path(path).expanduser().resolve())
    if sys.platform == "win32":
        return os.startfile(target)
    command = "open" if sys.platform == "darwin" else "xdg-open"
    return subprocess.Popen([command, target], shell=False)


def open_editor(path, editor=None):
    """Use a configured editor, VISUAL, EDITOR, or the desktop file association."""
    command = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not command:
        return open_path(path)
    if isinstance(command, (tuple, list)):
        argv = [str(value) for value in command]
    else:
        # A saved Windows executable path can contain spaces without quoting.
        expanded = os.path.expandvars(os.path.expanduser(str(command).strip()))
        argv = [expanded] if Path(expanded).is_file() else shlex.split(expanded)
    if not argv or not argv[0]:
        raise ValueError("Configure an editor executable or leave the editor setting empty.")
    return subprocess.Popen(argv + [str(Path(path).expanduser().resolve())], shell=False)
