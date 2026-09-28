import json
import os
import posixpath
import random
import re
import shlex
import shutil
import tempfile
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

from app.core.config_manager import ConfigManager
from app.core.charge_density import calculate_charge_difference
from app.core.deepseek_advisor import (
    apply_incar_suggestions,
    parse_incar,
    validate_suggestions,
)
from app.core.interface_builder import search_interface_candidates
from app.core.interface_scan import inclusive_float_range, inclusive_integer_range
from app.core.input_generators import get_elements_from_poscar, write_cif, write_incar, write_kpoints, write_poscar
from app.core.incar_presets import PRESET_LABELS, get_incar_preset
from app.core.language_manager import LanguageManager
from app.core.paths import APP_ICON, OUTPUTS_DIR, PROJECTS_DIR, ensure_dirs
from app.core.path_utils import is_path_within, normalize_local_path
from app.core.platform_utils import UI_FONT, MONO_FONT, open_path
from app.core.potcar_manager import PotcarManager
from app.core.result_analysis import calculate_surface_energy, parse_vasp_results, parse_vasp_text
from app.core.reliable_submission import ReliableSlurmSubmitter
from app.core.error_recovery import create_recovery_attempt
from app.core.science_exports import export_charge_difference_publication
from app.core.slab_builder import cross_section_area, generate_slab, list_slab_terminations
from app.core.slurm_manager import render_slurm, write_slurm
from app.core.slurm_status import parse_sacct, parse_squeue
from app.core.structure_model import Structure, from_pymatgen_structure, load_structure
from app.core.task_files import format_task_file_errors, standard_vasp_files, validate_task_files
from app.core.task_preflight import validate_task_preflight
from app.core.task_database import TaskDatabase, TaskState
from app.core.vasp_progress import parse_vasp_progress, parse_vasp_progress_directory
from app.core.workflow_builder import build_candidate_workflow
from app.ui.bottom_panel import BottomPanel
from app.ui.task_progress_bar import TaskProgressBar
from app.ui.ai_advisor_window import AIAdvisorWindow
from app.ui.dialogs import ReplaceDialog, SettingsDialog, SupercellDialog
from app.ui.high_throughput_window import HighThroughputWindow
from app.ui.project_panel import ProjectPanel
from app.ui.post_processing_window import PostProcessingWindow
from app.ui.remote_server_panel import RemoteServerPanel
from app.ui.right_panel import RightPanel
from app.ui.simple_ssh_dialog import SimpleSSHDialog
from app.ui.structure_viewer import StructureViewer
from app.ui.structure_tools_dialog import StructureToolsDialog
from app.ui.task_center_window import TaskCenterWindow
from app.ui.theme import (
    BG,
    BORDER,
    BORDER_STRONG,
    PANEL,
    PANEL_ALT,
    TEXT,
    BLUE,
    BLUE_LIGHT,
    IS_LIGHT_THEME,
    configure_style,
    apply_tk_options,
    enable_dark_title_bar,
    install_window_background,
    refresh_window_backgrounds,
)
from app.ui.widgets import FlowStrip, ToolbarButton
from app.ui.widgets import ToolTip
from app.ui import file_dialogs
from app.ui.window_geometry import fit_window_to_workarea, bind_wraplength
from app.version import DISPLAY_NAME, APP_VERSION

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    BaseTk = TkinterDnD.Tk
except Exception:
    BaseTk = tk.Tk


