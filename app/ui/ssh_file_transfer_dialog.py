import os
import posixpath
import re
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from app.core.ssh_client import SSHClientManager, STANDARD_VASP_FILES
from app.core.platform_utils import open_path, open_ssh_terminal
from app.ui import file_dialogs
from app.ui.responsive_rows import WrappingRow
from app.ui.theme import BG, PANEL


TEXT = {
    "zh_CN": {
        "title": "SSH connection and file transfer",
        "basic": "Basic SSH settings",
        "host": "Remote host",
        "username": "Username",
        "password": "Password",
        "port": "Port",
        "test": "Test connection",
        "connect": "Connect",
        "disconnect": "Disconnect",
        "history": "Connection history",
        "remember_password": "Remember password",
        "auto_connect": "Reconnect to the last server automatically",
        "local_files": "Local files",
        "remote_files": "Remote server",
        "local_path": "Current local directory",
        "remote_path": "Current remote directory",
        "open_local": "Open local directory",
        "refresh": "Refresh",
        "up": "Parent directory",
        "new_folder": "New folder",
        "delete": "Delete",
        "choose_task": "Select current task directory",
        "enter": "Go",
        "upload": "Upload →",
        "download": "← Download",
        "sync_task": "Sync current task",
        "log": "Connection log",
        "slurm": "Slurm actions",
        "script": "Job script",
        "submit_cmd": "Submission command",
        "query_cmd": "Queue command",
        "cancel_cmd": "Cancellation command",
        "submit_job": "Submit task",
        "query_queue": "Query queue",
        "cancel_job": "Cancel task",
        "mobaxterm": "SSH terminal",
    },
    "en_US": {
        "title": "SSH Connection And File Transfer",
        "basic": "Basic SSH Settings",
        "host": "Remote host",
        "username": "Username",
        "password": "Password",
        "port": "Port",
        "test": "Test Connection",
        "connect": "Connect",
        "disconnect": "Disconnect",
        "history": "Connection History",
        "remember_password": "Remember password",
        "auto_connect": "Auto connect last server",
        "local_files": "Local Files",
        "remote_files": "Remote Files",
        "local_path": "Current Local Path",
        "remote_path": "Current Remote Path",
        "open_local": "Open Local Folder",
        "refresh": "Refresh",
        "up": "Up",
        "new_folder": "New Folder",
        "delete": "Delete",
        "choose_task": "Choose Task Folder",
        "enter": "Enter",
        "upload": "Upload →",
        "download": "← Download",
        "sync_task": "Sync Current Task",
        "log": "Connection Log",
        "slurm": "Slurm Actions",
        "script": "Script",
        "submit_cmd": "Submit Command",
        "query_cmd": "Query Command",
        "cancel_cmd": "Cancel Command",
        "submit_job": "Submit Job",
        "query_queue": "Query Queue",
        "cancel_job": "Cancel Job",
        "mobaxterm": "SSH terminal",
    },
}


