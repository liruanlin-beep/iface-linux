import posixpath
import stat
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RemoteFileItem:
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: str
    permissions: str

    @property
    def type_name(self):
        return 'Folder' if self.is_dir else 'File'


class RemoteFileBrowser:
    def __init__(self, ssh_client, sftp_client, log_callback=None):
        self.ssh = ssh_client
        self.sftp = sftp_client
        self.current_path = None
        self.log_callback = log_callback

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def get_home_dir(self):
        _stdin, stdout, stderr = self.ssh.exec_command("echo $HOME")
        home = stdout.read().decode("utf-8", errors="ignore").strip()
        error = stderr.read().decode("utf-8", errors="ignore").strip()
        if not home:
            raise RuntimeError(f'Cannot obtain remote HOME: {error}')
        return home

    def normalize_remote_path(self, path):
        if not path or not str(path).strip():
            return self.get_home_dir()
        path = str(path).strip()
        if path == "~":
            return self.get_home_dir()
        if path.startswith("~/"):
            return posixpath.join(self.get_home_dir(), path[2:])
        return posixpath.normpath(path)

    def list_dir(self, remote_path=None):
        if self.sftp is None:
            raise RuntimeError('SFTP is not connected; cannot browse remote files')
        if remote_path is None:
            remote_path = self.current_path or self.get_home_dir()
        remote_path = self.normalize_remote_path(remote_path)
        self.log(f'Reading remote directory: {remote_path}')
        try:
            attrs = self.sftp.listdir_attr(remote_path)
        except PermissionError as exc:
            raise RuntimeError(f'Permission denied reading remote directory: {remote_path}') from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f'Remote directory does not exist: {remote_path}') from exc
        except OSError as exc:
            raise RuntimeError(f'Failed to read remote directory: {remote_path}; error: {exc}') from exc

        items = []
        for attr in attrs:
            if attr.filename in (".", ".."):
                continue
            full_path = posixpath.join(remote_path, attr.filename)
            is_dir = stat.S_ISDIR(attr.st_mode)
            items.append(
                RemoteFileItem(
                    name=attr.filename,
                    path=full_path,
                    is_dir=is_dir,
                    size=attr.st_size,
                    mtime=datetime.fromtimestamp(attr.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    permissions=stat.filemode(attr.st_mode),
                )
            )
        items.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        self.current_path = remote_path
        self.log(f'Read complete: {len(items)} items')
        return items

    def enter_dir(self, folder_name):
        current = self.current_path or self.get_home_dir()
        return self.list_dir(posixpath.join(current, folder_name))

    def go_parent(self):
        current = self.current_path or self.get_home_dir()
        parent = posixpath.dirname(current.rstrip("/")) or "/"
        return self.list_dir(parent)

    def make_dir(self, folder_name):
        current = self.current_path or self.get_home_dir()
        new_path = posixpath.join(current, folder_name)
        try:
            self.sftp.mkdir(new_path)
        except Exception as exc:
            raise RuntimeError(f'Failed to create remote folder: {new_path}; error: {exc}') from exc
        self.log(f'Remote folder created: {new_path}')
        return self.list_dir(current)
