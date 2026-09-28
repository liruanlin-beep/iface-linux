import math
import tkinter as tk
from tkinter import messagebox, ttk

from app.core.structure_model import Atom
from app.ui.theme import BG


class StructureToolsDialog(tk.Toplevel):
    """Selection, measurement and common structure-editing tools."""

    def __init__(self, master, callbacks):
        super().__init__(master)
        self.callbacks = callbacks
        self.title('Structure tools')
        width = min(720, max(600, self.winfo_screenwidth() - 80))
        height = min(680, max(520, self.winfo_screenheight() - 120))
        self.geometry(f"{width}x{height}")
        self.minsize(min(600, width), min(520, height))
        self.transient(master)
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        self.selection_page = ttk.Frame(tabs, padding=14)
        self.measure_page = ttk.Frame(tabs, padding=14)
        self.edit_host = ttk.Frame(tabs)
        self.edit_host.rowconfigure(0, weight=1)
        self.edit_host.columnconfigure(0, weight=1)
        self.edit_canvas = tk.Canvas(
            self.edit_host, bg=BG, highlightthickness=0, borderwidth=0
        )
        edit_scrollbar = ttk.Scrollbar(
            self.edit_host, orient="vertical", command=self.edit_canvas.yview
        )
        self.edit_canvas.configure(yscrollcommand=edit_scrollbar.set)
        self.edit_canvas.grid(row=0, column=0, sticky="nsew")
        edit_scrollbar.grid(row=0, column=1, sticky="ns")
        self.edit_page = ttk.Frame(self.edit_canvas, padding=14)
        self._edit_window = self.edit_canvas.create_window(
            (0, 0), window=self.edit_page, anchor="nw"
        )
        self.edit_page.bind(
            "<Configure>",
            lambda _event: self.edit_canvas.configure(
                scrollregion=self.edit_canvas.bbox("all")
            ),
        )
        self.edit_canvas.bind(
            "<Configure>",
            lambda event: self.edit_canvas.itemconfigure(
                self._edit_window, width=max(1, event.width)
            ),
        )
        self.edit_canvas.bind("<Enter>", self._bind_edit_scroll)
        self.edit_canvas.bind("<Leave>", self._unbind_edit_scroll)
        tabs.add(self.selection_page, text='Batch selection')
        tabs.add(self.measure_page, text='Measure')
        tabs.add(self.edit_host, text='Edit structure')
        self._build_selection()
        self._build_measure()
        self._build_edit()

    def _bind_edit_scroll(self, _event=None):
        self.bind_all("<MouseWheel>", self._scroll_edit_page)

    def _unbind_edit_scroll(self, _event=None):
        self.unbind_all("<MouseWheel>")

    def _scroll_edit_page(self, event):
        self.edit_canvas.yview_scroll(int(-event.delta / 120), "units")

    def structure(self):
        return self.callbacks["get_structure"]()

    def _build_selection(self):
        page = self.selection_page
        ttk.Label(page, text='Select by element').grid(row=0, column=0, sticky="w", pady=6)
        self.element = tk.StringVar()
        self.element_combo = ttk.Combobox(page, textvariable=self.element, width=18)
        self.element_combo.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(page, text='Select', command=self.select_element).grid(row=0, column=2)

        ttk.Label(page, text='Coordinate range').grid(row=1, column=0, sticky="nw", pady=10)
        range_box = ttk.Frame(page)
        range_box.grid(row=1, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        self.range_vars = {}
        for row, axis in enumerate(("X", "Y", "Z")):
            ttk.Label(range_box, text=axis).grid(row=row, column=0, padx=4, pady=3)
            low = tk.StringVar()
            high = tk.StringVar()
            self.range_vars[axis] = (low, high)
            ttk.Entry(range_box, textvariable=low, width=10).grid(row=row, column=1)
            ttk.Label(range_box, text="—").grid(row=row, column=2, padx=5)
            ttk.Entry(range_box, textvariable=high, width=10).grid(row=row, column=3)
        ttk.Button(page, text='Select range', command=self.select_range).grid(
            row=2, column=1, sticky="w", padx=8, pady=8
        )
        ttk.Button(page, text='Clear selection', command=self.clear_selection).grid(
            row=2, column=2, sticky="e", pady=8
        )
        ttk.Label(page, text='Layer height Z ± tolerance').grid(row=3, column=0, sticky="w", pady=6)
        layer_row = ttk.Frame(page)
        layer_row.grid(row=3, column=1, sticky="w", padx=8)
        self.layer_z = tk.StringVar(value="0")
        self.layer_tol = tk.StringVar(value="0.25")
        ttk.Entry(layer_row, textvariable=self.layer_z, width=9).pack(side="left")
        ttk.Label(layer_row, text=" ± ").pack(side="left")
        ttk.Entry(layer_row, textvariable=self.layer_tol, width=9).pack(side="left")
        ttk.Button(page, text='Select layer', command=self.select_layer).grid(row=3, column=2)
        ttk.Separator(page).grid(row=4, column=0, columnspan=3, sticky="ew", pady=12)
        ttk.Label(
            page,
            text='Leave a range blank for no limit. Selected atoms can be measured, fixed, substituted or deleted.',
            wraplength=500,
        ).grid(row=5, column=0, columnspan=3, sticky="w")
        page.columnconfigure(1, weight=1)
        self.bind("<Map>", self._refresh_elements, add="+")

    def _refresh_elements(self, _event=None):
        structure = self.structure()
        self.element_combo.configure(values=structure.elements if structure else ())

    def _apply_selection(self, predicate):
        structure = self.structure()
        if not structure:
            return
        structure.clear_selection()
        for atom in structure.atoms:
            atom.selected = bool(predicate(atom))
        self.callbacks["refresh"]()

    def select_element(self):
        element = self.element.get().strip()
        if element:
            self._apply_selection(lambda atom: atom.element.lower() == element.lower())

    def select_range(self):
        parsed = {}
        try:
            for axis, pair in self.range_vars.items():
                parsed[axis] = tuple(
                    float(value.get()) if value.get().strip() else None for value in pair
                )
        except ValueError:
            messagebox.showerror('Coordinate range', 'Range limits must be numbers or blank.', parent=self)
            return

        def inside(atom):
            for axis, value in zip(("X", "Y", "Z"), (atom.x, atom.y, atom.z)):
                low, high = parsed[axis]
                if low is not None and value < low:
                    return False
                if high is not None and value > high:
                    return False
            return True

        self._apply_selection(inside)

    def select_layer(self):
        try:
            center = float(self.layer_z.get())
            tolerance = max(0.0, float(self.layer_tol.get()))
        except ValueError:
            messagebox.showerror('Select by layer', 'Layer height and tolerance must be numbers.', parent=self)
            return
        self._apply_selection(lambda atom: abs(atom.z - center) <= tolerance)

    def clear_selection(self):
        structure = self.structure()
        if structure:
            structure.clear_selection()
            self.callbacks["refresh"]()

    def _build_measure(self):
        page = self.measure_page
        ttk.Label(
            page,
            text='Select the required atoms in order in the structure view (or right-drag a box), then measure.',
            wraplength=520,
        ).pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(page)
        row.pack(fill="x")
        ttk.Button(row, text='Two-point distance', command=lambda: self.measure(2)).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(row, text='Three-point angle', command=lambda: self.measure(3)).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(row, text='Four-point dihedral', command=lambda: self.measure(4)).pack(side="left", expand=True, fill="x", padx=3)
        self.measure_result = tk.Text(page, height=12, wrap="word")
        self.measure_result.pack(fill="both", expand=True, pady=(14, 0))

    def measure(self, required):
        structure = self.structure()
        indices = structure.selected_indices() if structure else []
        if len(indices) != required:
            messagebox.showinfo(
                'Structure measurement',
                f"This measurement requires exactly {required} atoms; currently selected: {len(indices)}.",
                parent=self,
            )
            return
        points = [
            (structure.atoms[i].x, structure.atoms[i].y, structure.atoms[i].z)
            for i in indices
        ]
        if required == 2:
            value = math.dist(points[0], points[1])
            result = f"Atoms {indices[0] + 1}—{indices[1] + 1}\nDistance = {value:.6f} Å"
        elif required == 3:
            value = _angle(points[0], points[1], points[2])
            result = f"Atoms {'—'.join(str(i + 1) for i in indices)}\nBond angle = {value:.4f}°"
        else:
            value = _dihedral(*points)
            result = f"Atoms {'—'.join(str(i + 1) for i in indices)}\nDihedral = {value:.4f}°"
        self.measure_result.delete("1.0", "end")
        self.measure_result.insert("1.0", result)

    def _build_edit(self):
        page = self.edit_page
        vacuum = ttk.LabelFrame(page, text='Vacuum and fixed layers', padding=10)
        vacuum.pack(fill="x", pady=(0, 10))
        self.vacuum = tk.StringVar(value="15")
        self.fixed_layers = tk.StringVar(value="2")
        self.layer_tolerance = tk.StringVar(value="0.25")
        _field(vacuum, 0, 'Vacuum thickness (Å)', self.vacuum)
        _field(vacuum, 1, 'Fixed bottom layers', self.fixed_layers)
        _field(vacuum, 2, 'Layer tolerance (Å)', self.layer_tolerance)
        ttk.Button(vacuum, text='Set vacuum and center', command=self.set_vacuum).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 3))
        ttk.Button(vacuum, text='Fix bottom atom layers', command=self.fix_bottom_layers).grid(row=4, column=0, columnspan=2, sticky="ew", pady=3)
        vacuum.columnconfigure(1, weight=1)

        defect = ttk.LabelFrame(page, text='Defects and adsorbates', padding=10)
        defect.pack(fill="x")
        self.defect_element = tk.StringVar(value="H")
        self.adsorb_coords = [tk.StringVar(value=value) for value in ("0", "0", "0")]
        _field(defect, 0, 'Element', self.defect_element)
        coords = ttk.Frame(defect)
        coords.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(defect, text='X/Y/Z coordinates (Å)').grid(row=1, column=0, sticky="w")
        for index, variable in enumerate(self.adsorb_coords):
            ttk.Entry(coords, textvariable=variable, width=8).pack(side="left", padx=(0, 4))
        ttk.Button(defect, text='Add adsorbate atom', command=self.add_atom).grid(row=2, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Button(defect, text='Substitute selected atoms', command=self.replace_selected).grid(row=3, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Button(defect, text='Delete selected atoms (vacancies)', command=self.delete_selected).grid(row=4, column=0, columnspan=2, sticky="ew", pady=3)
        defect.columnconfigure(1, weight=1)

    def _mutate(self, operation):
        structure = self.structure()
        if not structure or not structure.atoms:
            return
        self.callbacks["before_change"]()
        operation(structure)
        structure.pmg_structure = None
        self.callbacks["changed"]()

    def set_vacuum(self):
        try:
            vacuum = max(0.0, float(self.vacuum.get()))
        except ValueError:
            messagebox.showerror('Vacuum', 'Enter a valid thickness.', parent=self)
            return

        def operation(structure):
            c = structure.cell[2]
            length = math.sqrt(sum(value * value for value in c))
            if length < 1e-9:
                raise ValueError('Invalid lattice c-axis length.')
            unit = tuple(value / length for value in c)
            projections = [atom.x * unit[0] + atom.y * unit[1] + atom.z * unit[2] for atom in structure.atoms]
            low, high = min(projections), max(projections)
            new_length = max(1.0, high - low + vacuum)
            target_low = vacuum / 2.0
            shift = target_low - low
            for atom in structure.atoms:
                atom.x += unit[0] * shift
                atom.y += unit[1] * shift
                atom.z += unit[2] * shift
            structure.cell = (structure.cell[0], structure.cell[1], tuple(value * new_length for value in unit))

        try:
            self._mutate(operation)
        except ValueError as exc:
            messagebox.showerror('Vacuum', str(exc), parent=self)

    def fix_bottom_layers(self):
        try:
            count = max(1, int(self.fixed_layers.get()))
            tolerance = max(0.01, float(self.layer_tolerance.get()))
        except ValueError:
            messagebox.showerror('Fix atom layers', 'Invalid layer count or tolerance.', parent=self)
            return

        def operation(structure):
            c = structure.cell[2]
            length = math.sqrt(sum(value * value for value in c)) or 1.0
            unit = tuple(value / length for value in c)
            ordered = sorted(
                enumerate(structure.atoms),
                key=lambda item: item[1].x * unit[0] + item[1].y * unit[1] + item[1].z * unit[2],
            )
            layers = []
            for index, atom in ordered:
                position = atom.x * unit[0] + atom.y * unit[1] + atom.z * unit[2]
                if not layers or abs(position - layers[-1][0]) > tolerance:
                    layers.append([position, []])
                layers[-1][1].append(index)
            fixed = {index for _position, indices in layers[:count] for index in indices}
            for index, atom in enumerate(structure.atoms):
                atom.fixed = index in fixed

        self._mutate(operation)

    def add_atom(self):
        try:
            coords = [float(variable.get()) for variable in self.adsorb_coords]
        except ValueError:
            messagebox.showerror('Add atom', 'Coordinates must be numbers.', parent=self)
            return
        element = self.defect_element.get().strip()
        if not element:
            return
        self._mutate(lambda structure: structure.atoms.append(Atom(element, *coords)))

    def replace_selected(self):
        element = self.defect_element.get().strip()
        if element:
            self._mutate(lambda structure: structure.replace_selected(element))

    def delete_selected(self):
        self._mutate(lambda structure: structure.delete_selected())


def _field(parent, row, label, variable):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
    ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)


def _angle(a, b, c):
    first = tuple(a[i] - b[i] for i in range(3))
    second = tuple(c[i] - b[i] for i in range(3))
    denominator = math.sqrt(sum(v * v for v in first) * sum(v * v for v in second))
    if denominator < 1e-12:
        return 0.0
    cosine = max(-1.0, min(1.0, sum(first[i] * second[i] for i in range(3)) / denominator))
    return math.degrees(math.acos(cosine))


def _dihedral(a, b, c, d):
    b0 = [b[i] - a[i] for i in range(3)]
    b1 = [c[i] - b[i] for i in range(3)]
    b2 = [d[i] - c[i] for i in range(3)]
    norm = math.sqrt(sum(value * value for value in b1)) or 1.0
    b1 = [value / norm for value in b1]
    v = [b0[i] - sum(b0[j] * b1[j] for j in range(3)) * b1[i] for i in range(3)]
    w = [b2[i] - sum(b2[j] * b1[j] for j in range(3)) * b1[i] for i in range(3)]
    x = sum(v[i] * w[i] for i in range(3))
    cross = (
        b1[1] * v[2] - b1[2] * v[1],
        b1[2] * v[0] - b1[0] * v[2],
        b1[0] * v[1] - b1[1] * v[0],
    )
    y = sum(cross[i] * w[i] for i in range(3))
    return math.degrees(math.atan2(y, x))
