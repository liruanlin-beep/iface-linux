import tkinter as tk
import threading
from pathlib import Path
from tkinter import messagebox, ttk

from app.core.input_generators import DEFAULT_INCAR
from app.core.incar_presets import PRESET_LABELS, render_incar_preset
from app.core.path_utils import normalize_local_path
from app.ui.theme import BLUE, BORDER_STRONG, PANEL_ALT, TEXT, MONO_FONT_FAMILY
from app.ui import file_dialogs
from app.ui.responsive_rows import VerticalScrolledFrame, WidthLabel, WrappingRow


class BottomPanel(ttk.Frame):
    """Compact input/task area: only the selected tab consumes screen space."""

    def __init__(self, master, tr, callbacks):
        super().__init__(master)
        self.tr = tr
        self.callbacks = callbacks
        self.config_manager = callbacks.get("get_config_manager", lambda: None)()
        self._progress_worker = None
        self.tabs = ttk.Notebook(self, style="Content.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        for title, builder in [
            ("INCAR", self._incar), ("KPOINTS", self._kpoints),
            ("POTCAR", self._potcar), ("Svasp.sh", self._slurm),
            ("Task monitoring", self._tasks), ("Results analysis", self._results),
        ]:
            # Every tab remains operable even when the viewer leaves only a
            # short inspector area: form controls keep their natural height.
            scroller = VerticalScrolledFrame(self.tabs)
            self.tabs.add(scroller, text=title)
            builder(scroller.body)
            scroller.finish()

    def _incar(self, body):
        row = WrappingRow(body, style="Panel.TFrame")
        row.pack(fill="x")
        self.incar_preset = tk.StringVar(
            value=PRESET_LABELS["surface_interface_relax"]
        )
        preset_box = ttk.Combobox(
            row,
            textvariable=self.incar_preset,
            values=list(PRESET_LABELS.values()),
            state="readonly",
            width=46,
        )
        row.add(preset_box)
        preset_box.bind("<<ComboboxSelected>>", lambda _event: self._load_selected_preset())
        for text, command in [
            ("Import local INCAR", self._import_incar),
            ("Generate selected preset", self._load_selected_preset),
            ("Save INCAR", self.callbacks["generate_incar"]),
            ("Check INCAR", self._check_incar),
        ]:
            row.add(ttk.Button(row, text=text, style="Compact.TButton", command=command))
        self.incar_source = tk.StringVar()
        WidthLabel(body, textvariable=self.incar_source, style="Muted.TLabel").pack(fill="x", pady=(6, 2))
        self.incar_text = tk.Text(
            body,
            height=10,
            bg=PANEL_ALT,
            fg=TEXT,
            insertbackground=BLUE,
            wrap="none",
            undo=True,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER_STRONG,
            highlightcolor=BLUE,
            padx=8,
            pady=6,
            font=(MONO_FONT_FAMILY, 10),
        )
        self.incar_text.pack(fill="both", expand=True)
        self._load_default_incar()

    def _load_default_incar(self):
        text = "\n".join(f"{key} = {value}" for key, value in DEFAULT_INCAR.items()) + "\n"
        self.incar_text.delete("1.0", "end")
        self.incar_text.insert("1.0", text)
        self.incar_source.set("Using the default template; edit it directly.")

    def _load_selected_preset(self):
        elements = self.callbacks.get("get_structure_elements", lambda: [])()
        selected_label = self.incar_preset.get()
        key = next(
            (
                preset_key
                for preset_key, label in PRESET_LABELS.items()
                if label == selected_label
            ),
            "surface_interface_relax",
        )
        text = render_incar_preset(key, elements)
        self.incar_text.delete("1.0", "end")
        self.incar_text.insert("1.0", text)
        self.incar_source.set(
            f"Preset: {PRESET_LABELS[key]}. MAGMOM follows the element order in the current structure."
        )

    def _import_incar(self):
        path = file_dialogs.askopenfilename(self.config_manager, "incar_import", parent=self, title="Choose INCAR file", filetypes=[("INCAR files", "INCAR *.incar *.txt *.*"), ("All files", "*.*")])
        if not path:
            return
        try:
            text = open(path, "r", encoding="utf-8", errors="ignore").read()
        except OSError as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.incar_text.delete("1.0", "end")
        self.incar_text.insert("1.0", text)
        self.incar_source.set(f"Imported INCAR: {path}")

    def _check_incar(self, show_success=True):
        try:
            text = self.get_incar_text()
        except RuntimeError as exc:
            messagebox.showwarning("INCAR check", str(exc))
            return
        warnings = []
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "!")) and "=" not in stripped:
                warnings.append(f"Line {number} may not be a valid parameter: {stripped}")
        if warnings:
            messagebox.showwarning("INCAR check", "\n".join(warnings))
        elif show_success:
            messagebox.showinfo("INCAR check", "Basic format checks passed.")

    def get_incar_text(self):
        text = self.incar_text.get("1.0", "end").rstrip()
        if not text:
            raise RuntimeError("INCAR is empty. Import or enter INCAR content.")
        return text + "\n"

    def _kpoints(self, body):
        row = WrappingRow(body, style="Panel.TFrame")
        row.pack(fill="x", pady=6)
        self.kpoint_mode = tk.StringVar(value="Gamma")
        row.add(ttk.Combobox(row, values=["Gamma", "Monkhorst-Pack"], textvariable=self.kpoint_mode, state="readonly", width=16))
        self.kpoint_vars = {}
        for label, value in [("Kx", "7"), ("Ky", "7"), ("Kz", "1")]:
            field = ttk.Frame(row)
            ttk.Label(field, text=label).pack(side="left")
            var = tk.StringVar(value=value)
            self.kpoint_vars[label] = var
            ttk.Entry(field, textvariable=var, width=5).pack(side="left", padx=(3, 0))
            row.add(field)
        ttk.Button(body, text="Generate KPOINTS", command=self.callbacks["generate_kpoints"]).pack(anchor="w")

    def get_kpoints_settings(self):
        def value(name, default):
            try:
                return int(self.kpoint_vars[name].get())
            except ValueError:
                return default
        return (value("Kx", 7), value("Ky", 7), value("Kz", 1)), self.kpoint_mode.get()

    def _potcar(self, body):
        row = ttk.Frame(body, style="Panel.TFrame")
        row.pack(fill="x", pady=(6, 2))
        ttk.Label(row, text="POTCAR root: ").pack(side="left")
        self.potcar_root = tk.StringVar(value=self.callbacks.get("get_potcar_root", lambda: "")())
        self.potcar_entry = ttk.Entry(row, textvariable=self.potcar_root, width=8)
        self.potcar_entry.pack(side="left", fill="x", expand=True)
        self.potcar_entry.bind("<Return>", self._save_potcar_root)
        self.potcar_entry.bind("<FocusOut>", self._save_potcar_root)
        ttk.Button(row, text="Browse", command=self._browse_potcar_root).pack(side="left", padx=6)

        actions = WrappingRow(body, style="Panel.TFrame")
        actions.pack(fill="x", pady=(2, 6))
        actions.add(ttk.Button(actions, text="Check POTCAR", command=self._check_potcar))
        actions.add(ttk.Button(actions, text="Generate POTCAR", command=self._generate_potcar))
        self.potcar_status = tk.StringVar()
        WidthLabel(body, textvariable=self.potcar_status, style="Muted.TLabel").pack(fill="x")
        self._update_potcar_status()

    def _browse_potcar_root(self):
        path = file_dialogs.askdirectory(self.config_manager, "potcar", parent=self, title="Choose POTCAR root directory", initialdir=self.potcar_root.get())
        if path:
            path = normalize_local_path(path)
            self.potcar_root.set(path)
            callback = self.callbacks.get("set_potcar_root")
            if callback:
                callback(path)
            self._update_potcar_status()

    def _save_potcar_root(self, _event=None):
        path = normalize_local_path(self.potcar_root.get().strip())
        self.potcar_root.set(path)
        callback = self.callbacks.get("set_potcar_root")
        if callback:
            callback(path)
        self._update_potcar_status()
        return "break" if _event and getattr(_event, "keysym", "") == "Return" else None

    def _update_potcar_status(self):
        path_text = normalize_local_path(self.potcar_root.get().strip())
        if not path_text:
            self.potcar_status.set("Not configured")
        elif Path(path_text).is_dir():
            self.potcar_status.set("Directory valid; configuration saved")
        else:
            self.potcar_status.set("Directory does not exist")

    def _check_potcar(self):
        self._save_potcar_root()
        callback = self.callbacks.get("check_potcar")
        if callback:
            callback()

    def _generate_potcar(self):
        self._save_potcar_root()
        callback = self.callbacks.get("generate_potcar")
        if callback:
            callback()

    def get_potcar_root(self):
        return normalize_local_path(self.potcar_root.get())

    def _slurm(self, body):
        row = WrappingRow(body)
        row.pack(fill="x")
        row.add(ttk.Button(row, text="Generate Svasp.sh", command=self.callbacks.get("generate_slurm")))
        row.add(ttk.Button(row, text="Generate all input files", command=self.callbacks.get("generate_inputs")))

    def _tasks(self, body):
        intro = ttk.Frame(body, style="SectionHeader.TFrame", padding=(14, 12))
        intro.pack(fill="both", expand=True)
        WidthLabel(
            intro,
            text="Task monitoring is available in Task Center",
            style="SectionTitle.TLabel",
        ).pack(fill="x")
        WidthLabel(
            intro,
            text=(
                "View local waiting, Slurm pending, running and completed states in a separate window, "
                "including each ionic step and electronic iteration. Closing Task Center does not stop server jobs."
            ),
            style="SectionTitle.TLabel",
            justify="left",
        ).pack(fill="x", pady=(8, 12))
        ttk.Button(
            intro,
            text="Open Task Center",
            style="Primary.TButton",
            command=self.callbacks["open_task_center"],
        ).pack(anchor="w")

    def _results(self, body):
        top = WrappingRow(body, style="Panel.TFrame")
        top.pack(fill="x")
        top.add(ttk.Button(top, text="Read OUTCAR / CONTCAR", command=self.analyze_results))
        top.add(ttk.Button(
            top,
            text="Open CONTCAR viewer",
            command=self.callbacks["open_result_structure"],
        ))
        top.add(ttk.Button(
            top,
            text="Refresh calculation progress",
            command=self.refresh_result_progress,
        ))
        self.result_summary = tk.StringVar(value="Automatically read OUTCAR / CONTCAR from the current task or remote directory.")
        WidthLabel(body, textvariable=self.result_summary, style="Muted.TLabel").pack(fill="x", pady=(6, 0))
        progress_row = ttk.Frame(body, style="Panel.TFrame")
        progress_row.pack(fill="x", pady=(7, 0))
        self.calculation_progress = ttk.Progressbar(
            progress_row, mode="determinate", maximum=100, length=100
        )
        self.calculation_progress.pack(fill="x")
        self.progress_summary = tk.StringVar(value="Calculation progress has not been read.")
        WidthLabel(
            progress_row,
            textvariable=self.progress_summary,
            style="Muted.TLabel",
        ).pack(fill="x", pady=(4, 0))
        box = ttk.LabelFrame(body, text="Surface energy", padding=6)
        box.pack(fill="x", pady=(8, 0))
        self.surface_vars = {}
        fields_row = WrappingRow(box, gap=10, row_gap=8)
        fields_row.pack(fill="x")
        fields = [("slab_energy", "Slab total energy (automatic)", ""), ("bulk_energy", "Bulk energy per atom (eV)", ""), ("atom_count", "Atom count N (automatic)", ""), ("area", "Oriented area Å² (automatic)", ""), ("surfaces", "Surface count", "2")]
        for key, label, default in fields:
            field = ttk.Frame(fields_row)
            ttk.Label(field, text=label).pack(anchor="w")
            var = tk.StringVar(value=default)
            self.surface_vars[key] = var
            ttk.Entry(field, textvariable=var, width=18).pack(fill="x", pady=(3, 0))
            fields_row.add(field)
        ttk.Button(box, text="Calculate surface energy", style="Primary.TButton", command=self.calculate_surface_energy).pack(anchor="w", pady=(8, 0))
        self.surface_result = tk.StringVar(value="γ = (Eslab − N × Ebulk) / (Surface count × A)")
        WidthLabel(box, textvariable=self.surface_result, style="Title.TLabel").pack(fill="x", pady=(8, 0))
        WidthLabel(
            box,
            text="A = |a × b| from the CONTCAR lattice vectors, consistent with the generated slab orientation.",
            style="Muted.TLabel",
        ).pack(fill="x", pady=(4, 0))

    def refresh_result_progress(self):
        if self._progress_worker and self._progress_worker.is_alive():
            return
        self.progress_summary.set("Reading current calculation progress…")

        def worker():
            try:
                result = self.callbacks["read_current_progress"]()
                self.after(0, lambda: self._show_progress(result))
            except Exception as exc:
                self.after(
                    0,
                    lambda value=str(exc): self.progress_summary.set(
                        "Could not read progress: " + value
                    ),
                )

        self._progress_worker = threading.Thread(target=worker, daemon=True)
        self._progress_worker.start()

    def _show_progress(self, progress):
        ionic = int(progress.get("ionic_step") or 0)
        max_ionic = int(progress.get("max_ionic_steps") or 0)
        electronic = int(progress.get("electronic_step") or 0)
        max_electronic = int(progress.get("max_electronic_steps") or 0)
        if progress.get("finished"):
            percent = 100
            state = "Calculation complete"
        elif max_ionic > 0:
            within = electronic / max(1, max_electronic)
            percent = min(99, 100 * (ionic + within) / max_ionic)
            state = "Running"
        elif max_electronic > 0:
            percent = min(99, 100 * electronic / max_electronic)
            state = "Electronic self-consistency"
        else:
            percent = 0
            state = "Waiting for valid logs"
        self.calculation_progress["value"] = percent
        energy = progress.get("energy_ev")
        self.progress_summary.set(
            f"{state} · Ionic step {ionic}/{max_ionic or '-'} · "
            f"Electronic step {electronic}/{max_electronic or '-'} · "
            f"Energy {energy if energy is not None else '-'} eV"
        )

    def refresh_tasks(self):
        self.callbacks["open_task_center"]()

    def analyze_results(self):
        try:
            result = self.callbacks["analyze_results"]()
            energy = result.get("energy_ev")
            force = result.get("max_force_ev_a")
            area = result.get("area_a2")
            atom_count = result.get("atom_count")
            text = f"Energy: {energy if energy is not None else 'Not found'} eV; area: {f'{area:.8f}' if area is not None else 'Not found'} Å²; atom count: {atom_count if atom_count is not None else 'Not found'}; maximum force: {force if force is not None else 'Not found'} eV/Å; ionic steps: {result['ionic_steps']}; converged: {'Yes' if result['converged'] else 'No/unknown'}"
            source = "Server" if result.get("source") == "remote" else "Local"
            geometry_source = result.get("geometry_source") or "No structure file"
            text = f"Source: {source} {result.get('directory', '')}; structure: {geometry_source}; {text}"
            self.result_summary.set(text)
            self._apply_surface_result(result)
            if energy is None:
                messagebox.showwarning(
                    "Results analysis",
                    "No energy was found. Check the result directory or remote directory for an OUTCAR containing TOTEN, "
                    "or an OSZICAR containing F=.\n\nChecked location: " + str(result.get("directory", "Unknown"))
                    + "\n\nRead details: \n" + "\n".join(result.get("read_errors", []) or ["Files were read, but no energy line was found."]),
                )
            elif area is None or atom_count is None:
                messagebox.showwarning(
                    "Results analysis",
                    "OUTCAR energy was read, but area and atom count could not be read from CONTCAR/POSCAR in this directory.\n\n"
                    "Checked location: " + str(result.get("directory", "Unknown"))
                    + "\n\nRead details: \n" + "\n".join(result.get("read_errors", []) or ["No valid CONTCAR or POSCAR was found."]),
                )
            return result
        except Exception as exc:
            messagebox.showwarning("Results analysis", str(exc))
            return None

    def _apply_surface_result(self, result):
        energy = result.get("energy_ev")
        atom_count = result.get("atom_count")
        area = result.get("area_a2")
        if energy is not None:
            self.surface_vars["slab_energy"].set(f"{energy:.12g}")
        if atom_count is not None:
            self.surface_vars["atom_count"].set(str(atom_count))
        if area is not None:
            self.surface_vars["area"].set(f"{area:.8f}")

    def calculate_surface_energy(self):
        try:
            result = self.callbacks["analyze_results"]()
            directory = result.get("directory", "Unknown")
            if result.get("energy_ev") is None:
                raise RuntimeError(f"No OUTCAR TOTEN energy was read from this directory: \n{directory}")
            if result.get("geometry_source") != "CONTCAR" or result.get("area_a2") is None or result.get("atom_count") is None:
                raise RuntimeError(f"No valid CONTCAR is available to determine oriented area and atom count: \n{directory}")
            self._apply_surface_result(result)
            ev_a2, j_m2 = self.callbacks["calculate_surface_energy"](
                self.surface_vars["slab_energy"].get(), self.surface_vars["bulk_energy"].get(),
                self.surface_vars["atom_count"].get(), self.surface_vars["area"].get(), self.surface_vars["surfaces"].get(),
            )
            self.surface_result.set(f"Surface energy γ = {ev_a2:.8f} eV/Å² = {j_m2:.6f} J/m²")
        except Exception as exc:
            messagebox.showwarning("Calculate surface energy", str(exc))
