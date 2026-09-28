"""Exclusive output creation, recoverable cleanup, and input fingerprints."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid


INPUTS = ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "job.sh")


def write_new(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if isinstance(content, bytes) else "x"
    kwargs = {} if mode == "xb" else {"encoding": "utf-8", "newline": "\n"}
    with path.open(mode, **kwargs) as stream:
        stream.write(content)
    return path


def write_json(path, payload):
    return write_new(path, json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


@contextmanager
def new_directory(path):
    """Stage a complete bundle, then publish it without replacing existing work."""
    target = Path(path).expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Output already exists: {target}. Choose a new directory.")
    stage = Path(tempfile.mkdtemp(prefix=".iface-stage-", dir=target.parent))
    try:
        yield stage
        # Reserve the name first: os.rename can replace empty directories on Unix.
        target.mkdir()
        try:
            for item in stage.iterdir():
                shutil.move(str(item), str(target / item.name))
        except BaseException:
            # Preserve partial output for diagnosis; never delete user-visible work.
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def fingerprint(directory):
    root = Path(directory)
    paths = [root / name for name in INPUTS]
    paths += sorted(root.glob("[0-9][0-9]/POSCAR"))
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def archive_outputs(directory, keep=(), apply=False):
    """Move outputs into a timestamped archive; input files are never deleted."""
    root = Path(directory).resolve()
    if not root.is_dir() or not (root / "POSCAR").is_file():
        raise ValueError("Cleanup requires a calculation directory containing POSCAR.")
    if (root / ".iface-submission.json").exists():
        raise ValueError("Cleanup is blocked by a submission record. Verify the job state first.")
    protected = set(INPUTS) | {".iface-archive", "manifest.json"} | set(keep)
    items = [p for p in root.iterdir() if p.name not in protected and not p.name.startswith(".iface-")]
    result = {"directory": str(root), "files_to_archive": [p.name for p in items], "applied": False}
    if apply and items:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        destination = root / ".iface-archive" / stamp
        destination.mkdir(parents=True)
        for item in items:
            shutil.move(str(item), str(destination / item.name))
        result.update(applied=True, archive=str(destination))
    return result
