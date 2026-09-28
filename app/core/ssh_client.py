from pathlib import Path, PurePosixPath
import fnmatch
import hashlib
import posixpath
import shlex
import socket
import stat
import tempfile

from app.core.remote_file_browser import RemoteFileBrowser
from app.core.task_files import STANDARD_VASP_FILES
from app.core.task_bundle import MANIFEST_NAME, create_task_bundle


def normalize_remote_path(remote_path, default="."):
    """Normalize remote paths as Linux/POSIX paths for SFTP."""
    text = str(remote_path or default).strip().replace("\\", "/")
    if not text:
        text = default
    return posixpath.normpath(text)


def is_shell_script(path):
    name = Path(path).name.lower()
    return name.endswith((".sh", ".slurm")) or name in {"svasp.sh", "slurm.sh", "submit.sh"}


class SSHClientManager:
    def __init__(self):
        self.client = None
        self.sftp = None
        self.remote_browser = None
        self.host = ""
        self.username = ""
        self.port = ""

    def connect(self, host, port, username, password, timeout=10):
        if not host:
            raise ValueError('Host cannot be empty')
        if not username:
            raise ValueError('Username cannot be empty')
        if not password:
            raise ValueError('Password cannot be empty')
        try:
            port = int(port)
        except ValueError as exc:
            raise ValueError('Port must be numeric') from exc
        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError('Paramiko is not installed; SSH/SFTP is unavailable') from exc

        self.close()
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            self.sftp = self.client.open_sftp()
            self.remote_browser = RemoteFileBrowser(self.client, self.sftp)
            output, error = self.exec_command("echo SSH_OK && whoami && pwd")
            if "SSH_OK" not in output:
                raise RuntimeError('SSH connected, but the remote command test failed: ' + error)
            self.host = host
            self.username = username
            self.port = str(port)
            return output
        except paramiko.AuthenticationException as exc:
            self.close()
            raise RuntimeError('Authentication failed. Check username and password') from exc
        except socket.timeout as exc:
            self.close()
            raise RuntimeError('Connection timed out. Check server IP, port, network or VPN') from exc
        except socket.gaierror as exc:
            self.close()
            raise RuntimeError('Cannot resolve server address. Check IP or Host') from exc
        except paramiko.SSHException as exc:
            self.close()
            raise RuntimeError(f'Paramiko error: {exc}') from exc
        except Exception:
            self.close()
            raise

    def list_remote_dir(self, remote_path):
        if not self.remote_browser:
            if not self.sftp or not self.client:
                raise RuntimeError('SFTP is not connected')
            self.remote_browser = RemoteFileBrowser(self.client, self.sftp)
        return [
            {
                "name": item.name,
                "path": item.path,
                "size": item.size,
                "mtime": item.mtime,
                "mode": item.permissions,
                "type": item.type_name,
                "is_dir": item.is_dir,
            }
            for item in self.remote_browser.list_dir(remote_path)
        ]

    def ensure_remote_dir(self, remote_path):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_path = normalize_remote_path(remote_path)
        if remote_path in ("", ".", "/"):
            return
        current = "/" if remote_path.startswith("/") else "."
        for part in PurePosixPath(remote_path).parts:
            if part in ("", "/", "."):
                continue
            current = posixpath.join(current, part)
            try:
                attrs = self.sftp.stat(current)
                if not stat.S_ISDIR(attrs.st_mode):
                    raise RuntimeError(f'Remote path exists but is not a directory: {current}')
            except OSError:
                self.sftp.mkdir(current)

    def verify_remote_file(self, remote_path, expected_size=None):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_path = normalize_remote_path(remote_path)
        try:
            attrs = self.sftp.stat(remote_path)
        except OSError as exc:
            raise RuntimeError(f'File not found on the server after upload: {remote_path}') from exc
        if stat.S_ISDIR(attrs.st_mode):
            raise RuntimeError(f'Remote path is a directory, not a file: {remote_path}')
        if expected_size is not None and attrs.st_size != expected_size:
            raise RuntimeError(
                f'Remote file size verification failed: {remote_path}, local {expected_size} B, remote {attrs.st_size} B'
            )
        return attrs

    def verify_remote_files(self, remote_dir, filenames):
        remote_dir = normalize_remote_path(remote_dir)
        missing = []
        verified = []
        for name in filenames:
            remote_path = posixpath.join(remote_dir, str(name).replace("\\", "/"))
            try:
                attrs = self.verify_remote_file(remote_path)
                verified.append((name, attrs.st_size))
            except RuntimeError:
                missing.append(name)
        if missing:
            raise RuntimeError('These files could not be confirmed on the server after upload:\n' + "\n".join(missing))
        return verified

    def upload_file(self, local_path, remote_dir):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        local_path = Path(local_path)
        if not local_path.is_file():
            raise RuntimeError(f'Local file does not exist: {local_path}')
        remote_dir = normalize_remote_path(remote_dir)
        self.ensure_remote_dir(remote_dir)
        remote_path = posixpath.join(remote_dir, local_path.name)
        self._put_file_verified(local_path, remote_path)
        return remote_path

    def upload_path(self, local_path, remote_dir):
        local_path = Path(local_path)
        remote_dir = normalize_remote_path(remote_dir)
        if local_path.is_file():
            return [self.upload_file(local_path, remote_dir)]
        if not local_path.is_dir():
            raise RuntimeError(f'Local path does not exist: {local_path}')
        uploaded = []
        base_remote = posixpath.join(remote_dir, local_path.name)
        self.ensure_remote_dir(base_remote)
        for item in local_path.rglob("*"):
            rel = item.relative_to(local_path).as_posix()
            remote_item = posixpath.join(base_remote, rel)
            if item.is_dir():
                self.ensure_remote_dir(remote_item)
            else:
                self.ensure_remote_dir(posixpath.dirname(remote_item))
                self._put_file_verified(item, remote_item)
                uploaded.append(remote_item)
        return uploaded

    def upload_to_remote_path(self, local_path, remote_path):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        local_path = Path(local_path)
        if not local_path.is_file():
            raise RuntimeError(f'Local file does not exist: {local_path}')
        remote_path = normalize_remote_path(remote_path)
        self.ensure_remote_dir(posixpath.dirname(remote_path))
        self._put_file_verified(local_path, remote_path)
        return remote_path

    def _put_file_verified(self, local_path, remote_path):
        local_path = Path(local_path)
        upload_path = local_path
        temp_path = None
        try:
            if is_shell_script(local_path):
                data = local_path.read_bytes()
                lf_data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                if lf_data != data:
                    temp = tempfile.NamedTemporaryFile(delete=False, suffix=local_path.suffix)
                    temp.write(lf_data)
                    temp.close()
                    temp_path = Path(temp.name)
                    upload_path = temp_path
            self.sftp.put(str(upload_path), remote_path)
            self.verify_remote_file(remote_path, upload_path.stat().st_size)
        finally:
            if temp_path:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def download_file(self, remote_path, local_dir):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_path = normalize_remote_path(remote_path)
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / PurePosixPath(remote_path).name
        self.sftp.get(remote_path, str(local_path))
        return local_path

    def download_dir(self, remote_dir, local_dir):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_dir = normalize_remote_path(remote_dir).rstrip("/")
        local_root = Path(local_dir) / PurePosixPath(remote_dir).name
        local_root.mkdir(parents=True, exist_ok=True)

        def walk(rdir, ldir):
            for attr in self.sftp.listdir_attr(rdir):
                rpath = posixpath.join(rdir, attr.filename)
                lpath = ldir / attr.filename
                if stat.S_ISDIR(attr.st_mode):
                    lpath.mkdir(parents=True, exist_ok=True)
                    walk(rpath, lpath)
                else:
                    self.sftp.get(rpath, str(lpath))

        walk(remote_dir, local_root)
        return local_root

    def download_path(self, remote_path, local_dir):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_path = normalize_remote_path(remote_path)
        attrs = self.sftp.stat(remote_path)
        if stat.S_ISDIR(attrs.st_mode):
            return self.download_dir(remote_path, local_dir)
        return self.download_file(remote_path, local_dir)

    def read_remote_text(self, remote_path, max_size=5 * 1024 * 1024):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_path = normalize_remote_path(remote_path)
        attrs = self.sftp.stat(remote_path)
        if stat.S_ISDIR(attrs.st_mode):
            raise IsADirectoryError(f'Remote path is a directory: {remote_path}')
        if attrs.st_size > max_size:
            raise ValueError(f'File exceeds {max_size // 1024 // 1024} MB; download it before opening: {remote_path}')
        with self.sftp.open(remote_path, "rb") as handle:
            return handle.read().decode("utf-8", errors="ignore")

    def read_remote_tail(self, remote_path, max_size=2 * 1024 * 1024):
        """Read the newest part of a growing remote text file over SFTP."""
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_path = normalize_remote_path(remote_path)
        attrs = self.sftp.stat(remote_path)
        if stat.S_ISDIR(attrs.st_mode):
            raise IsADirectoryError(f'Remote path is a directory: {remote_path}')
        start = max(0, int(attrs.st_size) - int(max_size))
        with self.sftp.open(remote_path, "rb") as handle:
            if start:
                handle.seek(start)
                handle.readline()
            return handle.read(max_size).decode("utf-8", errors="ignore")

    def find_remote_files(self, remote_dir, patterns):
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        remote_dir = normalize_remote_path(remote_dir)
        found = []
        for attr in self.sftp.listdir_attr(remote_dir):
            if stat.S_ISDIR(attr.st_mode):
                continue
            if any(fnmatch.fnmatch(attr.filename, pattern) for pattern in patterns):
                found.append(posixpath.join(remote_dir, attr.filename))
        return found

    def upload_current_vasp_task(self, local_task_dir, remote_task_dir, required_files=None):
        local_task_dir = Path(local_task_dir)
        if not local_task_dir.exists():
            raise RuntimeError(f'Local task directory does not exist: {local_task_dir}')
        remote_task_dir = normalize_remote_path(remote_task_dir)
        required_files = list(required_files or STANDARD_VASP_FILES)
        local_missing = [name for name in required_files if not (local_task_dir / name).is_file()]
        if local_missing:
            raise RuntimeError(
                'Local task files are missing:\n' + "\n".join(local_missing)
                + '\n\nClick Generate Input Files first.'
            )
        self.ensure_remote_dir(remote_task_dir)
        results = []
        for name in required_files:
            local_file = local_task_dir / name
            remote_path = self.upload_file(local_file, remote_task_dir)
            if name.lower().endswith((".sh", ".slurm")):
                try:
                    self.sftp.chmod(remote_path, 0o755)
                except OSError:
                    pass
            results.append((name, 'succeeded; verified by server stat'))
        self.verify_remote_files(remote_task_dir, required_files)
        return results

    def upload_task_bundle_atomic(
        self,
        local_task_dir,
        remote_task_dir,
        required_files=None,
        task_name="",
        task_type="vasp",
        metadata=None,
    ):
        """Stage and verify a complete bundle, then publish task.json last."""
        if not self.sftp:
            raise RuntimeError('SFTP is not connected')
        local_task_dir = Path(local_task_dir)
        remote_task_dir = normalize_remote_path(remote_task_dir)
        bundle = create_task_bundle(
            local_task_dir,
            task_name or local_task_dir.name,
            task_type,
            required_files,
            metadata,
        )
        self.ensure_remote_dir(remote_task_dir)
        stage_dir = posixpath.join(
            remote_task_dir, f".iface-uploading-{bundle.bundle_id}"
        )
        backup_dir = posixpath.join(
            remote_task_dir, ".iface-backup", bundle.bundle_id
        )
        self.ensure_remote_dir(stage_dir)
        uploaded = []
        try:
            for name in bundle.files:
                local_path = bundle.root / name
                remote_stage = posixpath.join(stage_dir, name)
                self._put_file_verified(local_path, remote_stage)
                remote_hash = self._remote_sha256(remote_stage)
                if remote_hash != bundle.hashes[name]:
                    raise RuntimeError(
                        f'Server hash verification failed: {name}\nLocal: {bundle.hashes[name]}\nRemote: {remote_hash}'
                    )
                uploaded.append((name, local_path.stat().st_size, remote_hash))

            publish_order = [
                name for name in bundle.files if name != MANIFEST_NAME
            ] + [MANIFEST_NAME]
            for name in publish_order:
                source = posixpath.join(stage_dir, name)
                destination = posixpath.join(remote_task_dir, name)
                if self._remote_exists(destination):
                    self.ensure_remote_dir(backup_dir)
                    backup = posixpath.join(backup_dir, name)
                    if self._remote_exists(backup):
                        self.sftp.remove(backup)
                    self.sftp.rename(destination, backup)
                self._rename_remote(source, destination)
                if name.lower().endswith((".sh", ".slurm")):
                    self.sftp.chmod(destination, 0o755)
            self.sftp.rmdir(stage_dir)
        except Exception:
            self._remove_remote_tree(stage_dir)
            raise
        return {
            "bundle_id": bundle.bundle_id,
            "remote_dir": remote_task_dir,
            "files": uploaded,
            "manifest": posixpath.join(remote_task_dir, MANIFEST_NAME),
        }

    def _remote_sha256(self, remote_path, chunk_size=1024 * 1024):
        digest = hashlib.sha256()
        with self.sftp.open(remote_path, "rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
        return digest.hexdigest()

    def _remote_exists(self, remote_path):
        try:
            self.sftp.stat(remote_path)
            return True
        except OSError:
            return False

    def _rename_remote(self, source, destination):
        posix_rename = getattr(self.sftp, "posix_rename", None)
        if callable(posix_rename):
            posix_rename(source, destination)
        else:
            self.sftp.rename(source, destination)

    def _remove_remote_tree(self, remote_path):
        if not self.sftp or not self._remote_exists(remote_path):
            return
        try:
            for item in self.sftp.listdir_attr(remote_path):
                path = posixpath.join(remote_path, item.filename)
                if stat.S_ISDIR(item.st_mode):
                    self._remove_remote_tree(path)
                else:
                    self.sftp.remove(path)
            self.sftp.rmdir(remote_path)
        except OSError:
            pass

    def build_remote_command(self, command, workdir=None, init_command="", use_login_shell=False):
        parts = []
        if workdir:
            parts.append(f"cd {shlex.quote(normalize_remote_path(workdir))}")
        if init_command:
            parts.append(init_command.strip())
        parts.append(command.strip())
        raw_command = " && ".join(part for part in parts if part)
        if use_login_shell:
            return f"bash -lc {shlex.quote(raw_command)}"
        return raw_command

    def run_remote_command(self, command, workdir=None, init_command="", use_login_shell=False):
        if not self.client:
            raise RuntimeError('SSH is not connected')
        final_command = self.build_remote_command(command, workdir, init_command, use_login_shell)
        _stdin, stdout, stderr = self.client.exec_command(final_command)
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, out, err, final_command

    def exec_command(self, command, workdir=None, init_command="", use_login_shell=False):
        _exit_code, out, err, _final_command = self.run_remote_command(command, workdir, init_command, use_login_shell)
        return out, err

    def close(self):
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.sftp = None
        self.client = None
        self.remote_browser = None
        self.host = ""
        self.username = ""
        self.port = ""
