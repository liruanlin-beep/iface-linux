"""Shared scientific-console visual system."""

import ctypes
import sys
import tkinter as tk
from pathlib import Path

THEME_PRESETS = {
    "白色专业版": (
        "#f5f6f8",
        "#ffffff",
        "#fafbfc",
        "#f0f2f5",
        "#e2e5e9",
        "#cdd3dc",
        "#2563eb",
        "#3b82f6",
        "#174ea6",
        "#e5efff",
        "#172033",
        "#62748a",
    ),
}


def _selected_theme_name():
    return "白色专业版"


SELECTED_THEME = _selected_theme_name()
(
    BG,
    PANEL,
    PANEL_ALT,
    PANEL_TINT,
    BORDER,
    BORDER_STRONG,
    BLUE,
    BLUE_HOVER,
    BLUE_DARK,
    BLUE_LIGHT,
    TEXT,
    MUTED,
) = THEME_PRESETS[SELECTED_THEME]

IS_LIGHT_THEME = True
CHROME_BG = PANEL
CHROME_TEXT = TEXT
CHROME_MUTED = MUTED
STATUS_BG = BG
STATUS_TEXT = MUTED
PROGRESS_BG = "#ffffff"
PROGRESS_TRACK = "#d9e9fd"
PROGRESS_BORDER = "#94b5df"
PROGRESS_FILL = BLUE
PROGRESS_GLOW = "#91b5fa"
PROGRESS_STRIPE = "#b8cfea"
PROGRESS_EYEBROW = BLUE_DARK
PROGRESS_TITLE = TEXT
PROGRESS_DETAIL = MUTED
PROGRESS_PERCENT = BLUE_DARK
CONTROL_DISABLED = "#d9e4f2"
CONTROL_DISABLED_TEXT = "#8a9bb0"
TAB_BG = PANEL_TINT
SELECTION_BG = BLUE
PRIMARY_TEXT = "#ffffff"

GREEN = "#13b981"
GREEN_HOVER = "#22d39a"
RED = "#e54868"
RED_HOVER = "#ff6380"

_DARKENED_WINDOWS = set()

FONT_FAMILY = "Microsoft YaHei UI" if sys.platform == "win32" else "DejaVu Sans"
MONO_FONT_FAMILY = "Cascadia Mono" if sys.platform == "win32" else "DejaVu Sans Mono"
FONT = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_TITLE = (FONT_FAMILY, 12, "bold")


