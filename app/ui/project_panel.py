import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from app.ui import file_dialogs


class ProjectPanel(ttk.Frame):
    def __init__(self, master, tr, on_export):
        super().__init__(master, padding=6)
        self.tr = tr
        self.on_export = on_export
        self.config_manager = getattr(self.winfo_toplevel(), "config_manager", None)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        tree_card = ttk.LabelFrame(
            self,
            text=tr("project_tree"),
            style="Card.TLabelframe",
            padding=(9, 8),
        )
        tree_card.grid(row=0, column=0, sticky="nsew")
        self.tree = ttk.Treeview(tree_card, show="tree", height=18, selectmode="browse")
        tree_scroll = ttk.Scrollbar(tree_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self._populate_empty()

        bottom = ttk.LabelFrame(
            self,
            text='Export structure',
            style="Card.TLabelframe",
            padding=(9, 8),
        )
        # Keep export actions reserved and visible; only the tree is allowed
        # to shrink when the application height is limited.
        bottom.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(bottom, text=tr("export_format"), style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", pady=4
        )
        self.export_var = tk.StringVar(value="CIF")
        ttk.Combobox(
            bottom,
            values=["CIF", "POSCAR", "POTCAR"],
            textvariable=self.export_var,
            state="readonly",
            width=10,
        ).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(bottom, text='Export directory', style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", pady=4
        )
        saved = self.config_manager.data.get("dialog_directories", {}).get("structure_export", "") if self.config_manager else ""
        self.export_dir = tk.StringVar(value=saved)
        export_entry = ttk.Entry(bottom, textvariable=self.export_dir, width=12)
        export_entry.grid(
            row=1, column=1, sticky="ew", pady=4
        )
        export_entry.bind("<FocusOut>", self._remember_export_dir)
        ttk.Button(
            bottom,
            text='Browse',
            style="Compact.TButton",
            command=self._browse_export_dir,
        ).grid(row=1, column=2, padx=(5, 0), pady=4)

        ttk.Label(bottom, text='File name', style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=4
        )
        self.filename = tk.StringVar(value="")
        ttk.Entry(bottom, textvariable=self.filename).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=4
        )
        ttk.Button(
            bottom,
            text=tr("export"),
            style="Primary.TButton",
            command=self._export,
        ).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(1, weight=1)

    def _browse_export_dir(self):
        path = file_dialogs.askdirectory(self.config_manager, "structure_export", parent=self, title='Select export directory')
        if path:
            self.export_dir.set(path)

    def _remember_export_dir(self, _event=None):
        if self.config_manager:
            self.config_manager.remember_dialog_path("structure_export", self.export_dir.get(), is_directory=True)

    def _export(self):
        self.on_export(
            self.export_var.get(),
            self.export_dir.get().strip(),
            self.filename.get().strip(),
        )

    def _populate_empty(self, project_name='No project open'):
        self.tree.delete(*self.tree.get_children())
        self.root = self.tree.insert("", "end", text=project_name, open=True)
        self.groups = {}
        for group in (
            'Structure files',
            'Calculation tasks',
            'KPOINTS tests',
            'ENCUT tests',
            'Generated input files',
        ):
            parent = self.tree.insert(self.root, "end", text=group, open=True)
            self.groups[group] = parent

    def load_project(self, project_dir):
        project_dir = Path(project_dir)
        self._populate_empty(project_dir.name)
        structure_suffixes = {".cif", ".vasp", ".poscar", ".contcar", ".xsf"}
        if project_dir.is_dir():
            for path in sorted(project_dir.iterdir()):
                if path.is_file() and (
                    path.suffix.lower() in structure_suffixes
                    or path.name.upper() in {"POSCAR", "CONTCAR"}
                ):
                    self.add_structure(path.name)
        task_root = project_dir / "tasks"
        if task_root.is_dir():
            for task_dir in sorted(path for path in task_root.iterdir() if path.is_dir()):
                self.add_task(task_dir.name)
        generated = []
        for filename in ("INCAR", "KPOINTS", "POSCAR", "POTCAR", "Svasp.sh"):
            if any((task_root / task / filename).is_file() for task in self._task_names()):
                generated.append(filename)
        self.add_generated_files(generated)

    def _task_names(self):
        parent = self.groups['Calculation tasks']
        return [self.tree.item(child, "text") for child in self.tree.get_children(parent)]

    def set_project_name(self, name):
        self.tree.item(self.root, text=name)

    def _add_unique(self, group, name):
        parent = self.groups[group]
        existing = [self.tree.item(child, "text") for child in self.tree.get_children(parent)]
        if name not in existing:
            self.tree.insert(parent, "end", text=name)

    def add_structure(self, name):
        self._add_unique('Structure files', name)

    def add_task(self, name):
        self._add_unique('Calculation tasks', name)

    def add_generated_files(self, names):
        for name in names:
            self._add_unique('Generated input files', name)

    def set_default_filename(self, name):
        self.filename.set(name)
