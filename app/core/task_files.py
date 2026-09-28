from pathlib import Path


STANDARD_VASP_FILES = ["POSCAR", "INCAR", "KPOINTS", "POTCAR", "Svasp.sh"]


def standard_vasp_files(script_name="Svasp.sh"):
    script_name = (script_name or "Svasp.sh").strip()
    files = ["POSCAR", "INCAR", "KPOINTS", "POTCAR"]
    if script_name not in files:
        files.append(script_name)
    return files


def validate_task_files(task_dir, required=None):
    task_dir = Path(task_dir)
    missing = []
    empty = []
    for name in required or STANDARD_VASP_FILES:
        path = task_dir / name
        if not path.exists():
            missing.append(name)
        elif path.is_file() and path.stat().st_size <= 0:
            empty.append(name)
    return missing, empty


def format_task_file_errors(task_dir, missing, empty):
    lines = [f'Current task directory: {Path(task_dir)}']
    if missing:
        lines.append('Missing files: ' + ", ".join(missing))
    if empty:
        lines.append('Empty file: ' + ", ".join(empty))
    return "\n".join(lines)
