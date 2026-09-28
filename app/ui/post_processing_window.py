import os
from app.core.platform_utils import open_path
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from app.core.charge_density import calculate_charge_difference
from app.core.science_exports import (
    export_charge_difference_publication,
    export_pdos_publication,
    load_pdos_from_vasprun,
)
from app.ui.theme import BG, BORDER_STRONG
from app.ui import file_dialogs
from app.ui.window_geometry import bind_wraplength, fit_window_to_workarea


class PostProcessingWindow(tk.Toplevel):
    def __init__(self, master, callbacks):
        super().__init__(master)
        self.callbacks = callbacks
        self.config_manager = getattr(master, "config_manager", None)
        self.worker = None
        self.messages = queue.Queue()
        self._poll_id = None
        self.last_output_dir = Path(callbacks["get_result_dir"]())
        self._scrollable_canvases = []

        self.title("iface Post-processing and scientific plots")
        fit_window_to_workarea(self, (1040, 720), (720, 480))
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.bind("<MouseWheel>", self._scroll_content, add="+")
        self.bind("<Button-4>", self._scroll_content, add="+")
        self.bind("<Button-5>", self._scroll_content, add="+")
        self._poll_messages()

    def _build(self):
        header = ttk.Frame(self, style="AppBar.TFrame", padding=(14, 10))
        header.pack(fill="x", padx=12, pady=(12, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Post-processing and scientific plots", style="AppTitle.TLabel").pack(
            side="left"
        )
        ttk.Button(
            header,
            text="Open output directory",
            style="Compact.TButton",
            command=self.open_output_directory,
        ).pack(side="right")
        ttk.Label(self, text="Select results → Validate data → Export plots and Excel source data",
                  style="Muted.TLabel").pack(anchor="w", padx=24, pady=(0, 8))

        self.tabs = ttk.Notebook(self, style="Content.TNotebook")
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        charge_tab = self._create_scrollable_tab("Charge density difference")
        pdos_tab = self._create_scrollable_tab("PDOS")
        self._build_charge_tab(charge_tab)
        self._build_pdos_tab(pdos_tab)

        footer = ttk.Frame(self, style="Status.TFrame", padding=(12, 5))
        footer.pack(fill="x", padx=12, pady=(0, 10))
        self.status = tk.StringVar(value="Choose calculation result files.")
        footer.columnconfigure(0, weight=1)
        bind_wraplength(ttk.Label(footer, textvariable=self.status, style="Status.TLabel")).grid(
            row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=1, padx=(12, 0))

    def _create_scrollable_tab(self, title):
        host = ttk.Frame(self.tabs, style="Card.TFrame")
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        canvas = tk.Canvas(host, bg=BG, highlightthickness=0)
        self._scrollable_canvases.append(canvas)
        vertical = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(host, orient="horizontal", command=canvas.xview)
        canvas.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        content = ttk.Frame(canvas, style="Card.TFrame", padding=14)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_content(event):
            canvas.itemconfigure(window_id, width=max(event.width, 560))

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_content)
        self.tabs.add(host, text=title)
        return content

    def _scroll_content(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget in self._scrollable_canvases:
                upward = getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0
                widget.yview_scroll(-3 if upward else 3, "units")
                return "break"
            widget = getattr(widget, "master", None)
        return None

    def _build_charge_tab(self, parent):
        intro = ttk.Frame(parent, style="SectionHeader.TFrame", padding=(12, 10))
        intro.pack(fill="x", pady=(0, 12))
        bind_wraplength(ttk.Label(
            intro,
            text="Δρ = ρ(interface) − ρ(isolated substrate) − ρ(isolated film)",
            style="SectionTitle.TLabel",
        )).pack(fill="x")
        bind_wraplength(ttk.Label(
            intro,
            text=(
                "All three CHGCAR files must use the same interface cell, ENCUT and FFT grid. "
                "The lattice and NGXF/NGYF/NGZF are validated before pointwise subtraction."
            ),
            style="SectionTitle.TLabel",
            wraplength=900,
            justify="left",
        )).pack(fill="x", pady=(6, 0))

        files = ttk.LabelFrame(
            parent,
            text="CHGCAR files for three systems",
            style="Card.TLabelframe",
            padding=(12, 10),
        )
        files.pack(fill="x")
        current = Path(self.callbacks["get_current_task_dir"]())
        self.charge_paths = {
            "interface": tk.StringVar(value=str(current / "charge_interface" / "CHGCAR")),
            "substrate": tk.StringVar(value=str(current / "charge_substrate" / "CHGCAR")),
            "film": tk.StringVar(value=str(current / "charge_film" / "CHGCAR")),
        }
        for row, (key, label) in enumerate(
            (
                ("interface", "Interface"),
                ("substrate", "Isolated substrate"),
                ("film", "Isolated film"),
            )
        ):
            ttk.Label(files, text=label, style="Panel.TLabel", width=19).grid(
                row=row, column=0, sticky="w", pady=5
            )
            ttk.Entry(files, textvariable=self.charge_paths[key]).grid(
                row=row, column=1, sticky="ew", pady=5
            )
            ttk.Button(
                files,
                text="Browse",
                style="Compact.TButton",
                command=lambda variable=self.charge_paths[key]: self._choose_file(
                    variable, "Choose CHGCAR"
                ),
            ).grid(row=row, column=2, padx=(6, 0), pady=5)
        files.columnconfigure(1, weight=1)

        output = ttk.LabelFrame(
            parent,
            text="Export settings",
            style="Card.TLabelframe",
            padding=(12, 10),
        )
        output.pack(fill="x", pady=(10, 0))
        self.charge_output = tk.StringVar(value=self._saved_output("charge_export", "charge_difference"))
        ttk.Label(output, text="Output directory", style="Panel.TLabel", width=19).grid(
            row=0, column=0, sticky="w", pady=5
        )
        entry = ttk.Entry(output, textvariable=self.charge_output)
        entry.grid(row=0, column=1, sticky="ew", pady=5)
        entry.bind("<FocusOut>", lambda _event: self._remember_output(self.charge_output))
        ttk.Button(
            output,
            text="Browse",
            style="Compact.TButton",
            command=lambda: self._choose_directory(self.charge_output),
        ).grid(row=0, column=2, padx=(6, 0), pady=5)
        self.full_grid_excel = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            output,
            text="Include the full 3D grid in Excel (large CHGCAR files use multiple sheets)",
            variable=self.full_grid_excel,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 8))
        ttk.Button(
            output,
            text="Validate grid, calculate and export",
            style="Primary.TButton",
            command=self.run_charge_difference,
        ).grid(row=2, column=0, columnspan=3, sticky="ew")
        output.columnconfigure(1, weight=1)

        self.charge_summary = tk.StringVar(value="Not calculated yet.")
        bind_wraplength(ttk.Label(
            parent,
            textvariable=self.charge_summary,
            style="Muted.TLabel",
            wraplength=900,
            justify="left",
        )).pack(anchor="w", fill="x", pady=(12, 0))

    def _build_pdos_tab(self, parent):
        intro = ttk.Frame(parent, style="SectionHeader.TFrame", padding=(12, 10))
        intro.pack(fill="x", pady=(0, 12))
        bind_wraplength(ttk.Label(
            intro,
            text="Total DOS and element/orbital contributions near the Fermi level",
            style="SectionTitle.TLabel",
        )).pack(fill="x")
        bind_wraplength(ttk.Label(
            intro,
            text=(
                "Read vasprun.xml from a static or PDOS calculation; energies are shifted to E−EF. "
                "Spin down is plotted negative, while Excel retains the original positive DOS."
            ),
            style="SectionTitle.TLabel",
            wraplength=900,
            justify="left",
        )).pack(fill="x", pady=(6, 0))

        card = ttk.LabelFrame(
            parent,
            text="PDOS input and export",
            style="Card.TLabelframe",
            padding=(12, 10),
        )
        card.pack(fill="x")
        current = Path(self.callbacks["get_current_task_dir"]())
        self.vasprun_path = tk.StringVar(value=str(current / "03_pdos" / "vasprun.xml"))
        self.pdos_output = tk.StringVar(value=self._saved_output("pdos_export", "pdos"))
        for row, (label, variable, chooser) in enumerate(
            (
                ("vasprun.xml", self.vasprun_path, "file"),
                ("Output directory", self.pdos_output, "directory"),
            )
        ):
            ttk.Label(card, text=label, style="Panel.TLabel", width=19).grid(
                row=row, column=0, sticky="w", pady=6
            )
            entry = ttk.Entry(card, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            if chooser == "directory":
                entry.bind("<FocusOut>", lambda _event, var=variable: self._remember_output(var))
            command = (
                (lambda var=variable: self._choose_file(var, "Choose vasprun.xml"))
                if chooser == "file"
                else (lambda var=variable: self._choose_directory(var))
            )
            ttk.Button(
                card,
                text="Browse",
                style="Compact.TButton",
                command=command,
            ).grid(row=row, column=2, padx=(6, 0), pady=6)
        ttk.Button(
            card,
            text="Read PDOS and export plots and Excel",
            style="Primary.TButton",
            command=self.run_pdos,
        ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        card.columnconfigure(1, weight=1)
        self.pdos_summary = tk.StringVar(value="PDOS has not been loaded.")
        bind_wraplength(ttk.Label(
            parent,
            textvariable=self.pdos_summary,
            style="Muted.TLabel",
            wraplength=900,
            justify="left",
        )).pack(anchor="w", fill="x", pady=(12, 0))

    def _saved_output(self, purpose, subdirectory):
        fallback = str(self.last_output_dir / subdirectory)
        if self.config_manager:
            return self.config_manager.data.get("dialog_directories", {}).get(purpose) or fallback
        return fallback

    def _output_purpose(self, variable):
        return "charge_export" if variable is self.charge_output else "pdos_export"

    def _remember_output(self, variable):
        path = variable.get().strip()
        if path and self.config_manager:
            self.config_manager.remember_dialog_path(self._output_purpose(variable), path, is_directory=True)

    def _output_directory(self, variable):
        value = variable.get().strip()
        if not value:
            messagebox.showwarning("Output directory", "Enter or choose an output directory.", parent=self)
            return None
        self._remember_output(variable)
        return Path(value)

    def run_charge_difference(self):
        if self._busy():
            return
        arguments = {
            key: value.get().strip() for key, value in self.charge_paths.items()
        }
        output_dir = self._output_directory(self.charge_output)
        if output_dir is None:
            return
        include_full = self.full_grid_excel.get()
        self._start_worker(
            self._charge_worker,
            arguments,
            output_dir,
            include_full,
            message="Validating CHGCAR grids and calculating charge density difference…",
        )

    def _charge_worker(self, paths, output_dir, include_full):
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            result = calculate_charge_difference(
                paths["interface"],
                paths["substrate"],
                paths["film"],
                output_dir / "CHGDIFF.vasp",
            )
            exports = export_charge_difference_publication(
                result,
                output_dir,
                include_full_grid_excel=include_full,
            )
            self.messages.put(("charge_ok", (result, exports, output_dir)))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def run_pdos(self):
        if self._busy():
            return
        source = self.vasprun_path.get().strip()
        output_dir = self._output_directory(self.pdos_output)
        if output_dir is None:
            return
        self._start_worker(
            self._pdos_worker,
            source,
            output_dir,
            message="Reading vasprun.xml and generating PDOS plots…",
        )

    def _pdos_worker(self, source, output_dir):
        try:
            dataset = load_pdos_from_vasprun(source)
            exports = export_pdos_publication(dataset, output_dir)
            self.messages.put(("pdos_ok", (dataset, exports, output_dir)))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _start_worker(self, target, *args, message):
        self.status.set(message)
        self.progress.start(10)
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _busy(self):
        if self.worker and self.worker.is_alive():
            self.status.set("A post-processing task is running. Please wait.")
            return True
        return False

    def _poll_messages(self):
        while not self.messages.empty():
            kind, payload = self.messages.get_nowait()
            self.progress.stop()
            if kind == "charge_ok":
                result, exports, output_dir = payload
                self.last_output_dir = Path(output_dir)
                self.charge_summary.set(
                    f"FFT grid: {result.grid}; cell volume: {result.volume_a3:.6f} Å³; "
                    f"Net electron difference: {result.report.electron_difference:.6g} e; "
                    f"Accumulated: {result.report.accumulated_electrons:.6g} e; "
                    f"Depleted: {result.report.depleted_electrons:.6g} e.\n"
                    f"Generated: {', '.join(Path(path).name for path in exports.values())}"
                )
                self.status.set("Charge density difference and scientific exports completed.")
            elif kind == "pdos_ok":
                dataset, exports, output_dir = payload
                self.last_output_dir = Path(output_dir)
                self.pdos_summary.set(
                    f"Fermi energy: {dataset.fermi_ev:.8f} eV; "
                    f"Data channels: {len(dataset.channels)}; "
                    f"Energy points: {len(dataset.energies_ev)}.\n"
                    f"Generated: {', '.join(Path(path).name for path in exports.values())}"
                )
                self.status.set("PDOS plots and Excel source data exported.")
            else:
                self.status.set("Post-processing failed.")
                messagebox.showerror("Post-processing failed", payload, parent=self)
        self._poll_id = self.after(250, self._poll_messages)

    def _choose_file(self, variable, title):
        path = file_dialogs.askopenfilename(self.config_manager, "postprocessing_input",
                                            parent=self, title=title,
                                            initialdir=str(Path(variable.get()).parent))
        if path:
            variable.set(path)

    def _choose_directory(self, variable):
        path = file_dialogs.askdirectory(self.config_manager, self._output_purpose(variable),
                                        parent=self, title="Choose output directory", initialdir=variable.get())
        if path:
            variable.set(path)

    def open_output_directory(self):
        variable = self.charge_output if self.tabs.index(self.tabs.select()) == 0 else self.pdos_output
        path = self._output_directory(variable)
        if path is None:
            return
        try:
            path.mkdir(parents=True, exist_ok=True)
            self._remember_output(variable)
            open_path(path)
        except OSError as exc:
            messagebox.showerror("Could not open directory", str(exc), parent=self)

    def _close(self):
        self._remember_output(self.charge_output)
        self._remember_output(self.pdos_output)
        if self._poll_id:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self.destroy()
