import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from app.core.slurm_diagnostics import (
    SLURM_DIAGNOSTIC_COMMAND,
    classify_submit_error,
    submit_error_hint,
    submit_error_title,
    troubleshooting_commands,
)
from app.core.ssh_client import SSHClientManager
from app.core.platform_utils import open_path, open_editor
from app.ui import file_dialogs
from app.ui.responsive_rows import VerticalScrolledFrame, WidthLabel, WrappingRow
from app.core.task_preflight import validate_task_preflight
from app.core.reliable_submission import (
    ReliableSlurmSubmitter,
    SubmissionOutcomeUnknown,
)


SCRIPT_CANDIDATES = ["Svasp.sh", "slurm.sh", "run.slurm", "submit.sh", "job.sh", "job.slurm"]
RESULT_PATTERNS = ["OUTCAR", "OSZICAR", "CONTCAR", "vasp.out", "slurm-*.out", "slurm-*.err"]


class RemoteServerPanel(ttk.Frame):
    """MobaXterm-like single remote SFTP browser with a command area."""

    def __init__(self, master, callbacks):
        super().__init__(master, style="Panel.TFrame", padding=8)
        self.callbacks = callbacks
        self.config_manager = callbacks.get("get_config_manager", lambda: None)()
        self.ssh_manager = None
        self.remote_browser = None
        self.home_path = ""
        self.remote_path = tk.StringVar(value="")
        self.remote_edit_mapping = {}
        self.last_edited_local_path = tk.StringVar(value="")

        config = self.callbacks["get_config"]()
        self.host = tk.StringVar(value=config.get("default_remote_host", ""))
        self.port = tk.StringVar(value=str(config.get("default_remote_port", "22")))
        self.username = tk.StringVar(value="")
        self.password = tk.StringVar(value="")

        ttk.Label(self, text="Remote server", style="Title.TLabel").pack(anchor="w")
        self.status = tk.StringVar(value="Status: disconnected")
        WidthLabel(self, textvariable=self.status, style="Muted.TLabel").pack(fill="x", pady=(4, 6))

        self.connect_box = ttk.LabelFrame(self, text="SSH connection", padding=8)
        self.connect_box.pack(fill="x", pady=(0, 6))
        self._build_connect_box()

        self.workspace_tabs = ttk.Notebook(self, style="Content.TNotebook")
        self.workspace_tabs.pack(fill="both", expand=True)
        self.browser_page = VerticalScrolledFrame(self.workspace_tabs)
        self.browser_box = self.browser_page.body
        self.workspace_tabs.add(self.browser_page, text="Remote files")
        self.command_page = VerticalScrolledFrame(self.workspace_tabs)
        self.workspace_tabs.add(self.command_page, text="Submission and logs")
        self._build_remote_browser()
        self.browser_page.finish()
        self._build_command_area()

        self.log_text = tk.Text(self.command_page.body, height=6, width=1, wrap="word")
        self.log_text.pack(fill="both", expand=True, pady=(6, 0))
        self.command_page.finish()
        self.log("Not connected to a server.")
        self.update_command_preview()

    def _build_connect_box(self):
        self.connect_box.columnconfigure(1, weight=1)
        for index, (label, variable) in enumerate([
            ("Remote host", self.host), ("Port", self.port),
            ("Username", self.username), ("Password", self.password),
        ]):
            ttk.Label(self.connect_box, text=label).grid(row=index, column=0, sticky="w", padx=(0, 8), pady=2)
            options = {"show": "*"} if variable is self.password else {}
            ttk.Entry(self.connect_box, textvariable=variable, width=8 if variable is self.port else 16, **options).grid(
                row=index, column=1, sticky="w" if variable is self.port else "ew", pady=2
            )
        row = WrappingRow(self.connect_box)
        row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for text, command in [("Connect", self.connect_inline), ("Test connection", self.test_inline_connection), ("SSH manager", self.open_ssh)]:
            row.add(ttk.Button(row, text=text, style="Compact.TButton", command=command))

    def _build_remote_browser(self):
        path_row = ttk.Frame(self.browser_box, style="Panel.TFrame")
        path_row.pack(fill="x", pady=(0, 4))
        ttk.Label(path_row, text="Remote path: ", style="Panel.TLabel").pack(side="left")
        ttk.Entry(path_row, textvariable=self.remote_path, width=8).pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="Go", command=self.go_path, width=5).pack(side="left", padx=(4, 0))

        tool_row = WrappingRow(self.browser_box, style="Panel.TFrame")
        tool_row.pack(fill="x", pady=(0, 4))
        for text, cmd in [
            ("Home", self.go_home), ("Parent", self.go_parent),
            ("Refresh", self.refresh), ("Upload current task", self.upload_current_task),
            ("Submit task", self.submit_task),
        ]:
            tool_row.add(ttk.Button(tool_row, text=text, style="Compact.TButton", command=cmd))
        more = ttk.Menubutton(tool_row, text="More")
        more_menu = tk.Menu(more, tearoff=False)
        for text, cmd in [
            ("Upload files", self.upload_files), ("Upload folder", self.upload_folder),
            ("New folder", self.make_dir), ("Download", self.download_selected_to_results),
            ("Download results", self.download_results), ("Copy remote path", self.copy_current_remote_path),
            ("Verify remote directory", self.verify_remote_dir),
        ]:
            more_menu.add_command(label=text, command=cmd)
        more.configure(menu=more_menu)
        tool_row.add(more)

        hint = "Drop files to upload; dragging out first downloads them to the local cache."
        WidthLabel(self.browser_box, text=hint, style="Muted.TLabel").pack(fill="x", pady=(0, 4))

        table_frame = ttk.Frame(self.browser_box, style="Panel.TFrame")
        table_frame.pack(fill="both", expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(
            table_frame,
            columns=("kind", "size", "mtime", "permissions", "path"),
            show="tree headings",
            height=11,
        )
        for col, text, width in [
            ("#0", "Name", 160),
            ("kind", "Type", 70),
            ("size", "Size", 80),
            ("mtime", "Modified", 135),
            ("permissions", "Mode", 90),
            ("path", "Full path", 220),
        ]:
            self.table.heading(col, text=text)
            self.table.column(col, width=width, minwidth=width, stretch=False)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.table.bind("<Double-1>", self.open_selected)
        self.table.bind("<Button-3>", self.show_remote_menu)
        self._enable_optional_drop_upload()

    def _build_command_area(self):
        box = ttk.LabelFrame(self.command_page.body, text="Remote commands / job submission", padding=6)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        config = self.callbacks["get_config"]()
        slurm = config.get("slurm", {})
        self.scheduler = tk.StringVar(value=config.get("scheduler", "Slurm"))
        self.submit_script = tk.StringVar(value=config.get("submit_script", config.get("slurm_script_name", "Svasp.sh")))
        self.submit_command = tk.StringVar(value=slurm.get("submit_command", "sbatch Svasp.sh"))
        self.init_command = tk.StringVar(value=config.get("submit_init_command", ""))
        self.use_login_shell = tk.BooleanVar(value=config.get("submit_use_login_shell", True))
        self.command_preview = tk.StringVar(value="")

        for index, (label, variable) in enumerate([
            ("Job script", self.submit_script), ("Submission command", self.submit_command),
            ("Environment initialization", self.init_command),
        ]):
            ttk.Label(box, text=label).grid(row=index, column=0, sticky="w", pady=3)
            ttk.Entry(box, textvariable=variable, width=12).grid(row=index, column=1, sticky="ew", padx=(6, 0), pady=3)
        ttk.Checkbutton(box, text="Use bash -lc", variable=self.use_login_shell, command=self.update_command_preview).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        WidthLabel(box, textvariable=self.command_preview, style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        action = WrappingRow(box)
        action.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for text, command in [
            ("Save settings", self.save_submit_settings), ("Test Slurm environment", self.test_submit_environment),
            ("End-to-end submission test", self.run_end_to_end_acceptance), ("Copy diagnostic commands", self.copy_submit_troubleshooting_commands),
            ("Submit task", self.submit_task), ("Query queue", self.query_queue),
        ]:
            action.add(ttk.Button(action, text=text, style="Compact.TButton", command=command))
        for var in (self.submit_script, self.submit_command, self.init_command):
            var.trace_add("write", lambda *_: self.update_command_preview())

    def _enable_optional_drop_upload(self):
        try:
            from tkinterdnd2 import DND_FILES

            self.table.drop_target_register(DND_FILES)
            self.table.dnd_bind("<<Drop>>", self.handle_drop_upload)
            self.table.drag_source_register(1, DND_FILES)
            self.table.dnd_bind("<<DragInitCmd>>", self.begin_remote_file_drag)
            if hasattr(self, "log_text"):
                self.log("Drag-and-drop upload enabled.")
        except Exception:
            # Plain tkinter has no native Explorer drop support; upload buttons remain available.
            pass

    def begin_remote_file_drag(self, _event=None):
        """Materialize the selected SFTP file locally and expose a desktop file drag."""
        try:
            from tkinterdnd2 import COPY, DND_FILES

            local_path = self.download_remote_file_to_edit_cache()
            if not local_path:
                return ()
            # Tcl braces preserve paths with spaces for the native file-drag backend.
            drag_data = "{" + str(Path(local_path).resolve()) + "}"
            self.log(f"Dragging remote file to the desktop: {local_path}")
            return COPY, DND_FILES, drag_data
        except Exception as exc:
            self.log(f"Could not drag out remote file: {exc}")
            return ()

    def handle_drop_upload(self, event):
        paths = self.tk.splitlist(event.data)
        self.upload_local_paths(paths)

    def open_ssh(self):
        self.callbacks["open_ssh"]()

    def connect_inline(self):
        try:
            client = self.ssh_manager or SSHClientManager()
            output = client.connect(self.host.get().strip(), self.port.get().strip(), self.username.get().strip(), self.password.get())
            self.set_connection(client)
            config = self.callbacks["get_config"]()
            config["default_remote_host"] = self.host.get().strip()
            config["default_remote_port"] = self.port.get().strip()
            self.callbacks["save_config"]()
            self.log(output.strip())
        except Exception as exc:
            self.log(f"Connection failed: {exc}")
            messagebox.showerror("SSH connection failed", str(exc))

    def test_inline_connection(self):
        try:
            temp = SSHClientManager()
            output = temp.connect(self.host.get().strip(), self.port.get().strip(), self.username.get().strip(), self.password.get())
            temp.close()
            messagebox.showinfo("SSH test passed", output.strip())
        except Exception as exc:
            messagebox.showerror("SSH test failed", str(exc))

    def set_connection(self, ssh_manager, items=None, path=None):
        self.ssh_manager = ssh_manager
        self.remote_browser = ssh_manager.remote_browser
        self.home_path = path or (self.remote_browser.current_path if self.remote_browser else "")
        self.host.set(ssh_manager.host or self.host.get())
        self.username.set(ssh_manager.username or self.username.get())
        self.port.set(getattr(ssh_manager, "port", "") or self.port.get())
        if items is not None:
            self.refresh_remote_table(items)
        elif self.remote_browser:
            self.refresh()
        self.update_connection_status()
        self.log("SSH connected; SFTP file browser loaded.")

    def ensure_connected(self):
        if not self.ssh_manager or not self.remote_browser or not self.ssh_manager.sftp:
            messagebox.showwarning("Remote server", "Connect to a server first.")
            return False
        return True

    def refresh_remote_table(self, items):
        self.table.delete(*self.table.get_children())
        parent = posixpath.dirname((self.remote_browser.current_path or "").rstrip("/")) or "/"
        self.table.insert("", "end", text="[DIR] ..", values=("dir", "", "", "", parent))
        for item in items:
            kind = "dir" if item.is_dir else "file"
            name = ("[DIR] " if item.is_dir else "[FILE] ") + item.name
            size = "" if item.is_dir else self.format_size(item.size)
            self.table.insert("", "end", text=name, values=(kind, size, item.mtime, item.permissions, item.path))
        current = self.remote_browser.current_path if self.remote_browser else ""
        self.remote_path.set(current or "")
        self.update_connection_status()
        self.auto_detect_submit_script(items)
        self.update_command_preview()

    def load_dir(self, path, title="Could not read remote directory"):
        if not self.ensure_connected():
            return False
        old_path = self.remote_browser.current_path
        try:
            items = self.remote_browser.list_dir(path)
            self.refresh_remote_table(items)
            self.log(f"Loaded remote directory: {self.remote_browser.current_path}")
            return True
        except Exception as exc:
            self.remote_browser.current_path = old_path
            self.log(str(exc))
            messagebox.showwarning(title, str(exc))
            return False

    def go_path(self):
        self.load_dir(self.remote_path.get().strip() or None, "Could not open directory")

    def go_home(self):
        if not self.ensure_connected():
            return
        home = self.home_path or self.remote_browser.get_home_dir()
        self.home_path = home
        self.load_dir(home, "Could not open home directory")

    def go_parent(self):
        if not self.ensure_connected():
            return
        try:
            items = self.remote_browser.go_parent()
            self.refresh_remote_table(items)
            self.log(f"Returned to: {self.remote_browser.current_path}")
        except Exception as exc:
            self.log(str(exc))
            messagebox.showwarning("Could not navigate back", str(exc))

    def refresh(self):
        self.load_dir(self.remote_path.get().strip() or None, "Refresh failed")

    def make_dir(self):
        if not self.ensure_connected():
            return
        name = simpledialog.askstring("New remote folder", "Folder name: ", parent=self)
        if not name:
            return
        try:
            items = self.remote_browser.make_dir(name.strip())
            self.refresh_remote_table(items)
        except Exception as exc:
            self.log(str(exc))
            messagebox.showwarning("Could not create folder", str(exc))

    def selected_remote_items(self):
        items = []
        for item_id in self.table.selection():
            values = self.table.item(item_id, "values")
            if values:
                items.append({"kind": values[0], "path": values[4], "name": posixpath.basename(values[4])})
        return items

    def project_dir(self):
        getter = self.callbacks.get("get_project_dir")
        if getter:
            return Path(getter())
        return Path(self.callbacks["get_result_dir"]()).parent.parent

    def remote_edit_cache_dir(self):
        cache_dir = self.project_dir() / ".remote_edit_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def remote_edit_mapping_file(self):
        return self.remote_edit_cache_dir() / "remote_edit_mapping.json"

    def upload_log_path(self):
        log_dir = self.project_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "sftp_upload.log"

    def append_upload_log(self, message):
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.upload_log_path().open("a", encoding="utf-8") as handle:
                handle.write(f"[{stamp}] {message}\n")
        except OSError:
            pass

    def current_connection_label(self):
        if not self.ssh_manager:
            return "Disconnected"
        user = self.ssh_manager.username or self.username.get().strip() or "?"
        host = self.ssh_manager.host or self.host.get().strip() or "?"
        port = getattr(self.ssh_manager, "port", "") or self.port.get().strip() or "22"
        return f"{user}@{host}:{port}"

    def update_connection_status(self):
        if not self.ssh_manager:
            self.status.set("Status: disconnected")
            return
        remote_dir = self.remote_path.get().strip() or "(Not loaded)"
        self.status.set(f"Connection: {self.current_connection_label()}    Current remote directory: {remote_dir}")

    def load_remote_edit_mapping(self):
        path = self.remote_edit_mapping_file()
        if not path.exists():
            self.remote_edit_mapping = {}
            return self.remote_edit_mapping
        try:
            self.remote_edit_mapping = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.remote_edit_mapping = {}
        return self.remote_edit_mapping

    def save_remote_edit_mapping(self):
        path = self.remote_edit_mapping_file()
        path.write_text(json.dumps(self.remote_edit_mapping, ensure_ascii=False, indent=2), encoding="utf-8")

    def selected_remote_file(self):
        items = self.selected_remote_items()
        if not items:
            messagebox.showwarning("Remote files", "Select a remote file first.")
            return None
        item = items[0]
        if item["kind"] == "dir" or item["name"] == "..":
            messagebox.showwarning("Remote files", "Select a file. Folders cannot be edited in a text editor.")
            return None
        return item

    def download_remote_file_to_edit_cache(self):
        if not self.ensure_connected():
            return None
        item = self.selected_remote_file()
        if not item:
            return None
        try:
            local_path = self.ssh_manager.download_file(item["path"], self.remote_edit_cache_dir())
            self.load_remote_edit_mapping()
            self.remote_edit_mapping[str(local_path)] = item["path"]
            self.last_edited_local_path.set(str(local_path))
            self.save_remote_edit_mapping()
            self.log(f"Downloaded to editing cache: {item['path']} -> {local_path}")
            return local_path
        except Exception as exc:
            self.log(f"Could not download remote file: {exc}")
            messagebox.showwarning("Could not download remote file", str(exc))
            return None

    def open_cached_file(self, local_path, editor="default"):
        local_path = Path(local_path)
        try:
            if editor == "notepad++":
                config = self.callbacks["get_config"]()
                if sys.platform != "win32":
                    open_editor(local_path, config.get("editor_command") or None)
                else:
                    notepadpp = Path(config.get("notepadpp_path", r"C:\Program Files\Notepad++\notepad++.exe"))
                    if notepadpp.is_file():
                        open_editor(local_path, str(notepadpp))
                    else:
                        self.log("Custom editor unavailable; opened with the system default.")
                        open_path(local_path)
            elif editor == "notepad":
                open_editor(local_path, "notepad.exe" if sys.platform == "win32" else None)
            else:
                open_path(local_path)
        except Exception as exc:
            self.log(f"Could not open cached file: {exc}")
            messagebox.showwarning("Could not open cached file", str(exc))

    def download_remote_selected_to_cache(self):
        self.download_remote_file_to_edit_cache()

    def open_remote_in_notepadpp(self):
        local_path = self.download_remote_file_to_edit_cache()
        if local_path:
            self.open_cached_file(local_path, "notepad++")

    def open_remote_in_notepad(self):
        local_path = self.download_remote_file_to_edit_cache()
        if local_path:
            self.open_cached_file(local_path, "notepad")

    def upload_edited_file_back(self):
        if not self.ensure_connected():
            return
        self.load_remote_edit_mapping()
        local_path = self.last_edited_local_path.get().strip()
        if not local_path or local_path not in self.remote_edit_mapping:
            local_path = file_dialogs.askopenfilename(
                self.config_manager, "remote_edit", parent=self,
                title="Choose a cached file to upload back to the server",
                initialdir=str(self.remote_edit_cache_dir()),
            )
        if not local_path:
            return
        remote_path = self.remote_edit_mapping.get(str(local_path))
        if not remote_path:
            messagebox.showwarning("Save and upload back", "No remote path is associated with this cached file. Download or edit it again from the remote context menu.")
            return
        try:
            uploaded = self.ssh_manager.upload_to_remote_path(local_path, remote_path)
            attrs = self.ssh_manager.verify_remote_file(uploaded, Path(local_path).stat().st_size)
            self.log(f"Saved and uploaded back: {local_path} -> {uploaded}; remote size {attrs.st_size} B")
            self.refresh()
            messagebox.showinfo("Upload complete", f"Uploaded back and verified with stat: \n{uploaded}")
        except Exception as exc:
            self.log(f"Could not upload back to server: {exc}")
            messagebox.showwarning("Could not upload back to server", str(exc))

    def open_selected(self, _event=None):
        items = self.selected_remote_items()
        if not items:
            return
        item = items[0]
        if item["kind"] == "dir":
            self.load_dir(item["path"], "Could not read directory")
        else:
            self.preview_remote_text_file(item["path"])

    def upload_files(self):
        if not self.ensure_connected():
            return
        files = file_dialogs.askopenfilenames(self.config_manager, "upload", parent=self, title="Choose files to upload")
        self.upload_local_paths(files)

    def upload_folder(self):
        if not self.ensure_connected():
            return
        folder = file_dialogs.askdirectory(self.config_manager, "upload", parent=self, title="Choose a folder to upload")
        if folder:
            self.upload_local_paths([folder])

    def upload_local_paths(self, paths):
        if not paths:
            return
        if not self.ensure_connected():
            return
        remote_dir = self.remote_path.get().strip()
        try:
            for raw_path in paths:
                path = Path(str(raw_path).strip("{}"))
                self.log("Uploading files/folders")
                self.log(f"Connection: {self.current_connection_label()}")
                self.log(f"Local path: {path}")
                self.log(f"Remote directory: {remote_dir}")
                uploaded = self.ssh_manager.upload_path(path, remote_dir)
                if uploaded:
                    for remote_path in uploaded:
                        attrs = self.ssh_manager.verify_remote_file(remote_path)
                        self.log(f"sftp.stat verified: {remote_path}; size {attrs.st_size} B")
                        self.log(f"Upload successful: {path} -> {remote_path}")
                        if str(remote_path).lower().endswith((".sh", ".slurm")):
                            self.log("Script line endings were converted to Linux LF during upload.")
                else:
                    self.log(f"Upload complete: {path}")
            self.refresh()
            self.verify_remote_dir(remote_dir)
        except Exception as exc:
            self.log(f"Upload failed: {exc}")
            messagebox.showwarning("Upload failed", str(exc))

    def upload_current_task(self):
        if not self.ensure_connected():
            return
        local_task_dir = Path(self.callbacks["get_current_task_dir"]())
        # The visible SFTP directory is the user's explicit destination choice.
        # Never silently redirect an upload to the configured default task root.
        remote_task_dir = self.remote_path.get().strip().replace("\\", "/").rstrip("/")
        if not remote_task_dir:
            messagebox.showwarning("Upload current task", "Remote path is empty. Open the target directory in the remote file browser first.")
            return
        ensure_task_files = self.callbacks.get("ensure_task_files")
        if ensure_task_files and not ensure_task_files():
            self.log("Upload cancelled: current task files are incomplete.")
            return
        try:
            required = self.callbacks.get("get_required_task_files", lambda: None)()
            required = list(required or [])
            config = self.callbacks["get_config"]()
            script_name = str(
                config.get("submit_script", "Svasp.sh")
            ).strip()
            preflight = validate_task_preflight(
                local_task_dir,
                script_name,
                config.get("high_throughput", {}).get("hard_max_atoms", 1000),
            )
            preflight.raise_for_errors()
            self.log("Uploading current task")
            for check in preflight.checks:
                self.log("Pre-submission validation: " + check)
            for warning in preflight.warnings:
                self.log("Pre-submission warning: " + warning)
            self.log(f"Connection: {self.current_connection_label()}")
            self.log(f"Local task directory: {local_task_dir}")
            self.log(f"Upload target (current remote directory): {remote_task_dir}")
            for name in required:
                local_file = local_task_dir / name
                remote_file = posixpath.join(str(remote_task_dir).replace(chr(92), "/").rstrip("/"), name)
                self.log(f"Preparing upload: {local_file} -> {remote_file}")
            bundle = self.ssh_manager.upload_task_bundle_atomic(
                local_task_dir,
                remote_task_dir,
                required,
                task_name=self.callbacks.get(
                    "get_current_task_name", lambda: local_task_dir.name
                )(),
                metadata={
                    "project_dir": str(
                        self.callbacks.get("get_project_dir", lambda: "")()
                    ),
                    "remote_host": getattr(self.ssh_manager, "host", ""),
                    "remote_user": getattr(self.ssh_manager, "username", ""),
                    "preflight": preflight.to_dict(),
                },
            )
            self.log(f"Task bundle ID: {bundle['bundle_id']}")
            self.log("All SHA-256 checks passed; task.json was published last.")
            verified = [(name, size) for name, size, _hash in bundle["files"]]
            for name, size in verified:
                self.log(f"sftp.stat verified: {posixpath.join(str(remote_task_dir).replace(chr(92), '/').rstrip('/'), name)}; size {size} B")
                if str(name).lower().endswith((".sh", ".slurm")):
                    self.log(f"{name}: Converted to Linux LF line endings during upload.")
            self.load_dir(remote_task_dir, "Could not refresh after upload")
            self.verify_remote_dir(remote_task_dir)
            verified_names = "\n".join(name for name, _size in verified)
            messagebox.showinfo(
                "Verified upload complete",
                "Current task uploaded to the selected remote directory.\n"
                "All files passed SHA-256 verification; task.json was published last as the commit marker.\n\n"
                f"Task bundle ID: {bundle['bundle_id']}\n"
                f"Remote host: {getattr(self.ssh_manager, 'host', '')}\n"
                f"Remote user: {getattr(self.ssh_manager, 'username', '')}\n"
                f"Remote directory: {remote_task_dir}\n\n"
                f"Verified files: \n{verified_names}",
            )
        except Exception as exc:
            hint = (
                "\n\nIf another application cannot see the files, check: \n"
                "1. Both clients use the same IP and username;\n"
                "2. The external SSH client uses the same remote directory;\n"
                "3. Remote paths contain no Windows backslashes;\n"
                "4. Directory permissions allow your account to read and write."
            )
            self.log(str(exc))
            messagebox.showwarning("Upload failed", str(exc) + hint)

    def verify_remote_dir(self, remote_dir=None):
        if not self.ensure_connected():
            return
        remote_dir = remote_dir or self.remote_path.get().strip()
        if not remote_dir:
            messagebox.showwarning("Verify remote directory", "Current remote directory is empty.")
            return
        try:
            remote_dir = str(remote_dir).replace(chr(92), "/")
            exit_code, out, err, final_command = self.ssh_manager.run_remote_command(
                (
                    "echo HOSTNAME=$(hostname) && "
                    "echo USER=$(whoami) && "
                    "echo PWD=$(pwd) && "
                    "echo REALPATH=$(realpath . 2>/dev/null || pwd) && "
                    "echo SHELL=$SHELL && "
                    "echo HOME=$HOME && "
                    "df -h . && "
                    "(mount | grep ' on /home ' || true) && "
                    "(test -f /.dockerenv && echo DOCKER_CONTAINER=YES || echo DOCKER_CONTAINER=NO) && "
                    "ls -lah"
                ),
                workdir=remote_dir,
            )
            self.log(f"Connection: {self.current_connection_label()}")
            self.log(f"Verify remote directory: {remote_dir}")
            self.log(f"$ {final_command}")
            text = (out + "\n" + err).strip()
            self.log(text or f"ls completed; exit code {exit_code}")
            if exit_code != 0:
                messagebox.showwarning("Remote directory verification failed", text or f"Exit code: {exit_code}")
        except Exception as exc:
            self.log(f"Remote directory verification failed: {exc}")
            messagebox.showwarning("Remote directory verification failed", str(exc))

    def download_selected(self):
        self.download_selected_to_results()

    def download_selected_to_results(self):
        self.download_selected_to_folder(Path(self.callbacks["get_result_dir"]()))

    def download_selected_to_folder(self, local_dir=None):
        if not self.ensure_connected():
            return
        items = self.selected_remote_items()
        if not items:
            messagebox.showwarning("Download remote file", "Select remote files or folders first.")
            return
        if local_dir is None:
            local_dir = file_dialogs.askdirectory(self.config_manager, "download", parent=self, title="Choose download directory", initialdir=str(self.callbacks["get_result_dir"]()))
        if not local_dir:
            return
        try:
            downloaded = []
            for item in items:
                if item["name"] == "..":
                    continue
                local_path = self.ssh_manager.download_path(item["path"], local_dir)
                downloaded.append(str(local_path))
                self.log(f"Downloaded: {item['path']} -> {local_path}")
            messagebox.showinfo("Download complete", f"Downloaded {len(downloaded)} items.")
        except Exception as exc:
            self.log(f"Download failed: {exc}")
            messagebox.showwarning("Download failed", str(exc))

    def download_results(self):
        if not self.ensure_connected():
            return
        remote_dir = self.remote_path.get().strip()
        initial_dir = Path(self.callbacks["get_result_dir"]())
        initial_dir.mkdir(parents=True, exist_ok=True)
        selected_dir = file_dialogs.askdirectory(
            self.config_manager, "download", parent=self,
            title="Choose where to save calculation results",
            initialdir=str(initial_dir),
            mustexist=False,
        )
        if not selected_dir:
            return
        local_dir = Path(selected_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        if self.config_manager is not None:
            self.config_manager.remember_dialog_path("download", local_dir, is_directory=True)
        try:
            found = self.ssh_manager.find_remote_files(remote_dir, RESULT_PATTERNS)
            if not found:
                self.log("No standard calculation result files were found in this remote directory.")
                messagebox.showinfo("Download results", "No OUTCAR, OSZICAR, CONTCAR, vasp.out or Slurm output files were found.")
                return
            for remote_file in found:
                local_path = self.ssh_manager.download_file(remote_file, local_dir)
                self.log(f"Download results: {remote_file} -> {local_path}")
            messagebox.showinfo("Download results", f"Downloaded {len(found)} result files to: \n{local_dir}")
        except Exception as exc:
            self.log(f"Could not download results: {exc}")
            messagebox.showwarning("Could not download results", str(exc))

    def open_remote_in_windows(self):
        local_path = self.download_remote_file_to_edit_cache()
        if local_path:
            self.open_cached_file(local_path)

    def preview_remote_text_file(self, remote_path=None):
        items = self.selected_remote_items()
        if remote_path is None:
            if not items:
                return
            remote_path = items[0]["path"]
        try:
            text = self.ssh_manager.read_remote_text(remote_path)
        except Exception as exc:
            messagebox.showwarning("Preview failed", str(exc))
            return
        top = tk.Toplevel(self)
        top.title(f"Remote text preview - {posixpath.basename(remote_path)}")
        view = tk.Text(top, width=110, height=34, wrap="none")
        view.pack(fill="both", expand=True)
        view.insert("1.0", text)
        view.configure(state="disabled")

    def set_selected_as_submit_script(self):
        items = self.selected_remote_items()
        if not items or items[0]["kind"] == "dir":
            messagebox.showwarning("Set job script", "Select a remote script first.")
            return
        self.set_submit_script(items[0]["name"])

    def set_submit_script(self, script_name):
        self.submit_script.set(script_name)
        scheduler = self.scheduler.get()
        if scheduler == "PBS":
            self.submit_command.set(f"qsub {script_name}")
        elif scheduler == "LSF":
            self.submit_command.set(f"bsub < {script_name}")
        else:
            self.submit_command.set(f"sbatch {script_name}")
        self.save_submit_settings(show_message=False)
        self.log(f"Job script set: {script_name}")

    def auto_detect_submit_script(self, items):
        names = {item.name for item in items if not item.is_dir}
        for name in SCRIPT_CANDIDATES:
            if name in names:
                if not self.submit_script.get() or self.submit_script.get() in SCRIPT_CANDIDATES:
                    self.set_submit_script(name)
                return

    def update_command_preview(self):
        if not hasattr(self, "submit_command"):
            return
        if not self.ssh_manager:
            command = self.submit_command.get()
        else:
            command = self.ssh_manager.build_remote_command(
                self.submit_command.get(),
                self.remote_path.get().strip(),
                self.init_command.get().strip(),
                self.use_login_shell.get(),
            )
        self.command_preview.set("Final command preview: " + command)

    def save_submit_settings(self, show_message=True):
        config = self.callbacks["get_config"]()
        config["scheduler"] = self.scheduler.get()
        config["submit_script"] = self.submit_script.get().strip()
        config["slurm_script_name"] = self.submit_script.get().strip()
        config["submit_init_command"] = self.init_command.get().strip()
        config["submit_use_login_shell"] = self.use_login_shell.get()
        config.setdefault("slurm", {})["submit_command"] = self.submit_command.get().strip()
        self.callbacks["save_config"]()
        self.update_command_preview()
        if show_message:
            messagebox.showinfo("Submission settings", "Submission settings saved.")

    def test_submit_environment(self):
        if not self.ensure_connected():
            return
        config = self.callbacks["get_config"]()
        test_command = config.get("submit_test_command") or SLURM_DIAGNOSTIC_COMMAND
        try:
            exit_code, out, err, final_command = self.ssh_manager.run_remote_command(
                test_command,
                self.remote_path.get().strip(),
                self.init_command.get().strip(),
                self.use_login_shell.get(),
            )
            text = (out + "\n" + err).strip()
            self.log(f"$ {final_command}")
            self.log(text or "The test command returned no output.")
            error_type = classify_submit_error(err, out)
            if exit_code != 0 or error_type != "UNKNOWN":
                messagebox.showwarning(
                    submit_error_title(error_type),
                    submit_error_hint(error_type, self.submit_command.get().strip() or "sbatch Svasp.sh")
                    + "\n\nDiagnostic output: \n"
                    + text,
                )
            else:
                messagebox.showinfo("Slurm environment test", text or "Test passed.")
        except Exception as exc:
            messagebox.showwarning("Slurm environment test failed", str(exc))

    def run_end_to_end_acceptance(self):
        """Submit a tiny hostname job after explicit confirmation."""
        if not self.ensure_connected():
            return
        if not messagebox.askyesno(
            "End-to-end submission test",
            "This will submit a real hostname test job using one core for up to two minutes on the current Slurm server "
            "to verify sbatch, the queue and remote writes.\n\nContinue?",
        ):
            return
        remote_root = self.remote_path.get().strip() or self.home_path
        if not remote_root:
            messagebox.showwarning("End-to-end submission test", "Open a writable remote directory first.")
            return
        acceptance_dir = posixpath.join(remote_root.rstrip("/"), ".iface_acceptance")
        try:
            self.ssh_manager.ensure_remote_dir(acceptance_dir)
            marker = "iface-acceptance-ok"
            write_command = (
                f"printf %s {shlex.quote(marker)} > .write_test && "
                f"test \"$(cat .write_test)\" = {shlex.quote(marker)} && rm -f .write_test"
            )
            write_code, write_out, write_err, final_write = (
                self.ssh_manager.run_remote_command(
                    write_command,
                    acceptance_dir,
                    self.init_command.get().strip(),
                    self.use_login_shell.get(),
                )
            )
            self.log(f"$ {final_write}")
            if write_code != 0:
                raise RuntimeError(
                    write_err.strip() or write_out.strip() or "Remote directory write test failed"
                )
            output_template = posixpath.join(
                acceptance_dir, "slurm-acceptance-%j.out"
            )
            submit_command = (
                "sbatch --parsable --job-name=iface-acceptance "
                "--nodes=1 --ntasks=1 --time=00:02:00 "
                f"--output={shlex.quote(output_template)} "
                "--wrap='hostname && date && echo IFACE_SLURM_OK'"
            )
            code, out, err, final_command = self.ssh_manager.run_remote_command(
                submit_command,
                acceptance_dir,
                self.init_command.get().strip(),
                self.use_login_shell.get(),
            )
            combined = (out + "\n" + err).strip()
            self.log(f"$ {final_command}")
            self.log(combined or "The submission command returned no output.")
            if code != 0:
                error_type = classify_submit_error(err, out)
                raise RuntimeError(
                    submit_error_title(error_type)
                    + ": "
                    + submit_error_hint(error_type, submit_command)
                    + "\n\n"
                    + combined
                )
            match = re.search(r"\b(\d+)(?:;[^\s]+)?\b", combined)
            if not match:
                raise RuntimeError("sbatch returned, but no JobID was recognized: " + combined)
            job_id = match.group(1)
            query_command = (
                f"(squeue -h -j {job_id} -o '%i|%j|%T|%M|%R') "
                f"|| (/opt/slurm/bin/squeue -h -j {job_id} -o '%i|%j|%T|%M|%R')"
            )
            query_code, query_out, query_err, _query_final = (
                self.ssh_manager.run_remote_command(
                    query_command,
                    acceptance_dir,
                    self.init_command.get().strip(),
                    self.use_login_shell.get(),
                )
            )
            if query_code == 0 and query_out.strip():
                self.log("Test job queue status: " + query_out.strip())
            elif query_err.strip():
                self.log("Job submitted; the initial queue query reported: " + query_err.strip())
            messagebox.showinfo(
                "Submission checks complete; waiting for job results",
                f"Remote write succeeded; Slurm accepted the test job.\n"
                f"JobID: {job_id}\n"
                f"Results directory: {acceptance_dir}\n\n"
                "Verify the final state is COMPLETED, ExitCode is 0:0 and output contains "
                "IFACE_SLURM_OK to complete Slurm acceptance. This test does not validate VASP.",
            )
        except Exception as exc:
            self.log(f"End-to-end submission test failed: {exc}")
            messagebox.showerror("End-to-end submission test failed", str(exc))

    def submit_task(self):
        if not self.ensure_connected():
            return
        remote_path = self.remote_path.get().strip()
        command = self.submit_command.get().strip()
        if not remote_path:
            messagebox.showwarning("Submit task", "Current remote path is empty.")
            return
        if not command:
            messagebox.showwarning("Submit task", "Submission command cannot be empty.")
            return
        self.save_submit_settings(show_message=False)
        try:
            config = self.callbacks["get_config"]()
            job_name = str(
                config.get("slurm", {}).get(
                    "job_name",
                    self.callbacks.get("get_current_task_name", lambda: "iface")(),
                )
            ).strip()
            submitter = ReliableSlurmSubmitter(
                self.ssh_manager,
                remote_path,
                self.init_command.get().strip(),
                self.use_login_shell.get(),
                getattr(self.ssh_manager, "username", ""),
            )
            job_id, text, final_command = submitter.submit(
                command,
                config.get("submit_script", "Svasp.sh"),
                job_name,
            )
            self.log(f"$ {final_command}")
            self.log(text)
            self.callbacks["set_current_job_id"](job_id)
            messagebox.showinfo("Submission successful", f"JobID = {job_id}\n\n{text}")
        except SubmissionOutcomeUnknown as exc:
            self.log(str(exc))
            messagebox.showwarning(
                "Remote submission state unknown",
                f"{exc}\n\nThe application will not resubmit automatically. Query the queue first, "
                "or reconcile using squeue/sacct in Task Center.",
            )
        except Exception as exc:
            self.log(str(exc))
            messagebox.showwarning("Submission failed", str(exc))

    def query_queue(self):
        if not self.ensure_connected():
            return
        config = self.callbacks["get_config"]()
        command = config.get("slurm", {}).get("query_command", "squeue -u {username}").format(username=self.ssh_manager.username)
        try:
            exit_code, out, err, final_command = self.ssh_manager.run_remote_command(
                command,
                self.remote_path.get().strip(),
                self.init_command.get().strip(),
                self.use_login_shell.get(),
            )
            self.log(f"$ {final_command}")
            self.log((out + "\n" + err).strip() or f"Query complete; exit code {exit_code}")
        except Exception as exc:
            messagebox.showwarning("Queue query failed", str(exc))

    def delete_remote_selected(self):
        if not self.ensure_connected():
            return
        items = [item for item in self.selected_remote_items() if item["name"] != ".."]
        if not items:
            return
        if not messagebox.askyesno("Delete remote files", "Delete the selected remote files or empty folders?"):
            return
        try:
            for item in items:
                if item["kind"] == "dir":
                    self.ssh_manager.sftp.rmdir(item["path"])
                else:
                    self.ssh_manager.sftp.remove(item["path"])
                self.log(f"Deleted remote item: {item['path']}")
            self.refresh()
        except Exception as exc:
            messagebox.showwarning("Deletion failed", str(exc))

    def show_remote_menu(self, event):
        row = self.table.identify_row(event.y)
        if row:
            self.table.selection_set(row)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Download to project results", command=self.download_selected_to_results)
        menu.add_command(label="Download to selected folder", command=lambda: self.download_selected_to_folder(None))
        menu.add_command(label="Download locally", command=self.download_remote_selected_to_cache)
        menu.add_command(label="Open with default application", command=self.open_remote_in_windows)
        menu.add_command(label="Edit with custom editor", command=self.open_remote_in_notepadpp)
        menu.add_command(label="Edit with default editor", command=self.open_remote_in_notepad)
        menu.add_command(label="Save and upload back", command=self.upload_edited_file_back)
        menu.add_command(label="Text preview", command=self.preview_remote_text_file)
        menu.add_command(label="Copy remote path", command=self.copy_remote_path)
        menu.add_command(label="Use as job script", command=self.set_selected_as_submit_script)
        menu.add_separator()
        menu.add_command(label="Delete remote files", command=self.delete_remote_selected)
        menu.add_command(label="Refresh remote directory", command=self.refresh)
        menu.tk_popup(event.x_root, event.y_root)

    def copy_remote_path(self):
        items = self.selected_remote_items()
        if not items:
            return
        self.clipboard_clear()
        self.clipboard_append(items[0]["path"])
        self.log(f"Copied remote path: {items[0]['path']}")

    def copy_current_remote_path(self):
        remote_dir = self.remote_path.get().strip()
        if not remote_dir:
            messagebox.showwarning("Copy current remote path", "Current remote path is empty.")
            return
        self.clipboard_clear()
        self.clipboard_append(remote_dir)
        self.log(f"Copied current remote path. Run in an SSH terminal: cd {remote_dir}")

    def copy_submit_troubleshooting_commands(self):
        remote_dir = self.remote_path.get().strip()
        if not remote_dir:
            messagebox.showwarning("Copy diagnostic commands", "Current remote path is empty.")
            return
        command_text = troubleshooting_commands(remote_dir, self.submit_command.get().strip() or "sbatch Svasp.sh")
        self.clipboard_clear()
        self.clipboard_append(command_text)
        self.log("Copied Slurm diagnostic commands. Paste them into an SSH terminal: ")
        self.log(command_text)

    def format_size(self, size):
        try:
            size = float(size)
        except (TypeError, ValueError):
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def log(self, message):
        self.append_upload_log(str(message))
        try:
            if not hasattr(self, "log_text") or not self.log_text.winfo_exists():
                return
            stamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{stamp}] {message}\n")
            self.log_text.see("end")
        except tk.TclError:
            return