def configure_style(style, scale=1.0):
    scale = max(0.82, min(1.38, float(scale)))
    font_size = max(8, round(10 * scale))
    small_size = max(8, round(9 * scale))
    title_size = max(10, round(12 * scale))
    brand_size = max(13, round(16 * scale))
    font = (FONT_FAMILY, font_size)
    small_font = (FONT_FAMILY, small_size)
    font_bold = (FONT_FAMILY, font_size, "bold")
    font_title = (FONT_FAMILY, title_size, "bold")
    font_brand = (FONT_FAMILY, brand_size, "bold")
    button_pad = (max(8, round(10 * scale)), max(4, round(5 * scale)))
    compact_pad = (max(6, round(8 * scale)), max(3, round(4 * scale)))
    tab_pad = (max(8, round(11 * scale)), max(4, round(6 * scale)))

    style.theme_use("clam")
    style.configure(".", font=font, background=BG, foreground=TEXT)
    style.configure("TFrame", background=BG)
    style.configure(
        "Panel.TFrame",
        background=PANEL,
        relief="solid",
        borderwidth=1,
        bordercolor=BORDER,
    )
    style.configure(
        "Card.TFrame",
        background=PANEL,
        relief="solid",
        borderwidth=1,
        bordercolor=BORDER_STRONG,
    )
    style.configure("AppBar.TFrame", background=PANEL, relief="solid", borderwidth=1)
    style.configure("MenuBar.TFrame", background=CHROME_BG, relief="flat")
    style.configure("Status.TFrame", background=STATUS_BG, relief="flat")
    style.configure("ProgressHud.TFrame", background=CHROME_BG, relief="flat")
    style.configure("SectionHeader.TFrame", background=PANEL_TINT)

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Title.TLabel", background=PANEL, foreground=TEXT, font=font_title)
    style.configure("SectionTitle.TLabel", background=PANEL_TINT, foreground=BLUE_DARK, font=font_title)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=small_font)
    style.configure("AppTitle.TLabel", background=PANEL, foreground=TEXT, font=font_brand)
    style.configure("AppSubtitle.TLabel", background=PANEL, foreground=MUTED, font=small_font)
    style.configure("Status.TLabel", background=STATUS_BG, foreground=STATUS_TEXT, font=small_font)
    style.configure("ProgressHud.TFrame", background=PROGRESS_BG, relief="flat", borderwidth=0)
    style.configure("ProgressEyebrow.TLabel", background=PROGRESS_BG, foreground=PROGRESS_EYEBROW, font=("Cascadia Mono", small_size, "bold"))
    style.configure("ProgressTitle.TLabel", background=PROGRESS_BG, foreground=PROGRESS_TITLE, font=font_bold)
    style.configure("ProgressDetail.TLabel", background=PROGRESS_BG, foreground=PROGRESS_DETAIL, font=("Cascadia Mono", small_size))
    style.configure("ProgressPercent.TLabel", background=PROGRESS_BG, foreground=PROGRESS_PERCENT, font=("Cascadia Mono", max(10, round(12 * scale)), "bold"))
    style.configure("Badge.TLabel", background=PANEL_TINT, foreground=BLUE_DARK, font=font_bold, padding=(8, 4))

    style.configure(
        "TButton",
        padding=button_pad,
        relief="solid",
        borderwidth=1,
        background=PANEL,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        focusthickness=1,
        focuscolor=BLUE,
    )
    style.map(
        "TButton",
        background=[("pressed", BLUE_LIGHT), ("active", PANEL_TINT), ("disabled", CONTROL_DISABLED)],
        foreground=[("disabled", CONTROL_DISABLED_TEXT)],
        bordercolor=[("focus", BLUE), ("active", BORDER_STRONG)],
    )
    style.configure("Compact.TButton", padding=compact_pad)
    style.configure("SidebarToggle.TButton", padding=(7, 5), relief="flat", borderwidth=0, background=CHROME_BG)
    style.map("SidebarToggle.TButton", background=[("pressed", BLUE_LIGHT), ("active", PANEL_TINT)])
    style.configure(
        "Menu.TMenubutton",
        background=CHROME_BG,
        foreground=CHROME_TEXT,
        borderwidth=0,
        relief="flat",
        padding=(10, 5),
        font=small_font,
        arrowcolor=CHROME_MUTED,
    )
    style.map(
        "Menu.TMenubutton",
        background=[("active", PANEL_TINT), ("pressed", BLUE_LIGHT)],
        foreground=[("active", BLUE_DARK)],
        arrowcolor=[("active", BLUE_DARK)],
    )
    style.configure(
        "Toolbar.TButton",
        padding=(max(7, round(10 * scale)), max(4, round(6 * scale))),
        background=PANEL,
        bordercolor=PANEL,
        lightcolor=PANEL,
        darkcolor=PANEL,
        font=font,
    )
    style.map(
        "Toolbar.TButton",
        background=[("pressed", BLUE_LIGHT), ("active", PANEL_TINT)],
        bordercolor=[("pressed", BORDER_STRONG), ("active", BORDER)],
    )
    style.configure(
        "Primary.TButton",
        background=BLUE,
        foreground=PRIMARY_TEXT,
        bordercolor=BLUE,
        lightcolor=BLUE,
        darkcolor=BLUE,
        font=font_bold,
        padding=button_pad,
    )
    style.map(
        "Primary.TButton",
        background=[("pressed", BLUE_DARK), ("active", BLUE_HOVER), ("disabled", CONTROL_DISABLED)],
        foreground=[("active", PRIMARY_TEXT), ("disabled", CONTROL_DISABLED_TEXT)],
        bordercolor=[("active", BLUE_HOVER), ("focus", BLUE_DARK)],
    )
    style.configure(
        "Success.TButton",
        background=GREEN,
        foreground="#04111f",
        bordercolor=GREEN,
        lightcolor=GREEN,
        darkcolor=GREEN,
        font=font_bold,
        padding=button_pad,
    )
    style.map(
        "Success.TButton",
        background=[("pressed", "#0b5f36"), ("active", GREEN_HOVER)],
        foreground=[("active", "#04111f")],
    )
    style.configure(
        "Danger.TButton",
        background=RED,
        foreground="#ffffff",
        bordercolor=RED,
        lightcolor=RED,
        darkcolor=RED,
        font=font_bold,
        padding=button_pad,
    )
    style.map(
        "Danger.TButton",
        background=[("pressed", "#96202c"), ("active", RED_HOVER)],
        foreground=[("active", "#ffffff")],
    )

    style.configure(
        "TEntry",
        fieldbackground=PANEL,
        foreground=TEXT,
        borderwidth=1,
        relief="solid",
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        padding=max(4, round(5 * scale)),
    )
    style.map("TEntry", bordercolor=[("focus", BLUE)], lightcolor=[("focus", BLUE)], darkcolor=[("focus", BLUE)])
    style.configure(
        "TCombobox",
        fieldbackground=PANEL,
        background=PANEL,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        arrowsize=max(12, round(14 * scale)),
        padding=max(3, round(4 * scale)),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PANEL)],
        selectbackground=[("readonly", PANEL_TINT)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", BLUE)],
    )
    style.configure("TCheckbutton", background=PANEL, foreground=TEXT, padding=(0, 2))
    style.configure("TRadiobutton", background=PANEL, foreground=TEXT, padding=(0, 2))
    style.map(
        "TCheckbutton",
        background=[("active", PANEL)],
        indicatorcolor=[("selected", BLUE), ("!selected", PANEL)],
    )
    style.map(
        "TRadiobutton",
        background=[("active", PANEL)],
        indicatorcolor=[("selected", BLUE), ("!selected", PANEL)],
    )

    style.configure(
        "TLabelframe",
        background=PANEL,
        relief="solid",
        borderwidth=1,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
    )
    style.configure(
        "TLabelframe.Label",
        background=PANEL,
        foreground=BLUE_DARK,
        font=font_bold,
        padding=(4, 0),
    )
    style.configure(
        "Card.TLabelframe",
        background=PANEL,
        relief="solid",
        borderwidth=1,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=PANEL,
        foreground=BLUE_DARK,
        font=font_title,
        padding=(6, 0),
    )

    style.configure(
        "Treeview",
        rowheight=max(23, round(28 * scale)),
        background=PANEL,
        fieldbackground=PANEL,
        foreground=TEXT,
        borderwidth=1,
        relief="solid",
        bordercolor=BORDER,
    )
    style.configure(
        "Treeview.Heading",
        background=PANEL_TINT,
        foreground=BLUE_DARK,
        font=font_bold,
        relief="solid",
        borderwidth=1,
        padding=(6, 5),
    )
    style.map(
        "Treeview",
        background=[("selected", SELECTION_BG)],
        foreground=[("selected", "#ffffff")],
    )
    style.map("Treeview.Heading", background=[("active", BLUE_LIGHT)])

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", padding=tab_pad, background=TAB_BG, borderwidth=1)
    style.map(
        "TNotebook.Tab",
        background=[("selected", PANEL), ("active", BLUE_LIGHT)],
        foreground=[("selected", BLUE_DARK), ("active", TEXT)],
        font=[("selected", font_bold)],
    )
    style.configure("Content.TNotebook", background=BG, borderwidth=0)
    style.configure("Content.TNotebook.Tab", padding=tab_pad, background=TAB_BG, borderwidth=1)
    style.map(
        "Content.TNotebook.Tab",
        background=[("selected", PANEL), ("active", BLUE_LIGHT)],
        foreground=[("selected", BLUE_DARK), ("active", TEXT)],
        font=[("selected", font_bold)],
    )

    style.configure("TSeparator", background=BORDER)
    style.configure(
        "TProgressbar",
        background=BLUE,
        troughcolor=PANEL_TINT,
        bordercolor=BORDER,
        lightcolor=BLUE,
        darkcolor=BLUE,
    )
    for scrollbar_style in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            scrollbar_style,
            background=BORDER_STRONG,
            troughcolor=BG,
            bordercolor=BG,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowcolor=TEXT,
        )
        style.map(
            scrollbar_style,
            background=[("active", BLUE_HOVER), ("pressed", BLUE)],
            arrowcolor=[("active", BLUE_DARK)],
        )


