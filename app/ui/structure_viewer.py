import math
import tkinter as tk
from itertools import product
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from app.core.element_color_manager import get_element_color
from app.core.structure_model import project_point
from app.core.platform_utils import UI_FONT
from app.ui.theme import BLUE, BORDER_STRONG, MUTED, PANEL, PANEL_ALT, TEXT
from app.ui.widgets import ToolTip


FIXED_ATOM_COLOR = "#FF8A3D"
FIXED_ATOM_OUTLINE = "#7C2D12"
SELECTED_ATOM_COLOR = "#22D3EE"
SELECTED_ATOM_OUTLINE = "#ECFEFF"


class StructureViewer(ttk.Frame):
    def __init__(self, master, on_select=None, on_undo=None, on_redo=None):
        super().__init__(master, style="Panel.TFrame", padding=8)
        self.structure = None
        self.on_select = on_select
        self.on_undo = on_undo
        self.on_redo = on_redo
        self.scale = 48
        self.rx = -0.58
        self.rz = 0.72
        self._drag = None
        self._drag_origin = None
        self._box_start = None
        self._box_rect = None
        self._box_additive = False
        self.screen_atoms = []
        self.display_mode = tk.StringVar(value='VESTA full cell')
        self._auto_fit_pending = False
        self.auto_rotate = tk.BooleanVar(value=False)
        self.rotate_step = tk.StringVar(value="15")
        self._auto_rotate_job = None
        self._redraw_job = None
        self._scene_cache = None
        self._legend_signature = None
        self._info_cache = {}
        self._background_source = None
        self._background_render = None
        self._background_render_size = None
        self.show_bonds = tk.BooleanVar(value=True)
        self.atom_style = tk.StringVar(value='VESTA ball-and-stick')
        self.quality = tk.StringVar(value='Standard')
        self._radius_cache = {}
        self._interactive_motion = False
        self._full_info_text = ""
        self._control_layout = None
        self._viewer_layout_job = None

        self.title = ttk.Label(self, text='Structure viewer: no structure loaded', style="Title.TLabel")
        self.title.pack(anchor="w", fill="x", pady=(0, 3))
        self.info = ttk.Label(self, text="", style="Muted.TLabel", wraplength=760, justify="left")
        self.info.pack(anchor="w", pady=(0, 5), fill="x")
        self._info_tooltip = ToolTip(self.info, 'Import a structure to view cell information')
        self.canvas = tk.Canvas(
            self,
            bg=PANEL_ALT,
            highlightthickness=2,
            highlightbackground=BORDER_STRONG,
            highlightcolor=BLUE,
            height=240,
        )
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_rotate)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonPress-3>", self._box_press)
        self.canvas.bind("<B3-Motion>", self._box_drag)
        self.canvas.bind("<ButtonRelease-3>", self._box_release)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda _e: self.zoom(1.08))
        self.canvas.bind("<Button-5>", lambda _e: self.zoom(0.92))

        self._build_view_controls()
        # Reserve controls first; the expandable canvas receives the remaining
        # height, including when the center pane is short on a laptop screen.
        self.canvas.pack(fill="both", expand=True)
        self.bind("<Configure>", self._schedule_viewer_layout, add="+")
        self.after_idle(self._layout_viewer_controls)
        self.display_mode.trace_add("write", self._display_mode_changed)
        self.atom_style.trace_add("write", lambda *_args: self.redraw())
        self.quality.trace_add("write", lambda *_args: self.redraw())

    def _build_view_controls(self):
        ttk.Style(self).configure("Viewer.TButton", padding=(4, 3))
        self.controls = ttk.Frame(self, style="Panel.TFrame", padding=(0, 4, 0, 0))
        self.controls.pack(side="bottom", fill="x", pady=(5, 0))
        self.control_toolbar = ttk.Frame(self.controls, style="Panel.TFrame")
        self.control_toolbar.pack(fill="x")
        self.control_toolbar.bind("<Configure>", lambda _event: self._schedule_viewer_layout(), add="+")
        self.control_toolbar.columnconfigure(50, weight=1)
        self.legend = ttk.Frame(self.controls, style="Panel.TFrame")
        self.legend.pack(fill="x", pady=(3, 0))
        ToolTip(self.canvas, 'Drag to rotate · Wheel to zoom · Right-drag to select · Ctrl+right-drag to extend')

        self._primary_view_buttons = []
        self._extra_view_buttons = []
        commands = [
            ("Undo", 'Undo', self.on_undo),
            ("Redo", 'Redo', self.on_redo),
            ("A", 'View along crystal A axis', lambda: self.set_axis_view("a")),
            ("B", 'View along crystal B axis', lambda: self.set_axis_view("b")),
            ("C", 'View along crystal C axis', lambda: self.set_axis_view("c")),
            ("Fit", 'Fit to window', self.fit_to_view),
            ("-", 'Zoom out', lambda: self.zoom(0.88)),
            ("+", 'Zoom in', lambda: self.zoom(1.12)),
            ("Home", 'Reset view', self.reset_view),
        ]
        for index, (text, tip, command) in enumerate(commands):
            button = ttk.Button(self.control_toolbar, text=text, width=max(2, len(text) + 1),
                                style="Viewer.TButton", command=command)
            if command is None:
                button.state(["disabled"])
            ToolTip(button, tip)
            target = self._primary_view_buttons if index < 6 else self._extra_view_buttons
            target.append(button)

        self.view_menu_button = ttk.Menubutton(self.control_toolbar, text='View', takefocus=True)
        self.view_menu = tk.Menu(self.view_menu_button, tearoff=False)
        self.view_menu_button.configure(menu=self.view_menu)
        self.view_menu.add_command(label='Structure information…', command=self._show_structure_info)
        self.view_menu.add_separator()
        for label, variable, values in [
            ('Display range', self.display_mode, ['VESTA full cell', 'Original atoms', '2×2×1 preview']),
            ('Atom style', self.atom_style, ['VESTA ball-and-stick', 'Space-filling']),
            ('Rendering quality', self.quality, ['Fast', 'Standard', 'High quality']),
        ]:
            submenu = tk.Menu(self.view_menu, tearoff=False)
            for value in values:
                submenu.add_radiobutton(label=value, variable=variable, value=value)
            self.view_menu.add_cascade(label=label, menu=submenu)
        self.view_menu.add_checkbutton(label='Show chemical bonds', variable=self.show_bonds, command=self.redraw)
        self.view_menu.add_separator()
        for axis in ("a", "b", "c"):
            self.view_menu.add_command(label=f"View along crystal {axis.upper()} axis", command=lambda value=axis: self.set_axis_view(value))
        for label, command in [('Fit to window', self.fit_to_view), ('Zoom out', lambda: self.zoom(0.88)),
                               ('Zoom in', lambda: self.zoom(1.12)), ('Reset view', self.reset_view)]:
            self.view_menu.add_command(label=label, command=command)
        self.view_menu.add_separator()
        self.view_menu.add_command(label='Rotate left', command=lambda: self.rotate_by(-self._rotation_step()))
        self.view_menu.add_command(label='Rotate right', command=lambda: self.rotate_by(self._rotation_step()))
        steps = tk.Menu(self.view_menu, tearoff=False)
        for value in ("5", "15", "30", "45", "90"):
            steps.add_radiobutton(label=f"{value}°", variable=self.rotate_step, value=value)
        steps.add_command(label='Custom step…', command=self._choose_rotation_step)
        self.view_menu.add_cascade(label='Rotation step', menu=steps)
        self.view_menu.add_checkbutton(label='Auto-rotate', variable=self.auto_rotate, command=self.toggle_auto_rotate)
        self.view_menu.add_separator()
        for label, command in [('Undo', self.on_undo), ('Redo', self.on_redo)]:
            self.view_menu.add_command(label=label, command=command, state="normal" if command else "disabled")
        ToolTip(self.view_menu_button, 'Display range, atom style, rendering quality, rotation and full structure information')

    def _choose_rotation_step(self):
        value = simpledialog.askfloat('Rotation step', 'Angle per rotation step (1–180°)', initialvalue=self._rotation_step(),
                                      minvalue=1, maxvalue=180, parent=self)
        if value is not None:
            self.rotate_step.set(f"{value:g}")

    def _show_structure_info(self):
        messagebox.showinfo('Structure information', self._full_info_text or 'No structure loaded.', parent=self)

    def _schedule_viewer_layout(self, event=None):
        if event is not None and event.widget is not self:
            return
        if self._viewer_layout_job is None:
            self._viewer_layout_job = self.after_idle(self._layout_viewer_controls)

    def _layout_viewer_controls(self):
        self._viewer_layout_job = None
        available = max(1, self.winfo_width() - 16)
        visible = list(self._primary_view_buttons)
        menu_width = self.view_menu_button.winfo_reqwidth() + 4
        width_of = lambda items: sum(item.winfo_reqwidth() + 4 for item in items) + menu_width
        # Every omitted action remains in the keyboard-accessible view menu.
        while len(visible) > 1 and width_of(visible) > available:
            visible.pop(1 if len(visible) == len(self._primary_view_buttons) else 0)
        for group in (self._extra_view_buttons[:2], self._extra_view_buttons[2:]):
            if width_of(visible + group) <= available:
                visible.extend(group)
        signature = tuple((str(button), button.winfo_reqwidth()) for button in visible)
        if signature != self._control_layout:
            self._control_layout = signature
            for button in self._primary_view_buttons + self._extra_view_buttons:
                button.grid_remove()
            for column, button in enumerate(visible):
                button.grid(row=0, column=column, padx=(0, 4), sticky="w")
            self.view_menu_button.grid(row=0, column=51, sticky="e")
        self.info.configure(wraplength=max(180, available))
        if self.structure and (available < 700 or self.winfo_height() < 450):
            summary = f"{len(self.structure.atoms)} atoms · " + " / ".join(self.structure.elements)
            self.info.configure(text=summary)
        else:
            self.info.configure(text=self._full_info_text)
        self._layout_legend()

    def _layout_legend(self):
        available = max(1, self.winfo_width() - 16)
        row = column = used = 0
        children = self.legend.winfo_children()
        for child in children:
            child.pack_forget()
        for child in children:
            width = child.winfo_reqwidth() + 12
            if used and used + width > available:
                row += 1
                column = used = 0
            child.grid(row=row, column=column, sticky="w", padx=(0, 12), pady=(0, 1))
            used += width
            column += 1

    def set_structure(self, structure):
        self.structure = structure
        self._scene_cache = None
        self.title.configure(text=f"Structure viewer: {structure.name}")
        info_key = (
            id(structure),
            len(structure.atoms),
            tuple(structure.elements),
            tuple(
                tuple(round(float(value), 7) for value in row)
                for row in structure.cell
            ),
        )
        if info_key not in self._info_cache:
            self._info_cache[info_key] = self._info_text(structure)
            if len(self._info_cache) > 24:
                self._info_cache.pop(next(iter(self._info_cache)))
        self._full_info_text = self._info_cache[info_key]
        self._info_tooltip.text = self._full_info_text
        self._schedule_viewer_layout()
        if not structure.atoms:
            self.redraw()
            return
        self._auto_fit_pending = True
        self.after_idle(self.fit_to_view)

    def set_background_image(self, path):
        self._background_source = None
        self._background_render = None
        self._background_render_size = None
        raw_path = str(path or "").strip()
        if not raw_path:
            self.redraw()
            return True
        path = Path(raw_path)
        if not path.is_file():
            self.redraw()
            return False
        try:
            from PIL import Image

            with Image.open(path) as source:
                self._background_source = source.convert("RGB")
                self._background_source.load()
        except (ImportError, OSError, ValueError):
            self._background_source = None
            self.redraw()
            return False
        self.redraw()
        return True

    def _draw_background_image(self, width, height):
        if self._background_source is None:
            return
        size = (max(1, int(width)), max(1, int(height)))
        if self._background_render_size != size:
            try:
                from PIL import Image, ImageTk

                source = self._background_source
                factor = max(size[0] / source.width, size[1] / source.height)
                resampling = getattr(Image, "Resampling", Image)
                resized = source.resize(
                    (
                        max(1, round(source.width * factor)),
                        max(1, round(source.height * factor)),
                    ),
                    resampling.LANCZOS,
                )
                left = max(0, (resized.width - size[0]) // 2)
                top = max(0, (resized.height - size[1]) // 2)
                resized = resized.crop(
                    (left, top, left + size[0], top + size[1])
                )
                dark = Image.new("RGB", size, PANEL_ALT)
                # Retain the image character while preserving atom contrast.
                composited = Image.blend(resized, dark, 0.62)
                self._background_render = ImageTk.PhotoImage(composited)
                self._background_render_size = size
            except (OSError, ValueError, tk.TclError):
                self._background_render = None
                return
        if self._background_render is not None:
            self.canvas.create_image(
                width / 2,
                height / 2,
                image=self._background_render,
                anchor="center",
            )

    def _display_mode_changed(self, *_args):
        self._scene_cache = None
        self.fit_to_view()

    def _info_text(self, structure):
        if not structure:
            return ""
        if not structure.atoms:
            return 'No structure data. Import a file to view the formula, atom count, lattice, volume and space group.'
        counts = {
            element: sum(1 for atom in structure.atoms if atom.element == element)
            for element in structure.elements
        }
        composition = " ".join(f"{element}:{count}" for element, count in counts.items())
        formula = "".join(
            element + (str(count) if count != 1 else "")
            for element, count in counts.items()
        )
        try:
            pmg = structure.pmg_structure
            if pmg is not None:
                a, b, c = pmg.lattice.abc
                alpha, beta, gamma = pmg.lattice.angles
                volume = pmg.volume
                space_group = "P1 (#1)"
                try:
                    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
                    analyzer = SpacegroupAnalyzer(pmg, symprec=0.1)
                    space_group = (
                        f"{analyzer.get_space_group_symbol()} "
                        f"(#{analyzer.get_space_group_number()})"
                    )
                except Exception:
                    pass
                return (
                    f"File: {structure.name}    Formula: {formula}    Cell atoms: {len(structure.atoms)}    Element counts: {composition}\n"
                    f"Lattice: a={a:.3f} Å, b={b:.3f} Å, c={c:.3f} Å; "
                    f"α={alpha:.2f}°, β={beta:.2f}°, γ={gamma:.2f}°; "
                    f"Volume={volume:.3f} Å³; space group={space_group}"
                )
        except Exception:
            pass
        a = math.dist((0, 0, 0), structure.cell[0])
        b = math.dist((0, 0, 0), structure.cell[1])
        c = math.dist((0, 0, 0), structure.cell[2])
        return (
            f"File: {structure.name}    Formula: {formula}    Cell atoms: {len(structure.atoms)}"
            f"    Element counts: {composition}\n"
            f"Lattice: a={a:.3f} Å, b={b:.3f} Å, c={c:.3f} Å"
        )

    def reset_view(self):
        self.rx = -0.58
        self.rz = 0.72
        self.fit_to_view()

    def _rotation_step(self):
        try:
            return max(1.0, min(180.0, abs(float(self.rotate_step.get()))))
        except ValueError:
            self.rotate_step.set("15")
            return 15.0

    def rotate_by(self, degrees):
        self.rz += math.radians(float(degrees))
        self._request_redraw()

    def set_axis_view(self, axis):
        if not self.structure or not self.structure.atoms:
            return
        # Align the actual (possibly non-orthogonal) lattice vector with the
        # viewing direction instead of assuming an orthogonal cell.
        vector_index = {"a": 0, "b": 1, "c": 2}.get(axis, 2)
        vector = self.structure.cell[vector_index]
        x, y, z = (float(value) for value in vector)
        in_plane = math.hypot(x, y)
        self.rz = math.atan2(x, y) if in_plane > 1e-12 else 0.0
        self.rx = math.atan2(in_plane, z)
        self.fit_to_view()

    def toggle_auto_rotate(self):
        if self.auto_rotate.get():
            self._schedule_auto_rotate()
        elif self._auto_rotate_job is not None:
            self.after_cancel(self._auto_rotate_job)
            self._auto_rotate_job = None

    def _schedule_auto_rotate(self):
        if not self.auto_rotate.get():
            self._auto_rotate_job = None
            return
        self.rotate_by(2.0)
        self._auto_rotate_job = self.after(60, self._schedule_auto_rotate)

    def zoom(self, factor):
        self.scale = max(3, min(260, self.scale * factor))
        self._request_redraw()

    def _request_redraw(self, delay=None):
        """Coalesce rapid events instead of rendering every mouse message."""
        if self._redraw_job is None:
            if delay is None:
                # Tk Canvas is CPU-rendered. About 30 FPS while dragging feels
                # smooth and leaves enough time for the rest of the interface.
                delay = 33 if self._interactive_motion else 20
            self._redraw_job = self.after(delay, self._run_scheduled_redraw)

    def _run_scheduled_redraw(self):
        self._redraw_job = None
        self.redraw()

    def fit_to_view(self):
        if not self.structure:
            return
        w = max(300, self.canvas.winfo_width() or 620)
        h = max(260, self.canvas.winfo_height() or 360)
        center = self._structure_center()
        points = []
        for x, y, z in self._cell_points():
            atom_like = type("P", (), {"x": x, "y": y, "z": z})()
            px, py, _pz = project_point(atom_like, w, h, 1.0, self.rx, self.rz, center)
            points.append((px, py))
        for _index, atom in self._scene_atoms():
            px, py, _pz = project_point(atom, w, h, 1.0, self.rx, self.rz, center)
            points.append((px, py))
        if not points:
            self.scale = 48
            self.redraw()
            return
        min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
        min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        self.scale = max(3, min(180, min((w - 48) / span_x, (h - 48) / span_y)))
        self._auto_fit_pending = False
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        self._box_rect = None
        if not self.structure:
            return
        w = self.canvas.winfo_width() or 620
        h = self.canvas.winfo_height() or 360
        self._draw_background_image(w, h)
        if not self.structure.atoms:
            self.canvas.create_text(
                w / 2,
                h / 2,
                text='No structure loaded\nSupported: CIF, POSCAR, CONTCAR, VASP, XSF',
                fill=MUTED,
                font=(UI_FONT, 12),
                justify="center",
            )
            return
        center = self._structure_center()
        self._draw_cell(w, h, center)
        scene_atoms = self._scene_atoms()
        projected = []
        for display_index, (i, atom) in enumerate(scene_atoms):
            x, y, z = project_point(atom, w, h, self.scale, self.rx, self.rz, center)
            projected.append((z, display_index, i, atom, x, y))
        quality = self.quality.get()
        fast_motion = quality == 'Fast' or (
            self._interactive_motion
            and len(scene_atoms) > (80 if quality == 'Standard' else 350)
        )
        if self.show_bonds.get() and not fast_motion:
            self._draw_bonds(projected, self._scene_bonds())
        self.screen_atoms = []
        for _z, _display_index, i, atom, x, y in sorted(
            projected, key=lambda item: (item[0], item[2], item[4], item[5])
        ):
            source_atom = self.structure.atoms[i]
            selected = bool(source_atom.selected)
            fixed = bool(source_atom.fixed)
            r = self._atom_screen_radius(atom.element)
            if selected:
                r += 2
            fill = (
                FIXED_ATOM_COLOR
                if fixed
                else SELECTED_ATOM_COLOR
                if selected
                else get_element_color(atom.element)
            )
            if selected:
                outline = SELECTED_ATOM_OUTLINE
                width = 4
            elif fixed:
                outline = FIXED_ATOM_OUTLINE
                width = 3
            else:
                outline = (
                    "#6687a3"
                    if getattr(atom, "periodic_image", False)
                    else "#345b7a"
                )
                width = 1
            self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline=outline, width=width)
            if not fast_motion:
                highlight = max(2, int(r * 0.34))
                self.canvas.create_oval(
                    x - r + highlight,
                    y - r + highlight - 1,
                    x - 1,
                    y - 1,
                    fill="#ffffff",
                    outline="",
                    stipple="gray50",
                )
            self.screen_atoms.append((i, x, y))
        self._draw_axes(w, h)
        self._draw_legend()

    def _structure_center(self):
        if not self.structure:
            return (3, 3, 3)
        a, b, c = self.structure.cell
        return (
            (a[0] + b[0] + c[0]) / 2,
            (a[1] + b[1] + c[1]) / 2,
            (a[2] + b[2] + c[2]) / 2,
        )

    def _display_atoms(self, include_boundary=None):
        if not self.structure:
            return []
        if include_boundary is None:
            include_boundary = self.display_mode.get() == 'VESTA full cell'
        if self.display_mode.get() == '2×2×1 preview':
            return self._supercell_preview_atoms()
        if not include_boundary:
            return list(enumerate(self.structure.atoms))
        try:
            from app.core.structure_model import Atom, to_pymatgen_structure

            pmg = to_pymatgen_structure(self.structure)
            matrix = pmg.lattice.matrix
            display = []
            tolerance = 0.015
            seen = set()
            for index, (site, atom) in enumerate(zip(pmg, self.structure.atoms)):
                frac = [float(value % 1.0) for value in site.frac_coords]
                frac_options = []
                for value in frac:
                    options = [value]
                    if value <= tolerance:
                        options.append(1.0)
                    if value >= 1.0 - tolerance:
                        options.append(0.0)
                    frac_options.append(options)
                for image_frac in product(*frac_options):
                    key = (
                        atom.element,
                        round(image_frac[0], 5),
                        round(image_frac[1], 5),
                        round(image_frac[2], 5),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    coords = (
                        image_frac[0] * matrix[0]
                        + image_frac[1] * matrix[1]
                        + image_frac[2] * matrix[2]
                    )
                    display_atom = Atom(
                        atom.element,
                        float(coords[0]),
                        float(coords[1]),
                        float(coords[2]),
                        atom.fixed,
                        atom.selected,
                    )
                    display_atom.periodic_image = any(
                        abs(image_frac[i] - frac[i]) > tolerance
                        for i in range(3)
                    )
                    display.append((index, display_atom))
            return display
        except Exception:
            return list(enumerate(self.structure.atoms))

    def _scene_signature(self):
        if not self.structure:
            return None
        return (
            id(self.structure),
            len(self.structure.atoms),
            self.display_mode.get(),
            tuple(tuple(round(float(value), 8) for value in row) for row in self.structure.cell),
        )

    def _scene_atoms(self):
        signature = self._scene_signature()
        if self._scene_cache is None or self._scene_cache["signature"] != signature:
            atoms = self._display_atoms()
            self._scene_cache = {
                "signature": signature,
                "atoms": atoms,
                "bonds": self._build_bond_pairs(atoms),
            }
        return self._scene_cache["atoms"]

    def _scene_bonds(self):
        self._scene_atoms()
        return self._scene_cache["bonds"]

    def _build_bond_pairs(self, atoms):
        """Spatial-hash bond search; avoids O(N²) work during every rotation."""
        if len(atoms) < 2:
            return ()
        bucket_size = 3.3
        buckets = {}
        for display_index, (_source_index, atom) in enumerate(atoms):
            key = (
                math.floor(atom.x / bucket_size),
                math.floor(atom.y / bucket_size),
                math.floor(atom.z / bucket_size),
            )
            buckets.setdefault(key, []).append(display_index)
        pairs = []
        neighbor_offsets = tuple(product((-1, 0, 1), repeat=3))
        for first_index, (first_source, first) in enumerate(atoms):
            key = (
                math.floor(first.x / bucket_size),
                math.floor(first.y / bucket_size),
                math.floor(first.z / bucket_size),
            )
            for dx, dy, dz in neighbor_offsets:
                for second_index in buckets.get(
                    (key[0] + dx, key[1] + dy, key[2] + dz), ()
                ):
                    if second_index <= first_index:
                        continue
                    second_source, second = atoms[second_index]
                    if first_source == second_source:
                        continue
                    distance = math.dist(
                        (first.x, first.y, first.z),
                        (second.x, second.y, second.z),
                    )
                    cutoff = self._bond_cutoff(first.element, second.element)
                    if 0.35 <= distance <= cutoff:
                        pairs.append((first_index, second_index))
        return tuple(pairs)

    def _supercell_preview_atoms(self):
        try:
            from app.core.structure_model import Atom

            a, b, _c = self.structure.cell
            display = []
            for tx, ty in product((0, 1), (0, 1)):
                shift = (tx * a[0] + ty * b[0], tx * a[1] + ty * b[1], tx * a[2] + ty * b[2])
                for index, atom in enumerate(self.structure.atoms):
                    display_atom = Atom(atom.element, atom.x + shift[0], atom.y + shift[1], atom.z + shift[2], atom.fixed, atom.selected)
                    display_atom.periodic_image = tx != 0 or ty != 0
                    display.append((index, display_atom))
            return display
        except Exception:
            return list(enumerate(self.structure.atoms))

    def _cell_points(self):
        cell = self.structure.cell if self.structure else ((6, 0, 0), (0, 6, 0), (0, 0, 6))
        a, b, c = cell
        def add(p, q):
            return (p[0] + q[0], p[1] + q[1], p[2] + q[2])
        origin = (0, 0, 0)
        return [origin, a, add(a, b), b, c, add(a, c), add(add(a, b), c), add(b, c)]

    def _draw_cell(self, w, h, center):
        screen = []
        for x, y, z in self._cell_points():
            atom_like = type("P", (), {"x": x, "y": y, "z": z})()
            screen.append(project_point(atom_like, w, h, self.scale, self.rx, self.rz, center))
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        for a, b in edges:
            self.canvas.create_line(screen[a][0], screen[a][1], screen[b][0], screen[b][1], fill=BLUE, dash=(4, 3), width=1)

    def _draw_bonds(self, projected, bond_pairs):
        by_display_index = {
            item[1]: item
            for item in projected
        }
        for first_index, second_index in bond_pairs:
            first = by_display_index.get(first_index)
            second = by_display_index.get(second_index)
            if first is None or second is None:
                continue
            self.canvas.create_line(
                first[4],
                first[5],
                second[4],
                second[5],
                fill="#6385a0",
                width=3 if self.atom_style.get() == 'VESTA ball-and-stick' else 1,
            )

    def _bond_cutoff(self, element_a, element_b):
        try:
            from pymatgen.core import Element

            radius_a = float(
                Element(element_a).atomic_radius
                or Element(element_a).average_ionic_radius
                or 0.8
            )
            radius_b = float(
                Element(element_b).atomic_radius
                or Element(element_b).average_ionic_radius
                or 0.8
            )
            return min(3.3, max(0.9, (radius_a + radius_b) * 1.18))
        except Exception:
            return 2.4

    def _atom_screen_radius(self, element):
        key = (element, self.atom_style.get())
        if key in self._radius_cache:
            return self._radius_cache[key]
        try:
            from pymatgen.core import Element

            item = Element(element)
            radius = float(
                item.atomic_radius
                or item.average_ionic_radius
                or 0.9
            )
        except Exception:
            radius = 0.9
        if self.atom_style.get() == 'Space-filling':
            pixels = max(10, min(23, round(9.0 * radius)))
        else:
            pixels = max(8, min(16, round(6.0 + 3.8 * radius)))
        self._radius_cache[key] = pixels
        return pixels

    def _draw_axes(self, w, h):
        x0, y0 = 60, h - 52
        for label, vector, color in zip(
            ("A", "B", "C"),
            self.structure.cell,
            ("#dc2626", "#16a34a", "#2563eb"),
        ):
            vx, vy, _vz = self._rotate_vector(vector)
            length = math.hypot(vx, vy)
            if length < 1e-9:
                # Axis is parallel to the viewing direction; show a dot.
                self.canvas.create_oval(
                    x0 - 3, y0 - 3, x0 + 3, y0 + 3, fill=color, outline=color
                )
                self.canvas.create_text(
                    x0 + 8, y0 - 8, text=label, fill=color, font=(UI_FONT, 8, "bold")
                )
                continue
            scale = 30.0 / length
            end_x = x0 + vx * scale
            end_y = y0 + vy * scale
            self.canvas.create_line(
                x0,
                y0,
                end_x,
                end_y,
                arrow=tk.LAST,
                fill=color,
                width=2,
            )
            self.canvas.create_text(
                end_x + (9 if vx >= 0 else -9),
                end_y + (8 if vy >= 0 else -8),
                text=label,
                fill=color,
                font=(UI_FONT, 8, "bold"),
            )

    def _rotate_vector(self, vector):
        x, y, z = (float(value) for value in vector)
        cy, sy = math.cos(self.rz), math.sin(self.rz)
        cx, sx = math.cos(self.rx), math.sin(self.rx)
        x, y = x * cy - y * sy, x * sy + y * cy
        y, z = y * cx - z * sx, y * sx + z * cx
        return x, y, z

    def _draw_legend(self):
        signature = (
            id(self.structure),
            tuple(self.structure.elements) if self.structure else (),
            sum(bool(atom.fixed) for atom in self.structure.atoms)
            if self.structure
            else 0,
            sum(bool(atom.selected) for atom in self.structure.atoms)
            if self.structure
            else 0,
        )
        if signature == self._legend_signature:
            return
        self._legend_signature = signature
        for child in self.legend.winfo_children():
            child.destroy()
        if not self.structure:
            return
        for element in self.structure.elements:
            row = ttk.Frame(self.legend, style="Panel.TFrame")
            row.pack(side="left", padx=(0, 16))
            dot = tk.Canvas(row, width=16, height=16, bg=PANEL, highlightthickness=0)
            dot.create_oval(3, 3, 13, 13, fill=get_element_color(element), outline=MUTED)
            dot.pack(side="left")
            ttk.Label(row, text=element, style="Panel.TLabel").pack(side="left", padx=(4, 0))
        if any(atom.fixed for atom in self.structure.atoms):
            row = ttk.Frame(self.legend, style="Panel.TFrame")
            row.pack(side="left", padx=(0, 16))
            dot = tk.Canvas(row, width=16, height=16, bg=PANEL, highlightthickness=0)
            dot.create_oval(
                2,
                2,
                14,
                14,
                fill=FIXED_ATOM_COLOR,
                outline=FIXED_ATOM_OUTLINE,
                width=2,
            )
            dot.pack(side="left")
            ttk.Label(row, text='Fixed', style="Panel.TLabel").pack(
                side="left", padx=(4, 0)
            )
        if any(atom.selected and not atom.fixed for atom in self.structure.atoms):
            row = ttk.Frame(self.legend, style="Panel.TFrame")
            row.pack(side="left", padx=(0, 16))
            dot = tk.Canvas(row, width=16, height=16, bg=PANEL, highlightthickness=0)
            dot.create_oval(
                2,
                2,
                14,
                14,
                fill=SELECTED_ATOM_COLOR,
                outline=SELECTED_ATOM_OUTLINE,
                width=2,
            )
            dot.pack(side="left")
            ttk.Label(row, text='Selected', style="Panel.TLabel").pack(
                side="left", padx=(4, 0)
            )
        self._layout_legend()

    def _press(self, event):
        self._drag = (event.x, event.y)
        self._drag_origin = (event.x, event.y)
        self._interactive_motion = False

    def _drag_rotate(self, event):
        if not self._drag:
            return
        self._interactive_motion = True
        dx = event.x - self._drag[0]
        dy = event.y - self._drag[1]
        self.rz += dx / 160
        self.rx += dy / 180
        self._drag = (event.x, event.y)
        self._request_redraw()

    def _release(self, event):
        clicked = (
            self._drag_origin is not None
            and abs(event.x - self._drag_origin[0])
            + abs(event.y - self._drag_origin[1])
            < 4
        )
        if clicked:
            self._select_at(event.x, event.y)
        self._drag = None
        self._drag_origin = None
        self._interactive_motion = False
        self.redraw()

    def _select_at(self, x, y):
        if not self.structure:
            return
        nearest = None
        best = 14
        for index, ax, ay in self.screen_atoms:
            dist = math.hypot(ax - x, ay - y)
            if dist < best:
                best = dist
                nearest = index
        if nearest is not None:
            self.structure.select_nearest(nearest)
            self.redraw()
            if self.on_select:
                self.on_select(nearest, self.structure.atoms[nearest])

    def _box_press(self, event):
        if not self.structure:
            return
        self._box_start = (event.x, event.y)
        self._box_additive = bool(event.state & 0x0004)
        self._box_rect = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#16a34a" if self._box_additive else BLUE,
            dash=(4, 3),
            width=2,
            fill="#16483e" if self._box_additive else "#123b5c",
            stipple="gray25",
        )

    def _box_drag(self, event):
        if self._box_start is None or self._box_rect is None:
            return
        x0, y0 = self._box_start
        self.canvas.coords(self._box_rect, x0, y0, event.x, event.y)

    def _box_release(self, event):
        if not self.structure or self._box_start is None:
            self._box_start = None
            return
        x0, y0 = self._box_start
        x1, y1 = event.x, event.y
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        selected = []
        for index, ax, ay in self.screen_atoms:
            if left <= ax <= right and top <= ay <= bottom:
                selected.append(index)
        if not self._box_additive:
            self.structure.clear_selection()
        for index in sorted(set(selected)):
            if 0 <= index < len(self.structure.atoms):
                self.structure.atoms[index].selected = True
        all_selected = self.structure.selected_indices()
        self._box_start = None
        self._box_additive = False
        if self._box_rect is not None:
            self.canvas.delete(self._box_rect)
            self._box_rect = None
        self.redraw()
        if all_selected and self.on_select:
            first = all_selected[0]
            self.on_select(first, self.structure.atoms[first])

    def _wheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return
        steps = max(-3, min(3, delta / 120))
        self.zoom(1.12 ** steps)

    def _bind_mousewheel(self, _event=None):
        self.canvas.focus_set()
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _unbind_mousewheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")

    def _resize(self, _event=None):
        self._background_render_size = None
        if self._auto_fit_pending:
            self.after_idle(self.fit_to_view)
        else:
            # A resize can emit dozens of Configure events; render only after
            # a short coalescing interval.
            self._request_redraw(delay=50)
