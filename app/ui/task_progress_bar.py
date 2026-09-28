import threading
import tkinter as tk
from tkinter import ttk

from app.core.vasp_progress import calculate_progress_percent
from app.ui.theme import (
    PROGRESS_BG,
    PROGRESS_BORDER,
    PROGRESS_FILL,
    PROGRESS_GLOW,
    PROGRESS_STRIPE,
    PROGRESS_TRACK,
)


class TaskProgressBar(ttk.Frame):
    """Persistent, auto-refreshing progress HUD for the current VASP task."""

    REFRESH_MS = 5000

    def __init__(self, master, read_progress, get_task_name):
        super().__init__(master, style="ProgressHud.TFrame", padding=(10, 5))
        self.read_progress = read_progress
        self.get_task_name = get_task_name
        self._worker = None
        self._after_id = None
        self._percent = 0.0

        self.columnconfigure(1, weight=1)
        title_box = ttk.Frame(self, style="ProgressHud.TFrame")
        title_box.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.task_label = tk.StringVar(value="Current task · Waiting for data")
        ttk.Label(title_box, textvariable=self.task_label, style="ProgressTitle.TLabel", width=30).pack(anchor="w")

        self.canvas = tk.Canvas(
            self, height=4, bg=PROGRESS_BG, highlightthickness=0, bd=0
        )
        self.canvas.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        self.canvas.bind("<Configure>", lambda _event: self._draw_bar())

        self.detail = tk.StringVar(value="Reading OUTCAR / OSZICAR…")
        ttk.Label(self, textvariable=self.detail, style="ProgressDetail.TLabel", width=1).grid(
            row=0, column=1, sticky="ew"
        )
        self.percent_label = tk.StringVar(value="0%")
        ttk.Label(self, textvariable=self.percent_label, style="ProgressPercent.TLabel").grid(
            row=0, column=2, sticky="e", padx=(12, 2)
        )

        self.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh()

    def refresh(self):
        if not self.winfo_exists():
            return
        if not self._worker or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._read_worker, daemon=True)
            self._worker.start()
        self._after_id = self.after(self.REFRESH_MS, self.refresh)

    def _read_worker(self):
        try:
            progress = self.read_progress()
            self.after(0, lambda value=progress: self._apply_progress(value))
        except Exception as exc:
            self.after(0, lambda message=str(exc): self._show_error(message))

    def _apply_progress(self, progress):
        self._percent = calculate_progress_percent(progress)
        self.percent_label.set(f"{self._percent:.0f}%")
        task_name = self.get_task_name() or "Unnamed task"
        finished = bool(progress.get("finished"))
        errors = progress.get("errors") or []
        state = "Calculation complete" if finished else ("Error detected" if errors else "Calculation running")
        if not any((progress.get("ionic_step"), progress.get("electronic_step"), finished)):
            state = "Waiting for calculation logs"
        self.task_label.set(f"{task_name}  ·  {state}")
        energy = progress.get("energy_ev")
        energy_text = f"{energy:.6f} eV" if isinstance(energy, (int, float)) else "—"
        self.detail.set(
            f"ION  {progress.get('ionic_step') or 0}/{progress.get('max_ionic_steps') or '—'}"
            f"    ·    SCF  {progress.get('electronic_step') or 0}/{progress.get('max_electronic_steps') or '—'}"
            f"    ·    ENERGY  {energy_text}"
        )
        self._draw_bar()

    def _show_error(self, message):
        self.task_label.set(f"{self.get_task_name() or 'Current task'}  ·  Temporarily unavailable")
        self.detail.set(message[:120])

    def _draw_bar(self):
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        self.canvas.create_rectangle(
            0,
            0,
            width,
            height,
            fill=PROGRESS_TRACK,
            outline=PROGRESS_BORDER,
        )
        filled = width * max(0.0, min(100.0, self._percent)) / 100.0
        if filled > 0:
            self.canvas.create_rectangle(
                1,
                1,
                filled,
                height - 1,
                fill=PROGRESS_FILL,
                outline="",
            )
            glow_start = max(1, filled - 34)
            self.canvas.create_rectangle(
                glow_start,
                3,
                filled,
                height - 3,
                fill=PROGRESS_GLOW,
                outline="",
            )

    def _on_destroy(self, event):
        if event.widget is self and self._after_id:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
