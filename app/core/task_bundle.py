import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.task_files import standard_vasp_files, validate_task_files


MANIFEST_NAME = "task.json"
CHECKSUM_NAME = "checksums.sha256"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class TaskBundle:
    root: Path
    bundle_id: str
    manifest_path: Path
    checksum_path: Path
    files: tuple
    hashes: dict


def create_task_bundle(
    task_dir,
    task_name,
    task_type="vasp",
    required_files=None,
    metadata=None,
    bundle_id=None,
):
    root = Path(task_dir)
    required = tuple(required_files or standard_vasp_files())
    missing, empty = validate_task_files(root, required)
    if missing or empty:
        details = []
        if missing:
            details.append('Missing: ' + ", ".join(missing))
        if empty:
            details.append('Empty file: ' + ", ".join(empty))
        raise ValueError('Task bundle verification failed; ' + "；".join(details))

    for name in required:
        path = root / name
        if path.suffix.lower() in {".sh", ".slurm"}:
            data = path.read_bytes()
            normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            if normalized != data:
                path.write_bytes(normalized)
    hashes = {name: sha256_file(root / name) for name in required}
    bundle_id = str(bundle_id or uuid.uuid4().hex)
    manifest = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "task_name": str(task_name).strip(),
        "task_type": str(task_type).strip() or "vasp",
        "created_at": utc_now(),
        "files": [
            {
                "name": name,
                "size": (root / name).stat().st_size,
                "sha256": hashes[name],
            }
            for name in required
        ],
        "metadata": metadata or {},
    }
    manifest_path = root / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    hashes[MANIFEST_NAME] = sha256_file(manifest_path)
    checksum_path = root / CHECKSUM_NAME
    checksum_path.write_text(
        "".join(f"{hashes[name]}  {name}\n" for name in (*required, MANIFEST_NAME)),
        encoding="utf-8",
        newline="\n",
    )
    hashes[CHECKSUM_NAME] = sha256_file(checksum_path)
    files = (*required, CHECKSUM_NAME, MANIFEST_NAME)
    return TaskBundle(
        root,
        bundle_id,
        manifest_path,
        checksum_path,
        tuple(files),
        hashes,
    )


def verify_task_bundle(task_dir):
    root = Path(task_dir)
    manifest_path = root / MANIFEST_NAME
    checksum_path = root / CHECKSUM_NAME
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise ValueError('Task bundle lacks task.json or checksums.sha256')
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or len(digest) != 64 or not name:
            raise ValueError(f'Invalid checksum file format: {line}')
        expected[name] = digest
    for name, digest in expected.items():
        path = root / name
        if not path.is_file():
            raise ValueError(f'Task bundle file missing: {name}')
        actual = sha256_file(path)
        if actual != digest:
            raise ValueError(f'Task bundle hash mismatch: {name}')
    listed = {item["name"]: item for item in manifest.get("files", [])}
    for name, item in listed.items():
        if expected.get(name) != item.get("sha256"):
            raise ValueError(f'task.json differs from checksums.sha256: {name}')
    return manifest