class MainWindow(BaseTk):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.config_manager = ConfigManager()
        self.task_database = TaskDatabase()
        self.lang = LanguageManager(self.config_manager.data.get("language", "en_US"))
        self.structure = Structure()
        self.current_structure = self.structure
        self.preview_structure = None
        self.structures = {self.structure.name: self.structure}
        self.project_dir = PROJECTS_DIR / "example_project"
        self.current_task_dir = self.project_dir / "tasks" / "default_task"
        self.current_slab_area = 0.0
        self.current_task_name = "default_task"
        self.current_job_id = ""
        self.ssh_manager = None
        self.undo_stack = []
        self.redo_stack = []
        self.structure_tabs = {}
        self.active_structure_tab = None
        self._structure_tab_sequence = 0
        self.last_generated_structure_path = None
        self._ui_scale = 1.0
        self._scale_after_id = None
        saved_layout = self.config_manager.data.get("workspace_layout", {})
        self._panel_preferences = {
            "left": bool(saved_layout.get("left_visible", True)),
            "right": bool(saved_layout.get("right_visible", True)),
        }
        priority = saved_layout.get("sidebar_priority", "left")
        self._sidebar_priority = priority if priority in ("left", "right") else "left"
        self._layout_signature = None
        self.task_center_window = None
        self.high_throughput_window = None
        self.post_processing_window = None
        self.structure_tools_window = None
        # Each Agent window owns an independent DeepSeek model, API key,
        # conversation, worker and approval state.
        self.ai_advisor_windows = []
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.current_task_dir.mkdir(parents=True, exist_ok=True)

        from app.version import VERSION
        self.title(f"{self.tr('app_title')} · {VERSION}")
        try:
            self.iconbitmap(default=str(APP_ICON))
        except (OSError, tk.TclError):
            pass
        fit_window_to_workarea(self, (1440, 900), (820, 560))
        self.configure(bg=BG)
        self.style = ttk.Style(self)
        configure_style(self.style, self._ui_scale)
        apply_tk_options(self)
        self._wallpaper_source = None
        self._wallpaper_render = None
        self._wallpaper_render_size = None
        self._wallpaper_after_id = None
        self._active_background_path = ""
        self._wallpaper_label = tk.Label(
            self,
            bg=BG,
            borderwidth=0,
            highlightthickness=0,
        )
        self._wallpaper_label.place(x=0, y=0, relwidth=1, relheight=1)
        self._wallpaper_label.lower()

        self._build_menu()
        self._build_layout()
        self.project_panel.load_project(self.project_dir)
        self.viewer.set_structure(self.structure)
        appearance = self.config_manager.data.get("appearance", {})
        self.apply_background_image(appearance.get("background_image", ""))
        self.bind_all("<Map>", self._apply_dark_title_to_mapped_window, add="+")
        self.after_idle(lambda: enable_dark_title_bar(self))
        self.bind("<Configure>", self._schedule_ui_scale, add="+")
        self.bind("<Configure>", self._schedule_wallpaper_render, add="+")
        self.after(200, self._restore_pane_positions)
        self._enable_file_drop()

    def _apply_dark_title_to_mapped_window(self, event):
        try:
            top = event.widget.winfo_toplevel()
            enable_dark_title_bar(top)
            if top is not self and isinstance(top, tk.Toplevel):
                install_window_background(top, self._active_background_path)
        except tk.TclError:
            pass

    def _enable_file_drop(self):
        register = getattr(self, "drop_target_register", None)
        binder = getattr(self, "dnd_bind", None)
        if not callable(register) or not callable(binder):
            return
        register(DND_FILES)
        binder("<<Drop>>", self._on_files_dropped)

    def _on_files_dropped(self, event):
        paths = [Path(value) for value in self.tk.splitlist(event.data or "")]
        failures = []
        opened = 0
        for path in paths:
            if not path.is_file():
                continue
            try:
                structure = load_structure(path)
                self.structures[structure.name] = structure
                self.add_structure_tab(structure, path.name)
                opened += 1
            except Exception as exc:
                failures.append(f"{path.name}：{exc}")
        if failures:
            messagebox.showwarning(
                'Some files could not be opened as structures',
                "\n".join(failures[:12]),
                parent=self,
            )
        return "copy" if opened else "none"

    def tr(self, key):
        return self.lang.t(key)

    def _build_menu(self):
        self.menu_bar = ttk.Frame(
            self, style="MenuBar.TFrame", padding=(6, 1)
        )
        self.menu_bar.pack(fill="x")
        # Compact pane symbol indicates the workspace sidebar toggle.
        self._sidebar_icon = tk.PhotoImage(width=18, height=18)
        for x1, y1, x2, y2 in [(2, 3, 16, 4), (2, 14, 16, 15),
                              (2, 3, 3, 15), (15, 3, 16, 15), (6, 3, 7, 15)]:
            self._sidebar_icon.put(TEXT, to=(x1, y1, x2, y2))
        self.sidebar_toggle = ttk.Button(
            self.menu_bar, image=self._sidebar_icon, style="SidebarToggle.TButton",
            command=lambda: self.toggle_sidebar("left"), takefocus=True,
        )
        self.sidebar_toggle.pack(side="left", padx=(4, 8), pady=3)
        ToolTip(self.sidebar_toggle, 'Show / hide project and server sidebar · Ctrl+B')
        self.bind("<Control-b>", lambda _e: self.toggle_sidebar("left"))
        self.bind("<Control-B>", lambda _e: self.toggle_sidebar("left"))
        specs = [
            ("file", [("new_project", self.new_project), ("open_project", self.open_project), ("save_project", self.save_project), None, ("import_structure", self.import_structure), ("export_structure", lambda: self.export_structure("CIF")), None, ("exit", self.destroy)]),
            ("project", [("new_task", self.new_task), ("copy_task", self.copy_task), ("delete_task", self.confirm_delete_task), ("open_local_dir", self.open_local_dir), ("open_remote_dir", self.open_ssh)]),
            ("structure", [("import_cif", self.import_structure), ("import_poscar", self.import_structure), ("import_contcar", self.import_structure), ("supercell", self.make_supercell), ("replace_atom", self.replace_selection), ("fix_atom", self.fix_selection), ("delete_atom", self.delete_selection), ("export_structure", lambda: self.export_structure("POSCAR"))]),
            ("tools", [("high_throughput", self.open_high_throughput), ("task_center", self.open_task_center), ("post_processing", self.open_post_processing), ("ai_advisor", self.open_ai_advisor), None, ("incar_templates", self.open_incar_templates), ("kpoints_settings", self.open_kpoints_settings), ("ssh_manager", self.open_ssh), ("slurm_template", self.show_slurm)]),
            ("settings", [("settings", self.open_settings)]),
            ("help", [("user_guide", self.show_user_guide), ("feature_status", self.show_feature_status), ("about", self.about)]),
        ]
        for title_key, items in specs:
            sub = tk.Menu(
                self.menu_bar,
                tearoff=False,
                bg=PANEL,
                fg=TEXT,
                activebackground=BLUE_LIGHT,
                activeforeground=TEXT,
                borderwidth=1,
                relief="solid",
            )
            for item in items:
                if item is None:
                    sub.add_separator()
                else:
                    sub.add_command(label=self.tr(item[0]), command=item[1])
            button = ttk.Menubutton(
                self.menu_bar,
                text=self.tr(title_key),
                menu=sub,
                style="Menu.TMenubutton",
                width=0,
            )
            button.pack(side="left")
        self.inspector_toggle = ttk.Button(
            self.menu_bar, text='Structure panel', style="Compact.TButton",
            command=lambda: self.toggle_sidebar("right"),
        )
        self.inspector_toggle.pack(side="right", padx=(4, 8))
        ToolTip(self.inspector_toggle, 'Show / hide atom and slab settings')

    def _build_layout(self):
        self._build_toolbar()
        # Reserve the persistent task/status area before the expandable body.
        # Packing it after the body allowed tall child widgets to push it
        # outside the visible client area on scaled Windows desktops.
        self._build_statusbar()
        self.main_panes = tk.PanedWindow(
            self,
            orient="horizontal",
            sashwidth=7,
            sashrelief="flat",
            bd=0,
            bg=BG,
            showhandle=False,
            opaqueresize=True,
        )
        self.main_panes.pack(fill="both", expand=True, padx=12, pady=(8, 6))

        left = ttk.Frame(self.main_panes, style="Card.TFrame", padding=1)
        self.left_host = left
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.left_tabs = ttk.Notebook(left)
        self.left_tabs.grid(row=0, column=0, sticky="nsew")

        project_tab = ttk.Frame(self.left_tabs)
        project_tab.rowconfigure(0, weight=1)
        project_tab.columnconfigure(0, weight=1)
        self.left_tabs.add(project_tab, text='Project')
        self.project_panel = ProjectPanel(project_tab, self.tr, self.export_structure)
        self.project_panel.grid(row=0, column=0, sticky="nsew")
        self.project_panel.configure(width=280)

        remote_tab = ttk.Frame(self.left_tabs)
        remote_tab.rowconfigure(0, weight=1)
        remote_tab.columnconfigure(0, weight=1)
        self.left_tabs.add(remote_tab, text='Remote server')
        self.remote_panel = RemoteServerPanel(
            remote_tab,
            {
                "open_ssh": self.open_ssh,
                "get_current_task_dir": lambda: self.current_task_dir,
                "get_current_task_name": lambda: self.current_task_name,
                "get_project_dir": lambda: self.project_dir,
                "get_required_task_files": self.required_task_files,
                "get_remote_task_dir": self.remote_task_dir,
                "get_result_dir": self.result_dir,
                "get_config": lambda: self.config_manager.data,
                "get_config_manager": lambda: self.config_manager,
                "save_config": self.config_manager.save,
                "get_submit_command": lambda: self.config_manager.data.get("slurm", {}).get("submit_command", "sbatch Svasp.sh"),
                "set_current_job_id": self.set_current_job_id,
                "ensure_task_files": self.ensure_current_task_files,
                "open_result_structure": self.open_result_structure,
            },
        )
        self.remote_panel.grid(row=0, column=0, sticky="nsew")

        center = ttk.Frame(self.main_panes)
        self.center_host = center
        self.center_panes = tk.PanedWindow(
            center,
            orient="vertical",
            sashwidth=7,
            sashrelief="flat",
            bd=0,
            bg=BG,
            showhandle=False,
            handlesize=18,
            handlepad=8,
            opaqueresize=True,
        )
        self.center_panes.pack(fill="both", expand=True)

        viewer_frame = ttk.Frame(self.center_panes, style="Card.TFrame", padding=1)
        self.structure_tab_bar = ttk.Frame(viewer_frame, style="Panel.TFrame")
        self.structure_tab_bar.pack(fill="x", padx=8, pady=(6, 0))
        self.viewer = StructureViewer(viewer_frame, on_select=self.on_atom_selected, on_undo=self.undo_structure_edit, on_redo=self.redo_structure_edit)
        self.viewer.pack(fill="both", expand=True)

        callbacks = {
            "get_config_manager": lambda: self.config_manager,
            "generate_incar": self.generate_incar,
            "generate_inputs": self.generate_inputs,
            "generate_kpoints": self.generate_kpoints,
            "get_potcar_root": lambda: self.config_manager.data.get("potcar_root", ""),
            "set_potcar_root": self.set_potcar_root,
            "check_potcar": self.check_potcar,
            "generate_potcar": self.generate_potcar,
            "generate_slurm": self.generate_slurm,
            "match_potcar": self.match_potcar,
            "query_tasks": self.query_remote_tasks,
            "open_task_center": self.open_task_center,
            "analyze_results": self.analyze_current_results,
            "read_current_progress": self.read_current_progress,
            "calculate_surface_energy": self.calculate_surface_energy_values,
            "get_surface_defaults": self.surface_energy_defaults,
            "get_structure_elements": lambda: [
                atom.element for atom in (self.structure.atoms if self.structure else [])
            ],
            "open_result_structure": self.open_result_structure,
            "read_current_progress": self.read_current_calculation_progress,
        }
        bottom_frame = ttk.Frame(self.center_panes, style="Card.TFrame", padding=1)
        ttk.Label(
            bottom_frame,
            text='Calculation inputs and results   ·   Drag divider to resize',
            style="Muted.TLabel",
        ).pack(fill="x", padx=8, pady=(3, 1))
        self.bottom_panel = BottomPanel(bottom_frame, self.tr, callbacks)
        self.bottom_panel.pack(fill="both", expand=True)
        self.center_panes.add(viewer_frame, minsize=180, stretch="always")
        self.center_panes.add(bottom_frame, minsize=155, stretch="never")

        right_callbacks = {
            "fix": self.fix_selection,
            "replace": self.replace_selection,
            "delete": self.delete_selection,
            "preview_slab": self.preview_slab,
            "apply_slab": self.apply_slab,
            "list_terminations": self.list_terminations,
            "export_slab_poscar": self.export_slab_poscar,
        }
        right_host = ttk.Frame(self.main_panes, style="Card.TFrame", padding=1)
        self.right_host = right_host
        right_host.rowconfigure(0, weight=1)
        right_host.columnconfigure(0, weight=1)
        self.right_canvas = tk.Canvas(right_host, bg=BG, highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(right_host, orient="vertical", command=self.right_canvas.yview)
        self.right_canvas.configure(yscrollcommand=right_scrollbar.set)
        self.right_canvas.grid(row=0, column=0, sticky="nsew")
        right_scrollbar.grid(row=0, column=1, sticky="ns")
        self.right_panel = RightPanel(self.right_canvas, self.tr, right_callbacks)
        self.right_window = self.right_canvas.create_window((0, 0), window=self.right_panel, anchor="nw")
        self.right_panel.bind("<Configure>", self._update_right_scrollregion)
        self.right_canvas.bind("<Configure>", self._resize_right_panel)
        self.bind("<MouseWheel>", self._scroll_right_panel, add="+")

        self.main_panes.add(left, minsize=300, width=340, stretch="never")
        self.main_panes.add(center, minsize=360, stretch="always")
        self.main_panes.add(right_host, minsize=280, width=300, stretch="never")
        self.main_panes.bind("<ButtonRelease-1>", self._save_pane_positions, add="+")
        self.center_panes.bind("<ButtonRelease-1>", self._save_pane_positions, add="+")

    def _update_right_scrollregion(self, _event=None):
        self.right_canvas.configure(scrollregion=self.right_canvas.bbox("all"))

    def _resize_right_panel(self, event):
        self.right_canvas.itemconfigure(self.right_window, width=max(1, event.width))

    def _scroll_right_panel(self, event):
        widget = event.widget
        while widget is not None:
            if widget is self.right_canvas:
                self.right_canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"
            widget = getattr(widget, "master", None)

    def toggle_sidebar(self, side="left"):
        visible = self._visible_sidebar(side)
        self._panel_preferences[side] = not visible
        if not visible:
            self._sidebar_priority = side
        self._apply_workspace_layout(force=True)
        self.config_manager.data.setdefault("workspace_layout", {}).update({
            "left_visible": self._panel_preferences["left"],
            "right_visible": self._panel_preferences["right"],
            "sidebar_priority": self._sidebar_priority,
        })
        self.config_manager.save()
        return "break"

    def _visible_sidebar(self, side):
        host = self.left_host if side == "left" else self.right_host
        return str(host) in {str(p) for p in self.main_panes.panes()}

    def show_remote_panel(self):
        self._panel_preferences["left"] = True
        self._sidebar_priority = "left"
        self._apply_workspace_layout(force=True)
        self.left_tabs.select(1)
        self.config_manager.data.setdefault("workspace_layout", {}).update({
            "left_visible": True,
            "right_visible": self._panel_preferences["right"],
            "sidebar_priority": "left",
        })
        self.config_manager.save()

    def download_results(self):
        self.show_remote_panel()
        self.remote_panel.download_results()

    def _apply_workspace_layout(self, force=False):
        if not hasattr(self, "main_panes"):
            return
        width = max(1, self.winfo_width())
        show_left = self._panel_preferences["left"]
        show_right = self._panel_preferences["right"]
        # A narrow desktop keeps one useful inspector rather than crushing all panes.
        if width < 1280 and show_left and show_right:
            show_left, show_right = self._sidebar_priority == "left", self._sidebar_priority == "right"
        signature = (show_left, show_right)
        if force or signature != self._layout_signature:
            for host in (self.left_host, self.center_host, self.right_host):
                if str(host) in {str(p) for p in self.main_panes.panes()}:
                    self.main_panes.forget(host)
            if show_left:
                self.main_panes.add(self.left_host, minsize=300, width=340, stretch="never")
            self.main_panes.add(self.center_host, minsize=360, stretch="always")
            if show_right:
                self.main_panes.add(self.right_host, minsize=280, width=300, stretch="never")
            self._layout_signature = signature
            self.sidebar_toggle.state(["pressed"] if show_left else ["!pressed"])
            self.inspector_toggle.configure(text='Hide structure panel' if show_right else 'Structure panel')
            self.after_idle(self._position_workspace_panes)
        self._layout_toolbar()

    def _position_workspace_panes(self):
        try:
            width = self.main_panes.winfo_width()
            layout = self.config_manager.data.get("workspace_layout", {})
            left_width = max(300, min(440, int(layout.get("left_width", 340))))
            right_width = max(280, min(380, int(layout.get("right_width", 300))))
            if self._visible_sidebar("left"):
                self.main_panes.sash_place(0, min(left_width, max(300, width - 370)), 0)
            if self._visible_sidebar("right"):
                index = len(self.main_panes.panes()) - 2
                self.main_panes.sash_place(index, max(360, width - right_width), 0)
        except (ValueError, TypeError, tk.TclError):
            pass

    def _restore_pane_positions(self):
        self._apply_workspace_layout(force=True)
        # Reattaching panes changes their allocated height on the next Tk layout pass.
        self.after(100, self._position_vertical_pane)

    def _position_vertical_pane(self):
        ratios = self.config_manager.data.get("pane_ratios", {})
        try:
            height = max(1, self.center_panes.winfo_height())
            # Keep at least roughly 30% of the center height for input tabs.
            # Older saved layouts could leave INCAR/KPOINTS only one line tall.
            bottom = min(0.70, max(0.42, float(ratios.get("bottom", 0.62))))
            self.center_panes.sash_place(0, 0, int(height * bottom))
        except (ValueError, tk.TclError):
            pass

    def _save_pane_positions(self, _event=None):
        try:
            width = max(1, self.main_panes.winfo_width())
            height = max(1, self.center_panes.winfo_height())
            ratios = {"bottom": round(self.center_panes.sash_coord(0)[1] / height, 4)}
            layout = self.config_manager.data.setdefault("workspace_layout", {})
            if self._visible_sidebar("left"):
                layout["left_width"] = self.left_host.winfo_width()
            if self._visible_sidebar("right"):
                layout["right_width"] = self.right_host.winfo_width()
            self.config_manager.data["pane_ratios"] = ratios
            self.config_manager.save()
        except (IndexError, tk.TclError):
            pass

    def _schedule_ui_scale(self, event):
        if event.widget is not self:
            return
        if self._scale_after_id:
            self.after_cancel(self._scale_after_id)
        self._scale_after_id = self.after(120, self._apply_responsive_scale)

    def _apply_responsive_scale(self):
        self._scale_after_id = None
        self._apply_workspace_layout()
        width = max(820, self.winfo_width())
        height = max(560, self.winfo_height())
        # Windows DPI scaling already enlarges Tk widgets. Growing them again
        # based on a wide screen caused controls to be clipped vertically.
        # Responsive scaling may compact the UI, but never magnifies it.
        scale = 0.92 if width < 1280 or height < 760 else 1.0
        if abs(scale - self._ui_scale) < 0.04:
            return
        self._ui_scale = scale
        configure_style(self.style, scale)
        for name, base_size in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10), ("TkHeadingFont", 11)):
            try:
                tkfont.nametofont(name).configure(size=max(7, round(base_size * scale)))
            except tk.TclError:
                pass

    def _build_toolbar(self):
        toolbar = ttk.Frame(self, style="AppBar.TFrame", padding=(10, 6))
        toolbar.pack(fill="x", padx=12, pady=(4, 0))
        toolbar.columnconfigure(1, weight=1)
        brand = ttk.Frame(toolbar, style="Panel.TFrame")
        brand.grid(row=0, column=0, sticky="w", padx=(2, 18))
        ttk.Label(brand, text="iface", style="AppTitle.TLabel").pack(anchor="w")
        actions = ttk.Frame(toolbar, style="Panel.TFrame")
        actions.grid(row=0, column=1, sticky="ew")
        self._toolbar_actions = actions
        items = [
            ('Import structure', self.import_structure), ('Structure tools', self.open_structure_tools),
            ('Generate inputs', self.generate_inputs),
            ('High throughput', self.open_high_throughput),
            ('Task center', self.open_task_center),
            ('Post-processing plots', self.open_post_processing),
            ('Server', self.show_remote_panel),
            ("iface Agent", self.open_ai_advisor),
            ('Download results', self.download_results),
            ('SSH connection', self.open_ssh),
        ]
        self._toolbar_buttons = []
        self._toolbar_visible_count = -1
        for text, command in items:
            style = "Primary.TButton" if text == 'High throughput' else "Toolbar.TButton"
            button = ttk.Button(actions, text=text, command=command, style=style)
            self._toolbar_buttons.append((button, text, command))
        self._more_menu = tk.Menu(actions, tearoff=False)
        self._more_button = ttk.Menubutton(actions, text='More', menu=self._more_menu, style="Menu.TMenubutton")
        actions.bind("<Configure>", lambda _e: self._layout_toolbar(), add="+")
        self.after_idle(self._layout_toolbar)

    def _layout_toolbar(self):
        if not hasattr(self, "_toolbar_buttons"):
            return
        available = max(1, self._toolbar_actions.winfo_width())
        widths = [button.winfo_reqwidth() + 4 for button, _, _ in self._toolbar_buttons]
        budget = available if sum(widths) <= available else available - self._more_button.winfo_reqwidth() - 6
        count, used = 0, 0
        for width in widths:
            if used + width > budget:
                break
            count += 1
            used += width
        if count == self._toolbar_visible_count:
            return
        self._toolbar_visible_count = count
        for button, _, _ in self._toolbar_buttons:
            button.pack_forget()
        self._more_button.pack_forget()
        self._more_menu.delete(0, "end")
        for index, (button, text, command) in enumerate(self._toolbar_buttons):
            if index < count:
                button.pack(side="left", padx=2)
            else:
                self._more_menu.add_command(label=text, command=command)
        if count < len(self._toolbar_buttons):
            self._more_button.pack(side="left", padx=(4, 0))

    def _build_statusbar(self):
        bar = ttk.Frame(self, style="Status.TFrame", padding=(10, 3))
        bar.pack(side="bottom", fill="x", padx=12, pady=(0, 5))
        self.status_text = tk.StringVar(value='Ready · Local workspace')
        ttk.Label(bar, textvariable=self.status_text, style="Status.TLabel", width=1).pack(fill="x", expand=True)
        self.task_progress_bar = TaskProgressBar(
            self,
            read_progress=self.read_current_progress,
            get_task_name=lambda: self.current_task_name,
        )
        self.task_progress_bar.pack(side="bottom", fill="x", padx=12)

    def read_current_progress(self):
        """Read the active local calculation without blocking the Tk event loop."""
        return parse_vasp_progress_directory(self.current_task_dir).to_dict()

    def new_project(self):
        name = f"project_{len(list(PROJECTS_DIR.glob('project_*'))) + 1:02d}"
        self.project_dir = PROJECTS_DIR / name
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self._set_current_task("default_task")
        self.config_manager.add_recent_project(self.project_dir)
        self.project_panel.load_project(self.project_dir)
        messagebox.showinfo('New project', f"Project directory created:\n{self.project_dir}")

    def open_project(self):
        path = file_dialogs.askdirectory(self.config_manager, "project", parent=self, initialdir=str(PROJECTS_DIR), title='Open project')
        if path:
            self.project_dir = Path(path)
            self._set_current_task("default_task")
            self.config_manager.add_recent_project(path)
            self.project_panel.load_project(self.project_dir)
            messagebox.showinfo('Open project', f"Current project:\n{path}")

    def save_project(self):
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        self.config_manager.add_recent_project(self.project_dir)
        messagebox.showinfo('Save project', 'Project record saved.')

    def new_task(self):
        name = f"task_{len(list((self.project_dir / 'tasks').glob('task_*'))) + 1:02d}"
        self._set_current_task(name)
        self.project_panel.add_task(name)
        messagebox.showinfo('New calculation task', f"Task directory created:\n{self.current_task_dir}")

    def copy_task(self):
        source = self.current_task_dir
        target_name = f"{source.name}_copy"
        target = self.project_dir / "tasks" / target_name
        if source.exists():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            target.mkdir(parents=True, exist_ok=True)
        self._set_current_task(target_name)
        self.project_panel.add_task(target_name)
        messagebox.showinfo('Copy calculation task', f"Copied to:\n{target}")

    def _set_current_task(self, name):
        self.current_task_name = name
        self.current_task_dir = self.project_dir / "tasks" / name
        self.current_task_dir.mkdir(parents=True, exist_ok=True)

    def remote_task_dir(self):
        base = self.config_manager.data.get("default_remote_root", "/home/user/vasp_projects").rstrip("/")
        if self.ssh_manager and getattr(self.ssh_manager, "username", "") and base == "/home/user/vasp_projects":
            base = f"/home/{self.ssh_manager.username}/vasp_projects"
        return f"{base}/{self.project_dir.name}/{self.current_task_name}"

    def result_dir(self):
        path = self.project_dir / "results" / self.current_task_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def poscar_coordinate_mode(self):
        if hasattr(self, "right_panel"):
            return self.right_panel.get_poscar_options()[0]
        return "Direct"

    def write_current_poscar(self, path):
        mode, selective = self.right_panel.get_poscar_options() if hasattr(self, "right_panel") else ("Direct", True)
        write_poscar(path, self.structure, mode, selective)

    def set_current_job_id(self, job_id):
        self.current_job_id = str(job_id)

    def current_task_record(self):
        high_throughput = self.config_manager.data.get("high_throughput", {})
        return {
            "name": self.current_task_name,
            "project_id": self.project_dir.name,
            "task_type": "vasp",
            "local_path": str(self.current_task_dir),
            "remote_path": self.remote_task_dir(),
            "slurm_job_id": self.current_job_id,
            "max_retries": high_throughput.get("max_automatic_retries", 3),
            "config": {"vasp_version": "6.4.3"},
        }

    def open_task_center(self):
        if self.task_center_window and self.task_center_window.winfo_exists():
            self.task_center_window.deiconify()
            self.task_center_window.lift()
            self.task_center_window.focus_force()
            return
        max_inflight = self.config_manager.data.get("high_throughput", {}).get(
            "max_inflight_jobs", 10
        )
        poll_interval = self.config_manager.data.get("high_throughput", {}).get(
            "poll_interval_seconds", 15
        )
        automation_policy = self.config_manager.data.get(
            "high_throughput", {}
        ).get("slurm_automation", {})
        stale_claim_seconds = self.config_manager.data.get(
            "high_throughput", {}
        ).get("stale_claim_seconds", 900)
        self.task_center_window = TaskCenterWindow(
            self,
            {
                "get_current_task": self.current_task_record,
                "query_slurm": self.query_remote_tasks,
                "query_slurm_background": self.query_remote_tasks_background,
                "query_finished_slurm_background": self.query_finished_slurm_background,
                "reconcile_unknown_task": self.reconcile_unknown_task,
                "read_remote_progress": self.read_remote_task_progress,
                "submit_queued_task": self.submit_queued_task,
                "execute_local_task": self.execute_local_workflow_task,
                "cancel_slurm": self.cancel_remote_job,
                "apply_recovery_plan": self.apply_recovery_plan,
            },
            max_inflight=max_inflight,
            poll_interval_seconds=poll_interval,
            automation_policy=automation_policy,
            stale_claim_seconds=stale_claim_seconds,
        )

    def open_high_throughput(self):
        if self.high_throughput_window and self.high_throughput_window.winfo_exists():
            self.high_throughput_window.deiconify()
            self.high_throughput_window.lift()
            self.high_throughput_window.focus_force()
            return
        self.high_throughput_window = HighThroughputWindow(
            self,
            self.config_manager,
            {
                "preview_structure": self.preview_high_throughput_structure,
                "open_task_center": self.open_task_center,
            },
        )

    def preview_high_throughput_structure(self, structure):
        self.preview_structure = structure
        self.viewer.set_structure(structure)

    def open_post_processing(self):
        if self.post_processing_window and self.post_processing_window.winfo_exists():
            self.post_processing_window.deiconify()
            self.post_processing_window.lift()
            self.post_processing_window.focus_force()
            return
        self.post_processing_window = PostProcessingWindow(
            self,
            {
                "get_current_task_dir": lambda: self.current_task_dir,
                "get_result_dir": self.result_dir,
            },
        )

    def open_ai_advisor(self):
        self.ai_advisor_windows = [
            window for window in self.ai_advisor_windows if window.winfo_exists()
        ]
        window = AIAdvisorWindow(
            self,
            {
                "get_agent_context": self.get_agent_context,
                "execute_agent_action": self.execute_agent_action,
                "load_ai_credentials": self.config_manager.load_ai_credentials,
                "save_ai_credentials": self.config_manager.save_ai_credentials,
                "remove_ai_credentials": self.config_manager.remove_ai_credentials,
            },
        )
        self.ai_advisor_windows.append(window)
        offset = 28 * ((len(self.ai_advisor_windows) - 1) % 8)
        window.geometry(f"1100x760+{80 + offset}+{55 + offset}")
        window.focus_force()
        return window

    def get_agent_context(self):
        """Return a secret-free snapshot used by the workspace Agent."""
        structure = self.structure
        composition = {
            element: sum(
                1 for atom in structure.atoms if atom.element == element
            )
            for element in structure.elements
        }
        files = []
        if self.current_task_dir.is_dir():
            for path in sorted(self.current_task_dir.iterdir()):
                if path.is_file():
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    files.append({"name": path.name, "size_bytes": size})
        database = TaskDatabase()
        record = database.find_task_by_local_path(self.current_task_dir)
        progress = database.get_progress(record.id) if record else {}
        manager = self.active_ssh_manager()
        incar_text = ""
        incar_path = self.current_task_dir / "INCAR"
        if incar_path.is_file():
            try:
                incar_text = incar_path.read_text(
                    encoding="utf-8", errors="replace"
                )[:128000]
            except OSError:
                incar_text = ""
        if not incar_text:
            try:
                incar_text = self.bottom_panel.get_incar_text()[:128000]
            except RuntimeError:
                incar_text = ""
        kpoints_mesh, kpoints_mode = self.bottom_panel.get_kpoints_settings()
        return {
            "software": "iface 2.0",
            "structure": {
                "name": structure.name,
                "atom_count": len(structure.atoms),
                "composition": composition,
                "cell_A": structure.cell,
                "selected_indices": structure.selected_indices(),
            },
            "task": {
                "name": self.current_task_name,
                "local_directory": str(self.current_task_dir),
                "files": files,
                "incar_content": incar_text,
                "kpoints": {
                    "mesh": kpoints_mesh,
                    "mode": kpoints_mode,
                },
                "database_state": record.state if record else "not_registered",
                "slurm_job_id": record.slurm_job_id if record else "",
                "progress": progress,
            },
            "remote": {
                "connected": bool(manager and manager.client and manager.sftp),
                "host": getattr(manager, "host", "") if manager else "",
                "username": getattr(manager, "username", "") if manager else "",
            },
            "viewer": {
                "display_mode": self.viewer.display_mode.get(),
                "atom_style": self.viewer.atom_style.get(),
                "show_bonds": bool(self.viewer.show_bonds.get()),
            },
        }

    def execute_agent_action(self, action):
        """Execute one allow-listed Agent action after the Agent UI confirms it."""
        tool = action.tool
        arguments = action.arguments or {}
        if tool == "inspect_current_context":
            return self.get_agent_context()
        if tool == "analyze_current_results":
            return self.analyze_current_results()
        if tool == "set_crystal_view":
            axis = arguments["axis"]
            self.viewer.set_axis_view(axis)
            return f"Viewing the structure along the {axis.upper()} crystal axis."
        if tool == "fit_structure_view":
            self.viewer.fit_to_view()
            return 'Structure fitted to the current window.'
        if tool == "toggle_bonds":
            enabled = bool(arguments["enabled"])
            self.viewer.show_bonds.set(enabled)
            self.viewer.redraw()
            return 'Chemical bonds are visible.' if enabled else 'Chemical bonds are hidden.'
        if tool == "list_surface_terminations":
            terms = list_slab_terminations(
                self.structure,
                (arguments["h"], arguments["k"], arguments["l"]),
            )
            return [
                {
                    "index": item.index,
                    "label": item.label,
                    "top": item.top_species,
                    "bottom": item.bottom_species,
                }
                for item in terms
            ]
        if tool == "preview_surface_slab":
            result = generate_slab(
                self.structure,
                (arguments["h"], arguments["k"], arguments["l"]),
                arguments["layers"],
                arguments["vacuum"],
                arguments["termination_index"],
            )
            slab = result.lightweight
            self._fix_bottom_layers(
                slab,
                arguments["fixed_layers"],
                arguments["layer_tolerance"],
            )
            self.preview_structure = slab
            self.viewer.set_structure(slab)
            return result.summary
        if tool == "generate_surface_slab":
            result = self.apply_slab(arguments, notify=False)
            return result
        if tool == "open_high_throughput":
            self.open_high_throughput()
            return 'Opened the high-throughput and interface builder window.'
        if tool == "open_task_center":
            self.open_task_center()
            return 'Opened the task center.'
        if tool == "open_post_processing":
            self.open_post_processing()
            return 'Opened the post-processing and scientific plotting window.'
        if tool == "generate_input_files":
            self.generate_inputs()
            return f"Generated/checked VASP input files in {self.current_task_dir}."
        if tool == "propose_incar_patch":
            incar_path = self.current_task_dir / "INCAR"
            if not incar_path.is_file():
                self.current_task_dir.mkdir(parents=True, exist_ok=True)
                write_incar(incar_path, self.bottom_panel.get_incar_text())
            current = parse_incar(incar_path)
            suggestions, warnings = validate_suggestions(
                arguments.get("changes"),
                current,
            )
            if not suggestions:
                raise RuntimeError(
                    'All Agent INCAR changes were blocked by the safety policy:'
                    + "；".join(warnings)
                )
            backup = apply_incar_suggestions(incar_path, suggestions)
            updated_text = incar_path.read_text(encoding="utf-8", errors="replace")
            self.bottom_panel.incar_text.delete("1.0", "end")
            self.bottom_panel.incar_text.insert("1.0", updated_text)
            self.bottom_panel.incar_source.set(
                f"Agent updated: {incar_path} (original file backed up)"
            )
            return {
                "updated": [
                    {
                        "key": item.key,
                        "old": item.old_value,
                        "new": item.new_value,
                    }
                    for item in suggestions
                ],
                "backup": str(backup),
                "warnings": warnings,
            }
        if tool == "configure_kpoints":
            mesh = tuple(arguments["mesh"])
            mode = arguments["mode"]
            self.current_task_dir.mkdir(parents=True, exist_ok=True)
            path = self.current_task_dir / "KPOINTS"
            write_kpoints(path, mesh=mesh, mode=mode)
            self.bottom_panel.kpoint_mode.set(mode)
            for label, value in zip(("Kx", "Ky", "Kz"), mesh):
                self.bottom_panel.kpoint_vars[label].set(str(value))
            return {
                "path": str(path),
                "mesh": mesh,
                "mode": mode,
            }
        if tool == "start_task_queue":
            self.open_task_center()
            if not self.task_center_window._queue_running:
                self.task_center_window.toggle_queue()
            return 'Automatic Slurm queue started; the software settings still control the active-task limit.'
        if tool == "upload_current_task":
            manager = self.active_ssh_manager()
            if not manager or not manager.sftp:
                raise RuntimeError('SSH/SFTP is disconnected. Connect on the server page first.')
            remote_dir = self.remote_panel.remote_path.get().strip().replace("\\", "/").rstrip("/")
            if not remote_dir:
                raise RuntimeError('No remote task directory is selected.')
            required = self.required_task_files()
            preflight = validate_task_preflight(
                self.current_task_dir,
                self.submit_script_name(),
                self.config_manager.data.get("high_throughput", {}).get(
                    "hard_max_atoms", 1000
                ),
            )
            preflight.raise_for_errors()
            bundle = manager.upload_task_bundle_atomic(
                self.current_task_dir,
                remote_dir,
                required,
                task_name=self.current_task_name,
                metadata={
                    "source": "iface_agent",
                    "preflight": preflight.to_dict(),
                },
            )
            return {
                "remote_directory": remote_dir,
                "bundle_id": bundle["bundle_id"],
                "files": [name for name, _size, _hash in bundle["files"]],
            }
        if tool == "submit_remote_task":
            manager = self.active_ssh_manager()
            if not manager or not manager.client:
                raise RuntimeError('SSH is disconnected; cannot submit the task.')
            remote_dir = self.remote_panel.remote_path.get().strip().replace("\\", "/").rstrip("/")
            if not remote_dir:
                raise RuntimeError('No remote task directory is selected.')
            script_name = self.submit_script_name()
            command = self.config_manager.data.get("slurm", {}).get(
                "submit_command", f"sbatch {script_name}"
            ).strip()
            submitter = ReliableSlurmSubmitter(
                manager,
                remote_dir,
                self.config_manager.data.get("submit_init_command", ""),
                self.config_manager.data.get("submit_use_login_shell", True),
                getattr(manager, "username", ""),
            )
            job_id, message, _final = submitter.submit(
                command, script_name, self.current_task_name
            )
            self.set_current_job_id(job_id)
            return {
                "job_id": job_id,
                "remote_directory": remote_dir,
                "message": message,
            }
        if tool == "query_remote_jobs":
            return [
                {
                    "job_id": row[0],
                    "name": row[1],
                    "state": row[2],
                    "elapsed": row[3],
                    "reason_or_node": row[4],
                }
                for row in self.query_remote_tasks()
            ]
        if tool == "download_current_results":
            manager = self.active_ssh_manager()
            if not manager or not manager.sftp:
                raise RuntimeError('SFTP is disconnected; cannot download results.')
            remote_dir = self.remote_panel.remote_path.get().strip().replace("\\", "/").rstrip("/")
            if not remote_dir:
                raise RuntimeError('No remote results directory is selected.')
            local_dir = self.result_dir()
            local_dir.mkdir(parents=True, exist_ok=True)
            patterns = [
                "OUTCAR", "OSZICAR", "CONTCAR", "vasp.out",
                "slurm-*.out", "slurm-*.err",
            ]
            found = manager.find_remote_files(remote_dir, patterns)
            downloaded = [
                str(manager.download_file(remote_file, local_dir))
                for remote_file in found
            ]
            return {
                "remote_directory": remote_dir,
                "local_directory": str(local_dir),
                "downloaded": downloaded,
            }
        raise RuntimeError(f"Unsupported Agent tool: {tool}")

    def cancel_remote_job(self, job_id):
        manager = self.active_ssh_manager()
        if not manager or not manager.client:
            raise RuntimeError('SSH is disconnected; cannot run scancel.')
        job_id = str(job_id).strip()
        if not job_id.isdigit():
            raise RuntimeError('Invalid JobID: digits only.')
        command = self.config_manager.data.get("slurm", {}).get(
            "cancel_command", "scancel {job_id}"
        ).format(job_id=job_id)
        code, out, err, _final = manager.run_remote_command(
            command,
            self.remote_panel.remote_path.get().strip() or None,
            self.config_manager.data.get("submit_init_command", ""),
            self.config_manager.data.get("submit_use_login_shell", True),
        )
        if code != 0:
            raise RuntimeError(err.strip() or out.strip() or 'scancel failed')
        return out.strip()

    def query_remote_tasks_background(self):
        manager = self.active_ssh_manager()
        if not manager or not manager.client:
            raise RuntimeError('SSH is disconnected; automatic queue submission is on hold.')
        command = self._squeue_command(manager.username)
        code, out, err, _final = manager.run_remote_command(
            command,
            None,
            self.config_manager.data.get("submit_init_command", ""),
            self.config_manager.data.get("submit_use_login_shell", True),
        )
        if code != 0:
            raise RuntimeError(err.strip() or out.strip() or 'squeue query failed')
        return parse_squeue(out)

    def query_finished_slurm_background(self, job_ids):
        manager = self.active_ssh_manager()
        if not manager or not manager.client:
            raise RuntimeError('SSH is disconnected; cannot read Slurm job history.')
        clean_ids = sorted({str(job_id) for job_id in job_ids if str(job_id).isdigit()})
        if not clean_ids:
            return {}
        command = (
            "sacct -n -X -j "
            + ",".join(clean_ids)
            + " --format=JobIDRaw,State -P"
        )
        code, out, err, _final = manager.run_remote_command(
            command,
            None,
            self.config_manager.data.get("submit_init_command", ""),
            self.config_manager.data.get("submit_use_login_shell", True),
        )
        if code != 0:
            raise RuntimeError(err.strip() or out.strip() or 'sacct query failed')
        return parse_sacct(out)

    def read_remote_task_progress(self, task):
        manager = self.active_ssh_manager()
        if not manager or not manager.sftp:
            raise RuntimeError('SFTP is disconnected; cannot read remote calculation progress.')
        remote_dir = str(task.remote_path or "").strip().replace("\\", "/").rstrip("/")
        if not remote_dir:
            raise RuntimeError('The task has no remote directory.')

        def read_optional(name, max_size):
            try:
                return manager.read_remote_tail(
                    posixpath.join(remote_dir, name), max_size=max_size
                )
            except (FileNotFoundError, OSError, IOError):
                return ""

        return parse_vasp_progress(
            oszicar_text=read_optional("OSZICAR", 4 * 1024 * 1024),
            outcar_text=read_optional("OUTCAR", 4 * 1024 * 1024),
            incar_text=read_optional("INCAR", 256 * 1024),
        )

    def submit_queued_task(self, task):
        """Upload and submit one durable queue task; safe to call from a worker thread."""
        manager = self.active_ssh_manager()
        if not manager or not manager.client:
            raise RuntimeError('SSH is disconnected; cannot upload or submit.')
        local_dir = Path(task.local_path)
        remote_dir = str(task.remote_path or "").strip().replace("\\", "/")
        if not remote_dir:
            raise RuntimeError('The task has no remote directory.')
        script_name = self.config_manager.data.get("submit_script", "Svasp.sh").strip()
        required = standard_vasp_files(script_name)
        hard_limit = self.config_manager.data.get("high_throughput", {}).get(
            "hard_max_atoms", 1000
        )
        preflight = validate_task_preflight(local_dir, script_name, hard_limit)
        preflight.raise_for_errors()
        self.task_database.add_event(
            task.id,
            "preflight_passed",
            "INFO",
            'Pre-submission validation passed; ' + "；".join(preflight.checks),
            preflight.to_dict(),
        )
        self.task_database.set_state(
            task.id,
            TaskState.UPLOADING,
            'Input validation passed; uploading the task bundle and verifying SHA-256',
        )
        bundle = manager.upload_task_bundle_atomic(
            local_dir,
            remote_dir,
            required,
            task_name=task.name,
            task_type=task.task_type,
            metadata={
                "task_id": task.id,
                "project_id": task.project_id,
                "dependencies": list(task.dependencies),
                "attempt": task.attempts + 1,
                "preflight": preflight.to_dict(),
            },
        )
        self.task_database.add_event(
            task.id,
            "bundle_uploaded",
            "INFO",
            f"Task bundle verified and published: {bundle['bundle_id']}",
            {"bundle_id": bundle["bundle_id"], "remote_dir": remote_dir},
        )
        task_config = task.config or {}
        parent_remote = str(task_config.get("parent_remote_path") or "").strip()
        if task_config.get("copy_parent_restart") and parent_remote:
            source = shlex.quote(parent_remote.rstrip("/"))
            prepare_command = (
                f"test -s {source}/CONTCAR && cp {source}/CONTCAR POSCAR && "
                f"(test ! -s {source}/CHGCAR || cp {source}/CHGCAR CHGCAR) && "
                f"(test ! -s {source}/WAVECAR || cp {source}/WAVECAR WAVECAR)"
            )
            prepare_code, prepare_out, prepare_err, _prepare_final = manager.run_remote_command(
                prepare_command,
                remote_dir,
                self.config_manager.data.get("submit_init_command", ""),
                self.config_manager.data.get("submit_use_login_shell", True),
            )
            if prepare_code != 0:
                raise RuntimeError(
                    prepare_err.strip()
                    or prepare_out.strip()
                    or 'Cannot copy CONTCAR/CHGCAR/WAVECAR from the previous stage'
                )
        command = self.config_manager.data.get("slurm", {}).get(
            "submit_command", f"sbatch {script_name}"
        ).strip()
        self.task_database.set_state(
            task.id,
            TaskState.SUBMITTING,
            'Task bundle published completely; running sbatch --parsable',
        )
        job_name = task.name
        try:
            script_text = (local_dir / script_name).read_text(
                encoding="utf-8", errors="ignore"
            )
            match = re.search(
                r"^\s*#SBATCH\s+--job-name(?:=|\s+)(\S+)",
                script_text,
                flags=re.MULTILINE,
            )
            if match:
                job_name = match.group(1)
        except OSError:
            pass
        submitter = ReliableSlurmSubmitter(
            manager,
            remote_dir,
            self.config_manager.data.get("submit_init_command", ""),
            self.config_manager.data.get("submit_use_login_shell", True),
            getattr(manager, "username", ""),
        )
        job_id, message, _final = submitter.submit(
            command, script_name, job_name
        )
        self.task_database.add_event(
            task.id,
            "slurm_submitted",
            "INFO",
            message,
            {"job_id": job_id, "job_name": job_name},
        )
        return job_id

    def reconcile_unknown_task(self, task):
        manager = self.active_ssh_manager()
        if not manager or not manager.client:
            return ""
        local_dir = Path(task.local_path)
        script_name = self.config_manager.data.get(
            "submit_script", "Svasp.sh"
        ).strip()
        job_name = task.name
        try:
            script_text = (local_dir / script_name).read_text(
                encoding="utf-8", errors="ignore"
            )
            match = re.search(
                r"^\s*#SBATCH\s+--job-name(?:=|\s+)(\S+)",
                script_text,
                flags=re.MULTILINE,
            )
            if match:
                job_name = match.group(1)
        except OSError:
            pass
        submitter = ReliableSlurmSubmitter(
            manager,
            task.remote_path,
            self.config_manager.data.get("submit_init_command", ""),
            self.config_manager.data.get("submit_use_login_shell", True),
            getattr(manager, "username", ""),
        )
        return submitter.reconcile(job_name)

    def apply_recovery_plan(self, task, plan):
        local_dir = Path(task.local_path)
        local_dir.mkdir(parents=True, exist_ok=True)
        contcar_path = local_dir / "CONTCAR"
        manager = self.active_ssh_manager()
        remote_dir = str(task.remote_path or "").strip().replace("\\", "/")
        with tempfile.TemporaryDirectory() as temporary:
            if (
                plan.restart_from_contcar
                and remote_dir
                and manager
                and manager.sftp
            ):
                try:
                    downloaded = manager.download_file(
                        posixpath.join(remote_dir, "CONTCAR"), temporary
                    )
                    if downloaded.is_file() and downloaded.stat().st_size > 0:
                        shutil.copy2(downloaded, contcar_path)
                except Exception:
                    pass
            attempt_number = max(2, int(task.attempts) + 1)
            attempt_dir, changes = create_recovery_attempt(
                local_dir,
                plan,
                attempt_number,
                contcar_path if contcar_path.is_file() else None,
            )
        removed = []
        if remote_dir and manager and manager.sftp:
            for name in plan.remove_remote_files:
                path = posixpath.join(remote_dir, name)
                try:
                    manager.sftp.remove(path)
                    removed.append(name)
                except OSError:
                    pass
        self.task_database.add_event(
            task.id,
            "recovery_approved",
            "WARNING",
            f"User approved recovery plan: {plan.title}",
            {
                "attempt_dir": str(attempt_dir),
                "changes": changes,
                "removed_remote_files": removed,
            },
        )
        details = ", ".join(changes) if changes else 'INCAR unchanged'
        return (
            f"Recovery snapshot: {attempt_dir}\n"
            f"Applied: {details}\n"
            f"Removed remotely: {', '.join(removed) if removed else 'None'}"
        )

    def execute_local_workflow_task(self, task):
        """Execute dependency-aware local workflow steps in the queue worker."""
        config = task.config or {}
        if task.task_type == "local:charge_prepare":
            return self._prepare_charge_subsystems(config)
        if task.task_type == "local:charge_difference":
            return self._finish_charge_difference(config)
        if task.task_type == "local:interface_rebuild":
            return self._rebuild_adaptive_interface(config)
        raise RuntimeError(f"Unsupported local workflow type: {task.task_type}")

    def _ensure_workflow_result_file(self, local_path, remote_dir, filename):
        local_path = Path(local_path)
        if local_path.is_file() and local_path.stat().st_size > 0:
            return local_path
        manager = self.active_ssh_manager()
        if not manager or not manager.sftp:
            raise RuntimeError(
                f"Missing local file {filename}; SFTP is disconnected, so it cannot be downloaded."
            )
        remote_dir = str(remote_dir or "").strip().replace("\\", "/").rstrip("/")
        if not remote_dir:
            raise RuntimeError(f"{filename} has no corresponding remote directory.")
        downloaded = manager.download_file(
            posixpath.join(remote_dir, filename),
            local_path.parent,
        )
        if Path(downloaded) != local_path:
            shutil.copy2(downloaded, local_path)
        if not local_path.is_file() or local_path.stat().st_size == 0:
            raise RuntimeError(f"{filename} is empty after download: {local_path}")
        return local_path

    def _prepare_charge_subsystems(self, config):
        from pymatgen.core import Structure as PmgStructure

        relax_dir = Path(config["relax_local_path"])
        contcar = self._ensure_workflow_result_file(
            relax_dir / "CONTCAR",
            config.get("relax_remote_path"),
            "CONTCAR",
        )
        interface = PmgStructure.from_file(str(contcar))
        substrate_indices = sorted({int(value) for value in config["substrate_indices"]})
        film_indices = sorted({int(value) for value in config["film_indices"]})
        all_indices = set(range(len(interface)))
        if not substrate_indices or not film_indices:
            raise RuntimeError('Interface layer indices are empty; cannot split the three systems.')
        if set(substrate_indices) & set(film_indices):
            raise RuntimeError('Substrate and film atom indices overlap.')
        if not (set(substrate_indices) | set(film_indices)).issubset(all_indices):
            raise RuntimeError(
                'The relaxed CONTCAR atom count differs from the model; cannot safely split the three systems.'
            )

        substrate = interface.copy()
        substrate.remove_sites(sorted(all_indices - set(substrate_indices), reverse=True))
        film = interface.copy()
        film.remove_sites(sorted(all_indices - set(film_indices), reverse=True))
        substrate_path = Path(config["substrate_poscar"])
        film_path = Path(config["film_poscar"])
        write_poscar(
            substrate_path,
            from_pymatgen_structure(substrate, substrate_path.parent.name),
            "Direct",
            False,
        )
        write_poscar(
            film_path,
            from_pymatgen_structure(film, film_path.parent.name),
            "Direct",
            False,
        )
        write_kpoints(
            substrate_path.parent / "KPOINTS",
            self._charge_kmesh(interface),
            "Gamma",
        )
        write_kpoints(
            film_path.parent / "KPOINTS",
            self._charge_kmesh(interface),
            "Gamma",
        )
        return (
            f"Split the relaxed interface into an isolated substrate with {len(substrate)} atoms and "
            f"an isolated film with {len(film)} atoms; both retain the same cell and FFT reference."
        )

    @staticmethod
    def _charge_kmesh(structure, spacing=0.25):
        import math
        import numpy as np

        lengths = np.linalg.norm(structure.lattice.matrix, axis=1)
        return tuple(
            1
            if index == 2
            else max(1, int(math.ceil((2 * math.pi / max(length, 1e-9)) / spacing)))
            for index, length in enumerate(lengths)
        )

    def _finish_charge_difference(self, config):
        entries = [
            (
                config["interface_chgcar"],
                config.get("interface_remote_path"),
            ),
            (
                config["substrate_chgcar"],
                config.get("substrate_remote_path"),
            ),
            (
                config["film_chgcar"],
                config.get("film_remote_path"),
            ),
        ]
        paths = [
            self._ensure_workflow_result_file(path, remote, "CHGCAR")
            for path, remote in entries
        ]
        output_dir = Path(config["output_dir"])
        result = calculate_charge_difference(
            paths[0],
            paths[1],
            paths[2],
            output_dir / "CHGDIFF.vasp",
        )
        exported = export_charge_difference_publication(
            result,
            output_dir,
            include_full_grid_excel=True,
        )
        return (
            f"Charge-density difference completed: grid {result.grid}, net difference "
            f"{result.report.electron_difference:.6g} e；"
            f"Exported {Path(exported['png']).name}、"
            f"{Path(exported['tiff']).name} and raw Excel data."
        )

    def _rebuild_adaptive_interface(self, config):
        substrate = self._ensure_workflow_result_file(
            config["substrate_contcar"],
            config.get("substrate_remote_path"),
            "CONTCAR",
        )
        film = self._ensure_workflow_result_file(
            config["film_contcar"],
            config.get("film_remote_path"),
            "CONTCAR",
        )
        parameters = dict(config.get("search_parameters") or {})
        candidate_limit = max(1, int(config.get("candidate_limit", 3)))
        gaps = self._adaptive_gap_values(parameters)
        substrate_layers = parameters.get("substrate_layer_values")
        if not substrate_layers:
            substrate_layers = inclusive_integer_range(
                parameters.get("substrate_layers", 6),
                parameters.get("substrate_layers", 6),
                1,
            )
        film_layers = parameters.get("film_layer_values")
        if not film_layers:
            film_layers = inclusive_integer_range(
                parameters.get("film_layers", 6),
                parameters.get("film_layers", 6),
                1,
            )
        candidates = []
        for a_layers in substrate_layers:
            for b_layers in film_layers:
                found = search_interface_candidates(
                    substrate,
                    film,
                    substrate_miller=tuple(parameters.get("substrate_hkl", (1, 0, 0))),
                    film_miller=tuple(parameters.get("film_hkl", (1, 0, 0))),
                    substrate_layers=int(a_layers),
                    film_layers=int(b_layers),
                    gap_values=gaps,
                    max_strain=float(parameters.get("max_strain", 0.05)),
                    max_area=float(parameters.get("max_area", 500.0)),
                    max_atoms=min(1000, int(parameters.get("max_atoms", 1000))),
                    lateral_offsets=((0.0, 0.0),),
                    limit=candidate_limit * len(gaps),
                )
                for local_index, candidate in enumerate(found, 1):
                    source_a = (parameters.get("substrates") or [substrate])[0]
                    source_b = (parameters.get("films") or [film])[0]
                    candidate.source_a = Path(source_a).name
                    candidate.source_b = Path(source_b).name
                    candidate.scan_pair_id = str(
                        parameters.get("scan_pair_id")
                        or f"{candidate.source_a} × {candidate.source_b}"
                    )
                    candidate.substrate_layers = int(a_layers)
                    candidate.film_layers = int(b_layers)
                    candidate.lightweight.name = (
                        f"interface_L{int(a_layers):02d}-{int(b_layers):02d}"
                        f"_D{candidate.gap:.3f}_{local_index:03d}"
                    ).replace(".", "p")
                candidates.extend(found)
        candidates.sort(key=lambda item: (item.score, item.atoms, item.area))
        for index, candidate in enumerate(candidates):
            candidate.index = index
        if not candidates:
            raise RuntimeError('Both bulk relaxations finished, but no interface meets the strain, area and atom-count limits.')
        database = TaskDatabase()
        results = []
        warnings = []
        for candidate in candidates:
            result = build_candidate_workflow(
                candidate,
                config["output_root"],
                config["project_name"],
                self.config_manager.data,
                database=database,
                include_pdos=bool(config.get("include_pdos", True)),
                include_charge=bool(config.get("include_charge", True)),
                magnetic=bool(config.get("magnetic", True)),
                dft_u=config.get("dft_u") or {},
                vdw=config.get("vdw", "none"),
            )
            results.append(result)
            warnings.extend(result.warnings)
        report = {
            "optimized_substrate": str(substrate),
            "optimized_film": str(film),
            "candidate_count": len(candidates),
            "candidates": [
                {
                    "rank": index + 1,
                    "name": candidate.lightweight.name,
                    "termination": candidate.label,
                    "gap_a": candidate.gap,
                    "substrate_layers": candidate.substrate_layers,
                    "film_layers": candidate.film_layers,
                    "area_a2": candidate.area,
                    "atoms": candidate.atoms,
                    "strain": candidate.strain,
                    "mismatch_a": candidate.mismatch_a,
                    "mismatch_b": candidate.mismatch_b,
                    "compatibility_percent": candidate.compatibility_percent,
                    "workflow_root": str(results[index].root),
                }
                for index, candidate in enumerate(candidates)
            ],
            "warnings": warnings,
        }
        report_path = Path(config["output_root"]) / config["project_name"] / (
            "_adaptive_bulk/03_rebuild_interface/interface_ranking.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return (
            f"Rebuilt {len(candidates)} best interfaces from the two relaxed CONTCAR files; "
            f"subsequent relaxation, static, PDOS and charge-difference tasks were queued."
        )

    @staticmethod
    def _adaptive_gap_values(parameters):
        explicit = parameters.get("gap_values")
        if explicit:
            return [float(value) for value in explicit]
        start = float(parameters.get("gap_min", 1.8))
        stop = float(parameters.get("gap_max", 3.2))
        if parameters.get("gap_step") is not None:
            return inclusive_float_range(
                start,
                stop,
                float(parameters.get("gap_step")),
            )
        count = max(1, int(parameters.get("gap_count", 4)))
        if count == 1:
            return [start]
        step = (stop - start) / (count - 1)
        return [start + index * step for index in range(count)]

    def query_remote_tasks(self):
        manager = self.active_ssh_manager()
        if not manager or not manager.client:
            raise RuntimeError('SSH is disconnected. Connect to the server first.')
        command = self._squeue_command(manager.username)
        code, out, err, _final = manager.run_remote_command(
            command,
            self.remote_panel.remote_path.get().strip() or None,
            self.config_manager.data.get("submit_init_command", ""),
            self.config_manager.data.get("submit_use_login_shell", True),
        )
        if code != 0:
            message = err.strip() or out.strip()
            if "command not found" in message or "not found" in message:
                job = self.current_job_id or "-"
                return [(job, self.current_task_name, 'Cannot query: squeue is unavailable in the login environment', "-", 'Enter the environment initialization command in Settings')]
            raise RuntimeError(message or 'squeue query failed')
        rows = []
        for line in out.splitlines():
            parts = [part.strip() for part in line.split("|", 4)]
            if len(parts) == 5:
                rows.append(tuple(parts))
        return rows

    def _squeue_command(self, username):
        safe_user = shlex.quote(str(username or "").strip())
        configured = str(
            self.config_manager.data.get("slurm", {}).get("query_command") or ""
        ).strip()
        if configured:
            configured = configured.replace("{username}", safe_user)
            if " -o " in f" {configured} " or "--format" in configured:
                base = configured
            else:
                base = configured + " -h -o '%i|%j|%T|%M|%R'"
        else:
            base = f"squeue -h -u {safe_user} -o '%i|%j|%T|%M|%R'"
        fallback = (
            f"/opt/slurm/bin/squeue -h -u {safe_user} "
            "-o '%i|%j|%T|%M|%R'"
        )
        return f"({base}) || ({fallback})"

    def analyze_current_results(self):
        local_candidates = [self.current_task_dir, self.result_dir()]
        best_local = None
        for directory in local_candidates:
            try:
                candidate = parse_vasp_results(directory)
            except Exception as exc:
                candidate = {
                    "directory": str(directory), "energy_ev": None, "area_a2": None,
                    "atom_count": None, "ionic_steps": 0, "converged": False,
                    "max_force_ev_a": None, "source": "local", "read_errors": [str(exc)],
                }
            if candidate.get("energy_ev") is not None and candidate.get("area_a2") is not None:
                return candidate
            if best_local is None or candidate.get("energy_ev") is not None or candidate.get("area_a2") is not None:
                best_local = candidate
        manager = self.active_ssh_manager()
        if manager and manager.sftp:
            remote_dir = self.remote_panel.remote_path.get().strip().replace("\\", "/").rstrip("/")
            if not remote_dir:
                raise RuntimeError('The current remote directory is empty. Open the calculation results directory on the remote server page first.')
            outcar = ""
            oszicar = ""
            structure_text = ""
            geometry_source = ""
            errors = []
            try:
                outcar = manager.read_remote_text(f"{remote_dir}/OUTCAR", max_size=50 * 1024 * 1024)
            except Exception as exc:
                errors.append(f"Direct OUTCAR read failed: {exc}")
                code, tail, tail_err, _cmd = manager.run_remote_command("tail -n 12000 OUTCAR", remote_dir)
                if code == 0:
                    outcar = tail
                else:
                    errors.append(f"tail OUTCAR failed: {tail_err or tail}")
            try:
                oszicar = manager.read_remote_text(f"{remote_dir}/OSZICAR", max_size=20 * 1024 * 1024)
            except Exception as exc:
                errors.append(f"Direct OSZICAR read failed: {exc}")
                code, tail, tail_err, _cmd = manager.run_remote_command("tail -n 5000 OSZICAR", remote_dir)
                if code == 0:
                    oszicar = tail
                else:
                    errors.append(f"tail OSZICAR failed: {tail_err or tail}")
            for filename in ("CONTCAR", "POSCAR"):
                try:
                    structure_text = manager.read_remote_text(f"{remote_dir}/{filename}", max_size=20 * 1024 * 1024)
                    geometry_source = filename
                    break
                except Exception as exc:
                    errors.append(f"Reading {filename} failed: {exc}")
            try:
                remote_result = parse_vasp_text(outcar, oszicar, structure_text)
            except Exception as exc:
                remote_result = parse_vasp_text(outcar, oszicar)
                errors.append(str(exc))
            remote_result.update({
                "directory": remote_dir,
                "has_outcar": bool(outcar),
                "has_oszicar": bool(oszicar),
                "has_contcar": geometry_source == "CONTCAR",
                "geometry_source": geometry_source,
                "read_errors": errors,
                "source": "remote",
            })
            return remote_result
        result = best_local or parse_vasp_results(self.current_task_dir)
        result.setdefault("read_errors", []).append('SSH is disconnected: results analysis has no available remote SFTP connection.')
        result["source"] = "local"
        return result

    def active_ssh_manager(self):
        panel_manager = getattr(getattr(self, "remote_panel", None), "ssh_manager", None)
        return panel_manager or self.ssh_manager

    def open_structure_window(self, structure, title='Structure viewer'):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry("980x760")
        top.minsize(620, 460)
        try:
            top.iconbitmap(default=str(APP_ICON))
        except (OSError, tk.TclError):
            pass
        viewer = StructureViewer(top)
        viewer.pack(fill="both", expand=True)
        viewer.set_structure(structure)
        return top

    def open_result_structure(self):
        """Open CONTCAR in a new independent viewer without replacing the editor."""
        local_candidates = [
            self.current_task_dir / "CONTCAR",
            self.result_dir() / "CONTCAR",
        ]
        path = next((item for item in local_candidates if item.is_file()), None)
        manager = self.active_ssh_manager()
        remote_dir = ""
        if getattr(self, "remote_panel", None):
            remote_dir = self.remote_panel.remote_path.get().strip().replace("\\", "/")
        if path is None and manager and manager.sftp and remote_dir:
            target_dir = self.result_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                path = Path(
                    manager.download_file(
                        posixpath.join(remote_dir, "CONTCAR"), target_dir
                    )
                )
            except Exception as exc:
                messagebox.showwarning(
                    'View CONTCAR',
                    f"Cannot download CONTCAR from the current server directory:\n{exc}",
                    parent=self,
                )
                return
        if path is None or not path.is_file():
            messagebox.showinfo(
                'View CONTCAR',
                'No CONTCAR exists in the current task or results directory. Wait for relaxation to produce it, '
                'or download the results from the server first.',
                parent=self,
            )
            return
        try:
            structure = load_structure(path)
        except Exception as exc:
            messagebox.showerror('View CONTCAR', str(exc), parent=self)
            return
        self.open_structure_window(structure, f"CONTCAR structure viewer - {path.parent.name}")

    def read_current_calculation_progress(self):
        manager = self.active_ssh_manager()
        remote_dir = ""
        if getattr(self, "remote_panel", None):
            remote_dir = self.remote_panel.remote_path.get().strip().replace("\\", "/")
        if manager and manager.sftp and remote_dir:
            def read_optional(name, max_bytes):
                try:
                    return manager.read_remote_text(
                        posixpath.join(remote_dir, name), max_size=max_bytes
                    )
                except Exception:
                    return ""

            progress = parse_vasp_progress(
                oszicar_text=read_optional("OSZICAR", 8 * 1024 * 1024),
                outcar_text=read_optional("OUTCAR", 8 * 1024 * 1024),
                incar_text=read_optional("INCAR", 256 * 1024),
            )
        else:
            from app.core.vasp_progress import parse_vasp_progress_directory

            progress = parse_vasp_progress_directory(self.current_task_dir)
        return progress.to_dict()

    def calculate_surface_energy_values(self, slab_energy, bulk_energy, atom_count, area, surfaces):
        return calculate_surface_energy(slab_energy, bulk_energy, atom_count, area, surfaces)

    def surface_energy_defaults(self):
        area = self.current_slab_area or (cross_section_area(self.structure.cell) if self.structure else 0.0)
        return len(self.structure.atoms) if self.structure else 0, area

    def add_structure_tab(self, structure, label=None):
        """Add and activate an independently closable structure document."""
        self._structure_tab_sequence += 1
        tab_id = f"structure-{self._structure_tab_sequence}"
        tab = tk.Frame(
            self.structure_tab_bar,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=3,
            pady=2,
        )
        name = str(label or structure.name or f"Structure {self._structure_tab_sequence}")
        name_label = tk.Label(
            tab,
            text=name,
            bg=PANEL,
            fg=TEXT,
            padx=8,
            cursor="hand2",
        )
        name_label.pack(side="left")
        close_label = tk.Label(
            tab,
            text="×",
            bg=PANEL,
            fg="#89a9c4",
            padx=5,
            cursor="hand2",
            font=(UI_FONT, 11, "bold"),
        )
        close_label.pack(side="left")
        tab.pack(side="left", padx=(0, 4), pady=2)
        self.structure_tabs[tab_id] = {
            "structure": structure,
            "frame": tab,
            "label": name_label,
            "close": close_label,
            "name": name,
        }
        for widget in (tab, name_label):
            widget.bind("<Button-1>", lambda _event, value=tab_id: self.select_structure_tab(value))
        close_label.bind(
            "<Button-1>",
            lambda _event, value=tab_id: self.close_structure_tab(value),
        )
        self.select_structure_tab(tab_id)
        return tab_id

    def select_structure_tab(self, tab_id):
        record = self.structure_tabs.get(tab_id)
        if not record:
            return
        self.active_structure_tab = tab_id
        for current_id, current in self.structure_tabs.items():
            active = current_id == tab_id
            background = BLUE_LIGHT if active else PANEL
            border = BLUE if active else BORDER
            current["frame"].configure(
                bg=background, highlightbackground=border
            )
            current["label"].configure(bg=background)
            current["close"].configure(bg=background)
        self.structure = record["structure"]
        self.current_structure = self.structure
        self.preview_structure = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.viewer.set_structure(self.structure)

    def close_structure_tab(self, tab_id):
        record = self.structure_tabs.get(tab_id)
        if not record:
            return
        tab_ids = list(self.structure_tabs)
        closed_index = tab_ids.index(tab_id)
        was_active = self.active_structure_tab == tab_id
        record["frame"].destroy()
        del self.structure_tabs[tab_id]
        if not was_active:
            return
        remaining = list(self.structure_tabs)
        if remaining:
            next_index = min(closed_index, len(remaining) - 1)
            self.select_structure_tab(remaining[next_index])
            return
        self.active_structure_tab = None
        self.structure = Structure()
        self.current_structure = self.structure
        self.preview_structure = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.viewer.set_structure(self.structure)

    def _store_active_structure_tab(self):
        if self.active_structure_tab in self.structure_tabs:
            self.structure_tabs[self.active_structure_tab]["structure"] = self.structure

    def open_structure_tools(self):
        if (
            self.structure_tools_window
            and self.structure_tools_window.winfo_exists()
        ):
            self.structure_tools_window.deiconify()
            self.structure_tools_window.lift()
            return
        self.structure_tools_window = StructureToolsDialog(
            self,
            {
                "get_structure": self._active_structure,
                "before_change": lambda: self._push_structure_history(
                    self._active_structure()
                ),
                "refresh": self._refresh_structure_tools,
                "changed": self._structure_tools_changed,
            },
        )

    def _refresh_structure_tools(self):
        self.viewer.redraw()
        selected = self._active_structure().selected_indices()
        if selected:
            index = selected[0]
            self.on_atom_selected(index, self._active_structure().atoms[index])
        else:
            self.right_panel.clear_selection()

    def _structure_tools_changed(self):
        self.structure = self._active_structure()
        self.current_structure = self.structure
        self.preview_structure = None
        self.structures[self.structure.name] = self.structure
        self._store_active_structure_tab()
        self.viewer.set_structure(self.structure)
        self.auto_save_generated_structure("structure_tool")

    def import_structure(self):
        path = file_dialogs.askopenfilename(self.config_manager, "structure_import", parent=self,
            title='Import structure file',
            filetypes=[("Structure Files", "*.cif *.vasp *.poscar *.contcar *.xsf POSCAR CONTCAR"), ("All Files", "*.*")],
        )
        if not path:
            return
        progress = tk.Toplevel(self)
        progress.title('Importing structure')
        progress.geometry("360x120")
        progress.resizable(False, False)
        progress.transient(self)
        ttk.Label(
            progress,
            text=f"Reading {Path(path).name}; please wait…",
            wraplength=320,
        ).pack(padx=18, pady=(18, 10))
        indicator = ttk.Progressbar(progress, mode="indeterminate")
        indicator.pack(fill="x", padx=18)
        indicator.start(12)
        self.status_text.set(f"Reading structure in background · {Path(path).name}")
        results = queue.Queue()

        def worker():
            try:
                results.put(("ok", load_structure(path)))
            except Exception as exc:
                results.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                kind, payload = results.get_nowait()
            except queue.Empty:
                if progress.winfo_exists():
                    self.after(60, poll)
                return
            indicator.stop()
            if progress.winfo_exists():
                progress.destroy()
            self.status_text.set('Ready · Local workspace')
            if kind == "error":
                messagebox.showerror(
                    'Import failed', f"Cannot read structure file:\n{payload}", parent=self
                )
                return
            self._finish_structure_import(path, payload)

        self.after(60, poll)

    def _finish_structure_import(self, path, structure):
        self.structure = structure
        self.current_structure = self.structure
        self.structures[self.structure.name] = self.structure
        self.add_structure_tab(self.structure, Path(path).name)
        target = self.project_dir / Path(path).name
        try:
            shutil.copy2(path, target)
        except OSError:
            pass
        self.project_panel.add_structure(Path(path).name)
        self.project_panel.set_default_filename(f"{Path(path).stem}.cif")
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        poscar_path = self.current_task_dir / "POSCAR"
        self.write_current_poscar(poscar_path)
        self.project_panel.add_generated_files(["POSCAR"])
        self.auto_save_generated_structure("import")
        messagebox.showinfo('Import successful', f"Structure imported and converted to standard POSCAR:\n{poscar_path}")

    def export_structure(self, fmt, export_dir="", filename=""):
        if not self.structure or not self.structure.atoms:
            messagebox.showerror('Export failed', 'No structure is available for export.')
            return
        saved_export = self.config_manager.data.get("dialog_directories", {}).get("structure_export", "")
        target_dir = Path(export_dir or saved_export) if (export_dir or saved_export) else self.project_dir / "exports"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror('Export failed', f"Cannot create export directory:\n{exc}")
            return
        if not filename:
            filename = "POSCAR" if fmt == "POSCAR" else ("POTCAR" if fmt == "POTCAR" else f"{Path(self.structure.name).stem}.cif")
        path = target_dir / filename
        try:
            if fmt == "POSCAR":
                self.write_current_poscar(path)
            elif fmt == "POTCAR":
                write_potcar(path, self.structure, self._potcar_root())
            else:
                if path.suffix.lower() != ".cif":
                    path = path.with_suffix(".cif")
                write_cif(path, self.structure)
        except Exception as exc:
            messagebox.showerror('Export failed', str(exc))
            return
        self.config_manager.remember_dialog_path("structure_export", path)
        self.project_panel.export_dir.set(str(target_dir))
        messagebox.showinfo('Export successful', f"Exported:\n{path}")

    def export_slab_poscar(self):
        if not self.structure or not self.structure.atoms:
            messagebox.showerror('Slab POSCAR export failed', 'No slab or structure is available for export.')
            return
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        path = file_dialogs.asksaveasfilename(self.config_manager, "structure_export", parent=self,
            title='Export slab POSCAR',
            initialdir=str(self.current_task_dir),
            initialfile="POSCAR",
            defaultextension="",
            filetypes=[("VASP POSCAR", "POSCAR *.vasp *.poscar"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
                self.write_current_poscar(Path(path))
        except Exception as exc:
            messagebox.showerror('Slab POSCAR export failed', str(exc))
            return
        messagebox.showinfo('Export slab POSCAR', f"Exported:\n{path}")

    def on_atom_selected(self, index, atom):
        self.right_panel.update_selection(index, atom, self._active_structure())

    def _active_structure(self):
        return self.viewer.structure if getattr(self, "viewer", None) and self.viewer.structure is not None else self.structure

    def _sync_active_structure(self):
        active = self._active_structure()
        if active is not self.structure:
            self.structure = active
            self.structures[self.structure.name] = self.structure
        return self.structure

    def _push_structure_history(self, structure=None):
        structure = structure or self._active_structure()
        self.undo_stack.append(structure.copy())
        self.undo_stack = self.undo_stack[-50:]
        self.redo_stack.clear()

    def _restore_structure_snapshot(self, snapshot):
        self.structure = snapshot.copy()
        self.current_structure = self.structure
        self.preview_structure = None
        self.structures[self.structure.name] = self.structure
        self._store_active_structure_tab()
        self.viewer.set_structure(self.structure)

    def undo_structure_edit(self):
        if not self.undo_stack:
            messagebox.showinfo('Undo changes', 'No structure changes can be undone.')
            return
        self.redo_stack.append(self._active_structure().copy())
        self._restore_structure_snapshot(self.undo_stack.pop())

    def redo_structure_edit(self):
        if not self.redo_stack:
            messagebox.showinfo('Redo changes', 'No structure changes can be redone.')
            return
        self.undo_stack.append(self._active_structure().copy())
        self._restore_structure_snapshot(self.redo_stack.pop())

    def generated_structure_dir(self):
        configured = self.config_manager.data.get("generated_structure_dir", "").strip()
        return Path(normalize_local_path(configured)) if configured else OUTPUTS_DIR / "structures"

    def auto_save_generated_structure(self, operation="generated"):
        if not self.structure or not self.structure.atoms:
            return None
        root = self.generated_structure_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in Path(self.structure.name).stem)
        target = root / f"{stamp}_{operation}_{safe_name}"
        target.mkdir(parents=True, exist_ok=True)
        self.write_current_poscar(target / "POSCAR")
        write_cif(target / f"{safe_name}.cif", self.structure)
        self.last_generated_structure_path = target
        return target

    def fix_selection(self):
        structure = self._active_structure()
        selected = structure.selected_indices()
        if not selected:
            messagebox.showwarning('Fix selection', 'Select atoms first.')
            return
        self._push_structure_history(structure)
        structure.fix_selected()
        self._sync_active_structure()
        self.viewer.redraw()
        first = selected[0]
        self.right_panel.update_selection(first, structure.atoms[first], structure)
        self.auto_save_generated_structure("fixed")

    def replace_selection(self):
        structure = self._active_structure()
        selected = structure.selected_indices()
        if not selected:
            messagebox.showwarning('Replace selection', 'Select atoms first.')
            return
        atom = structure.atoms[selected[0]]
        ReplaceDialog(self, atom.element, len(selected), self._apply_replace)

    def _apply_replace(self, element, mode="selected", count=1, ratio=100, seed=2026):
        structure = self._active_structure()
        self._push_structure_history(structure)
        selected = structure.selected_indices()
        if mode == "random":
            rng = random.Random(seed)
            chosen = set(rng.sample(selected, min(max(0, int(count)), len(selected))))
            for i, atom in enumerate(structure.atoms):
                if i in chosen:
                    atom.element = element
        elif mode == "ratio":
            n = round(len(selected) * max(0.0, min(100.0, float(ratio))) / 100)
            rng = random.Random(seed)
            chosen = set(rng.sample(selected, min(n, len(selected))))
            for i, atom in enumerate(structure.atoms):
                if i in chosen:
                    atom.element = element
        else:
            structure.replace_selected(element)
        structure.pmg_structure = None
        self._sync_active_structure()
        self.viewer.redraw()
        self.project_panel.add_structure(f"{Path(self.structure.name).stem}_replace_{element}")
        self.auto_save_generated_structure("replace")

    def delete_selection(self):
        structure = self._active_structure()
        count = len(structure.selected_indices())
        if not count:
            messagebox.showwarning('Delete selection', 'Select atoms first.')
            return
        if messagebox.askyesno('Delete selection', f"Delete the selected {count} atoms?"):
            self._push_structure_history(structure)
            structure.delete_selected()
            structure.pmg_structure = None
            self._sync_active_structure()
            self.viewer.redraw()
            self.auto_save_generated_structure("delete")

    def make_supercell(self):
        SupercellDialog(self, self.preview_supercell, self.apply_supercell)

    def preview_supercell(self, nx, ny, nz):
        self.preview_structure = self.structure.supercell(nx, ny, nz)
        self.viewer.set_structure(self.preview_structure)
        messagebox.showinfo('Preview supercell', f"Current preview: {nx}×{ny}×{nz}; atoms: {len(self.preview_structure.atoms)}。")

    def apply_supercell(self, nx, ny, nz):
        self._push_structure_history(self.structure)
        self.structure = self.structure.supercell(nx, ny, nz)
        self.structures[self.structure.name] = self.structure
        self.project_panel.add_structure(self.structure.name)
        self._store_active_structure_tab()
        self.viewer.set_structure(self.structure)
        saved = self.auto_save_generated_structure("supercell")
        messagebox.showinfo('Build supercell', f"Applied {nx}×{ny}×{nz} supercell; atoms: {len(self.structure.atoms)}.\nAutosaved: {saved}")

    def preview_slab(self, params=None):
        params = params or self.right_panel.get_slab_params()
        try:
            result = generate_slab(
                self.structure,
                (params["h"], params["k"], params["l"]),
                params["layers"],
                params["vacuum"],
                params.get("termination_index", 0),
            )
            slab = result.lightweight
            self._fix_bottom_layers(slab, params.get("fixed_layers", 2), params.get("layer_tolerance", 0.2))
            self.preview_structure = slab
            self.viewer.set_structure(slab)
            messagebox.showinfo('Preview slab structure', "\n".join(f"{k}: {v}" for k, v in result.summary.items()))
        except Exception as exc:
            messagebox.showerror('Slab preview failed', str(exc))

    def apply_slab(self, params, notify=True):
        original = self.structure.copy()
        try:
            result = generate_slab(
                self.structure,
                (params["h"], params["k"], params["l"]),
                params["layers"],
                params["vacuum"],
                params.get("termination_index", 0),
            )
        except Exception as exc:
            if notify:
                messagebox.showerror('Slab generation failed', str(exc))
                return None
            raise
        self.structure = result.lightweight
        self.undo_stack.append(original)
        self.redo_stack.clear()
        self._fix_bottom_layers(self.structure, params.get("fixed_layers", 2), params.get("layer_tolerance", 0.2))
        self.current_slab_area = cross_section_area(result.structure.lattice)
        self.structures[self.structure.name] = self.structure
        self._set_current_task(self.structure.name)
        self.project_panel.add_structure(self.structure.name)
        self.project_panel.add_task(self.current_task_name)
        self._store_active_structure_tab()
        self.viewer.set_structure(self.structure)
        saved = self.auto_save_generated_structure("slab")
        summary = {
            **result.summary,
            "task_directory": str(self.current_task_dir),
            "saved": str(saved),
        }
        if notify:
            messagebox.showinfo('Generate slab', f"Applied slab: {self.structure.name}\nTermination: {result.termination.label}\nCurrent task directory:\n{self.current_task_dir}\nAutosaved: {saved}")
        return summary

    def _fix_bottom_layers(self, structure, fixed_layers=2, tolerance=0.2):
        fixed_layers = max(0, int(fixed_layers or 0))
        if fixed_layers == 0 or not structure.atoms:
            return
        tolerance = max(0.01, float(tolerance or 0.2))
        layers = []
        for z in sorted(atom.z for atom in structure.atoms):
            if not layers or abs(z - layers[-1]) > tolerance:
                layers.append(z)
        cutoff_layers = layers[:fixed_layers]
        for atom in structure.atoms:
            atom.fixed = any(abs(atom.z - z) <= tolerance for z in cutoff_layers)

    def list_terminations(self, params):
        try:
            terms = list_slab_terminations(self.structure, (params["h"], params["k"], params["l"]))
        except Exception as exc:
            messagebox.showerror('Failed to list terminations', str(exc))
            return
        self.right_panel.set_terminations(terms)
        messagebox.showinfo('Terminations', f"Found {len(terms)} terminations.")

    def generate_incar(self):
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        path = self.current_task_dir / "INCAR"
        write_incar(path, self.bottom_panel.get_incar_text())
        messagebox.showinfo('Generate INCAR', f"Generated:\n{path}")

    def generate_kpoints(self):
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        path = self.current_task_dir / "KPOINTS"
        mesh, mode = self.bottom_panel.get_kpoints_settings()
        write_kpoints(path, mesh=mesh, mode=mode)
        messagebox.showinfo('Generate KPOINTS', f"Generated:\n{path}")

    def _potcar_root(self):
        root = self.bottom_panel.get_potcar_root() if hasattr(self, "bottom_panel") else ""
        return normalize_local_path(root or self.config_manager.data.get("potcar_root", ""))

    def set_potcar_root(self, path):
        path = normalize_local_path(path)
        self.config_manager.data["potcar_root"] = path
        self.config_manager.save()
        if hasattr(self, "bottom_panel") and hasattr(self.bottom_panel, "potcar_root"):
            self.bottom_panel.potcar_root.set(path)

    def match_potcar(self):
        if not self.structure or not self.structure.atoms:
            raise RuntimeError('No current structure; cannot match POTCAR.')
        elements = self.structure.elements
        poscar_path = self.current_task_dir / "POSCAR"
        if poscar_path.exists():
            try:
                elements = get_elements_from_poscar(poscar_path)
            except Exception:
                pass
        return PotcarManager(self._potcar_root()).match_elements(elements)

    def generate_potcar(self):
        if not self.structure or not self.structure.atoms:
            messagebox.showerror('POTCAR generation failed', 'No current structure.')
            return False
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        poscar_path = self.current_task_dir / "POSCAR"
        if not poscar_path.exists():
            self.write_current_poscar(poscar_path)
        try:
            elements = get_elements_from_poscar(poscar_path)
            PotcarManager(self._potcar_root()).build_potcar(elements, self.current_task_dir / "POTCAR")
            self.project_panel.add_generated_files(["POTCAR"])
            messagebox.showinfo('Generate POTCAR', f"Generated:\n{self.current_task_dir / 'POTCAR'}")
            return True
        except Exception as exc:
            messagebox.showerror('POTCAR generation failed', str(exc))
            return False

    def check_potcar(self):
        try:
            matches, missing = self.match_potcar()
            lines = [f"{element}: {path if path else 'Not found'}" for element, path in matches]
            if missing:
                messagebox.showerror('POTCAR validation failed', 'No POTCAR matched the following elements:\n' + "\n".join(lines))
            else:
                messagebox.showinfo('Validate POTCAR', 'POTCAR element-order and file-matching checks passed:\n' + "\n".join(lines))
        except Exception as exc:
            messagebox.showerror('POTCAR validation failed', str(exc))

    def submit_script_name(self):
        return (
            self.config_manager.data.get("submit_script")
            or self.config_manager.data.get("slurm_script_name")
            or "Svasp.sh"
        ).strip()

    def required_task_files(self):
        return standard_vasp_files(self.submit_script_name())

    def generate_slurm(self):
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        script_name = self.submit_script_name()
        try:
            write_slurm(self.current_task_dir / script_name, self.config_manager.data, job_name=self.current_task_name)
            self.project_panel.add_generated_files([script_name])
            messagebox.showinfo('Generate submission script', f"Generated:\n{self.current_task_dir / script_name}")
            return True
        except Exception as exc:
            messagebox.showerror('Submission script generation failed', str(exc))
            return False

    def generate_inputs(self):
        if not self.structure or not self.structure.atoms:
            messagebox.showerror('Input generation failed', 'No current structure.')
            return False
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        script_name = self.submit_script_name()
        errors = []
        created = []
        poscar_path = self.current_task_dir / "POSCAR"
        try:
            self.write_current_poscar(poscar_path)
            created.append("POSCAR")
        except Exception as exc:
            errors.append(f"POSCAR generation failed: {exc}")
        try:
            write_incar(self.current_task_dir / "INCAR", self.bottom_panel.get_incar_text())
            created.append("INCAR")
        except Exception as exc:
            errors.append(f"INCAR generation failed: {exc}")
        try:
            mesh, mode = self.bottom_panel.get_kpoints_settings()
            write_kpoints(self.current_task_dir / "KPOINTS", mesh=mesh, mode=mode)
            created.append("KPOINTS")
        except Exception as exc:
            errors.append(f"KPOINTS generation failed: {exc}")
        try:
            write_slurm(self.current_task_dir / script_name, self.config_manager.data, job_name=self.current_task_name)
            created.append(script_name)
        except Exception as exc:
            errors.append(f"{script_name} generation failed: {exc}")
        try:
            elements = get_elements_from_poscar(poscar_path) if poscar_path.exists() else self.structure.elements
            PotcarManager(self._potcar_root()).build_potcar(elements, self.current_task_dir / "POTCAR")
            created.append("POTCAR")
        except Exception as exc:
            errors.append(f"POTCAR generation failed: {exc}")

        required = self.required_task_files()
        missing, empty = validate_task_files(self.current_task_dir, required)
        if missing or empty:
            errors.append(format_task_file_errors(self.current_task_dir, missing, empty))
        if errors:
            if created:
                self.project_panel.add_generated_files(created)
            messagebox.showerror('Input generation failed', "\n\n".join(errors))
            return False
        self.project_panel.add_generated_files(required)
        messagebox.showinfo('Generate input files', f"Generated POSCAR / INCAR / KPOINTS / POTCAR / {script_name}：\n{self.current_task_dir}")
        return True

    def validate_current_task_files(self, show_error=True):
        missing, empty = validate_task_files(self.current_task_dir, self.required_task_files())
        if missing or empty:
            if show_error:
                messagebox.showwarning('Current task files are incomplete', format_task_file_errors(self.current_task_dir, missing, empty))
            return False
        return True

    def ensure_current_task_files(self):
        if self.validate_current_task_files(show_error=False):
            return True
        missing, empty = validate_task_files(self.current_task_dir, self.required_task_files())
        message = format_task_file_errors(self.current_task_dir, missing, empty)
        message += '\n\nRegenerate the standard input files now?'
        if not messagebox.askyesno('Pre-upload validation failed', message):
            return False
        return self.generate_inputs()

    def submit_job(self):
        if self.generate_inputs():
            self.open_ssh()

    def integrated_run(self):
        self.submit_job()

    def show_slurm(self):
        top = tk.Toplevel(self)
        top.title('Slurm script templates')
        text = tk.Text(top, width=80, height=22)
        text.pack(fill="both", expand=True)
        text.insert("1.0", render_slurm(self.config_manager.data, job_name=self.current_task_name))

    def open_ssh(self):
        SimpleSSHDialog(
            self,
            self.config_manager.data,
            self.config_manager,
            self.current_task_dir,
            self.project_dir.name,
            self.current_task_name,
            on_connected=self.on_ssh_connected,
            shared_client=self.ssh_manager,
        )

    def on_ssh_connected(self, ssh_manager, home_path, items):
        self.ssh_manager = ssh_manager
        self.remote_panel.set_connection(ssh_manager, items, home_path)
        if hasattr(self, "status_text"):
            self.status_text.set(
                f"SSH connected · {getattr(ssh_manager, 'username', '')}@"
                f"{getattr(ssh_manager, 'host', '')}"
            )

    def open_settings(self):
        SettingsDialog(
            self,
            self.config_manager,
            self.set_potcar_root,
            self.apply_background_image,
        )

    def apply_background_image(self, path):
        raw_path = str(path or "").strip()
        if not raw_path:
            self.viewer.set_background_image("")
            self._active_background_path = ""
            self._wallpaper_source = None
            self._wallpaper_render = None
            self._wallpaper_render_size = None
            self._wallpaper_label.configure(image="", bg=BG)
            self._wallpaper_label.lower()
            refresh_window_backgrounds(self, "")
            return True
        image_path = Path(raw_path)
        if not image_path.is_file():
            return False
        try:
            from PIL import Image

            with Image.open(image_path) as source:
                self._wallpaper_source = source.convert("RGB")
                self._wallpaper_source.load()
        except (ImportError, OSError, ValueError):
            return False
        self.viewer.set_background_image(raw_path)
        self._active_background_path = raw_path
        self._wallpaper_render = None
        self._wallpaper_render_size = None
        self._render_wallpaper()
        refresh_window_backgrounds(self, raw_path)
        return True

    def _schedule_wallpaper_render(self, event=None):
        if event is not None and event.widget is not self:
            return
        if self._wallpaper_source is None:
            return
        if self._wallpaper_after_id:
            try:
                self.after_cancel(self._wallpaper_after_id)
            except tk.TclError:
                pass
        self._wallpaper_after_id = self.after(140, self._render_wallpaper)

    def _render_wallpaper(self):
        self._wallpaper_after_id = None
        if self._wallpaper_source is None:
            return
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        size = (width, height)
        if size == self._wallpaper_render_size:
            return
        try:
            from PIL import Image, ImageTk

            source = self._wallpaper_source
            factor = max(width / source.width, height / source.height)
            resampling = getattr(Image, "Resampling", Image)
            resized = source.resize(
                (
                    max(1, round(source.width * factor)),
                    max(1, round(source.height * factor)),
                ),
                resampling.LANCZOS,
            )
            left = max(0, (resized.width - width) // 2)
            top = max(0, (resized.height - height) // 2)
            resized = resized.crop((left, top, left + width, top + height))
            overlay = Image.new(
                "RGB",
                size,
                "#dceaff" if IS_LIGHT_THEME else PANEL_ALT,
            )
            # A light wash keeps the wallpaper visible without reducing
            # contrast around the functional panels.
            composited = Image.blend(resized, overlay, 0.24)
            self._wallpaper_render = ImageTk.PhotoImage(composited)
            self._wallpaper_render_size = size
            self._wallpaper_label.configure(image=self._wallpaper_render)
            self._wallpaper_label.lower()
        except (ImportError, OSError, ValueError, tk.TclError):
            self._wallpaper_render = None

    def open_local_dir(self):
        self.current_task_dir.mkdir(parents=True, exist_ok=True)
        try:
            open_path(self.current_task_dir)
        except OSError:
            messagebox.showinfo('Local task directory', str(self.current_task_dir))

    def confirm_delete_task(self):
        if messagebox.askyesno('Delete calculation task', f"Delete the current task directory?\n{self.current_task_dir}"):
            task_root = self.project_dir / "tasks"
            if not is_path_within(self.current_task_dir, task_root):
                messagebox.showerror('Delete calculation task', "Safety check failed: the target is outside this project's tasks directory.")
                return
            shutil.rmtree(self.current_task_dir)
            self._set_current_task("default_task")
            messagebox.showinfo('Delete calculation task', 'Task deleted; switched back to default_task.')

    def about(self):
        messagebox.showinfo(
            'About iface',
            f"{DISPLAY_NAME}\nVersion: {APP_VERSION}\n"
            'Structure modeling, VASP input generation, SSH/SFTP file transfer, '
            'Slurm high-throughput queues and stepwise calculation monitoring for alloy systems.',
        )

    def show_user_guide(self):
        english = self.lang.language == "en_US"
        title = "User Guide" if english else 'User guide'
        guide = (
            "1. Import CIF/POSCAR/CONTCAR and inspect the lattice and atoms.\n"
            "2. Open Structure Tools to select, measure, fix, replace or delete atoms.\n"
            "3. Build a slab from the right panel, or open High Throughput for A/B interfaces.\n"
            "4. For interface scans, select one or more A/B structures and set layer and spacing ranges.\n"
            "5. Review the preview and atom count before applying or exporting a model.\n"
            "6. Generate POSCAR, INCAR, KPOINTS, POTCAR and Svasp.sh in the bottom panel.\n"
            "7. Run the preflight checks and correct every red item before uploading.\n"
            "8. Open SSH, connect, browse to the target directory, then upload and verify files.\n"
            "9. Submit only after confirming the remote command and target directory.\n"
            "10. Use Task Center to monitor Slurm state and progress; review recovery suggestions before retrying.\n"
            "11. Download CONTCAR/OUTCAR/vasprun.xml, then use Result Analysis or Post-processing.\n"
            "12. Bader, CI-NEB, VASPsol and COHP entries are input templates, not complete external workflows."
            if english else
            '[1. Structures and modeling]\n'
            '1. Click Import structure, select CIF, POSCAR or CONTCAR, and check the lattice, atom count and elements.\n'
            '2. Open Structure tools for batch selection, distances and angles, fixing, substitution, deletion or addition of atoms.\n'
            '3. To build a surface, enter Miller indices, layers, thickness and vacuum on the right. Preview the slab before generating it.\n'
            '4. For two-material interfaces, open High throughput, select A/B structures, and set layer-count and spacing minimum, maximum and step values.\n'
            '5. Review the estimated model count, mismatch, strain and atoms. Confirm the 1000-atom limit before applying or exporting.\n\n'
            '[2. Generate and submit calculations]\n'
            '6. Generate POSCAR, INCAR, KPOINTS, POTCAR and Svasp.sh in the bottom panel.\n'
            '7. Run validation and correct all missing files, element-order issues and parameter errors before uploading.\n'
            '8. Open SSH, enter host, port, username and password, connect, and navigate to the intended remote submission directory.\n'
            '9. Click Upload current task and wait for file verification. Recheck the remote path and submission command before submitting.\n'
            '10. Track queued/running tasks and electronic/ionic steps in Task center. Review recovery suggestions before retrying.\n\n'
            '[3. Results and AI]\n'
            '11. Download CONTCAR, OUTCAR, vasprun.xml and other results, then analyze energies, spacings, PDOS or charge differences.\n'
            '12. iface Agent uses DeepSeek. Test the key before encrypted storage; writing files and submitting still require user confirmation.\n'
            '13. Bader, CI-NEB, VASPsol and COHP provide input templates. External programs, plugins, NEB image directories and final result checks must be prepared separately.'
        )
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry("720x480")
        text = tk.Text(top, wrap="word", padx=16, pady=16)
        text.pack(fill="both", expand=True)
        text.insert("1.0", guide)
        text.configure(state="disabled")

    def show_feature_status(self):
        text_value = (
            'Implemented features (validated items are listed in the release acceptance report)\n'
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            '1. Projects: create, open, save, copy/delete tasks and browse real directories.\n'
            '2. Structures: CIF/POSCAR/CONTCAR/VASP/XSF import, conversion, undo/redo, '
            'selection, fixing, replacement, deletion, supercells, A/B/C views and periodic cell display.\n'
            '3. Modeling: surface termination search, slabs, two-material lattice matching, spacing/offset candidates, '
            'strain and compatibility scores, and the 1000-atom limit.\n'
            '4. VASP: INCAR templates and validation, KPOINTS, POTCAR matching/concatenation, POSCAR and '
            'Slurm Svasp.sh generation.\n'
            '5. Remote: SSH/SFTP, directory browsing, upload/download, remote editing and command execution; '
            'bundle staging, SHA-256 checks, atomic publication and backups.\n'
            '6. Tasks: dependency queues, up to 10 active tasks, Slurm query/cancel/retry, '
            'electronic/ionic progress and error detection; reconcile unclear submissions via squeue/sacct '
            'before resubmission.\n'
            '7. Results: OUTCAR/OSZICAR/CONTCAR reading, energy, force, convergence and surface energy.\n'
            '8. Post-processing: three-system CHGCAR checks and subtraction; PDOS; PNG/TIFF/PDF/SVG/'
            'Excel/NPZ scientific exports.\n'
            '9. High throughput: dependent relax → static → PDOS → charge-difference workflows and '
            'adaptive interface rebuilding after bulk relaxation.\n'
            '10. Recovery: allowed parameter changes for recognized errors; after approval, save before snapshots and '
            'recovery.json audit records, then requeue. High-risk errors require manual handling.\n'
            '11. iface Agent: workspace context, allowed tools, risk levels and confirmation before execution.\n\n'
            '12. Template scope: Bader, CI-NEB, VASPsol and COHP provide INCAR preprocessing templates, '
            'including no external-program installation, NEB image generation or complete LOBSTER workflow.\n\n'
            'Final acceptance requires an external environment\n'
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            '• Real Slurm submission requires a valid server login and correct server module/'
            'VASP 6.4.3 launch commands.\n'
            '• Online iface Agent planning requires a valid DeepSeek API key and network access to its API.\n'
            '• Real PDOS parsing requires a complete vasprun.xml from a finished calculation.\n'
            '• Real charge-difference analysis requires three CHGCAR files with matching grids, cells and atom ordering.\n'
        )
        top = tk.Toplevel(self)
        top.title('Feature list and acceptance status')
        top.geometry("820x650")
        viewer = tk.Text(
            top,
            wrap="word",
            padx=18,
            pady=16,
            font=(UI_FONT, 10),
        )
        viewer.pack(fill="both", expand=True)
        viewer.insert("1.0", text_value)
        viewer.configure(state="disabled")

    def open_incar_templates(self):
        presets = {
            'Alloy relaxation (magnetic)': {
                "SYSTEM": "alloy_relax",
                "ENCUT": "520",
                "EDIFF": "1E-6",
                "EDIFFG": "-0.02",
                "ISPIN": "2",
                "MAGMOM": 'Autofill: check each element',
                "IBRION": "2",
                "NSW": "120",
                "ISIF": "3",
                "ISMEAR": "1",
                "SIGMA": "0.20",
                "LREAL": "Auto",
                "LASPH": ".TRUE.",
            },
            'Surface/interface relaxation (magnetic)': {
                "SYSTEM": "surface_interface_relax",
                "ENCUT": "520",
                "EDIFF": "1E-6",
                "EDIFFG": "-0.02",
                "ISPIN": "2",
                "MAGMOM": 'Autofill: check each element',
                "IBRION": "2",
                "NSW": "150",
                "ISIF": "2",
                "ISMEAR": "1",
                "SIGMA": "0.20",
                "LREAL": "Auto",
                "LDIPOL": ".TRUE.",
                "IDIPOL": "3",
                "LASPH": ".TRUE.",
            },
            'Static self-consistent energy': {
                "SYSTEM": "static",
                "ENCUT": "520",
                "EDIFF": "1E-7",
                "ISPIN": "2",
                "IBRION": "-1",
                "NSW": "0",
                "ISMEAR": "-5",
                "LREAL": ".FALSE.",
                "LCHARG": ".TRUE.",
                "LWAVE": ".TRUE.",
                "LASPH": ".TRUE.",
            },
            "PDOS": {
                "SYSTEM": "pdos",
                "ENCUT": "520",
                "EDIFF": "1E-7",
                "ISPIN": "2",
                "IBRION": "-1",
                "NSW": "0",
                "ISMEAR": "-5",
                "LORBIT": "11",
                "NEDOS": "3001",
                "LREAL": ".FALSE.",
                "ICHARG": "11",
            },
            'DFT+U (check element parameters)': {
                "ENCUT": "520",
                "EDIFF": "1E-6",
                "ISPIN": "2",
                "LDAU": ".TRUE.",
                "LDAUTYPE": "2",
                "LDAUL": 'Enter values for each element',
                "LDAUU": 'Enter values for each element',
                "LDAUJ": 'Enter values for each element',
                "LMAXMIX": "4",
                "LASPH": ".TRUE.",
            },
            'van der Waals D3(BJ)': {
                "ENCUT": "520",
                "EDIFF": "1E-6",
                "ISPIN": "2",
                "IVDW": "12",
                "LASPH": ".TRUE.",
            },
        }
        elements = [atom.element for atom in self.structure.atoms]
        # Keep this dialog and the inline INCAR selector on one authoritative
        # VASP 6.x preset library. The historical dictionary above remains
        # readable during migration but is intentionally not exposed.
        presets = {
            label: get_incar_preset(key, elements)
            for key, label in PRESET_LABELS.items()
        }
        top = tk.Toplevel(self)
        top.title('INCAR templates')
        top.geometry("660x470")
        top.transient(self)
        host = ttk.Frame(top, padding=12)
        host.pack(fill="both", expand=True)
        bind_wraplength(ttk.Label(
            host,
            text='After selecting a template, check MAGMOM, DFT+U and system-specific parameters before generating INCAR.',
            style="Muted.TLabel",
            justify="left",
        )).pack(fill="x", pady=(0, 8))
        body = ttk.Frame(host)
        body.pack(fill="both", expand=True)
        names = tk.Listbox(body, exportselection=False, width=28)
        names.pack(side="left", fill="y")
        preview = tk.Text(body, wrap="none", font=(MONO_FONT, 10))
        preview.pack(side="left", fill="both", expand=True, padx=(10, 0))
        for name in presets:
            names.insert("end", name)

        def selected_text():
            if not names.curselection():
                return ""
            params = presets[names.get(names.curselection()[0])]
            return "\n".join(f"{key} = {value}" for key, value in params.items()) + "\n"

        def show_preview(_event=None):
            preview.delete("1.0", "end")
            preview.insert("1.0", selected_text())

        def apply_template():
            text = selected_text()
            if not text:
                messagebox.showinfo('INCAR templates', 'Select a template first.', parent=top)
                return
            self.bottom_panel.incar_text.delete("1.0", "end")
            self.bottom_panel.incar_text.insert("1.0", text)
            self.bottom_panel.incar_source.set('Loaded from the template library; check placeholder parameters before generation.')
            self.bottom_panel.tabs.select(0)
            top.destroy()

        names.bind("<<ListboxSelect>>", show_preview)
        names.bind("<Double-Button-1>", lambda _event: apply_template())
        names.selection_set(0)
        show_preview()
        buttons = ttk.Frame(host)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text='Cancel', command=top.destroy).pack(side="right")
        ttk.Button(
            buttons,
            text='Apply to INCAR',
            style="Primary.TButton",
            command=apply_template,
        ).pack(side="right", padx=(0, 8))

    def open_kpoints_settings(self):
        top = tk.Toplevel(self)
        top.title('KPOINTS settings')
        top.geometry("440x280")
        top.transient(self)
        host = ttk.Frame(top, padding=16)
        host.pack(fill="both", expand=True)
        mesh, current_mode = self.bottom_panel.get_kpoints_settings()
        mode = tk.StringVar(value=current_mode)
        values = [tk.StringVar(value=str(value)) for value in mesh]
        ttk.Label(host, text='Mesh type').grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(
            host,
            values=["Gamma", "Monkhorst-Pack"],
            textvariable=mode,
            state="readonly",
            width=20,
        ).grid(row=0, column=1, columnspan=3, sticky="ew", pady=6)
        for column, (label, variable) in enumerate(zip(("Kx", "Ky", "Kz"), values), 1):
            ttk.Label(host, text=label).grid(row=1, column=column, pady=(12, 4))
            ttk.Entry(host, textvariable=variable, width=8, justify="center").grid(
                row=2, column=column, padx=4, sticky="ew"
            )
        bind_wraplength(ttk.Label(
            host,
            text='Surface/interface calculations usually use Kz=1; recheck when the vacuum direction changes.',
            style="Muted.TLabel",
            justify="left",
        )).grid(row=3, column=0, columnspan=4, sticky="ew", pady=(14, 4))

        def apply_settings():
            try:
                parsed = [int(variable.get()) for variable in values]
                if any(value < 1 for value in parsed):
                    raise ValueError
            except ValueError:
                messagebox.showerror('KPOINTS settings', 'Kx, Ky and Kz must be integers greater than or equal to 1.', parent=top)
                return
            self.bottom_panel.kpoint_mode.set(mode.get())
            for label, value in zip(("Kx", "Ky", "Kz"), parsed):
                self.bottom_panel.kpoint_vars[label].set(str(value))
            self.bottom_panel.tabs.select(1)
            top.destroy()

        buttons = ttk.Frame(host)
        buttons.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        ttk.Button(buttons, text='Cancel', command=top.destroy).pack(side="right")
        ttk.Button(
            buttons,
            text='Apply settings',
            style="Primary.TButton",
            command=apply_settings,
        ).pack(side="right", padx=(0, 8))
        host.columnconfigure(0, weight=1)
        for column in range(1, 4):
            host.columnconfigure(column, weight=1)


def main():
    app = MainWindow()
    app.mainloop()
