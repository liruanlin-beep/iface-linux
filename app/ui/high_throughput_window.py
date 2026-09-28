import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from app.core.high_throughput_models import search_surface_candidates
from app.core.high_throughput_self_test import run_high_throughput_self_test
from app.core.interface_builder import search_interface_candidates
from app.core.interface_scan import (
    MAX_SCAN_MODELS,
    analyze_interface_project,
    estimate_scan_models,
    inclusive_float_range,
    inclusive_integer_range,
)
from app.core.slurm_manager import sanitize_job_name
from app.core.task_database import TaskDatabase
from app.core.workflow_builder import (
    build_adaptive_interface_workflow,
    build_candidate_workflow,
)
from app.core.workflow_integrity import write_batch_manifest
from app.ui.theme import BG, BORDER, PANEL
from app.ui import file_dialogs
from app.ui.window_geometry import bind_wraplength, fit_window_to_workarea


class HighThroughputWindow(tk.Toplevel):
    """Build surface/interface candidates and durable VASP workflows."""

    def __init__(self, master, config_manager, callbacks):
        super().__init__(master)
        self.config_manager = config_manager
        self.callbacks = callbacks
        self.candidates = []
        self.candidate_by_iid = {}
        self.scan_results = {}
        self.worker = None
        self.messages = queue.Queue()
        self._poll_id = None

        self.title('iface high-throughput calculations')
        fit_window_to_workarea(self, (1200, 760), (760, 480))
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._poll_messages()

    def _build(self):
        header = ttk.Frame(self, style="AppBar.TFrame", padding=(12, 8))
        header.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(header, text='High-throughput workspace', style="AppTitle.TLabel").pack(side="left")
        ttk.Label(header, text='Structures and scans → Compare candidates → Calculation tasks', style="AppSubtitle.TLabel").pack(
            side="left", padx=(16, 0))
        ttk.Button(header, text='Task center', style="Compact.TButton",
                   command=self.callbacks["open_task_center"]).pack(side="right")
        panes = tk.PanedWindow(
            self,
            orient="horizontal",
            sashwidth=6,
            sashrelief="flat",
            bd=0,
            bg=BORDER,
            showhandle=True,
            opaqueresize=True,
        )
        panes.pack(fill="both", expand=True, padx=10, pady=(8, 10))
        form_host = ttk.Frame(panes, style="Panel.TFrame")
        form_host.rowconfigure(0, weight=1)
        form_host.columnconfigure(0, weight=1)
        canvas = tk.Canvas(form_host, bg=PANEL, highlightthickness=0)
        self.form_canvas = canvas
        scrollbar = ttk.Scrollbar(form_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        ttk.Button(form_host, text='Search candidate structures', style="Primary.TButton",
                   command=self.search).grid(row=1, column=0, columnspan=2,
                                             sticky="ew", padx=10, pady=10)
        form = ttk.Frame(canvas, style="Panel.TFrame", padding=12)
        window_id = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        self.bind("<MouseWheel>", self._scroll_parameter_form, add="+")
        self.bind("<Button-4>", self._scroll_parameter_form, add="+")
        self.bind("<Button-5>", self._scroll_parameter_form, add="+")

        ttk.Label(form, text='Structures and orientations', style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.substrate_path = tk.StringVar()
        self.film_path = tk.StringVar()
        self._path_row(form, 1, 'Structure A (multiple allowed)', self.substrate_path)
        self._path_row(form, 2, 'Structure B (multiple / optional)', self.film_path)
        bind_wraplength(ttk.Label(
            form,
            text=(
                'Use Add... to select several files. Leave B empty to generate surfaces for each A; '
                'with B specified, scan all A × B combinations.'
            ),
            style="Muted.TLabel",
            wraplength=330,
        )).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 10))

        self.values = {
            "substrate_hkl": tk.StringVar(value="1 0 0"),
            "film_hkl": tk.StringVar(value="1 0 0"),
            "substrate_layers_min": tk.StringVar(value="6"),
            "substrate_layers_max": tk.StringVar(value="6"),
            "substrate_layers_step": tk.StringVar(value="1"),
            "film_layers_min": tk.StringVar(value="6"),
            "film_layers_max": tk.StringVar(value="6"),
            "film_layers_step": tk.StringVar(value="1"),
            "vacuum": tk.StringVar(value="15.0"),
            "gap_min": tk.StringVar(value="1.8"),
            "gap_max": tk.StringVar(value="3.2"),
            "gap_step": tk.StringVar(value="0.2"),
            "max_strain": tk.StringVar(value="5.0"),
            "max_area": tk.StringVar(value="500"),
            "max_atoms": tk.StringVar(value="1000"),
            "limit": tk.StringVar(value="1"),
        }
        fields = [
            ("substrate_hkl", 'A orientation (h k l)'),
            ("film_hkl", 'B orientation (h k l)'),
            ("substrate_layers_min", 'A minimum layers'),
            ("substrate_layers_max", 'A maximum layers'),
            ("substrate_layers_step", 'A layer step'),
            ("film_layers_min", 'B minimum layers'),
            ("film_layers_max", 'B maximum layers'),
            ("film_layers_step", 'B layer step'),
            ("vacuum", 'Vacuum thickness (Å)'),
            ("gap_min", 'Minimum interface gap (Å)'),
            ("gap_max", 'Maximum interface gap (Å)'),
            ("gap_step", 'Interface gap step (Å)'),
            ("max_strain", 'Maximum in-plane strain (%)'),
            ("max_area", 'Maximum matching area (Å²)'),
            ("max_atoms", 'Atom limit (≤1000)'),
            ("limit", 'Candidates per gap'),
        ]
        for row, (key, label) in enumerate(fields, 4):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=self.values[key], width=10).grid(
                row=row, column=1, columnspan=2, sticky="ew", pady=3
            )

        separator_row = 4 + len(fields)
        self.estimate_text = tk.StringVar(value='Estimated models: select structures first')
        ttk.Label(
            form,
            textvariable=self.estimate_text,
            style="Title.TLabel",
            wraplength=330,
        ).grid(row=separator_row, column=0, columnspan=3, sticky="w", pady=(8, 2))
        separator_row += 1
        ttk.Separator(form).grid(
            row=separator_row, column=0, columnspan=3, sticky="ew", pady=10
        )
        ttk.Label(form, text='Calculation workflow', style="Title.TLabel").grid(
            row=separator_row + 1, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        default_output = self.config_manager.data.get("dialog_directories", {}).get(
            "high_throughput_output") or self.config_manager.data.get("test_workspace_dir")
        if not default_output:
            default_output = self.config_manager.get_dialog_directory("high_throughput_output")
        self.output_root = tk.StringVar(value=default_output)
        self.project_name = tk.StringVar(
            value="alloy_ht_" + datetime.now().strftime("%Y%m%d_%H%M")
        )
        self._directory_row(form, separator_row + 2, 'Output root directory', self.output_root)
        ttk.Label(form, text='Project name').grid(row=separator_row + 3, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.project_name).grid(
            row=separator_row + 3, column=1, columnspan=2, sticky="ew", pady=3
        )
        self.magnetic = tk.BooleanVar(value=True)
        self.include_pdos = tk.BooleanVar(value=True)
        self.include_charge = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text='Magnetic calculation (ISPIN=2)', variable=self.magnetic).grid(
            row=separator_row + 4, column=0, columnspan=3, sticky="w", pady=3
        )
        ttk.Checkbutton(form, text='Generate PDOS stage', variable=self.include_pdos).grid(
            row=separator_row + 5, column=0, columnspan=3, sticky="w", pady=3
        )
        ttk.Checkbutton(
            form,
            text='Charge difference (3 systems)',
            variable=self.include_charge,
        ).grid(row=separator_row + 6, column=0, columnspan=3, sticky="w", pady=3)
        self.dft_u = tk.StringVar()
        ttk.Label(form, text="DFT+U (Fe=4,Ni=6.2)").grid(
            row=separator_row + 7, column=0, sticky="w", pady=3
        )
        ttk.Entry(form, textvariable=self.dft_u, width=10).grid(
            row=separator_row + 7, column=1, columnspan=2, sticky="ew", pady=3
        )
        self.vdw = tk.StringVar(value="none")
        ttk.Label(form, text='van der Waals correction').grid(
            row=separator_row + 8, column=0, sticky="w", pady=3
        )
        ttk.Combobox(
            form,
            textvariable=self.vdw,
            values=("none", "D3", "D3(BJ)", "optB86b-vdW"),
            state="readonly",
        ).grid(row=separator_row + 8, column=1, columnspan=2, sticky="ew", pady=3)

        button_row = separator_row + 9
        ttk.Button(
            form,
            text='Adaptive: relax A/B first',
            style="Success.TButton",
            command=self.create_adaptive_workflow,
        ).grid(row=button_row + 1, column=0, columnspan=3, sticky="ew", pady=5)
        ttk.Button(
            form,
            text='Scan energies and best structures',
            style="Primary.TButton",
            command=self.analyze_scan_results,
        ).grid(row=button_row + 4, column=0, columnspan=3, sticky="ew", pady=5)
        ttk.Button(
            form,
            text='Run high-throughput stress self-test',
            command=self.run_self_test,
        ).grid(row=button_row + 5, column=0, columnspan=3, sticky="ew", pady=5)
        form.columnconfigure(1, weight=1)
        self.substrate_path.trace_add("write", lambda *_args: self._update_estimate())
        self.film_path.trace_add("write", lambda *_args: self._update_estimate())
        for key in (
            "substrate_layers_min",
            "substrate_layers_max",
            "substrate_layers_step",
            "film_layers_min",
            "film_layers_max",
            "film_layers_step",
            "gap_min",
            "gap_max",
            "gap_step",
            "limit",
        ):
            self.values[key].trace_add("write", lambda *_args: self._update_estimate())

        results = ttk.Frame(panes, style="Panel.TFrame", padding=8)
        results.rowconfigure(1, weight=1)
        results.columnconfigure(0, weight=1)
        header = ttk.Frame(results, style="Panel.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(header, text='Compare candidates', style="Title.TLabel").pack(
            anchor="w"
        )
        self.status = tk.StringVar(value='Select one or two structure files.')
        bind_wraplength(ttk.Label(header, textvariable=self.status, style="Muted.TLabel")).pack(
            fill="x", pady=(4, 0)
        )
        columns = (
            "rank",
            "pair",
            "layers",
            "gap",
            "termination",
            "atoms",
            "fit",
            "energy",
            "delta",
            "best",
        )
        self.table = ttk.Treeview(results, columns=columns, show="headings", selectmode="extended")
        for key, title, width in [
            ("rank", 'Rank', 60),
            ("pair", 'A/B structures', 155),
            ("layers", 'A/B layers', 110),
            ("gap", 'Gap (Å)', 85),
            ("termination", 'Termination pair', 165),
            ("atoms", 'Atoms', 75),
            ("fit", 'Match score', 125),
            ("energy", 'Total energy (eV)', 170),
            ("delta", 'Adjacent ΔE', 130),
            ("best", 'Result flags', 125),
        ]:
            self.table.heading(key, text=title)
            self.table.column(
                key,
                width=width,
                minwidth=width,
                stretch=key in {"pair", "termination"},
            )
        self.table.bind("<Double-1>", lambda _e: self.preview_selected())
        ybar = ttk.Scrollbar(results, orient="vertical", command=self.table.yview)
        xbar = ttk.Scrollbar(results, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.table.grid(row=1, column=0, sticky="nsew")
        ybar.grid(row=1, column=1, sticky="ns")
        xbar.grid(row=2, column=0, sticky="ew")
        actions = ttk.Frame(results, style="Panel.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        actions.columnconfigure((0, 1), weight=1)
        ttk.Button(actions, text='Create tasks for selected candidates', style="Primary.TButton",
                   command=self.create_selected_workflows).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(actions, text='Create tasks for all candidates',
                   command=self.create_all_workflows).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ttk.Label(actions, text='Scores describe geometric matching; total energies come from completed calculations. Double-click to preview.',
                  style="Muted.TLabel", wraplength=460).grid(row=1, column=0, columnspan=2,
                                                           sticky="w", pady=(6, 0))

        panes.add(form_host, minsize=320, width=360, stretch="never")
        panes.add(results, minsize=350, stretch="always")

    def _scroll_parameter_form(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget == self.form_canvas:
                steps = -1 if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0 else 1
                self.form_canvas.yview_scroll(steps * 3, "units")
                return "break"
            widget = getattr(widget, "master", None)
        return None

    def _path_row(self, parent, row, label, variable):
        host = ttk.Frame(parent, style="Panel.TFrame")
        host.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        host.columnconfigure(0, weight=1)
        ttk.Label(host, text=label).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))
        ttk.Entry(host, textvariable=variable, width=16).grid(row=1, column=0, sticky="ew")
        controls = ttk.Frame(host, style="Panel.TFrame")
        controls.grid(row=1, column=1, padx=(5, 0))
        ttk.Button(
            controls,
            text='Add...',
            width=6,
            command=lambda: self._choose_structures(variable),
        ).pack(side="left")
        ttk.Button(
            controls,
            text='Clear',
            width=5,
            command=lambda: variable.set(""),
        ).pack(side="left", padx=(3, 0))

    def _directory_row(self, parent, row, label, variable):
        host = ttk.Frame(parent, style="Panel.TFrame")
        host.grid(row=row, column=0, columnspan=3, sticky="ew", pady=3)
        host.columnconfigure(0, weight=1)
        ttk.Label(host, text=label + ' (remembered)').grid(row=0, column=0, columnspan=2, sticky="w")
        entry = ttk.Entry(host, textvariable=variable, width=16)
        entry.grid(row=1, column=0, sticky="ew", pady=3)
        entry.bind("<FocusOut>", lambda _event: self._remember_output_directory())
        ttk.Button(
            host,
            text='Browse',
            style="Compact.TButton",
            command=lambda: self._choose_directory(variable),
        ).grid(row=1, column=1, padx=(5, 0), pady=3)

    def _choose_structures(self, variable):
        paths = file_dialogs.askopenfilenames(self.config_manager, "structure_import",
            parent=self,
            title='Select one or more structure files',
            filetypes=[
                ('Structure files', "*.cif *.vasp *.poscar *.contcar POSCAR CONTCAR"),
                ('All files', "*.*"),
            ],
        )
        if paths:
            variable.set(";".join(paths))

    def _choose_directory(self, variable):
        path = file_dialogs.askdirectory(self.config_manager, "high_throughput_output",
                                        parent=self, title='Select output root directory',
                                        initialdir=variable.get())
        if path:
            variable.set(path)

    def _remember_output_directory(self):
        path = self.output_root.get().strip()
        if path:
            self.config_manager.remember_dialog_path("high_throughput_output", path, is_directory=True)

    def search(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            params = self._search_parameters()
        except Exception as exc:
            messagebox.showwarning('Invalid parameters', str(exc), parent=self)
            return
        self.status.set('Generating surfaces and searching lattice matches; please wait…')
        self.table.delete(*self.table.get_children())
        self.candidates = []
        self.candidate_by_iid = {}
        self.scan_results = {}
        self.worker = threading.Thread(
            target=self._search_worker, args=(params,), daemon=True
        )
        self.worker.start()

    def _search_worker(self, params):
        try:
            candidates = []
            if params["films"]:
                for a_index, substrate in enumerate(params["substrates"], 1):
                    for b_index, film in enumerate(params["films"], 1):
                        pair_id = self._pair_id(
                            a_index, substrate, b_index, film
                        )
                        for a_layers in params["substrate_layer_values"]:
                            for b_layers in params["film_layer_values"]:
                                found = search_interface_candidates(
                                    substrate,
                                    film,
                                    substrate_miller=params["substrate_hkl"],
                                    film_miller=params["film_hkl"],
                                    substrate_layers=a_layers,
                                    film_layers=b_layers,
                                    gap_values=params["gap_values"],
                                    max_strain=params["max_strain"],
                                    max_area=params["max_area"],
                                    max_atoms=params["max_atoms"],
                                    lateral_offsets=((0.0, 0.0),),
                                    limit=params["limit"] * len(params["gap_values"]),
                                )
                                for local_index, candidate in enumerate(found, 1):
                                    candidate.source_a = Path(substrate).name
                                    candidate.source_b = Path(film).name
                                    candidate.source_a_path = str(Path(substrate))
                                    candidate.source_b_path = str(Path(film))
                                    candidate.scan_pair_id = pair_id
                                    candidate.substrate_layers = a_layers
                                    candidate.film_layers = b_layers
                                    candidate.lightweight.name = (
                                        f"interface_A{a_index:02d}_B{b_index:02d}"
                                        f"_L{a_layers:02d}-{b_layers:02d}"
                                        f"_D{candidate.gap:.3f}_{local_index:03d}"
                                    ).replace(".", "p")
                                candidates.extend(found)
                mode = 'Interface'
            else:
                for a_index, substrate in enumerate(params["substrates"], 1):
                    for a_layers in params["substrate_layer_values"]:
                        found = search_surface_candidates(
                            substrate,
                            miller=params["substrate_hkl"],
                            layers=a_layers,
                            vacuum=params["vacuum"],
                            max_atoms=params["max_atoms"],
                            limit=params["limit"],
                        )
                        pair_id = f"A{a_index:02d}:{Path(substrate).name}"
                        for local_index, candidate in enumerate(found, 1):
                            candidate.source_a = Path(substrate).name
                            candidate.source_b = ""
                            candidate.source_a_path = str(Path(substrate))
                            candidate.source_b_path = ""
                            candidate.scan_pair_id = pair_id
                            candidate.substrate_layers = a_layers
                            candidate.film_layers = None
                            candidate.lightweight.name = (
                                f"surface_A{a_index:02d}_L{a_layers:02d}"
                                f"_{local_index:03d}"
                            )
                        candidates.extend(found)
                mode = 'Surface'
            candidates.sort(key=lambda item: (item.score, item.atoms, item.area))
            for index, candidate in enumerate(candidates):
                candidate.index = index
            self.messages.put(("search_ok", (mode, candidates)))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _search_parameters(self):
        substrates = self._structure_paths(self.substrate_path.get())
        films = self._structure_paths(self.film_path.get())
        if not substrates:
            raise ValueError('Select at least one structure A.')
        for path in substrates:
            if not Path(path).is_file():
                raise FileNotFoundError(f"Structure A does not exist: {path}")
        for path in films:
            if not Path(path).is_file():
                raise FileNotFoundError(f"Structure B does not exist: {path}")
        max_atoms = int(self.values["max_atoms"].get())
        if not 1 <= max_atoms <= 1000:
            raise ValueError('The maximum atom count must be between 1 and 1000.')
        substrate_layers = inclusive_integer_range(
            self.values["substrate_layers_min"].get(),
            self.values["substrate_layers_max"].get(),
            self.values["substrate_layers_step"].get(),
        )
        film_layers = inclusive_integer_range(
            self.values["film_layers_min"].get(),
            self.values["film_layers_max"].get(),
            self.values["film_layers_step"].get(),
        )
        gaps = inclusive_float_range(
            self.values["gap_min"].get(),
            self.values["gap_max"].get(),
            self.values["gap_step"].get(),
        )
        per_gap_limit = max(1, min(8, int(self.values["limit"].get())))
        estimated = estimate_scan_models(
            len(substrates),
            len(films) if films else 1,
            substrate_layers,
            film_layers if films else [None],
            gaps if films else [float(self.values["vacuum"].get())],
            per_gap_limit,
        )
        if estimated > MAX_SCAN_MODELS:
            raise ValueError(
                f"The current settings may generate {estimated} models, exceeding the safety limit of "
                f"{MAX_SCAN_MODELS}. Reduce the structure files, layer ranges, gap ranges or candidates per group."
            )
        return {
            "substrates": substrates,
            "films": films,
            "substrate": substrates[0],
            "film": films[0] if films else "",
            "substrate_hkl": self._hkl(self.values["substrate_hkl"].get()),
            "film_hkl": self._hkl(self.values["film_hkl"].get()),
            "substrate_layer_values": substrate_layers,
            "film_layer_values": film_layers,
            "substrate_layers": substrate_layers[0],
            "film_layers": film_layers[0],
            "vacuum": float(self.values["vacuum"].get()),
            "gap_min": gaps[0],
            "gap_max": gaps[-1],
            "gap_step": float(self.values["gap_step"].get()),
            "gap_count": len(gaps),
            "gap_values": gaps,
            "max_strain": float(self.values["max_strain"].get()) / 100.0,
            "max_area": float(self.values["max_area"].get()),
            "max_atoms": max_atoms,
            "limit": per_gap_limit,
            "estimated_models": estimated,
        }

    @staticmethod
    def _structure_paths(value):
        values = []
        for item in str(value or "").replace("\n", ";").split(";"):
            path = item.strip().strip('"')
            if path and path not in values:
                values.append(path)
        return values

    @staticmethod
    def _pair_id(a_index, substrate, b_index, film):
        return (
            f"A{a_index:02d}:{Path(substrate).name}"
            f" × B{b_index:02d}:{Path(film).name}"
        )

    def _update_estimate(self):
        try:
            substrates = self._structure_paths(self.substrate_path.get())
            films = self._structure_paths(self.film_path.get())
            if not substrates:
                self.estimate_text.set('Estimated models: select structures first')
                return
            a_layers = inclusive_integer_range(
                self.values["substrate_layers_min"].get(),
                self.values["substrate_layers_max"].get(),
                self.values["substrate_layers_step"].get(),
            )
            b_layers = inclusive_integer_range(
                self.values["film_layers_min"].get(),
                self.values["film_layers_max"].get(),
                self.values["film_layers_step"].get(),
            )
            gaps = inclusive_float_range(
                self.values["gap_min"].get(),
                self.values["gap_max"].get(),
                self.values["gap_step"].get(),
            )
            limit = max(1, int(self.values["limit"].get()))
            estimate = estimate_scan_models(
                len(substrates),
                len(films) if films else 1,
                a_layers,
                b_layers if films else [None],
                gaps if films else [0],
                limit,
            )
            warning = ' (reduce the scan range)' if estimate > MAX_SCAN_MODELS else ""
            self.estimate_text.set(
                f"Estimated maximum: {estimate} models; safety limit: {MAX_SCAN_MODELS} {warning}"
            )
        except (TypeError, ValueError):
            self.estimate_text.set('Estimated models: calculated after completing the parameters')

    @staticmethod
    def _hkl(value):
        parts = str(value).replace(",", " ").split()
        if len(parts) != 3:
            raise ValueError('Enter three integer Miller indices, for example 1 1 1.')
        result = tuple(int(part) for part in parts)
        if result == (0, 0, 0):
            raise ValueError('Miller indices cannot be 0 0 0.')
        return result

    def preview_selected(self):
        selected = self.table.selection()
        if not selected:
            return
        candidate = self.candidate_by_iid.get(selected[0])
        if candidate is not None:
            self.callbacks["preview_structure"](candidate.lightweight)

    def create_selected_workflows(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo('Create tasks', 'Select one or more candidates first.', parent=self)
            return
        candidates = [
            self.candidate_by_iid[item]
            for item in selected
            if item in self.candidate_by_iid
        ]
        if not candidates:
            messagebox.showinfo('Create tasks', 'Tasks cannot be created directly from analysis result rows.', parent=self)
            return
        self._start_workflow_worker(candidates)

    def create_all_workflows(self):
        if not self.candidates:
            messagebox.showinfo('Create tasks', 'Search for candidate structures first.', parent=self)
            return
        self._start_workflow_worker(list(self.candidates))

    def analyze_scan_results(self):
        if self.worker and self.worker.is_alive():
            return
        project_name = self.project_name.get().strip()
        output_root = self.output_root.get().strip()
        if not project_name or not output_root:
            messagebox.showwarning(
                'Analysis parameters', 'Enter the output root directory and project name first.', parent=self
            )
            return
        project_root = Path(output_root) / sanitize_job_name(project_name)
        self.status.set("Reading each candidate's 02_static/OUTCAR and comparing energies…")
        self.worker = threading.Thread(
            target=self._analysis_worker,
            args=(project_root,),
            daemon=True,
        )
        self.worker.start()

    def run_self_test(self):
        if self.worker and self.worker.is_alive():
            return
        self.status.set('Simulating 48 workflows to test concurrency, deduplication and restart recovery…')
        self.worker = threading.Thread(
            target=self._self_test_worker,
            daemon=True,
        )
        self.worker.start()

    def _self_test_worker(self):
        try:
            configured = self.config_manager.data.get("high_throughput", {})
            report = run_high_throughput_self_test(
                workflows=48,
                max_inflight=configured.get("max_inflight_jobs", 10),
            )
            self.messages.put(("self_test_ok", report))
        except Exception as exc:
            self.messages.put(("error", f"High-throughput self-test failed: {exc}"))

    def _analysis_worker(self, project_root):
        try:
            result = analyze_interface_project(project_root)
            self.messages.put(("analysis_ok", result))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def create_adaptive_workflow(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            params = self._search_parameters()
            if not params["films"]:
                raise ValueError('Adaptive interface calculation requires both structure A and structure B.')
            if not self.output_root.get().strip():
                raise ValueError('The output root directory cannot be empty.')
            output_root = Path(self.output_root.get().strip())
            project_name = self.project_name.get().strip()
            if not project_name:
                raise ValueError('The project name cannot be empty.')
            output_root.mkdir(parents=True, exist_ok=True)
            self._remember_output_directory()
            dft_u = self._parse_dft_u(self.dft_u.get())
        except Exception as exc:
            messagebox.showwarning('Invalid adaptive workflow parameters', str(exc), parent=self)
            return
        self.status.set('Creating A/B bulk-relaxation and automatic interface-rebuilding tasks…')
        args = (
            params,
            output_root,
            project_name,
            dft_u,
            self.include_pdos.get(),
            self.include_charge.get(),
            self.magnetic.get(),
            self.vdw.get(),
        )
        self.worker = threading.Thread(
            target=self._adaptive_workflow_worker,
            args=args,
            daemon=True,
        )
        self.worker.start()

    def _adaptive_workflow_worker(
        self,
        params,
        output_root,
        project_name,
        dft_u,
        include_pdos,
        include_charge,
        magnetic,
        vdw,
    ):
        try:
            results = []
            warnings = []
            failures = []
            database = TaskDatabase()
            pair_count = len(params["substrates"]) * len(params["films"])
            for a_index, substrate in enumerate(params["substrates"], 1):
                for b_index, film in enumerate(params["films"], 1):
                    pair_project = (
                        project_name
                        if pair_count == 1
                        else f"{project_name}_A{a_index:02d}_B{b_index:02d}"
                    )
                    pair_parameters = dict(params)
                    pair_parameters.update(
                        {
                            "substrate": substrate,
                            "film": film,
                            "substrates": [substrate],
                            "films": [film],
                            "scan_pair_id": self._pair_id(
                                a_index, substrate, b_index, film
                            ),
                        }
                    )
                    try:
                        result = build_adaptive_interface_workflow(
                            substrate,
                            film,
                            output_root,
                            pair_project,
                            self.config_manager.data,
                            pair_parameters,
                            database=database,
                            include_pdos=include_pdos,
                            include_charge=include_charge,
                            magnetic=magnetic,
                            dft_u=dft_u,
                            vdw=vdw,
                        )
                        results.append(result)
                        warnings.extend(result.warnings)
                    except Exception as exc:
                        failures.append(f"{pair_project}: {exc}")
            if not results:
                raise RuntimeError('All A/B combinations failed:\n' + "\n".join(failures[:8]))
            batch = write_batch_manifest(
                Path(output_root) / sanitize_job_name(project_name),
                project_name,
                "adaptive_interface",
                results,
                {
                    "pair_count": pair_count,
                    "include_pdos": include_pdos,
                    "include_charge": include_charge,
                    "magnetic": magnetic,
                    "vdw": vdw,
                },
            )
            self.messages.put(
                ("adaptive_workflow_ok", (results, warnings, failures, batch))
            )
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _start_workflow_worker(self, candidates):
        if self.worker and self.worker.is_alive():
            return
        try:
            if not self.output_root.get().strip():
                raise ValueError('The output root directory cannot be empty.')
            output_root = Path(self.output_root.get().strip())
            project_name = self.project_name.get().strip()
            if not project_name:
                raise ValueError('The project name cannot be empty.')
            output_root.mkdir(parents=True, exist_ok=True)
            self._remember_output_directory()
            dft_u = self._parse_dft_u(self.dft_u.get())
        except Exception as exc:
            messagebox.showwarning('Invalid workflow parameters', str(exc), parent=self)
            return
        self.status.set(f"Creating {len(candidates)} task groups…")
        args = (
            candidates,
            output_root,
            project_name,
            dft_u,
            self.include_pdos.get(),
            self.include_charge.get(),
            self.magnetic.get(),
            self.vdw.get(),
        )
        self.worker = threading.Thread(target=self._workflow_worker, args=args, daemon=True)
        self.worker.start()

    def _workflow_worker(
        self,
        candidates,
        output_root,
        project_name,
        dft_u,
        include_pdos,
        include_charge,
        magnetic,
        vdw,
    ):
        database = TaskDatabase()
        results = []
        warnings = []
        failures = []
        try:
            for candidate in candidates:
                try:
                    result = build_candidate_workflow(
                        candidate,
                        output_root,
                        project_name,
                        self.config_manager.data,
                        database=database,
                        include_pdos=include_pdos,
                        include_charge=include_charge,
                        magnetic=magnetic,
                        dft_u=dft_u,
                        vdw=vdw,
                    )
                    results.append(result)
                    warnings.extend(result.warnings)
                except Exception as exc:
                    name = getattr(candidate.lightweight, "name", 'Candidate')
                    failures.append(f"{name}: {exc}")
            if not results:
                raise RuntimeError('All candidates failed:\n' + "\n".join(failures[:8]))
            batch = write_batch_manifest(
                Path(output_root) / sanitize_job_name(project_name),
                project_name,
                "candidate",
                results,
                {
                    "requested_candidates": len(candidates),
                    "include_pdos": include_pdos,
                    "include_charge": include_charge,
                    "magnetic": magnetic,
                    "vdw": vdw,
                },
            )
            self.messages.put(("workflow_ok", (results, warnings, failures, batch)))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    @staticmethod
    def _parse_dft_u(text):
        text = str(text or "").strip()
        if not text:
            return {}
        result = {}
        for item in text.replace("，", ",").split(","):
            if "=" not in item:
                raise ValueError('Use the DFT+U format Fe=4.0,Ni=6.2.')
            element, value = item.split("=", 1)
            result[element.strip()] = float(value)
        return result

    def _candidate_values(self, candidate, result=None):
        result = result or {}
        layers = f"{candidate.substrate_layers or '—'}/{candidate.film_layers or '—'}"
        energy = result.get("energy_ev")
        delta = result.get("adjacent_delta_ev")
        marks = []
        if result.get("best_spacing"):
            marks.append('Best gap')
        if result.get("best_layer_screening"):
            marks.append('Layer screening')
        return (
            candidate.index + 1,
            candidate.scan_pair_id or candidate.source_a or "—",
            layers,
            f"{candidate.gap:.3f}",
            candidate.label,
            candidate.atoms,
            f"{candidate.compatibility_percent:.1f}",
            f"{energy:.8f}" if energy is not None else "—",
            f"{delta:+.8f}" if delta is not None else "—",
            "、".join(marks) or "—",
        )

    @staticmethod
    def _analysis_values(index, result):
        energy = result.get("energy_ev")
        delta = result.get("adjacent_delta_ev")
        marks = []
        if result.get("best_spacing"):
            marks.append('Best gap')
        if result.get("best_layer_screening"):
            marks.append('Layer screening')
        return (
            index + 1,
            result.get("pair_id") or "—",
            f"{result.get('substrate_layers') or '—'}/"
            f"{result.get('film_layers') or '—'}",
            (
                f"{result['gap_a']:.3f}"
                if result.get("gap_a") is not None
                else "—"
            ),
            result.get("candidate") or "—",
            result.get("atoms") or "—",
            "—",
            f"{energy:.8f}" if energy is not None else "—",
            f"{delta:+.8f}" if delta is not None else "—",
            "、".join(marks) or "—",
        )

    def _show_analysis(self, result):
        self.scan_results = {
            row["candidate"]: row for row in result.get("rows", [])
        }
        self.table.delete(*self.table.get_children())
        self.candidate_by_iid = {}
        matched = set()
        for candidate in self.candidates:
            candidate_result = self.scan_results.get(candidate.lightweight.name)
            if candidate_result:
                matched.add(candidate.lightweight.name)
            iid = f"candidate:{candidate.index}"
            self.candidate_by_iid[iid] = candidate
            self.table.insert(
                "",
                "end",
                iid=iid,
                values=self._candidate_values(candidate, candidate_result),
            )
        for index, row in enumerate(result.get("rows", [])):
            if row["candidate"] in matched:
                continue
            self.table.insert(
                "",
                "end",
                iid=f"analysis:{index}",
                values=self._analysis_values(index, row),
            )

    def _poll_messages(self):
        while not self.messages.empty():
            kind, payload = self.messages.get_nowait()
            if kind == "search_ok":
                mode, self.candidates = payload
                self.candidate_by_iid = {}
                for candidate in self.candidates:
                    iid = f"candidate:{candidate.index}"
                    self.candidate_by_iid[iid] = candidate
                    self.table.insert(
                        "",
                        "end",
                        iid=iid,
                        values=self._candidate_values(candidate),
                    )
                if self.candidates:
                    self.table.selection_set("candidate:0")
                    self.status.set(
                        f"Found {len(self.candidates)} {mode} candidates; "
                        'select multiple candidates to create calculations, then analyze their energies.'
                    )
                    self.preview_selected()
                else:
                    self.status.set('No candidates satisfy the current strain, area and atom-count limits.')
            elif kind == "workflow_ok":
                results, warnings, failures, batch = payload
                self.status.set(f"Created {len(results)} workflows. Start the queue in Task center.")
                text = (
                    f"Created/restored {len(results)} relax → static → PDOS/charge-difference workflows.\n"
                    f"Batch ID: {batch['batch_id']}; tasks: {batch['task_count']}。"
                )
                if failures:
                    text += '\n\nSome candidates failed; other tasks are unaffected:\n' + "\n".join(failures[:6])
                if warnings:
                    text += (
                        '\n\nSome input files are incomplete; the relevant first tasks are paused:\n'
                        + "\n".join(warnings[:8])
                    )
                messagebox.showinfo('High-throughput tasks created', text, parent=self)
                self.callbacks["open_task_center"]()
            elif kind == "adaptive_workflow_ok":
                results, warnings, failures, batch = payload
                self.status.set(
                    f"{len(results)} A/B bulk-relaxation and automatic interface-rebuilding workflows added to Task center."
                )
                text = (
                    f"Created adaptive workflows for {len(results)} A/B structure combinations:\n"
                    'Bulk A relaxation + bulk B relaxation → automatic interface rematching → '
                    'interface relaxation/static/PDOS/charge difference.'
                    f"\nBatch ID: {batch['batch_id']}; tasks: {batch['task_count']}。"
                )
                if failures:
                    text += '\n\nSome combinations failed; other tasks are unaffected:\n' + "\n".join(failures[:6])
                if warnings:
                    text += (
                        '\n\nPOTCAR files are incomplete; the relevant tasks are paused:\n'
                        + "\n".join(warnings[:8])
                    )
                messagebox.showinfo('Adaptive workflows created', text, parent=self)
                self.callbacks["open_task_center"]()
            elif kind == "analysis_ok":
                self._show_analysis(payload)
                completed = payload["completed"]
                total = payload["total"]
                self.status.set(
                    f"Energy analysis completed: {completed}/{total} static calculations have results."
                )
                messagebox.showinfo(
                    'Gap/layer analysis completed',
                    (
                        f"Read {completed}/{total} 02_static results.\n\n"
                        'Same structures and layers: determine the best gap by total energy;\n'
                        'Different layer counts: preliminary screening by energy per atom.\n\n'
                        f"Tables and best structures saved to:\n{payload['analysis_dir']}"
                    ),
                    parent=self,
                )
            elif kind == "self_test_ok":
                report = payload
                verdict = 'Passed' if report.passed else 'Failed'
                self.status.set(
                    f"High-throughput self-test {verdict}：{report.workflows} workflows, "
                    f"{report.tasks} tasks, elapsed {report.elapsed_seconds:.3f} seconds."
                )
                messagebox.showinfo(
                    f"High-throughput self-test {verdict}",
                    (
                        f"Local high-throughput control self-test: {verdict}\n\n"
                        + "\n".join(report.checks)
                        + f"\n\nSimulated submissions: {report.submitted}; "
                        f"Total elapsed: {report.elapsed_seconds:.3f} seconds.\n\n"
                        'This validates the task database, dependencies, concurrency limits, deduplication and error recovery; '
                        'real VASP capacity still depends on the cluster, license, POTCAR and queue configuration.'
                    ),
                    parent=self,
                )
            elif kind == "error":
                self.status.set('Operation failed.')
                messagebox.showerror('High-throughput calculations', payload, parent=self)
        self._poll_id = self.after(250, self._poll_messages)

    def _close(self):
        self._remember_output_directory()
        if self._poll_id:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self.destroy()
