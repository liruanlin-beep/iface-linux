import os
from app.core.platform_utils import open_path
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from app.core.task_database import TaskDatabase, TaskState
from app.core.error_recovery import suggest_recovery
from app.core.submission_queue import SubmissionQueue
from app.core.vasp_progress import parse_vasp_progress_directory
from app.ui.theme import BG, BORDER, PANEL
from app.ui.window_geometry import bind_wraplength, fit_window_to_workarea


STATE_LABELS = {
    TaskState.LOCAL_WAITING.value: "Local waiting",
    TaskState.BLOCKED.value: "Waiting for dependencies",
    TaskState.READY.value: "Ready to submit",
    TaskState.VALIDATING.value: "Validating inputs",
    TaskState.UPLOADING.value: "Uploading with verification",
    TaskState.SUBMITTING.value: "Submitting",
    TaskState.UNKNOWN_REMOTE_STATE.value: "Remote state unknown",
    TaskState.PENDING.value: "Slurm pending",
    TaskState.RUNNING.value: "Running",
    TaskState.COMPLETING.value: "Completing",
    TaskState.COMPLETED.value: "Completed",
    TaskState.RETRY_WAIT.value: "Waiting to retry",
    TaskState.FAILED.value: "Failed",
    TaskState.CANCELLED.value: "Cancelled",
    TaskState.PAUSED.value: "Paused",
}


