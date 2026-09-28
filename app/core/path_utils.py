import os
from pathlib import Path


def normalize_local_path(path):
    if not path:
        return ""
    value = str(path).strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    value = value.strip()
    if not value:
        return ""
    return os.path.normpath(os.path.expanduser(value))


def local_path_exists(path):
    value = normalize_local_path(path)
    return bool(value) and Path(value).exists()


def is_path_within(path, parent):
    """Return True only when path is a strict descendant of parent."""
    try:
        resolved_path = Path(path).resolve()
        resolved_parent = Path(parent).resolve()
        return resolved_path != resolved_parent and resolved_path.is_relative_to(resolved_parent)
    except (OSError, RuntimeError, ValueError):
        return False
