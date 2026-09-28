import tkinter as tk
from datetime import datetime
import random
import socket
from pathlib import Path
from tkinter import messagebox, ttk

from app.core.input_generators import scan_potcar_root
from app.core.path_utils import normalize_local_path
from app.core.platform_utils import open_path
from app.ui.theme import BG, BLUE, PANEL, THEME_PRESETS, TEXT, MONO_FONT_FAMILY
from app.ui import file_dialogs
from app.ui.responsive_rows import VerticalScrolledFrame, WidthLabel
from app.ui.window_geometry import fit_window_to_workarea


ELEMENTS = [
    ("H", "Hydrogen"), ("He", "Helium"), ("Li", "Lithium"), ("Be", "Beryllium"), ("B", "Boron"), ("C", "Carbon"),
    ("N", "Nitrogen"), ("O", "Oxygen"), ("F", "Fluorine"), ("Ne", "Neon"), ("Na", "Sodium"), ("Mg", "Magnesium"),
    ("Al", "Aluminium"), ("Si", "Silicon"), ("P", "Phosphorus"), ("S", "Sulfur"), ("Cl", "Chlorine"), ("Ar", "Argon"),
    ("K", "Potassium"), ("Ca", "Calcium"), ("Sc", "Scandium"), ("Ti", "Titanium"), ("V", "Vanadium"), ("Cr", "Chromium"),
    ("Mn", "Manganese"), ("Fe", "Iron"), ("Co", "Cobalt"), ("Ni", "Nickel"), ("Cu", "Copper"), ("Zn", "Zinc"),
    ("Ga", "Gallium"), ("Ge", "Germanium"), ("As", "Arsenic"), ("Se", "Selenium"), ("Br", "Bromine"), ("Kr", "Krypton"),
    ("Rb", "Rubidium"), ("Sr", "Strontium"), ("Y", "Yttrium"), ("Zr", "Zirconium"), ("Nb", "Niobium"), ("Mo", "Molybdenum"),
    ("Tc", "Technetium"), ("Ru", "Ruthenium"), ("Rh", "Rhodium"), ("Pd", "Palladium"), ("Ag", "Silver"), ("Cd", "Cadmium"),
    ("In", "Indium"), ("Sn", "Tin"), ("Sb", "Antimony"), ("Te", "Tellurium"), ("I", "Iodine"), ("Xe", "Xenon"),
    ("Cs", "Caesium"), ("Ba", "Barium"), ("La", "Lanthanum"), ("Ce", "Cerium"), ("Pr", "Praseodymium"), ("Nd", "Neodymium"),
    ("Pm", "Promethium"), ("Sm", "Samarium"), ("Eu", "Europium"), ("Gd", "Gadolinium"), ("Tb", "Terbium"), ("Dy", "Dysprosium"),
    ("Ho", "Holmium"), ("Er", "Erbium"), ("Tm", "Thulium"), ("Yb", "Ytterbium"), ("Lu", "Lutetium"), ("Hf", "Hafnium"),
    ("Ta", "Tantalum"), ("W", "Tungsten"), ("Re", "Rhenium"), ("Os", "Osmium"), ("Ir", "Iridium"), ("Pt", "Platinum"),
    ("Au", "Gold"), ("Hg", "Mercury"), ("Tl", "Thallium"), ("Pb", "Lead"), ("Bi", "Bismuth"), ("Po", "Polonium"),
    ("At", "Astatine"), ("Rn", "Radon"), ("Fr", "Francium"), ("Ra", "Radium"), ("Ac", "Actinium"), ("Th", "Thorium"),
    ("Pa", "Protactinium"), ("U", "Uranium"), ("Np", "Neptunium"), ("Pu", "Plutonium"), ("Am", "Americium"), ("Cm", "Curium"),
    ("Bk", "Berkelium"), ("Cf", "Californium"), ("Es", "Einsteinium"), ("Fm", "Fermium"), ("Md", "Mendelevium"), ("No", "Nobelium"),
    ("Lr", "Lawrencium"), ("Rf", "Rutherfordium"), ("Db", "Dubnium"), ("Sg", "Seaborgium"), ("Bh", "Bohrium"), ("Hs", "Hassium"),
    ("Mt", "Meitnerium"), ("Ds", "Darmstadtium"), ("Rg", "Roentgenium"), ("Cn", "Copernicium"), ("Nh", "Nihonium"),
    ("Fl", "Flerovium"), ("Mc", "Moscovium"), ("Lv", "Livermorium"), ("Ts", "Tennessine"), ("Og", "Oganesson"),
]