class TaskCenterWindow(tk.Toplevel):
    """Durable task monitor for local files and Slurm states."""

    def __init__(
        self,
        master,
        callbacks,
        max_inflight=10,
        poll_interval_seconds=15,
        automation_policy=None,
        stale_claim_seconds=900,
    ):
        super().__init__(master)
        self.callbacks = callbacks
        self.database = TaskDatabase()
        self.queue = SubmissionQueue(
            self.database,
            max_inflight=max_inflight,
            automation_policy=automation_policy,
            stale_claim_seconds=stale_claim_seconds,
        )
        self._after_id = None
        self._selected_task_id = ""
        self._queue_running = False
        self._queue_thread = None
        self._worker_messages = queue.Queue()
        self.remote_progress = {}
        self.poll_interval_ms = max(5000, int(poll_interval_seconds) * 1000)

        self.title("iface Task Center")
        fit_window_to_workarea(self, (1160, 720), (760, 500))
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.refresh_local()
        self._schedule_refresh()

    def _build(self):
        header = ttk.Frame(self, style="AppBar.TFrame", padding=(12, 8))
        header.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Label(header, text="Task Center", style="AppTitle.TLabel").pack(side="left")
        ttk.Label(header, text="Local workflows and remote Slurm status", style="AppSubtitle.TLabel").pack(
            side="left", padx=(14, 0))
        toolbar = ttk.Frame(self, style="Panel.TFrame", padding=8)
        toolbar.pack(fill="x", padx=10, pady=(0, 6))
        queue_actions = ttk.Frame(toolbar, style="Panel.TFrame")
        queue_actions.pack(fill="x")
        self.queue_button_text = tk.StringVar(value="Start automatic queue")
        ttk.Button(
            queue_actions,
            textvariable=self.queue_button_text,
            command=self.toggle_queue,
            style="Success.TButton",
        ).pack(side="left", padx=(0, 6))
        for text, command, style in [
            ("Add current task", self.add_current_task, "Primary.TButton"),
            ("Refresh local progress", self.refresh_local, "TButton"),
            ("Sync Slurm", self.sync_slurm, "TButton"),
        ]:
            ttk.Button(queue_actions, text=text, command=command, style=style).pack(side="left", padx=(0, 6))
        selected_actions = ttk.Frame(toolbar, style="Panel.TFrame")
        selected_actions.pack(fill="x", pady=(6, 0))
        ttk.Label(selected_actions, text="Selected task", style="Muted.TLabel").pack(side="left", padx=(0, 10))
        for text, command, style in [
            ("Recovery suggestion", self.show_recovery_suggestion, "TButton"),
            ("Pause/resume", self.toggle_pause, "TButton"),
            ("Cancel task", self.cancel_task, "Danger.TButton"),
            ("Remove record only", self.remove_record, "TButton"),
            ("Open task directory", self.open_task_directory, "TButton"),
        ]:
            ttk.Button(selected_actions, text=text, command=command, style=style).pack(side="left", padx=(0, 6))
        self.summary = tk.StringVar(value="Loading tasks…")
        footer = ttk.Frame(self, style="Status.TFrame", padding=(10, 5))
        footer.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        bind_wraplength(ttk.Label(footer, textvariable=self.summary, style="Status.TLabel")).pack(fill="x")

        panes = tk.PanedWindow(
            self,
            orient="vertical",
            sashwidth=6,
            sashrelief="flat",
            bd=0,
            bg=BORDER,
            showhandle=True,
            opaqueresize=True,
        )
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        table_frame = ttk.Frame(panes, style="Panel.TFrame", padding=6)
        columns = ("name", "type", "state", "job", "ionic", "electronic", "energy", "updated")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = [
            ("name", "Task name", 170),
            ("type", "Task type", 105),
            ("state", "Status", 100),
            ("job", "JobID", 90),
            ("ionic", "Ionic step", 90),
            ("electronic", "Electronic step", 90),
            ("energy", "Energy (eV)", 115),
            ("updated", "Updated", 160),
        ]
        for key, title, width in headings:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=70, stretch=key in {"name", "updated"})
        self.table.tag_configure("running", background="#e6f0ff")
        self.table.tag_configure("completed", background="#e7f7ef")
        self.table.tag_configure("failed", background="#fdecef")
        self.table.bind("<<TreeviewSelect>>", self._selection_changed)
        ybar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        xbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

        detail = ttk.Notebook(panes)
        overview = ttk.Frame(detail, style="Panel.TFrame", padding=10)
        history = ttk.Frame(detail, style="Panel.TFrame", padding=8)
        events = ttk.Frame(detail, style="Panel.TFrame", padding=8)
        detail.add(overview, text="Task details")
        detail.add(history, text="Electronic iterations")
        detail.add(events, text="Events and errors")

        self.detail_text = tk.Text(
            overview, wrap="word", height=8, relief="flat", bg=PANEL, padx=8, pady=8
        )
        detail_scroll = ttk.Scrollbar(overview, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side="right", fill="y")
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.configure(state="disabled")

        history_columns = ("step", "algorithm", "energy", "delta", "rms")
        self.history_table = ttk.Treeview(history, columns=history_columns, show="headings")
        for key, title, width in [
            ("step", "Electronic step", 80),
            ("algorithm", "Algorithm", 90),
            ("energy", "Electronic energy (eV)", 150),
            ("delta", "ΔE (eV)", 150),
            ("rms", "RMS", 120),
        ]:
            self.history_table.heading(key, text=title)
            self.history_table.column(key, width=width, stretch=key in {"energy", "delta"})
        history.rowconfigure(0, weight=1)
        history.columnconfigure(0, weight=1)
        history_y = ttk.Scrollbar(history, orient="vertical", command=self.history_table.yview)
        history_x = ttk.Scrollbar(history, orient="horizontal", command=self.history_table.xview)
        self.history_table.configure(yscrollcommand=history_y.set, xscrollcommand=history_x.set)
        self.history_table.grid(row=0, column=0, sticky="nsew")
        history_y.grid(row=0, column=1, sticky="ns")
        history_x.grid(row=1, column=0, sticky="ew")

        self.event_text = tk.Text(
            events, wrap="word", height=8, relief="flat", bg=PANEL, padx=8, pady=8
        )
        event_scroll = ttk.Scrollbar(events, orient="vertical", command=self.event_text.yview)
        self.event_text.configure(yscrollcommand=event_scroll.set)
        event_scroll.pack(side="right", fill="y")
        self.event_text.pack(fill="both", expand=True)
        self.event_text.configure(state="disabled")

        panes.add(table_frame, minsize=150, height=285, stretch="always")
        panes.add(detail, minsize=125, height=180, stretch="always")

    def add_current_task(self):
        current = self.callbacks["get_current_task"]()
        local_path = Path(current["local_path"])
        existing = self.database.find_task_by_local_path(local_path)
        if existing and existing.state not in {
            TaskState.COMPLETED.value,
            TaskState.FAILED.value,
            TaskState.CANCELLED.value,
        }:
            self._selected_task_id = existing.id
            self.refresh_local()
            messagebox.showinfo("Task Center", "The current task is already in Task Center.", parent=self)
            return
        job_id = str(current.get("slurm_job_id") or "")
        state = TaskState.PENDING.value if job_id else TaskState.LOCAL_WAITING.value
        task_id = self.database.add_task(
            name=current["name"],
            project_id=current["project_id"],
            task_type=current.get("task_type", "vasp"),
            local_path=local_path,
            remote_path=current.get("remote_path", ""),
            config=current.get("config", {}),
            max_retries=current.get("max_retries", 3),
            state=state,
        )
        if job_id:
            self.database.update_task(task_id, slurm_job_id=job_id)
        self._selected_task_id = task_id
        self.refresh_local()

    def refresh_local(self):
        selected = self._selected_task_id or self._selected_id()
        tasks = self.database.list_tasks()
        for task in tasks:
            if task.id in self.remote_progress:
                continue
            local_dir = Path(task.local_path)
            stored_progress = self.database.get_progress(task.id)
            has_local_result = (local_dir / "OSZICAR").is_file() or (
                local_dir / "OUTCAR"
            ).is_file()
            if stored_progress and not has_local_result:
                continue
            progress = parse_vasp_progress_directory(task.local_path).to_dict()
            self.database.update_progress(task.id, progress)
            if progress["finished"] and task.state in {
                TaskState.PENDING.value,
                TaskState.RUNNING.value,
                TaskState.COMPLETING.value,
            }:
                self.database.set_state(task.id, TaskState.COMPLETED, "Local OUTCAR indicates a normal VASP exit")
        self.database.refresh_dependency_states()
        tasks = self.database.list_tasks()
        self.table.delete(*self.table.get_children())
        counts = {}
        for task in tasks:
            progress = self.database.get_progress(task.id)
            counts[task.state] = counts.get(task.state, 0) + 1
            ionic = self._step_text(progress.get("ionic_step"), progress.get("max_ionic_steps"))
            electronic = self._step_text(
                progress.get("electronic_step"), progress.get("max_electronic_steps")
            )
            energy = progress.get("energy_ev")
            tag = ""
            if task.state == TaskState.RUNNING.value:
                tag = "running"
            elif task.state == TaskState.COMPLETED.value:
                tag = "completed"
            elif task.state == TaskState.FAILED.value:
                tag = "failed"
            self.table.insert(
                "",
                "end",
                iid=task.id,
                values=(
                    task.name,
                    task.task_type,
                    STATE_LABELS.get(task.state, task.state),
                    task.slurm_job_id or "-",
                    ionic,
                    electronic,
                    f"{energy:.8f}" if energy is not None else "-",
                    task.updated_at.replace("T", " ")[:19],
                ),
                tags=(tag,) if tag else (),
            )
        if selected and self.table.exists(selected):
            self.table.selection_set(selected)
            self.table.focus(selected)
            self._selected_task_id = selected
        self.summary.set(
            f"Total {len(tasks)} tasks · Running {counts.get(TaskState.RUNNING.value, 0)} · "
            f"Pending {counts.get(TaskState.PENDING.value, 0)} · "
            f"Ready locally {counts.get(TaskState.READY.value, 0)} / limit {self.queue.max_inflight}"
        )
        self._render_selection()

    def toggle_queue(self):
        self._queue_running = not self._queue_running
        self.queue_button_text.set("Stop automatic queue" if self._queue_running else "Start automatic queue")
        if self._queue_running:
            self.summary.set(
                f"Automatic queue started: at most {self.queue.max_inflight} jobs pending or running in Slurm."
            )
            self._start_queue_cycle()
        else:
            self.summary.set("Automatic queue stopped; submitted Slurm jobs remain active.")

    def _start_queue_cycle(self, force=False):
        if not self._queue_running and not force:
            return
        if self._queue_thread and self._queue_thread.is_alive():
            return
        self._queue_thread = threading.Thread(
            target=self._queue_worker,
            args=(self._queue_running,),
            daemon=True,
        )
        self._queue_thread.start()

    def _queue_worker(self, allow_dispatch):
        remote_progress = {}
        local_completed = 0
        local_failed = 0
        try:
            self.database.refresh_dependency_states()
            reconciled = 0
            unresolved = 0
            for task in self.database.list_tasks(
                states=[TaskState.UNKNOWN_REMOTE_STATE]
            ):
                job_id = self.callbacks["reconcile_unknown_task"](task)
                if job_id:
                    self.database.update_task(task.id, slurm_job_id=job_id)
                    self.database.set_state(
                        task.id,
                        TaskState.PENDING,
                        f"Reconciled with squeue/sacct, JobID={job_id}",
                    )
                    reconciled += 1
                else:
                    unresolved += 1
            if allow_dispatch:
                local_completed, local_failed = self._execute_ready_local_steps()
            rows = self.callbacks["query_slurm_background"]()
            by_job = {str(row[0]): row for row in rows}
            missing_inflight = []
            for task in self.database.list_tasks():
                if task.slurm_job_id and task.slurm_job_id in by_job:
                    self.queue.update_slurm_state(task.id, by_job[task.slurm_job_id][2])
                elif task.slurm_job_id and task.state in {
                    TaskState.PENDING.value,
                    TaskState.RUNNING.value,
                    TaskState.COMPLETING.value,
                }:
                    missing_inflight.append(task)
            if missing_inflight:
                finished_states = self.callbacks["query_finished_slurm_background"](
                    [task.slurm_job_id for task in missing_inflight]
                )
                for task in missing_inflight:
                    state = finished_states.get(task.slurm_job_id)
                    if state:
                        self.queue.update_slurm_state(task.id, state)
            for task in self.database.list_tasks(
                states=[
                    TaskState.PENDING,
                    TaskState.RUNNING,
                    TaskState.COMPLETING,
                ]
            ):
                if not task.slurm_job_id:
                    continue
                try:
                    progress = self.callbacks["read_remote_progress"](task)
                except Exception:
                    continue
                self.database.update_progress(task.id, progress.to_dict())
                remote_progress[task.id] = progress
            if allow_dispatch:
                result = self.queue.dispatch_once(
                    self.callbacks["submit_queued_task"],
                    server_active_count=len(rows),
                )
                message = (
                    f"Queue poll complete: active remote jobs {len(rows)}, available slots {result.available_slots}, "
                    f"Submitted {result.submitted}, failed/retry pending {result.failed}; "
                    f"Recovered stale claims {result.recovered_stale_claims}; "
                    f"Local steps completed {local_completed}, failed {local_failed}; "
                    f"Unknown tasks reconciled {reconciled}, unresolved {unresolved}."
                )
            else:
                message = (
                    f"Remote sync complete: active Slurm jobs {len(rows)}, "
                    f"Read {len(remote_progress)} tasks with electronic/ionic progress; "
                    f"Unknown tasks reconciled {reconciled}, unresolved {unresolved}."
                )
        except Exception as exc:
            local_text = (
                f"; Local steps completed {local_completed}, failed/waiting {local_failed}"
                if allow_dispatch
                else ""
            )
            message = f"Automatic queue waiting for the next cycle: {exc}{local_text}"
        self._worker_messages.put((message, remote_progress))

    def _execute_ready_local_steps(self):
        completed = 0
        failed = 0
        for task in self.database.claim_ready_local_tasks(limit=2):
            try:
                result_text = self.callbacks["execute_local_task"](task)
                self.database.set_state(
                    task.id,
                    TaskState.COMPLETED,
                    result_text or "Local workflow step completed",
                )
                completed += 1
            except Exception as exc:
                error = str(exc)
                normalized_error = error.casefold()
                transient = any(marker in normalized_error for marker in (
                    "disconnected", "not connected")) or (
                    "cannot download" in normalized_error and "server" in normalized_error)
                if transient:
                    self.database.set_state(
                        task.id,
                        TaskState.RETRY_WAIT,
                        "Local step will retry after SSH/SFTP connects",
                        error=error,
                    )
                else:
                    attempts = task.attempts + 1
                    self.database.update_task(task.id, attempts=attempts)
                    if attempts <= task.max_retries:
                        self.database.set_state(
                            task.id,
                            TaskState.RETRY_WAIT,
                            f"Local step failed; retrying ({attempts}/{task.max_retries})",
                            error=error,
                        )
                    else:
                        self.database.set_state(
                            task.id,
                            TaskState.FAILED,
                            "Local step failed; retry limit reached",
                            error=error,
                        )
                failed += 1
        self.database.refresh_dependency_states()
        return completed, failed

    def _queue_cycle_finished(self, message, remote_progress=None):
        if not self.winfo_exists():
            return
        self.remote_progress.update(remote_progress or {})
        self.refresh_local()
        self.summary.set(message)

    def sync_slurm(self):
        if self._queue_thread and self._queue_thread.is_alive():
            self.summary.set("Remote sync is running. Please wait.")
            return
        self.summary.set("Syncing Slurm status and remote electronic iterations…")
        self._start_queue_cycle(force=True)

    def show_recovery_suggestion(self):
        task = self._selected_task()
        if not task:
            return
        progress = self.remote_progress.get(task.id)
        if progress is None:
            progress = parse_vasp_progress_directory(task.local_path)
        incar_path = Path(task.local_path) / "INCAR"
        incar_text = (
            incar_path.read_text(encoding="utf-8", errors="ignore")
            if incar_path.is_file()
            else ""
        )
        plan = suggest_recovery(progress, incar_text)
        if plan is None:
            messagebox.showinfo(
                "Recovery suggestion",
                "No known error that can be handled safely was found in the current logs.\n"
                "Sync remote progress or inspect OUTCAR, OSZICAR and Slurm output manually.",
                parent=self,
            )
            return
        patch_text = "\n".join(
            f"{key}: {value}" for key, value in plan.incar_patch.items()
        ) or "No INCAR changes"
        delete_text = (
            "\nRemove remotely before restart: " + ", ".join(plan.remove_remote_files)
            if plan.remove_remote_files
            else ""
        )
        details = (
            f"{plan.title}\n\n{plan.explanation}\n\n"
            f"Proposed changes: \n{patch_text}\n"
            f"Restart from CONTCAR: {'Yes' if plan.restart_from_contcar else 'No'}"
            f"{delete_text}"
        )
        if plan.risk == "manual":
            messagebox.showwarning(
                "Manual action required",
                details + "\n\nThis error does not create an automatic retry.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Approve recovery plan",
            details
            + "\n\nAfter approval, the application saves a before snapshot and recovery.json, "
            "then updates the current task and returns it to the retry queue. Continue?",
            parent=self,
        ):
            return
        try:
            result = self.callbacks["apply_recovery_plan"](task, plan)
            self.database.update_task(task.id, slurm_job_id="")
            self.database.set_state(
                task.id,
                TaskState.RETRY_WAIT,
                result or "Recovery plan approved; waiting to resubmit",
            )
            self.refresh_local()
            messagebox.showinfo("Recovery plan applied", result, parent=self)
        except Exception as exc:
            messagebox.showerror("Could not apply recovery plan", str(exc), parent=self)

    def toggle_pause(self):
        task = self._selected_task()
        if not task:
            return
        if task.state == TaskState.PAUSED.value:
            self.database.set_state(task.id, TaskState.LOCAL_WAITING, "Task resumed in the local queue")
        elif task.state in {
            TaskState.LOCAL_WAITING.value,
            TaskState.BLOCKED.value,
            TaskState.READY.value,
            TaskState.RETRY_WAIT.value,
        }:
            self.database.set_state(task.id, TaskState.PAUSED, "Task paused")
        else:
            messagebox.showinfo(
                "Pause task",
                "Jobs submitted to Slurm cannot be paused locally. Use Cancel task to stop them.",
                parent=self,
            )
            return
        self.refresh_local()

    def cancel_task(self):
        task = self._selected_task()
        if not task:
            return
        if not messagebox.askyesno(
            "Cancel task",
            f"Cancel task “{task.name}”?\n"
            + (f"This will run scancel {task.slurm_job_id}." if task.slurm_job_id else "This task has not been submitted; only its local queue record will be cancelled."),
            parent=self,
        ):
            return
        try:
            if task.slurm_job_id:
                self.callbacks["cancel_slurm"](task.slurm_job_id)
            self.database.set_state(task.id, TaskState.CANCELLED, "Task cancelled by user")
            self.refresh_local()
        except Exception as exc:
            messagebox.showerror("Cancellation failed", str(exc), parent=self)

    def remove_record(self):
        task = self._selected_task()
        if not task:
            return
        if not messagebox.askyesno(
            "Remove record",
            f"Remove only the Task Center record for “{task.name}”.\nCalculation directories and server files will remain. Continue?",
            parent=self,
        ):
            return
        self.database.delete_task(task.id)
        self._selected_task_id = ""
        self.refresh_local()

    def open_task_directory(self):
        task = self._selected_task()
        if not task:
            return
        path = Path(task.local_path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            open_path(path)
        except OSError as exc:
            messagebox.showerror("Could not open directory", str(exc), parent=self)

    def _selection_changed(self, _event=None):
        self._selected_task_id = self._selected_id()
        self._render_selection()

    def _render_selection(self):
        task = self._selected_task()
        self.history_table.delete(*self.history_table.get_children())
        if not task:
            self._set_text(self.detail_text, "Select a task to view its details.")
            self._set_text(self.event_text, "")
            return
        progress = self.remote_progress.get(task.id) or parse_vasp_progress_directory(
            task.local_path
        )
        detail = [
            f"Task: {task.name}",
            f"Type: {task.task_type}",
            f"Status: {STATE_LABELS.get(task.state, task.state)}",
            f"JobID: {task.slurm_job_id or 'Not submitted'}",
            f"Local directory: {task.local_path}",
            f"Remote directory: {task.remote_path or 'Not set'}",
            f"Ionic step: {progress.ionic_step}/{progress.max_ionic_steps or '-'}",
            f"Current electronic step: {progress.electronic_step}/{progress.max_electronic_steps or '-'}",
            f"Total energy: {progress.energy_ev if progress.energy_ev is not None else '-'} eV",
            f"Maximum force: {progress.max_force_ev_a if progress.max_force_ev_a is not None else '-'} eV/Å",
            f"Automatic retries: {task.attempts}/{task.max_retries}",
        ]
        if task.last_error:
            detail.append(f"Last error: {task.last_error}")
        if progress.errors:
            detail.append("VASP diagnostics: " + "; ".join(item["message"] for item in progress.errors))
        self._set_text(self.detail_text, "\n".join(detail))
        for item in progress.electronic_history[-300:]:
            self.history_table.insert(
                "",
                "end",
                values=(
                    item["step"],
                    item["algorithm"],
                    f"{item['energy_ev']:.10g}",
                    f"{item['delta_e_ev']:.5e}",
                    f"{item['rms']:.5e}" if item["rms"] is not None else "-",
                ),
            )
        events = self.database.list_events(task.id)
        event_lines = [
            f"{item['created_at'].replace('T', ' ')[:19]} [{item['level']}] {item['message']}"
            for item in events
        ]
        self._set_text(self.event_text, "\n".join(event_lines))

    def _selected_id(self):
        selected = self.table.selection()
        return selected[0] if selected else ""

    def _selected_task(self):
        task_id = self._selected_id() or self._selected_task_id
        return self.database.get_task(task_id) if task_id else None

    @staticmethod
    def _set_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    @staticmethod
    def _step_text(current, maximum):
        current = int(current or 0)
        maximum = int(maximum or 0)
        return f"{current}/{maximum}" if maximum else str(current or "-")

    def _schedule_refresh(self):
        self._after_id = self.after(500, self._periodic_refresh)

    def _periodic_refresh(self):
        self._after_id = None
        if self.winfo_exists():
            while not self._worker_messages.empty():
                message, remote_progress = self._worker_messages.get_nowait()
                self._queue_cycle_finished(message, remote_progress)
            self.refresh_local()
            self._start_queue_cycle()
            self._after_id = self.after(self.poll_interval_ms, self._periodic_refresh)

    def _close(self):
        self._queue_running = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        self.destroy()
