"""Build a source archive with LF scripts and an explicit source-only allowlist."""

import argparse
import hashlib
import gzip
from pathlib import Path
import re
import shutil
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "iface-linux-3.0.1"


def sources():
    files = [ROOT / name for name in (
        "pyproject.toml", "README.md", "VALIDATION.md", "install.sh", ".gitattributes",
        ".gitignore", "LICENSE", "NOTICE.md", "CITATION.cff", "MANIFEST.in",
        "CONTRIBUTING.md", "CHANGELOG.md")]
    for folder in ("iface", "tests", "examples", "tools", "docs", ".github"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                files.append(path)
    for path in files:
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed in the distribution: {path}")
        if path.suffix == ".png":
            if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Invalid PNG: {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"[\u3400-\u9fff]", text):
            raise ValueError(f"Non-English built-in text found in {path.relative_to(ROOT)}")
        if path.suffix == ".sh" and b"\r" in path.read_bytes():
            raise ValueError(f"Shell script contains CRLF: {path}")
    return sorted(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    files = sources()
    tar_path = args.output / f"{PREFIX}.tar.gz"
    with tar_path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for path in files:
                info = archive.gettarinfo(str(path), arcname=f"{PREFIX}/{path.relative_to(ROOT).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                info.mode = 0o755 if path.suffix == ".sh" else 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
    zip_path = args.output / f"{PREFIX}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(f"{PREFIX}/{path.relative_to(ROOT).as_posix()}", (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = ((0o100755 if path.suffix == ".sh" else 0o100644) << 16)
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    for name in ("README.md", "VALIDATION.md", "LICENSE", "NOTICE.md"):
        shutil.copyfile(ROOT / name, args.output / name)
    checksums = []
    for path in (tar_path, zip_path, *sorted(args.output.glob("*.whl"))):
        checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (args.output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="ascii")
    print(f"English audit passed. Packaged {len(files)} files.")
    print(tar_path)
    print(zip_path)


if __name__ == "__main__":
    main()
