import tkinter as tk
from collections import Counter
from tkinter import ttk
from app.ui.responsive_rows import WrappingRow, WidthLabel


class RightPanel(ttk.Frame):
    def __init__(self, master, tr, callbacks):
        super().__init__(master, padding=6)
        self.tr = tr
        self.callbacks = callbacks
        self.selection_label = None
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        selection_page = ttk.Frame(self.tabs, padding=(4, 6))
        slab_page = ttk.Frame(self.tabs, padding=(4, 6))
        self.tabs.add(selection_page, text='Selection')
        self.tabs.add(slab_page, text='Slab')
        self._build_selection(selection_page)
        self._build_slab(slab_page)

    def _build_selection(self, parent):
        card = ttk.LabelFrame(
            parent,
            text='Selection actions',
            style="Card.TLabelframe",
            padding=(10, 8),
        )
        card.pack(fill="x", pady=(0, 8))

        ttk.Label(card, text=self.tr("selection_mode"), style="Panel.TLabel").pack(
            anchor="w", pady=(0, 3)
        )
        self.mode = tk.StringVar(value="click")
        row = ttk.Frame(card, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Radiobutton(
            row,
            text=self.tr("click_select"),
            variable=self.mode,
            value="click",
        ).pack(anchor="w")
        ttk.Radiobutton(
            row,
            text=self.tr("box_select"),
            variable=self.mode,
            value="box",
        ).pack(anchor="w", pady=(3, 0))

        summary = ttk.Frame(card, style="SectionHeader.TFrame", padding=(8, 6))
        summary.pack(fill="x", pady=(8, 8))
        self.selection_label = WidthLabel(
            summary,
            text=self.tr("selected_none"),
            style="SectionTitle.TLabel",
            wraplength=260,
            justify="left",
        )
        self.selection_label.pack(fill="x")

        buttons = WrappingRow(card, style="Panel.TFrame")
        buttons.pack(fill="x")
        buttons.add(ttk.Button(
            buttons,
            text=self.tr("fix_selection"),
            style="Primary.TButton",
            command=self.callbacks["fix"],
        ))
        buttons.add(ttk.Button(
            buttons,
            text=self.tr("replace_selection"),
            style="Compact.TButton",
            command=self.callbacks["replace"],
        ))
        buttons.add(ttk.Button(
            buttons,
            text=self.tr("delete_selection"),
            style="Danger.TButton",
            command=self.callbacks["delete"],
        ))

        coordinate = ttk.LabelFrame(card, text='POSCAR options', padding=(8, 5))
        coordinate.pack(fill="x", pady=(9, 0))
        self.coordinate_mode = tk.StringVar(value="Direct")
        ttk.Radiobutton(
            coordinate,
            text='Direct coordinates',
            variable=self.coordinate_mode,
            value="Direct",
        ).pack(anchor="w")
        ttk.Radiobutton(
            coordinate,
            text='Cartesian coordinates',
            variable=self.coordinate_mode,
            value="Cartesian",
        ).pack(anchor="w")
        self.selective_dynamics = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            coordinate,
            text='Selective dynamics',
            variable=self.selective_dynamics,
        ).pack(anchor="w", pady=(3, 0))

    def _build_slab(self, parent):
        card = ttk.LabelFrame(
            parent,
            text=self.tr("slab_builder"),
            style="Card.TLabelframe",
            padding=(10, 8),
        )
        card.pack(fill="x")
        grid = ttk.Frame(card, style="Panel.TFrame")
        grid.pack(fill="x")
        ttk.Label(grid, text=self.tr("miller_index"), style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.miller_vars = []
        for index, value in enumerate(["1", "0", "0"]):
            var = tk.StringVar(value=value)
            self.miller_vars.append(var)
            ttk.Entry(grid, textvariable=var, width=5, justify="center").grid(
                row=0, column=index + 1, sticky="ew", padx=(4, 0), pady=5
            )

        self.slab_fields = {}
        fields = [
            (self.tr("layer_count"), "6", "layers"),
            (self.tr("slab_thickness"), "12.00", "thickness"),
            (self.tr("vacuum_thickness"), "15.00", "vacuum"),
            ('Fixed bottom layers', "2", "fixed_layers"),
            ('Layer tolerance (Å)', "0.20", "layer_tolerance"),
        ]
        for row_index, (label, value, key) in enumerate(fields, 1):
            ttk.Label(grid, text=label, style="Panel.TLabel").grid(
                row=row_index, column=0, sticky="w", pady=5
            )
            var = tk.StringVar(value=value)
            self.slab_fields[key] = var
            ttk.Entry(grid, textvariable=var).grid(
                row=row_index,
                column=1,
                columnspan=3,
                sticky="ew",
                padx=(4, 0),
                pady=5,
            )

        self.center_slab = tk.BooleanVar(value=True)
        ttk.Checkbutton(grid, text='Center slab', variable=self.center_slab).grid(
            row=6, column=0, columnspan=4, sticky="w", pady=5
        )

        ttk.Label(grid, text=self.tr("termination"), style="Panel.TLabel").grid(
            row=7, column=0, sticky="w", pady=5
        )
        self.termination = tk.StringVar(value="0: auto")
        self.termination_combo = ttk.Combobox(
            grid,
            textvariable=self.termination,
            values=["0: auto"],
            state="readonly",
        )
        self.termination_combo.grid(
            row=7, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=5
        )
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(2, weight=1)
        grid.columnconfigure(3, weight=1)

        ttk.Button(
            card,
            text=self.tr("preview_slab"),
            style="Primary.TButton",
            command=lambda: self.callbacks["preview_slab"](self.get_slab_params()),
        ).pack(fill="x", pady=(10, 5))
        ttk.Button(
            card,
            text='List terminations',
            command=lambda: self.callbacks["list_terminations"](self.get_slab_params()),
        ).pack(fill="x", pady=(0, 5))
        row = WrappingRow(card, style="Panel.TFrame")
        row.pack(fill="x")
        row.add(ttk.Button(
            row,
            text=self.tr("generate_slab"),
            command=lambda: self.callbacks["apply_slab"](self.get_slab_params()),
        ))
        row.add(ttk.Button(
            row,
            text=self.tr("generate_all_terminations"),
            command=lambda: self.callbacks["list_terminations"](self.get_slab_params()),
        ))
        ttk.Button(
            card,
            text='Export POSCAR',
            command=lambda: self.callbacks["export_slab_poscar"](),
        ).pack(fill="x", pady=(5, 0))

    def get_slab_params(self):
        def as_int(value, default):
            try:
                return int(value)
            except ValueError:
                return default

        def as_float(value, default):
            try:
                return float(value)
            except ValueError:
                return default

        return {
            "h": as_int(self.miller_vars[0].get(), 1),
            "k": as_int(self.miller_vars[1].get(), 0),
            "l": as_int(self.miller_vars[2].get(), 0),
            "layers": as_int(self.slab_fields["layers"].get(), 6),
            "thickness": as_float(self.slab_fields["thickness"].get(), 12.0),
            "vacuum": as_float(self.slab_fields["vacuum"].get(), 15.0),
            "fixed_layers": as_int(self.slab_fields["fixed_layers"].get(), 2),
            "layer_tolerance": as_float(
                self.slab_fields["layer_tolerance"].get(), 0.2
            ),
            "center_slab": self.center_slab.get(),
            "termination": self.termination.get(),
            "termination_index": as_int(
                self.termination.get().split(":", 1)[0], 0
            ),
        }

    def get_poscar_options(self):
        return self.coordinate_mode.get(), self.selective_dynamics.get()

    def set_terminations(self, terminations):
        values = [f"{item.index}: {item.label}" for item in terminations] or ["0: auto"]
        self.termination_combo.configure(values=values)
        self.termination.set(values[0])

    def update_selection(self, index, atom, structure=None):
        if not structure:
            self.selection_label.configure(
                text=(
                    f"1 atom selected\nIndex: {index + 1}  Element: {atom.element}\n"
                    f"Coordinates: ({atom.x:.3f}, {atom.y:.3f}, {atom.z:.3f})"
                )
            )
            return
        selected = [item for item in structure.atoms if item.selected]
        if not selected:
            self.selection_label.configure(text=self.tr("selected_none"))
            return
        counts = Counter(item.element for item in selected)
        composition = "，".join(f"{key} {value} " for key, value in counts.items())
        fixed_count = sum(bool(item.fixed) for item in selected)
        state_text = (
            f" · Fixed: {fixed_count} (orange)"
            if fixed_count
            else ' · Pending action (cyan)'
        )
        self.selection_label.configure(
            text=(
                f"Selected {len(selected)} atoms · {composition}{state_text}\n"
                f"Current indices: {index + 1}  Element: {atom.element}\n"
                f"Coordinates: ({atom.x:.3f}, {atom.y:.3f}, {atom.z:.3f})"
            )
        )

    def clear_selection(self):
        self.selection_label.configure(text=self.tr("selected_none"))