class SSHFileTransferDialog(tk.Toplevel):
    def __init__(self, master, config, config_manager, local_task_dir):
        super().__init__(master)
        self.config_data = config
        self.config_manager = config_manager
        self.lang = config.get("language", "en_US")
        self.text = TEXT.get(self.lang, TEXT["en_US"])
        self.client = SSHClientManager()
        self.local_dir = Path(local_task_dir)
        self.remote_dir = tk.StringVar(value=self._default_remote_dir())
        self.connected = False

        self.title(self.text["title"])
        self.geometry("1120x760")
        self.minsize(980, 640)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.refresh_local()
        self._load_history()

    def t(self, key):
        return self.text[key]

    def _default_remote_dir(self):
        user = self.config_data.get("servers", [{}])[0].get("username", "user") if self.config_data.get("servers") else "user"
        return f"/home/{user}/vasp_projects/{self.local_dir.name}"

    def _build(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        self._build_basic(outer)
        self._build_browsers(outer)
        self._build_bottom(outer)

    def _build_basic(self, parent):
        basic = ttk.LabelFrame(parent, text=self.t("basic"), padding=8)
        basic.grid(row=0, column=0, sticky="ew")
        for col in (1, 3, 5, 7):
            basic.columnconfigure(col, weight=1)

        self.host = tk.StringVar(value="")
        self.username = tk.StringVar(value="")
        self.password = tk.StringVar(value="")
        self.port = tk.StringVar(value="22")
        self.remember_password = tk.BooleanVar(value=False)
        self.auto_connect = tk.BooleanVar(value=False)

        fields = [(self.t("host"), self.host), (self.t("username"), self.username), (self.t("password"), self.password), (self.t("port"), self.port)]
        for i, (label, var) in enumerate(fields):
            ttk.Label(basic, text=label).grid(row=0, column=i * 2, sticky="w", padx=(0, 4), pady=3)
            show = "•" if var is self.password else ""
            ttk.Entry(basic, textvariable=var, show=show, width=18).grid(row=0, column=i * 2 + 1, sticky="ew", padx=(0, 8), pady=3)

        ttk.Checkbutton(basic, text=self.t("remember_password"), variable=self.remember_password).grid(row=1, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(basic, text=self.t("auto_connect"), variable=self.auto_connect).grid(row=1, column=2, columnspan=2, sticky="w", pady=3)
        ttk.Button(basic, text=self.t("test"), command=self.test_connection).grid(row=1, column=4, sticky="ew", padx=3)
        ttk.Button(basic, text=self.t("connect"), command=self.connect).grid(row=1, column=5, sticky="ew", padx=3)
        ttk.Button(basic, text=self.t("disconnect"), command=self.disconnect).grid(row=1, column=6, sticky="ew", padx=3)
        ttk.Button(basic, text=self.t("mobaxterm"), command=self.open_mobaxterm).grid(row=1, column=7, sticky="ew", padx=3)

        ttk.Label(basic, text=self.t("history")).grid(row=2, column=0, sticky="w", pady=(8, 2))
        self.history = ttk.Treeview(basic, columns=("host", "user", "port"), show="headings", height=3)
        for col, title in [("host", "Host"), ("user", "User"), ("port", "Port")]:
            self.history.heading(col, text=title)
            self.history.column(col, width=130)
        self.history.grid(row=3, column=0, columnspan=8, sticky="ew")
        self.history.bind("<<TreeviewSelect>>", self._select_history)

    def _build_browsers(self, parent):
        panes = ttk.Frame(parent)
        panes.grid(row=1, column=0, sticky="nsew", pady=8)
        panes.columnconfigure(0, weight=1, uniform="browser")
        panes.columnconfigure(2, weight=1, uniform="browser")
        panes.rowconfigure(0, weight=1)
        self._build_local_panel(panes).grid(row=0, column=0, sticky="nsew")
        self._build_transfer_buttons(panes).grid(row=0, column=1, sticky="ns", padx=8)
        self._build_remote_panel(panes).grid(row=0, column=2, sticky="nsew")

    def _build_local_panel(self, parent):
        panel = ttk.LabelFrame(parent, text=self.t("local_files"), padding=8)
        panel.rowconfigure(2, weight=1)
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text=self.t("local_path")).grid(row=0, column=0, sticky="w")
        self.local_path = tk.StringVar(value=str(self.local_dir))
        ttk.Entry(panel, textvariable=self.local_path).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(panel, text=self.t("enter"), command=self.enter_local_path).grid(row=0, column=2)
        local_buttons = WrappingRow(panel)
        local_buttons.grid(row=1, column=0, columnspan=3, sticky="ew", pady=5)
        for text, command in [
            (self.t("open_local"), self.open_local_folder),
            (self.t("refresh"), self.refresh_local),
            (self.t("up"), self.local_up),
            (self.t("new_folder"), self.new_local_folder),
            (self.t("delete"), self.delete_local),
            (self.t("choose_task"), self.choose_local_task),
        ]:
            local_buttons.add(ttk.Button(local_buttons, text=text, width=max(4, len(text)), command=command))
        self.local_table = ttk.Treeview(panel, columns=("size", "mtime", "type"), show="tree headings")
        self.local_table.heading("#0", text="Filename")
        self.local_table.column("#0", width=140, minwidth=100)
        for col, text in [("size", "Size"), ("mtime", "Modified"), ("type", "Type")]:
            self.local_table.heading(col, text=text)
            self.local_table.column(col, width={"size": 65, "mtime": 135, "type": 75}[col], stretch=False)
        self.local_table.grid(row=2, column=0, columnspan=3, sticky="nsew")
        local_vertical = ttk.Scrollbar(panel, orient="vertical", command=self.local_table.yview)
        local_vertical.grid(row=2, column=3, sticky="ns")
        local_horizontal = ttk.Scrollbar(panel, orient="horizontal", command=self.local_table.xview)
        local_horizontal.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.local_table.configure(yscrollcommand=local_vertical.set, xscrollcommand=local_horizontal.set)
        self.local_table.bind("<Double-1>", self.local_double_click)
        return panel

    def _build_transfer_buttons(self, parent):
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=8)
        ttk.Button(frame, text=self.t("upload"), command=self.upload_selected).pack(fill="x", pady=(80, 8))
        ttk.Button(frame, text=self.t("download"), command=self.download_selected).pack(fill="x", pady=8)
        ttk.Button(frame, text=self.t("sync_task"), style="Primary.TButton", command=self.sync_current_task).pack(fill="x", pady=8)
        return frame

    def _build_remote_panel(self, parent):
        panel = ttk.LabelFrame(parent, text=self.t("remote_files"), padding=8)
        panel.rowconfigure(2, weight=1)
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text=self.t("remote_path")).grid(row=0, column=0, sticky="w")
        ttk.Entry(panel, textvariable=self.remote_dir).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(panel, text=self.t("enter"), command=self.refresh_remote).grid(row=0, column=2)
        remote_buttons = WrappingRow(panel)
        remote_buttons.grid(row=1, column=0, columnspan=3, sticky="ew", pady=5)
        for text, command in [
            (self.t("refresh"), self.refresh_remote),
            (self.t("up"), self.remote_up),
            (self.t("new_folder"), self.new_remote_folder),
            (self.t("delete"), self.delete_remote),
            (self.t("download"), self.download_selected),
        ]:
            remote_buttons.add(ttk.Button(remote_buttons, text=text, width=max(4, len(text)), command=command))
        self.remote_table = ttk.Treeview(panel, columns=("size", "mtime", "mode", "type"), show="tree headings")
        self.remote_table.heading("#0", text="Filename")
        self.remote_table.column("#0", width=140, minwidth=100)
        for col, text in [("size", "Size"), ("mtime", "Modified"), ("mode", "Permissions"), ("type", "Type")]:
            self.remote_table.heading(col, text=text)
            self.remote_table.column(col, width={"size": 65, "mtime": 135, "mode": 110, "type": 75}[col], stretch=False)
        self.remote_table.grid(row=2, column=0, columnspan=3, sticky="nsew")
        remote_vertical = ttk.Scrollbar(panel, orient="vertical", command=self.remote_table.yview)
        remote_vertical.grid(row=2, column=3, sticky="ns")
        remote_horizontal = ttk.Scrollbar(panel, orient="horizontal", command=self.remote_table.xview)
        remote_horizontal.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.remote_table.configure(yscrollcommand=remote_vertical.set, xscrollcommand=remote_horizontal.set)
        self.remote_table.bind("<Double-1>", self.remote_double_click)
        return panel

    def _build_bottom(self, parent):
        bottom = ttk.Frame(parent)
        bottom.grid(row=2, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        log_panel = ttk.LabelFrame(bottom, text=self.t("log"), padding=6)
        log_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.log = tk.Text(log_panel, height=8, wrap="word")
        self.log.pack(fill="both", expand=True)
        slurm = ttk.LabelFrame(bottom, text=self.t("slurm"), padding=6)
        slurm.grid(row=0, column=1, sticky="nsew")
        slurm.columnconfigure(1, weight=1)
        slurm_config = self.config_data.get("slurm", {})
        self.slurm_script = tk.StringVar(value=self.config_data.get("submit_script", self.config_data.get("slurm_script_name", "Svasp.sh")))
        self.submit_command = tk.StringVar(value=slurm_config.get("submit_command", "sbatch Svasp.sh"))
        self.query_command = tk.StringVar(value=slurm_config.get("query_command", "squeue -u {username}"))
        self.cancel_command = tk.StringVar(value=slurm_config.get("cancel_command", "scancel {job_id}"))
        for row, (label, var) in enumerate([(self.t("script"), self.slurm_script), (self.t("submit_cmd"), self.submit_command), (self.t("query_cmd"), self.query_command), (self.t("cancel_cmd"), self.cancel_command)]):
            ttk.Label(slurm, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(slurm, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
        row = ttk.Frame(slurm)
        row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(row, text=self.t("submit_job"), command=self.submit_slurm).pack(side="left", padx=2)
        ttk.Button(row, text=self.t("query_queue"), command=self.query_queue).pack(side="left", padx=2)
        ttk.Button(row, text=self.t("cancel_job"), command=self.cancel_job).pack(side="left", padx=2)

    def add_log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")

    def _load_history(self):
        self.history.delete(*self.history.get_children())
        for item in self.config_data.get("servers", []):
            self.history.insert("", "end", values=(item.get("host", ""), item.get("username", ""), item.get("port", 22)))

    def _select_history(self, _event=None):
        selected = self.history.selection()
        if not selected:
            return
        host, user, port = self.history.item(selected[0], "values")
        self.host.set(host)
        self.username.set(user)
        self.port.set(port)
        self.remote_dir.set(f"/home/{user}/vasp_projects/{self.local_dir.name}")

    def _save_history(self):
        servers = [item for item in self.config_data.get("servers", []) if item.get("host") != self.host.get() or item.get("username") != self.username.get()]
        servers.insert(0, {"name": self.host.get(), "host": self.host.get(), "username": self.username.get(), "port": int(self.port.get()), "remote_root": self.remote_dir.get()})
        self.config_data["servers"] = servers[:10]
        self.config_manager.save()
        self._load_history()

    def test_connection(self):
        try:
            self._connect_core(close_after=True)
            messagebox.showinfo(self.t("test"), "Connection test passed")
        except Exception as exc:
            self.add_log(str(exc))
            messagebox.showerror(self.t("test"), str(exc))

    def connect(self):
        try:
            self._connect_core(close_after=False)
            self.connected = True
            self._save_history()
            self.refresh_remote()
        except Exception as exc:
            self.add_log(str(exc))
            messagebox.showerror(self.t("connect"), str(exc))

    def _connect_core(self, close_after=False):
        self.add_log(f"Connecting to {self.host.get()}:{self.port.get()}")
        output = self.client.connect(self.host.get().strip(), self.port.get().strip(), self.username.get().strip(), self.password.get())
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        self.add_log("Validating username and password")
        self.add_log("Connected")
        if len(lines) >= 3:
            self.add_log(f"Current user: {lines[-2]}")
            self.add_log(f"Current remote directory: {lines[-1]}")
            if self.remote_dir.get().endswith("/user/vasp_projects/" + self.local_dir.name):
                self.remote_dir.set(f"/home/{lines[-2]}/vasp_projects/{self.local_dir.name}")
        if close_after:
            self.client.close()

    def disconnect(self):
        self.client.close()
        self.connected = False
        self.add_log("Disconnected")

    def refresh_local(self):
        self.local_table.delete(*self.local_table.get_children())
        path = Path(self.local_path.get())
        if not path.exists():
            self.add_log(f"Local directory does not exist: {path}")
            return
        self.local_dir = path
        for item in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            item_type = "Directory" if item.is_dir() else "File"
            size = "" if item.is_dir() else str(item.stat().st_size)
            mtime = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            self.local_table.insert("", "end", text=item.name, values=(size, mtime, item_type))

    def refresh_remote(self):
        if not self.client.sftp:
            self.add_log("SFTP is disconnected. Connect to the server first.")
            return
        self.remote_table.delete(*self.remote_table.get_children())
        try:
            for item in self.client.list_remote_dir(self.remote_dir.get()):
                self.remote_table.insert("", "end", text=item["name"], values=(item["size"], item["mtime"], item["mode"], item["type"]))
            self.add_log(f"Current remote directory: {self.remote_dir.get()}")
        except OSError:
            if messagebox.askyesno(self.t("remote_files"), "Remote directory does not exist. Create it?"):
                self.client.ensure_remote_dir(self.remote_dir.get())
                self.refresh_remote()

    def enter_local_path(self):
        self.refresh_local()

    def local_double_click(self, _event=None):
        selected = self.local_table.selection()
        if not selected:
            return
        path = self.local_dir / self.local_table.item(selected[0], "text")
        if path.is_dir():
            self.local_path.set(str(path))
            self.refresh_local()

    def remote_double_click(self, _event=None):
        selected = self.remote_table.selection()
        if not selected:
            return
        name = self.remote_table.item(selected[0], "text")
        values = self.remote_table.item(selected[0], "values")
        if values and values[-1] == "Folder":
            self.remote_dir.set(posixpath.join(self.remote_dir.get(), name))
            self.refresh_remote()

    def open_local_folder(self):
        open_path(self.local_dir)

    def choose_local_task(self):
        path = file_dialogs.askdirectory(self.config_manager, "task", parent=self, initialdir=str(self.local_dir), title=self.t("choose_task"))
        if path:
            self.local_path.set(path)
            self.refresh_local()

    def local_up(self):
        parent = self.local_dir.parent
        self.local_path.set(str(parent))
        self.refresh_local()

    def remote_up(self):
        path = self.remote_dir.get().rstrip("/")
        self.remote_dir.set(posixpath.dirname(path) or "/")
        self.refresh_remote()

    def new_local_folder(self):
        name = filedialog.asksaveasfilename(initialdir=str(self.local_dir), title=self.t("new_folder"))
        if name:
            Path(name).mkdir(parents=True, exist_ok=True)
            self.refresh_local()

    def new_remote_folder(self):
        name = simpledialog.askstring(self.t("new_folder"), self.t("new_folder"))
        if name:
            self.client.ensure_remote_dir(posixpath.join(self.remote_dir.get(), name))
            self.refresh_remote()

    def delete_local(self):
        selected = self.local_table.selection()
        for row in selected:
            path = self.local_dir / self.local_table.item(row, "text")
            if path.is_file() and messagebox.askyesno(self.t("delete"), str(path)):
                path.unlink()
        self.refresh_local()

    def delete_remote(self):
        selected = self.remote_table.selection()
        for row in selected:
            name = self.remote_table.item(row, "text")
            values = self.remote_table.item(row, "values")
            if messagebox.askyesno(self.t("delete"), name):
                remote_path = posixpath.join(self.remote_dir.get(), name)
                if values and values[-1] == "Folder":
                    self.client.sftp.rmdir(remote_path)
                else:
                    self.client.sftp.remove(remote_path)
        self.refresh_remote()

    def upload_selected(self):
        selected = self.local_table.selection()
        if not selected:
            self.add_log("Select local files to upload")
            return
        for row in selected:
            path = self.local_dir / self.local_table.item(row, "text")
            remotes = self.client.upload_path(path, self.remote_dir.get())
            self.add_log(f"Upload complete: {path.name} ({len(remotes)} files)")
        self.refresh_remote()

    def download_selected(self):
        selected = self.remote_table.selection()
        if not selected:
            self.add_log("Select remote files to download")
            return
        for row in selected:
            name = self.remote_table.item(row, "text")
            size = int(self.remote_table.item(row, "values")[0] or 0)
            if size > 200 * 1024 * 1024 and not messagebox.askyesno(self.t("download"), "This is a large file. Continue downloading?"):
                continue
            local = self.client.download_file(posixpath.join(self.remote_dir.get(), name), self.local_dir)
            self.add_log(f"Download complete: {name} -> {local}")
        self.refresh_local()

    def sync_current_task(self):
        missing = [name for name in STANDARD_VASP_FILES if not (self.local_dir / name).exists()]
        if missing and not messagebox.askyesno(self.t("sync_task"), f"Missing {', '.join(missing)}; continue uploading?"):
            return
        results = self.client.upload_current_vasp_task(self.local_dir, self.remote_dir.get())
        self.add_log("Current task upload complete: ")
        for name, status in results:
            self.add_log(f"{name}: {status}")
        self.refresh_remote()

    def submit_slurm(self):
        command = self.submit_command.get().strip()
        out, err = self.client.exec_command(f"cd {self.remote_dir.get()} && {command}")
        self.add_log(out or err)
        match = re.search(r"Submitted batch job\s+(\d+)", out)
        if match:
            self.add_log(f"Task submitted, JobID = {match.group(1)}")

    def query_queue(self):
        command = self.query_command.get().format(username=self.username.get())
        out, err = self.client.exec_command(command)
        self.add_log(out or err)

    def cancel_job(self):
        job_id = simpledialog.askstring(self.t("cancel_job"), "JobID")
        if not job_id:
            return
        command = self.cancel_command.get().format(job_id=job_id)
        out, err = self.client.exec_command(command)
        self.add_log(out or err or f"Executed: {command}")

    def open_mobaxterm(self):
        if sys.platform != "win32":
            try:
                open_ssh_terminal(self.host.get(), self.username.get(), self.port.get(),
                                  self.config_data.get("ssh_terminal_command") or None)
            except (OSError, ValueError, RuntimeError) as exc:
                messagebox.showerror(self.t("mobaxterm"), f"Could not launch external SSH terminal: {exc}")
            return
        path = self.config_data.get("mobaxterm_path", "")
        if not path:
            messagebox.showwarning(self.t("mobaxterm"), "No external SSH terminal is configured.")
            return
        try:
            subprocess.Popen([path, f"-newtab", f"ssh {self.username.get()}@{self.host.get()} -p {self.port.get()}"])
        except OSError as exc:
            messagebox.showerror(self.t("mobaxterm"), f"Could not launch external SSH terminal: {exc}")

    def close(self):
        self.client.close()
        self.destroy()
