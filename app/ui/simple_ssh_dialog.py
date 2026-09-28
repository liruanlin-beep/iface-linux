import posixpath
import re
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from app.core.paths import CONFIG_DIR
from app.core.slurm_diagnostics import classify_submit_error, submit_error_hint, submit_error_title, troubleshooting_commands
from app.core.ssh_client import SSHClientManager
from app.core.task_files import format_task_file_errors, standard_vasp_files, validate_task_files


class SimpleSSHDialog(tk.Toplevel):
    def __init__(self, master, config, config_manager, local_task_dir, project_name, task_name, on_connected=None, shared_client=None):
        super().__init__(master)
        self.title("SSH connection manager")
        width = min(1180, max(900, int(self.winfo_screenwidth() * 0.82)))
        height = min(760, max(620, int(self.winfo_screenheight() * 0.80)))
        self.geometry(f"{width}x{height}")
        self.minsize(min(900, width), min(620, height))
        self.config_data = config
        self.config_manager = config_manager
        self.local_task_dir = Path(local_task_dir)
        self.project_name = project_name
        self.task_name = task_name
        self.client = shared_client or SSHClientManager()
        self.on_connected = on_connected
        self.keep_client_open = shared_client is not None
        self.connected = bool(shared_client and shared_client.sftp)
        self.closed = False

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        self._build_history(outer)
        self._build_settings(outer)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_history(self, outer):
        left = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        ttk.Label(left, text="Connection history", style="Title.TLabel").pack(anchor="w")
        self.history = tk.Listbox(left, width=24, height=16)
        self.history.pack(fill="both", expand=True, pady=8)
        self.history.bind("<<ListboxSelect>>", self._load_selected)
        row = ttk.Frame(left, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Save", command=self.save_connection).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text="Delete", command=self.delete_selected).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._refresh_history()

    def _build_settings(self, outer):
        right = ttk.Frame(outer, style="Panel.TFrame", padding=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.rowconfigure(13, weight=3)
        right.rowconfigure(15, weight=1)

        ttk.Label(right, text="Connection settings", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.vars = {}
        fields = [
            ("Connection name", "cluster01"),
            ("Host", self.config_data.get("default_remote_host", "")),
            ("Port", str(self.config_data.get("default_remote_port", "22"))),
            ("Username", ""),
            ("Remote project directory", self.config_data.get("default_remote_root", "/home/user/vasp_projects")),
        ]
        for i, (label, default) in enumerate(fields, 1):
            ttk.Label(right, text=label, style="Panel.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=default)
            self.vars[label] = var
            ttk.Entry(right, textvariable=var).grid(row=i, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(right, text="Password", style="Panel.TLabel").grid(row=6, column=0, sticky="w", pady=4)
        self.password = tk.StringVar(value="")
        self.password_entry = ttk.Entry(right, textvariable=self.password, show="*")
        self.password_entry.grid(row=6, column=1, sticky="ew", pady=4)
        self.show_password = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Show", variable=self.show_password, command=self._toggle_password).grid(row=6, column=2, padx=(8, 0))

        self.remember = tk.BooleanVar(value=bool(self.config_data.get("save_password", False)))
        ttk.Checkbutton(right, text="Remember connection (password reused only on this machine)", variable=self.remember).grid(row=7, column=1, columnspan=2, sticky="w", pady=4)

        ttk.Label(right, text="Current local task directory", style="Panel.TLabel").grid(row=8, column=0, sticky="w", pady=(8, 2))
        ttk.Label(right, text=str(self.local_task_dir), style="Muted.TLabel", wraplength=520).grid(row=8, column=1, columnspan=2, sticky="w", pady=(8, 2))

        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        for column in range(5):
            buttons.columnconfigure(column, weight=1)
        for column, (text, command, style) in enumerate(
            (
                ("Test connection", self.test_connection, None),
                ("Connect", self.connect, "Primary.TButton"),
                ("Upload current task", self.upload_task, None),
                ("Submit task", self.submit_task, None),
                ("Upload and submit", self.upload_and_submit, "Success.TButton"),
            )
        ):
            options = {"text": text, "command": command}
            if style:
                options["style"] = style
            ttk.Button(buttons, **options).grid(
                row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0)
            )

        command_row = ttk.Frame(right, style="Panel.TFrame")
        command_row.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Label(command_row, text="Remote command: ", style="Panel.TLabel").pack(side="left")
        self.command_text = tk.StringVar(value=self.config_data.get("slurm", {}).get("submit_command", "sbatch Svasp.sh"))
        ttk.Entry(command_row, textvariable=self.command_text).pack(side="left", fill="x", expand=True)
        ttk.Button(command_row, text="Run command", command=self.execute_remote_command).pack(side="left", padx=(6, 0))

        ttk.Label(right, text="Remote file browser", style="Title.TLabel").grid(row=11, column=0, columnspan=3, sticky="w", pady=(2, 4))
        path_row = ttk.Frame(right, style="Panel.TFrame")
        path_row.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        ttk.Label(path_row, text="Remote path: ", style="Panel.TLabel").pack(side="left")
        self.remote_path = tk.StringVar(value="")
        ttk.Entry(path_row, textvariable=self.remote_path).pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="Go", command=self.remote_go).pack(side="left", padx=(6, 0))
        ttk.Button(path_row, text="Parent directory", command=self.remote_parent).pack(side="left", padx=(6, 0))
        ttk.Button(path_row, text="Refresh", command=self.remote_refresh).pack(side="left", padx=(6, 0))

        table_frame = ttk.Frame(right, style="Panel.TFrame")
        table_frame.grid(row=13, column=0, columnspan=3, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.remote_table = ttk.Treeview(
            table_frame,
            columns=("type", "size", "mtime", "permissions", "path"),
            show="tree headings",
            height=5,
        )
        self.remote_table.heading("#0", text="Name")
        for col, text, width in [
            ("type", "Type", 70),
            ("size", "Size", 80),
            ("mtime", "Modified", 140),
            ("permissions", "Mode", 90),
            ("path", "Path", 260),
        ]:
            self.remote_table.heading(col, text=text)
            self.remote_table.column(col, width=width, stretch=col == "path")
        self.remote_table.column("#0", width=180, stretch=True)
        self.remote_table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.remote_table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.remote_table.configure(yscrollcommand=scrollbar.set)
        self.remote_table.bind("<Double-1>", self.remote_double_click)

        ttk.Label(right, text="Command output / logs", style="Title.TLabel").grid(row=14, column=0, columnspan=3, sticky="nw", pady=(8, 0))
        self.log = tk.Text(right, height=4, wrap="word")
        self.log.grid(row=15, column=0, columnspan=3, sticky="nsew", pady=(4, 0))

    def _toggle_password(self):
        self.password_entry.configure(show="" if self.show_password.get() else "*")

    def _refresh_history(self):
        self.history.delete(0, "end")
        for item in self.config_data.get("servers", []):
            name = item.get("name", "server")
            host = item.get("host", "")
            username = item.get("username", "")
            port = item.get("port", 22)
            self.history.insert("end", f"{name}  {username}@{host}:{port}")

    def _load_selected(self, _event=None):
        selected = self.history.curselection()
        servers = self.config_data.get("servers", [])
        if not selected or selected[0] >= len(servers):
            return
        item = servers[selected[0]]
        mapping = {
            "Connection name": "name",
            "Host": "host",
            "Port": "port",
            "Username": "username",
            "Remote project directory": "remote_root",
        }
        for label, key in mapping.items():
            self.vars[label].set(str(item.get(key, "")))
        self.password.set(self._unprotect_password(item.get("password_enc", "")))

    def _values(self):
        return {
            "name": self.vars["Connection name"].get().strip() or "cluster",
            "host": self.vars["Host"].get().strip(),
            "port": self.vars["Port"].get().strip() or "22",
            "username": self.vars["Username"].get().strip(),
            "remote_root": self.vars["Remote project directory"].get().strip() or "/home/user/vasp_projects",
            "password": self.password.get(),
        }

    def save_connection(self):
        data = self._values()
        if not self.remember.get():
            data.pop("password", None)
        else:
            data["password_enc"] = self._protect_password(data.pop("password", ""))
        data.pop("password", None)
        servers = [item for item in self.config_data.get("servers", []) if item.get("name") != data["name"]]
        servers.insert(0, data)
        self.config_data["servers"] = servers[:20]
        self.config_manager.save()
        self._refresh_history()
        self.add_log("Connection saved.")

    def _secret_key_path(self):
        return CONFIG_DIR / "ssh_secret.key"

    def _fernet(self):
        from cryptography.fernet import Fernet

        path = self._secret_key_path()
        if not path.exists():
            path.write_bytes(Fernet.generate_key())
        return Fernet(path.read_bytes())

    def _protect_password(self, password):
        if not password:
            return ""
        try:
            return self._fernet().encrypt(password.encode("utf-8")).decode("ascii")
        except Exception:
            return ""

    def _unprotect_password(self, token):
        if not token:
            return ""
        try:
            return self._fernet().decrypt(token.encode("ascii")).decode("utf-8")
        except Exception:
            return ""

    def delete_selected(self):
        selected = self.history.curselection()
        if not selected:
            return
        servers = self.config_data.get("servers", [])
        if selected[0] < len(servers):
            servers.pop(selected[0])
            self.config_data["servers"] = servers
            self.config_manager.save()
            self._refresh_history()
            self.add_log("Selected connection removed.")

    def add_log(self, text):
        if self.closed:
            return
        try:
            if not hasattr(self, "log") or not self.log.winfo_exists():
                return
            stamp = datetime.now().strftime("%H:%M:%S")
            self.log.insert("end", f"[{stamp}] {text}\n")
            self.log.see("end")
            if self.winfo_exists():
                self.update_idletasks()
        except tk.TclError:
            return

    def remote_task_dir(self):
        data = self._values()
        root = data["remote_root"].rstrip("/")
        return posixpath.join(root, self.project_name, self.task_name)

    def test_connection(self):
        try:
            output = self._connect()
            self.add_log("Connection test passed: ")
            self.add_log(output.strip())
            messagebox.showinfo("SSH test", "Connected; remote SSH_OK command passed.")
        except Exception as exc:
            self.add_log(f"Connection test failed: {exc}")
            messagebox.showerror("SSH test failed", str(exc))

    def _connect(self):
        data = self._values()
        return self.client.connect(data["host"], data["port"], data["username"], data["password"])

    def _ensure_connected(self):
        if not self.connected:
            self.connect()
        if not self.connected:
            raise RuntimeError("SSH is disconnected")

    def upload_task(self):
        try:
            self._ensure_connected()
            script_name = self.config_data.get("submit_script") or self.config_data.get("slurm_script_name") or "Svasp.sh"
            required = standard_vasp_files(script_name)
            missing, empty = validate_task_files(self.local_task_dir, required)
            if missing or empty:
                messagebox.showwarning("Current task files are incomplete", format_task_file_errors(self.local_task_dir, missing, empty))
                return False
            remote_dir = self.remote_task_dir()
            results = self.client.upload_current_vasp_task(self.local_task_dir, remote_dir, required)
            self.add_log(f"Remote task directory: {remote_dir}")
            for name, status in results:
                self.add_log(f"{name}: {status}")
            missing = [name for name, status in results if status == "Missing"]
            if missing:
                messagebox.showwarning("Upload finished with missing files", "These files are missing and were not uploaded: \n" + "\n".join(missing))
                return False
            else:
                self.load_remote_dir(remote_dir, show_errors=False)
                messagebox.showinfo("Upload successful", "Current task files uploaded.")
                return True
        except Exception as exc:
            self.add_log(f"Upload failed: {exc}")
            messagebox.showerror("Upload failed", str(exc))
            return False

    def submit_task(self):
        try:
            self._ensure_connected()
            self.execute_remote_command()
        except Exception as exc:
            self.add_log(f"Submission failed: {exc}")
            messagebox.showerror("Submission failed", str(exc))

    def upload_and_submit(self):
        if self.upload_task():
            self.submit_task()

    def connect(self):
        try:
            output = self._connect()
            self.connected = True
            self.add_log("Connected to server.")
            self.add_log(output.strip())
            if self.client.remote_browser:
                self.client.remote_browser.log_callback = self.add_log
                self.add_log("SFTP opened successfully.")
            if self.remember.get():
                self.save_connection()
            self.load_initial_remote_dir()
            self.keep_client_open = True
            if self.on_connected and self.client.remote_browser:
                self.on_connected(self.client, self.client.remote_browser.current_path, self._current_remote_items())
        except Exception as exc:
            self.connected = False
            self.add_log(f"Connection failed: {exc}")
            messagebox.showerror("Connection failed", str(exc))

    def load_initial_remote_dir(self):
        data = self._values()
        candidates = [data.get("remote_root", "").strip()]
        try:
            if self.client.remote_browser:
                candidates.append(self.client.remote_browser.get_home_dir())
        except Exception as exc:
            self.add_log(f"Could not read remote home directory: {exc}")
        for path in candidates:
            if not path:
                continue
            if self.load_remote_dir(path, show_errors=False):
                return
        self.load_remote_dir(None, show_errors=True)

    def load_remote_dir(self, path=None, show_errors=True):
        if not self.client.remote_browser:
            if show_errors:
                messagebox.showwarning("Remote file browser", "SFTP is disconnected; remote files are unavailable.")
            return False
        old_path = self.client.remote_browser.current_path
        try:
            items = self.client.remote_browser.list_dir(path)
            self.refresh_remote_table(items)
            return True
        except Exception as exc:
            self.client.remote_browser.current_path = old_path
            self.add_log(str(exc))
            if show_errors:
                messagebox.showwarning("Could not read remote directory", str(exc))
            return False

    def refresh_remote_table(self, items):
        self.remote_table.delete(*self.remote_table.get_children())
        for item in items:
            name = ("📁 " if item.is_dir else "📄 ") + item.name
            size = "" if item.is_dir else self.format_size(item.size)
            self.remote_table.insert(
                "",
                "end",
                text=name,
                values=(item.type_name, size, item.mtime, item.permissions, item.path),
            )
        current = self.client.remote_browser.current_path if self.client.remote_browser else ""
        self.remote_path.set(current or "")
        self._last_remote_items = items

    def _current_remote_items(self):
        return getattr(self, "_last_remote_items", [])

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

    def remote_double_click(self, _event=None):
        selected = self.remote_table.selection()
        if not selected:
            return
        values = self.remote_table.item(selected[0], "values")
        if len(values) < 5:
            return
        if values[0] == "Folder":
            self.load_remote_dir(values[4])

    def remote_parent(self):
        if not self.client.remote_browser:
            messagebox.showwarning("Remote file browser", "SFTP is disconnected.")
            return
        old_path = self.client.remote_browser.current_path
        try:
            items = self.client.remote_browser.go_parent()
            self.refresh_remote_table(items)
        except Exception as exc:
            self.client.remote_browser.current_path = old_path
            self.add_log(str(exc))
            messagebox.showwarning("Could not navigate back", str(exc))

    def remote_refresh(self):
        self.load_remote_dir(self.remote_path.get().strip() or None)

    def remote_go(self):
        self.load_remote_dir(self.remote_path.get().strip() or None)

    def execute_remote_command(self):
        try:
            self._ensure_connected()
            command = self.command_text.get().strip() or "sbatch Svasp.sh"
            workdir = self.remote_path.get().strip() or self.remote_task_dir()
            init_command = self.config_data.get("submit_init_command", "")
            use_login_shell = self.config_data.get("submit_use_login_shell", True)
            exit_code, output, error, final_command = self.client.run_remote_command(
                command,
                workdir=workdir,
                init_command=init_command,
                use_login_shell=use_login_shell,
            )
            text = (output + "\n" + error).strip()
            self.add_log(f"Running command: {final_command}")
            self.add_log(text or "Command executed; the server returned no output.")
            if exit_code != 0:
                error_type = classify_submit_error(error, output)
                self.add_log(f"Submission error category: {error_type}")
                self.add_log("Copy these commands into an SSH terminal to test: ")
                self.add_log(troubleshooting_commands(workdir, command))
                messagebox.showwarning(
                    submit_error_title(error_type),
                    f"Exit code: {exit_code}\n\n{text}\n\n{submit_error_hint(error_type, command)}",
                )
                return
            match = re.search(r"Submitted batch job\s+(\d+)", text)
            if match:
                job_id = match.group(1)
                self.add_log(f"JobID: {job_id}")
                messagebox.showinfo("Submission successful", f"JobID = {job_id}")
            elif error.strip():
                messagebox.showwarning("Command completed with errors", error.strip())
            else:
                messagebox.showinfo("Command completed", output.strip() or "Command completed.")
            self.remote_refresh()
        except Exception as exc:
            self.add_log(f"Command failed: {exc}")
            messagebox.showerror("Command failed", str(exc))

    def close(self):
        self.closed = True
        if not self.keep_client_open:
            self.client.close()
        try:
            self.destroy()
        except tk.TclError:
            pass