class PeriodicTableDialog(tk.Toplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.title("Select an element")
        self.configure(bg=BG)
        self.callback = callback
        frame = ttk.Frame(self, padding=12, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        for index, (symbol, name) in enumerate(ELEMENTS, 1):
            row = (index - 1) // 18
            col = (index - 1) % 18
            btn = ttk.Button(frame, text=symbol, width=4, command=lambda s=symbol: self.choose(s))
            btn.grid(row=row, column=col, padx=1, pady=1)
            self._tooltip(btn, f"{index}  {name}")
        self.transient(master)
        self.grab_set()

    def _tooltip(self, widget, text):
        tip = {"win": None}

        def enter(_event):
            tip["win"] = tk.Toplevel(widget)
            tip["win"].wm_overrideredirect(True)
            tip["win"].geometry(f"+{widget.winfo_rootx()+18}+{widget.winfo_rooty()+18}")
            ttk.Label(tip["win"], text=text, padding=4).pack()

        def leave(_event):
            if tip["win"]:
                tip["win"].destroy()
                tip["win"] = None

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def choose(self, symbol):
        self.callback(symbol)
        self.destroy()


class ReplaceDialog(tk.Toplevel):
    def __init__(self, master, current_element, selected_count, callback):
        super().__init__(master)
        self.title("Replace selected atoms")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.callback = callback
        frame = ttk.Frame(self, padding=16, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(frame, text=f"Current selection: {selected_count} atoms", style="Panel.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text=f"Original element: {current_element}", style="Panel.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))
        ttk.Label(frame, text="Target element: ", style="Panel.TLabel").grid(row=2, column=0, sticky="w")
        self.element = tk.StringVar(value="Ce" if current_element != "Ce" else "Al")
        ttk.Label(frame, textvariable=self.element, style="Title.TLabel").grid(row=2, column=1, sticky="w")
        ttk.Button(frame, text="Choose from periodic table", command=lambda: PeriodicTableDialog(self, self.element.set)).grid(row=2, column=2, sticky="ew")
        self.mode = tk.StringVar(value="selected")
        for i, (text, value) in enumerate([("Replace all selected atoms", "selected"), ("Randomly replace N selected atoms", "random"), ("Replace a fraction", "ratio")], 3):
            ttk.Radiobutton(frame, text=text, variable=self.mode, value=value).grid(row=i, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(frame, text="Number to replace", style="Panel.TLabel").grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.count = tk.IntVar(value=min(1, selected_count))
        ttk.Entry(frame, textvariable=self.count, width=8).grid(row=6, column=1, sticky="w", pady=(8, 0))
        ttk.Label(frame, text="Fraction (%)", style="Panel.TLabel").grid(row=7, column=0, sticky="w")
        self.ratio = tk.DoubleVar(value=12.5)
        ttk.Entry(frame, textvariable=self.ratio, width=8).grid(row=7, column=1, sticky="w")
        ttk.Label(frame, text="Random seed", style="Panel.TLabel").grid(row=8, column=0, sticky="w")
        self.seed = tk.IntVar(value=2026)
        ttk.Entry(frame, textvariable=self.seed, width=8).grid(row=8, column=1, sticky="w")
        ttk.Button(frame, text="Preview replacement", command=self.apply).grid(row=9, column=0, pady=(12, 0), sticky="ew")
        ttk.Button(frame, text="Apply replacement", style="Primary.TButton", command=self.apply).grid(row=9, column=1, pady=(12, 0), sticky="ew")
        ttk.Button(frame, text="Cancel", command=self.destroy).grid(row=9, column=2, pady=(12, 0), padx=(8, 0), sticky="ew")
        self.transient(master)
        self.grab_set()

    def apply(self):
        self.callback(self.element.get().strip() or "Ce", self.mode.get(), self.count.get(), self.ratio.get(), self.seed.get())
        self.destroy()


class SupercellDialog(tk.Toplevel):
    def __init__(self, master, preview_callback, apply_callback):
        super().__init__(master)
        self.title("Build supercell")
        self.configure(bg=BG)
        self.preview_callback = preview_callback
        self.apply_callback = apply_callback
        frame = ttk.Frame(self, padding=14, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(frame, text="Method 1: repeat along axes", style="Title.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        self.nx = tk.IntVar(value=2)
        self.ny = tk.IntVar(value=2)
        self.nz = tk.IntVar(value=1)
        for col, (label, var) in enumerate([("A repetitions", self.nx), ("B repetitions", self.ny), ("C repetitions", self.nz)]):
            ttk.Label(frame, text=label, style="Panel.TLabel").grid(row=1, column=col, sticky="w", pady=(8, 2))
            ttk.Spinbox(frame, from_=1, to=8, textvariable=var, width=6).grid(row=2, column=col, sticky="w")
        ttk.Label(frame, text="Method 2: transformation matrix (diagonal repetitions in this prototype)", style="Title.TLabel").grid(row=3, column=0, columnspan=4, sticky="w", pady=(12, 4))
        self.matrix = []
        defaults = ((2, 0, 0), (0, 2, 0), (0, 0, 1))
        for r in range(3):
            row = []
            for c in range(3):
                var = tk.IntVar(value=defaults[r][c])
                ttk.Entry(frame, textvariable=var, width=5).grid(row=4 + r, column=c, padx=2, pady=2)
                row.append(var)
            self.matrix.append(row)
        ttk.Button(frame, text="Preview supercell", command=self.preview).grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(frame, text="Apply supercell", style="Primary.TButton", command=self.apply).grid(row=7, column=1, sticky="ew", pady=(12, 0))
        ttk.Button(frame, text="Cancel", command=self.destroy).grid(row=7, column=2, sticky="ew", pady=(12, 0))
        self.transient(master)
        self.grab_set()

    def values(self):
        return max(1, self.nx.get()), max(1, self.ny.get()), max(1, self.nz.get())

    def preview(self):
        self.preview_callback(*self.values())

    def apply(self):
        self.apply_callback(*self.values())
        self.destroy()


class InterfaceBuilderDialog(tk.Toplevel):
    def __init__(self, master, structure_names, search_callback, preview_callback, apply_callback, export_callback):
        super().__init__(master)
        self.title("Interface model builder")
        fit_window_to_workarea(self, (1000, 540), (720, 420))
        self.configure(bg=BG)
        self.search_callback = search_callback
        self.preview_callback = preview_callback
        self.apply_callback = apply_callback
        self.export_callback = export_callback
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        self.a = tk.StringVar(value=structure_names[0] if structure_names else "")
        self.b = tk.StringVar(value=structure_names[-1] if structure_names else "")
        self.spacing = tk.DoubleVar(value=2.5)
        self.x_offset = tk.DoubleVar(value=0.0)
        self.y_offset = tk.DoubleVar(value=0.0)
        self.max_mismatch = tk.DoubleVar(value=5.0)
        for col, title, var in [(0, "Surface A", self.a), (2, "Surface B", self.b)]:
            panel = ttk.Frame(outer, style="Panel.TFrame", padding=8)
            panel.grid(row=0, column=col, sticky="nsew", padx=4)
            ttk.Label(panel, text=title, style="Title.TLabel").pack(anchor="w")
            ttk.Combobox(panel, textvariable=var, values=structure_names, state="readonly").pack(fill="x", pady=6)
            ttk.Combobox(panel, values=["top", "bottom", "auto"], state="readonly").pack(fill="x")
        params = ttk.Frame(outer, style="Panel.TFrame", padding=8)
        params.grid(row=0, column=1, sticky="nsew", padx=4)
        ttk.Label(params, text="Matching and assembly", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        for r, (label, var) in enumerate([("Maximum mismatch (%)", self.max_mismatch), ("Interlayer gap (Å)", self.spacing), ("X offset (Å)", self.x_offset), ("Y offset (Å)", self.y_offset)], 1):
            ttk.Label(params, text=label, style="Panel.TLabel").grid(row=r, column=0, sticky="w", pady=4)
            ttk.Entry(params, textvariable=var, width=10).grid(row=r, column=1, sticky="ew", pady=4)
        self.allow_supercell = tk.BooleanVar(value=True)
        ttk.Checkbutton(params, text="Allow supercell matching", variable=self.allow_supercell).grid(row=5, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(outer, style="Panel.TFrame")
        buttons.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Button(buttons, text="Search matches", command=self.search).pack(side="left")
        ttk.Button(buttons, text="Preview interface", style="Primary.TButton", command=self.preview).pack(side="left", padx=6)
        ttk.Button(buttons, text="Apply interface model", command=self.apply).pack(side="left")
        ttk.Button(buttons, text="Export POSCAR", command=self.export).pack(side="left", padx=6)
        self.table = ttk.Treeview(outer, columns=("idx", "term", "gap", "area", "atoms", "strain", "score"), show="headings", height=7)
        for col, text in [("idx", "#"), ("term", "Termination pair"), ("gap", "Gap (Å)"), ("area", "Area (Å²)"), ("atoms", "Atoms"), ("strain", "Strain"), ("score", "Score")]:
            self.table.heading(col, text=text)
            self.table.column(col, width=90 if col != "term" else 180)
        self.table.grid(row=2, column=0, columnspan=3, sticky="nsew")
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(2, weight=1)
        self.search()

    def search(self):
        self.table.delete(*self.table.get_children())
        for row in self.search_callback(self.a.get(), self.b.get(), self.max_mismatch.get()):
            self.table.insert("", "end", values=row)

    def _selected_plan(self):
        selected = self.table.selection()
        return self.table.item(selected[0], "values") if selected else None

    def preview(self):
        self.preview_callback(self.a.get(), self.b.get(), self.spacing.get(), self.x_offset.get(), self.y_offset.get(), self._selected_plan())

    def apply(self):
        self.apply_callback(self.a.get(), self.b.get(), self.spacing.get(), self.x_offset.get(), self.y_offset.get(), self._selected_plan())

    def export(self):
        self.export_callback()


class SSHConnectionDialog(tk.Toplevel):
    def __init__(self, master, config, config_manager=None):
        super().__init__(master)
        self.title("SSH connection manager")
        fit_window_to_workarea(self, (1000, 640), (760, 480))
        self.configure(bg=BG)
        self.config_data = config
        self.config_manager = config_manager
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        left.pack(side="left", fill="both", expand=False, padx=(0, 10))
        ttk.Label(left, text="Saved connections", style="Title.TLabel").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=24, height=10, borderwidth=0, bg=PANEL, activestyle="none")
        self.listbox.pack(fill="both", expand=True, pady=8)
        for item in self.config_data.get("servers", []):
            self.listbox.insert(tk.END, f"{item.get('name', 'server')}\n{item.get('username', '')}@{item.get('host', '')}:{item.get('port', 22)}")
        self.listbox.bind("<<ListboxSelect>>", self._load_selected)
        row = ttk.Frame(left, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Save", width=5, command=self.save_connection).pack(side="left", padx=2)
        ttk.Button(row, text="Delete", width=5, command=self.delete_selected).pack(side="left", padx=2)

        right = ttk.Frame(outer, style="Panel.TFrame", padding=12)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Connection settings", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        fields = [("Connection name", "cluster01 (compute node)"), ("Host", "cluster01.local"), ("Port", "22"), ("Username", "user"), ("Remote project directory", "/home/user/vasp")]
        self.vars = {}
        for i, (label, value) in enumerate(fields, 1):
            ttk.Label(right, text=label, style="Panel.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=value)
            self.vars[label] = var
            ttk.Entry(right, textvariable=var).grid(row=i, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Authentication", style="Panel.TLabel").grid(row=6, column=0, sticky="w", pady=4)
        self.auth_type = tk.StringVar(value="Password")
        ttk.Combobox(right, textvariable=self.auth_type, values=["Password", "Private key"], state="readonly").grid(row=6, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Password", style="Panel.TLabel").grid(row=7, column=0, sticky="w", pady=4)
        self.password = tk.StringVar(value="")
        ttk.Entry(right, textvariable=self.password, show="•").grid(row=7, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Private key file", style="Panel.TLabel").grid(row=8, column=0, sticky="w", pady=4)
        key_row = ttk.Frame(right, style="Panel.TFrame")
        key_row.grid(row=8, column=1, sticky="ew", pady=4)
        self.key_path = tk.StringVar(value="")
        ttk.Entry(key_row, textvariable=self.key_path).pack(side="left", fill="x", expand=True)
        ttk.Button(key_row, text="Browse", width=8, command=self.browse_key).pack(side="left", padx=(6, 0))
        self.remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Remember connection (no plain-text password)", variable=self.remember).grid(row=9, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(right, text="Connection log", style="Title.TLabel").grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 2))
        self.log = tk.Text(right, height=8, wrap="word")
        self.log.grid(row=11, column=0, columnspan=2, sticky="nsew")
        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Test connection", command=self.test_connection).pack(side="left")
        ttk.Button(buttons, text="Save connection", command=self.save_connection).pack(side="left", padx=6)
        ttk.Button(buttons, text="Connect", style="Primary.TButton", command=self.test_connection).pack(side="right")
        right.columnconfigure(1, weight=1)
        right.rowconfigure(11, weight=1)

    def browse_key(self):
        path = file_dialogs.askopenfilename(self.config_manager, "ssh_key", parent=self, title="Choose a private key file")
        if path:
            self.key_path.set(path)

    def add_log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")

    def _values(self):
        return {
            "name": self.vars["Connection name"].get().strip(),
            "host": self.vars["Host"].get().strip(),
            "port": self.vars["Port"].get().strip(),
            "username": self.vars["Username"].get().strip(),
            "remote_root": self.vars["Remote project directory"].get().strip(),
            "auth_type": "key" if self.auth_type.get() == "Private key" else "password",
            "key_path": self.key_path.get().strip(),
        }

    def test_connection(self):
        self.log.delete("1.0", "end")
        data = self._values()
        self.add_log(f"Connecting to {data['host']}:{data['port']}")
        ok, msg = self._test_ssh_connection(data)
        self.add_log(msg)
        if ok:
            messagebox.showinfo("SSH test", "Connected; remote echo SSH_OK test passed.")
        else:
            messagebox.showerror("SSH test failed", f"Connection failed: {msg}")

    def _test_ssh_connection(self, data):
        if not data["host"]:
            return False, "Host is empty."
        if not data["username"]:
            return False, "Username is empty."
        try:
            port = int(data["port"])
        except ValueError:
            return False, "Port must be a valid number."
        if data["auth_type"] == "key" and not data["key_path"]:
            return False, "Private key file does not exist."
        if data["auth_type"] == "key" and data["key_path"] and not Path(data["key_path"]).exists():
            return False, "Private key file does not exist."
        try:
            import paramiko
        except ImportError:
            return False, "Paramiko is not installed. Only parameter checks are available; install paramiko to test SSH."
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.add_log("Validating username and credentials")
            if data["auth_type"] == "key":
                key = paramiko.RSAKey.from_private_key_file(data["key_path"])
                client.connect(data["host"], port=port, username=data["username"], pkey=key, timeout=10, banner_timeout=10, auth_timeout=10)
            else:
                client.connect(data["host"], port=port, username=data["username"], password=self.password.get(), timeout=10, banner_timeout=10, auth_timeout=10, look_for_keys=False, allow_agent=False)
            self.add_log("Testing remote command echo SSH_OK")
            _stdin, stdout, _stderr = client.exec_command("echo SSH_OK")
            output = stdout.read().decode(errors="ignore").strip()
            client.close()
            return (output == "SSH_OK"), "Connected" if output == "SSH_OK" else "Connected, but the remote command test failed."
        except paramiko.AuthenticationException:
            return False, "Authentication failed. Check the username, password or private key."
        except paramiko.SSHException as exc:
            return False, f"SSH protocol error: {exc}"
        except socket.timeout:
            return False, "Connection timed out. Check the server address, port, network or VPN."
        except socket.gaierror:
            return False, "Cannot resolve host. Check the server address."
        except Exception as exc:
            return False, f"Unexpected error: {exc}"

    def save_connection(self):
        data = self._values()
        data["port"] = int(data["port"]) if str(data["port"]).isdigit() else data["port"]
        servers = [item for item in self.config_data.get("servers", []) if item.get("name") != data["name"]]
        servers.insert(0, data)
        self.config_data["servers"] = servers
        if self.config_manager:
            self.config_manager.save()
        self.listbox.delete(0, "end")
        for item in servers:
            self.listbox.insert(tk.END, f"{item.get('name', 'server')}\n{item.get('username', '')}@{item.get('host', '')}:{item.get('port', 22)}")
        self.add_log("Connection saved; password was not stored as plain text.")

    def delete_selected(self):
        selected = self.listbox.curselection()
        if not selected:
            return
        idx = selected[0]
        servers = self.config_data.get("servers", [])
        if 0 <= idx < len(servers):
            servers.pop(idx)
            self.config_data["servers"] = servers
            if self.config_manager:
                self.config_manager.save()
            self.listbox.delete(idx)

    def _load_selected(self, _event=None):
        selected = self.listbox.curselection()
        servers = self.config_data.get("servers", [])
        if not selected or selected[0] >= len(servers):
            return
        item = servers[selected[0]]
        mapping = {"Connection name": "name", "Host": "host", "Port": "port", "Username": "username", "Remote project directory": "remote_root"}
        for label, key in mapping.items():
            self.vars[label].set(str(item.get(key, "")))
        self.auth_type.set("Private key" if item.get("auth_type") == "key" else "Password")
        self.key_path.set(item.get("key_path", ""))


class SettingsDialog(tk.Toplevel):
    def __init__(
        self,
        master,
        config_manager,
        on_potcar_change=None,
        on_background_change=None,
    ):
        super().__init__(master)
        self.title("Settings")
        fit_window_to_workarea(self, (1000, 740), (760, 500))
        self.configure(bg=BG)
        self.config_manager = config_manager
        self.on_potcar_change = on_potcar_change
        self.on_background_change = on_background_change
        self.original_background_image = (
            self.config_manager.data.get("appearance", {}).get(
                "background_image", ""
            )
        )
        self._appearance_applied = False
        self.vars = {}
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        self.left_menu = tk.Listbox(outer, width=16, exportselection=False, activestyle="none")
        self.left_menu.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.categories = ["General", "Appearance", "SSH connection", "Submission settings", "Paths", "Advanced"]
        for item in self.categories:
            self.left_menu.insert("end", item)
        self.left_menu.bind("<<ListboxSelect>>", self._switch_page)

        self.page_area = ttk.Frame(outer, style="Panel.TFrame", padding=16)
        self.page_area.grid(row=0, column=1, sticky="nsew")
        self.page_area.columnconfigure(0, weight=1)
        self.page_area.rowconfigure(0, weight=1)
        self.pages = {}
        self._build_pages()

        buttons = ttk.Frame(outer)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Reset defaults", command=self.reset_defaults).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="OK", style="Primary.TButton", command=self.apply).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.left_menu.selection_set(0)
        self._show_page("General")

    def _build_pages(self):
        self._build_general_page()
        self._build_interface_page()
        self._build_ssh_page()
        self._build_submit_page()
        self._build_path_page()
        self._build_advanced_page()
        for page in self.pages.values():
            page.finish()

    def _new_page(self, name):
        scroller = VerticalScrolledFrame(self.page_area, style="Panel.TFrame")
        scroller.grid(row=0, column=0, sticky="nsew")
        scroller.grid_remove()
        self.pages[name] = scroller
        return scroller.body

    def _switch_page(self, _event=None):
        selected = self.left_menu.curselection()
        if selected:
            self._show_page(self.categories[selected[0]])

    def _show_page(self, name):
        for page in self.pages.values():
            page.grid_remove()
        self.pages[name].grid()

    def _entry_row(self, parent, label, key, default="", row=0, browse=False):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        var = tk.StringVar(value=str(default))
        self.vars[key] = var
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=5)
        if browse:
            ttk.Button(parent, text="Browse...", command=lambda k=key: self.browse_dir(k)).grid(row=row, column=2, padx=(6, 0), pady=5)
        return var

    def _check_row(self, parent, text, key, default=False, row=0):
        var = tk.BooleanVar(value=bool(default))
        self.vars[key] = var
        ttk.Checkbutton(parent, text=text, variable=var).grid(row=row, column=0, columnspan=3, sticky="w", pady=5)
        return var

    def _build_general_page(self):
        page = self._new_page("General")
        page.columnconfigure(1, weight=1)
        ttk.Label(page, text="General settings", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._entry_row(page, "Default project directory: ", "default_project_dir", self.config_manager.data.get("default_project_dir", ""), 1, True)
        self._entry_row(page, "Recent project count: ", "recent_project_limit", self.config_manager.data.get("recent_project_limit", 10), 2)
        self._check_row(page, "Open the last project at startup", "open_last_project", self.config_manager.data.get("open_last_project", True), 3)
        self._check_row(page, "Automatically save project settings", "auto_save_project", self.config_manager.data.get("auto_save_project", True), 4)

    def _build_interface_page(self):
        page = self._new_page("Appearance")
        page.columnconfigure(1, weight=1)
        ttk.Label(page, text="Appearance", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )
        appearance = self.config_manager.data.get("appearance", {})
        ttk.Label(page, text="Theme: ", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", pady=5
        )
        self.theme_name = tk.StringVar(value="白色专业版")
        ttk.Label(
            page,
            text="Professional white (application theme)",
            style="Panel.TLabel",
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=5)

        ttk.Label(page, text="Custom background: ", style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=5
        )
        self.background_image = tk.StringVar(
            value=appearance.get("background_image", "")
        )
        ttk.Entry(page, textvariable=self.background_image).grid(
            row=2, column=1, sticky="ew", pady=5
        )
        image_buttons = ttk.Frame(page, style="Panel.TFrame")
        image_buttons.grid(row=2, column=2, padx=(6, 0))
        ttk.Button(
            image_buttons,
            text="Choose image",
            command=self.browse_background_image,
        ).pack(side="left")
        ttk.Button(
            image_buttons,
            text="Clear",
            command=self.clear_background_image,
        ).pack(side="left", padx=(5, 0))

        self.theme_preview = tk.Canvas(
            page,
            height=76,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BLUE,
        )
        self.theme_preview.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(10, 14)
        )
        self.theme_preview.bind("<Configure>", self._draw_theme_preview)

        ttk.Separator(page).grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12)
        )
        ttk.Label(page, text="Language", style="Title.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        WidthLabel(
            page,
            text="The application uses the professional white theme. Background images are previewed immediately.",
            style="Panel.TLabel",
        ).grid(row=6, column=0, columnspan=3, sticky="ew")
        self.lang = tk.StringVar(value=self.config_manager.data.get("language", "en_US"))
        ttk.Radiobutton(
            page, text="Simplified Chinese", variable=self.lang, value="zh_CN"
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(14, 4))
        ttk.Radiobutton(
            page, text="English", variable=self.lang, value="en_US"
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=4)
        self.after_idle(self._draw_theme_preview)

    def _draw_theme_preview(self, _event=None):
        if not hasattr(self, "theme_preview"):
            return
        palette = THEME_PRESETS.get(
            self.theme_name.get(), THEME_PRESETS["白色专业版"]
        )
        bg, panel, _alt, tint, border, _strong, accent, _hover, title, _light, text, muted = palette
        canvas = self.theme_preview
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        canvas.configure(bg=bg, highlightbackground=border)
        canvas.create_rectangle(12, 12, width - 12, 64, fill=panel, outline=border)
        canvas.create_oval(24, 25, 32, 33, fill=accent, outline="")
        canvas.create_text(
            42, 29, text="Professional white", fill=title,
            anchor="w", font=(MONO_FONT_FAMILY, 10, "bold")
        )
        canvas.create_rectangle(
            width - 170, 22, width - 24, 50, fill=tint, outline=border
        )
        canvas.create_rectangle(
            width - 170, 22, width - 105, 50, fill=accent, outline=""
        )
        canvas.create_text(
            42, 49, text="Scientific computing preview", fill=muted, anchor="w"
        )

    def browse_background_image(self):
        path = file_dialogs.askopenfilename(
            self.config_manager, "background_image", parent=self,
            title="Choose a background image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.background_image.set(path)
            if not self._preview_background(path):
                self.background_image.set(self.original_background_image)
                self._preview_background(self.original_background_image)
                messagebox.showwarning(
                    "Background image",
                    "Cannot read the selected image. Choose another PNG, JPG, BMP, WEBP or TIFF image.",
                    parent=self,
                )

    def clear_background_image(self):
        self.background_image.set("")
        self._preview_background("")

    def _preview_background(self, path):
        if not self.on_background_change:
            return True
        return self.on_background_change(path) is not False

    def cancel(self):
        if not self._appearance_applied:
            self._preview_background(self.original_background_image)
        self.destroy()

    def _build_ssh_page(self):
        page = self._new_page("SSH connection")
        page.columnconfigure(1, weight=1)
        ttk.Label(page, text="Default SSH settings", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._entry_row(page, "Default remote host: ", "default_remote_host", self.config_manager.data.get("default_remote_host", ""), 1)
        self._entry_row(page, "Default port: ", "default_remote_port", self.config_manager.data.get("default_remote_port", 22), 2)
        self._entry_row(page, "Default remote project directory: ", "default_remote_root", self.config_manager.data.get("default_remote_root", "/home/user/vasp_projects"), 3)
        self._check_row(page, "Save SSH connection history", "save_ssh_history", self.config_manager.data.get("save_ssh_history", True), 4)
        self._check_row(page, "Save password", "save_password", self.config_manager.data.get("save_password", False), 5)

    def _build_submit_page(self):
        page = self._new_page("Submission settings")
        page.columnconfigure(1, weight=1)
        slurm = self.config_manager.data.get("slurm", {})
        ttk.Label(page, text="Submission settings", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(page, text="Scheduler: ", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=5)
        scheduler = tk.StringVar(value=self.config_manager.data.get("scheduler", "Slurm"))
        self.vars["scheduler"] = scheduler
        ttk.Combobox(page, textvariable=scheduler, values=["Slurm", "PBS", "LSF", "Custom"], state="readonly").grid(row=1, column=1, sticky="ew", pady=5)

        self._entry_row(page, "Default job script: ", "submit_script", self.config_manager.data.get("submit_script", self.config_manager.data.get("slurm_script_name", "Svasp.sh")), 2)
        self._entry_row(page, "Default submission command: ", "submit_command", slurm.get("submit_command", "sbatch Svasp.sh"), 3)
        self._entry_row(page, "Job name: ", "job_name", slurm.get("job_name", "gjn"), 4)
        self._entry_row(page, "Nodes: ", "nodes", slurm.get("nodes", 1), 5)
        self._entry_row(page, "Cores per node: ", "ntasks_per_node", slurm.get("ntasks_per_node", 20), 6)
        self._entry_row(page, "VASP path: ", "vasp_bin", slurm.get("vasp_bin", "/home/dell/Software/vasp.6.3.2/bin"), 7)
        self._entry_row(page, "Run command: ", "run_command", slurm.get("run_command", slurm.get("vasp_command", "mpirun -np $NP vasp_std")), 8)
        self._check_row(page, "Batch subdirectory mode", "batch_mode", slurm.get("batch_mode", False), 9)
        self._entry_row(page, "Environment initialization: ", "submit_init_command", self.config_manager.data.get("submit_init_command", ""), 10)
        self._check_row(page, "Run commands with bash -lc", "submit_use_login_shell", self.config_manager.data.get("submit_use_login_shell", True), 11)
        self._entry_row(page, "Test command: ", "submit_test_command", self.config_manager.data.get("submit_test_command", "command -v sbatch && sbatch --version"), 12)
        self._entry_row(page, "Default queue command: ", "query_command", slurm.get("query_command", "squeue -u {username}"), 13)
        self._entry_row(page, "Default cancellation command: ", "cancel_command", slurm.get("cancel_command", "scancel {job_id}"), 14)

        hint = "If sbatch is not found, try source ~/.bashrc or module load slurm and enable bash -lc."
        ttk.Label(page, text=hint, style="Muted.TLabel", wraplength=560).grid(row=15, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _build_path_page(self):
        page = self._new_page("Paths")
        page.columnconfigure(1, weight=1)
        ttk.Label(page, text="Local paths", style="Title.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(page, text="Configure POTCAR in the POTCAR tab of the main window.", style="Muted.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.potcar_root = tk.StringVar(value=self.config_manager.data.get("potcar_root", ""))
        self._entry_row(page, "Default export directory: ", "default_export_dir", self.config_manager.data.get("default_export_dir", ""), 2, True)
        self._entry_row(page, "Default results download directory: ", "default_download_dir", self.config_manager.data.get("default_download_dir", ""), 3, True)
        self._entry_row(page, "Generated structure autosave directory: ", "generated_structure_dir", self.config_manager.data.get("generated_structure_dir", ""), 4, True)

    def _build_advanced_page(self):
        page = self._new_page("Advanced")
        ttk.Label(page, text="Advanced settings", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._check_row(page, "Debug mode", "debug_mode", self.config_manager.data.get("debug_mode", False), 1)
        ttk.Label(page, text="Log level: normal", style="Panel.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=6)

    def browse_dir(self, key):
        current = self.vars[key].get().strip()
        initial = current if current and Path(current).exists() else str(Path.home())
        path = file_dialogs.askdirectory(self.config_manager, "setting_" + key, parent=self, title="Choose directory", initialdir=initial)
        if path:
            self.vars[key].set(path)

    def browse_potcar_root(self):
        initial = normalize_local_path(self.potcar_root.get())
        if not initial or not Path(initial).exists():
            initial = str(Path.home())
        path = file_dialogs.askdirectory(self.config_manager, "potcar", parent=self, title="Choose POTCAR root directory", initialdir=initial)
        if path:
            self.potcar_root.set(normalize_local_path(path))
            self.potcar_status.set(self._potcar_status_text())

    def open_potcar_root(self):
        path = Path(normalize_local_path(self.potcar_root.get()))
        if not path.exists():
            messagebox.showerror("Could not open POTCAR directory", f"Directory does not exist: \n{path}")
            return
        try:
            open_path(path)
        except OSError as exc:
            messagebox.showerror("Could not open POTCAR directory", str(exc))

    def check_potcar_root(self):
        root_value = normalize_local_path(self.potcar_root.get())
        path = Path(root_value)
        if not root_value:
            messagebox.showwarning("Check POTCAR directory", "POTCAR root directory is not configured.")
            return
        if not path.exists():
            messagebox.showerror("Check POTCAR directory", f"Directory does not exist: \n{path}")
            return
        _ok, found, _message = scan_potcar_root(root_value)
        common = ["Al", "Y", "O", "Ce", "Zr", "Fe", "Si", "Mg"]
        detected_symbols = {name.split("_", 1)[0] for name in found}
        missing = [elem for elem in common if elem not in detected_symbols]
        messagebox.showinfo(
            "Check complete",
            f"Directory exists: \n{path}\n\nElements found: {', '.join(found) if found else 'None'}\n\nNot found: {', '.join(missing)}",
        )
        self.potcar_status.set(self._potcar_status_text())

    def _potcar_status_text(self):
        value = normalize_local_path(self.potcar_root.get() if hasattr(self, "potcar_root") else self.config_manager.data.get("potcar_root", ""))
        if not value:
            return "Current POTCAR root: not configured"
        path = Path(value)
        return f"Current POTCAR root: {path}    Status: {'Exists' if path.exists() else 'Does not exist'}"

    def reset_defaults(self):
        if not messagebox.askyesno("Confirm reset", "Restore all settings to their defaults?"):
            return
        from app.core.config_manager import DEFAULT_SETTINGS
        self.config_manager.data = dict(DEFAULT_SETTINGS)
        self.config_manager.save()
        messagebox.showinfo("Defaults restored", "All settings were reset. Reopen Settings to view them.")
        self.destroy()

    def apply(self):
        potcar_root = normalize_local_path(self.potcar_root.get())
        if potcar_root and not Path(potcar_root).is_dir():
            messagebox.showwarning("Invalid path", f"POTCAR root does not exist: \n{potcar_root}")
            return
        background_image = self.background_image.get().strip()
        if background_image and not Path(background_image).is_file():
            messagebox.showwarning(
                "Background image",
                f"Background image does not exist: \n{background_image}",
                parent=self,
            )
            return
        self.config_manager.data.update(
            {
                "language": self.lang.get(),
                "default_project_dir": self.vars["default_project_dir"].get().strip(),
                "recent_project_limit": self.vars["recent_project_limit"].get().strip(),
                "open_last_project": self.vars["open_last_project"].get(),
                "auto_save_project": self.vars["auto_save_project"].get(),
                "default_remote_host": self.vars["default_remote_host"].get().strip(),
                "default_remote_port": self.vars["default_remote_port"].get().strip(),
                "default_remote_root": self.vars["default_remote_root"].get().strip(),
                "save_ssh_history": self.vars["save_ssh_history"].get(),
                "save_password": self.vars["save_password"].get(),
                "potcar_root": potcar_root,
                "default_export_dir": self.vars["default_export_dir"].get().strip(),
                "default_download_dir": self.vars["default_download_dir"].get().strip(),
                "generated_structure_dir": self.vars["generated_structure_dir"].get().strip(),
                "slurm_script_name": self.vars.get("submit_script", self.vars.get("slurm_script_name")).get().strip(),
                "submit_script": self.vars.get("submit_script", self.vars.get("slurm_script_name")).get().strip(),
                "scheduler": self.vars.get("scheduler").get().strip(),
                "submit_init_command": self.vars.get("submit_init_command").get().strip(),
                "submit_use_login_shell": self.vars.get("submit_use_login_shell").get(),
                "submit_test_command": self.vars.get("submit_test_command").get().strip(),
                "debug_mode": self.vars["debug_mode"].get(),
                "appearance": {
                    "theme": "白色专业版",
                    "background_image": background_image,
                },
            }
        )
        self.config_manager.data.setdefault("slurm", {})
        self.config_manager.data["slurm"].update(
            {
                "submit_command": self.vars["submit_command"].get().strip(),
                "query_command": self.vars["query_command"].get().strip(),
                "cancel_command": self.vars["cancel_command"].get().strip(),
                "job_name": self.vars["job_name"].get().strip(),
                "nodes": self.vars["nodes"].get().strip(),
                "ntasks_per_node": self.vars["ntasks_per_node"].get().strip(),
                "vasp_bin": self.vars["vasp_bin"].get().strip(),
                "run_command": self.vars["run_command"].get().strip(),
                "vasp_command": self.vars["run_command"].get().strip(),
                "batch_mode": self.vars["batch_mode"].get(),
            }
        )
        self.config_manager.save()
        if self.on_potcar_change:
            self.on_potcar_change(potcar_root)
        if not self._preview_background(background_image):
            messagebox.showwarning(
                "Background image",
                "Settings were saved, but the background image could not be read. Choose another image.",
                parent=self,
            )
            return
        self._appearance_applied = True
        self.destroy()