def apply_tk_options(root):
    """Apply the console palette to classic Tk widgets and popup menus."""
    root.option_add("*Menu.background", PANEL)
    root.option_add("*Menu.foreground", TEXT)
    root.option_add("*Menu.activeBackground", BLUE_LIGHT)
    root.option_add("*Menu.activeForeground", TEXT)
    root.option_add("*Menu.selectColor", BLUE)
    root.option_add("*Text.background", PANEL_ALT)
    root.option_add("*Text.foreground", TEXT)
    root.option_add("*Text.insertBackground", BLUE)
    root.option_add("*Text.selectBackground", SELECTION_BG)
    root.option_add("*Text.selectForeground", "#ffffff")
    root.option_add("*Listbox.background", PANEL_ALT)
    root.option_add("*Listbox.foreground", TEXT)
    root.option_add("*Listbox.selectBackground", SELECTION_BG)
    root.option_add("*Listbox.selectForeground", "#ffffff")


def enable_dark_title_bar(window):
    """Keep the native Windows title bar light for the single white theme."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = int(window.winfo_id())
        # Tk creates a native wrapper HWND around the drawable child returned
        # by winfo_id(); DWM attributes must target that outer wrapper.
        parent = int(ctypes.windll.user32.GetParent(ctypes.c_void_p(hwnd)) or 0)
        if parent:
            hwnd = parent
        if hwnd in _DARKENED_WINDOWS:
            return
        enabled = ctypes.c_int(0)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attribute),
                ctypes.byref(enabled),
                ctypes.sizeof(enabled),
            )
            if result == 0:
                break
        _DARKENED_WINDOWS.add(hwnd)
    except (AttributeError, OSError, ValueError):
        pass


def install_window_background(window, path=""):
    """Install a lightweight, resize-aware wallpaper behind a Tk window."""
    if not isinstance(window, (tk.Tk, tk.Toplevel)):
        return False
    if not hasattr(window, "_iface_wallpaper_label"):
        label = tk.Label(
            window,
            bg=BG,
            borderwidth=0,
            highlightthickness=0,
        )
        label.place(x=0, y=0, relwidth=1, relheight=1)
        label.lower()
        window._iface_wallpaper_label = label
        window._iface_wallpaper_source = None
        window._iface_wallpaper_photo = None
        window._iface_wallpaper_size = None
        window._iface_wallpaper_path = None
        window._iface_wallpaper_after = None
        window.bind(
            "<Configure>",
            lambda event, target=window: _schedule_window_wallpaper(target, event),
            add="+",
        )
    return set_window_background(window, path)


def set_window_background(window, path=""):
    raw_path = str(path or "").strip()
    if not hasattr(window, "_iface_wallpaper_label"):
        return install_window_background(window, raw_path)
    if raw_path == getattr(window, "_iface_wallpaper_path", None):
        window._iface_wallpaper_label.lower()
        return True
    if not raw_path:
        window._iface_wallpaper_path = ""
        window._iface_wallpaper_source = None
        window._iface_wallpaper_photo = None
        window._iface_wallpaper_size = None
        window._iface_wallpaper_label.configure(image="", bg=BG)
        window._iface_wallpaper_label.lower()
        return True
    image_path = Path(raw_path)
    if not image_path.is_file():
        return False
    try:
        from PIL import Image

        with Image.open(image_path) as source:
            loaded = source.convert("RGB")
            loaded.load()
    except (ImportError, OSError, ValueError):
        return False
    window._iface_wallpaper_path = raw_path
    window._iface_wallpaper_source = loaded
    window._iface_wallpaper_size = None
    _schedule_window_wallpaper(window)
    return True


def refresh_window_backgrounds(root, path=""):
    """Apply the current wallpaper to every open child window."""
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel):
            install_window_background(child, path)


def _schedule_window_wallpaper(window, event=None):
    if event is not None and event.widget is not window:
        return
    if getattr(window, "_iface_wallpaper_source", None) is None:
        return
    pending = getattr(window, "_iface_wallpaper_after", None)
    if pending:
        try:
            window.after_cancel(pending)
        except tk.TclError:
            pass
    try:
        window._iface_wallpaper_after = window.after(
            120, lambda target=window: _render_window_wallpaper(target)
        )
    except tk.TclError:
        pass


def _render_window_wallpaper(window):
    window._iface_wallpaper_after = None
    source = getattr(window, "_iface_wallpaper_source", None)
    if source is None:
        return
    width = max(1, window.winfo_width())
    height = max(1, window.winfo_height())
    size = (width, height)
    if size == getattr(window, "_iface_wallpaper_size", None):
        return
    try:
        from PIL import Image, ImageTk

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
        wash = Image.new("RGB", size, "#dceaff" if IS_LIGHT_THEME else PANEL_ALT)
        composited = Image.blend(resized, wash, 0.30)
        photo = ImageTk.PhotoImage(composited)
        window._iface_wallpaper_photo = photo
        window._iface_wallpaper_size = size
        window._iface_wallpaper_label.configure(image=photo)
        window._iface_wallpaper_label.lower()
    except (ImportError, OSError, ValueError, tk.TclError):
        window._iface_wallpaper_photo = None
