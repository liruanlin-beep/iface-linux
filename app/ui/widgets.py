import tkinter as tk
from tkinter import ttk

from app.ui.theme import BLUE, BORDER, PANEL, PANEL_ALT, TEXT, FONT_FAMILY


class ToolTip:
    """Small delayed tooltip suitable for icon-only controls."""

    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._job = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def _schedule(self, _event=None):
        self.hide()
        self._job = self.widget.after(self.delay, self.show)

    def show(self):
        self._job = None
        if self._window or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._window,
            text=self.text,
            bg="#172033",
            fg="white",
            padx=8,
            pady=5,
            relief="solid",
            borderwidth=1,
            font=(FONT_FAMILY, 9),
        ).pack()

    def hide(self, _event=None):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._window is not None:
            self._window.destroy()
            self._window = None


class Card(ttk.Frame):
    def __init__(self, master, title=None, **kwargs):
        super().__init__(master, style="Panel.TFrame", padding=10, **kwargs)
        if title:
            ttk.Label(self, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 8))


class ToolbarButton(ttk.Button):
    def __init__(self, master, icon, text, command=None):
        super().__init__(master, text=text, command=command, width=max(8, len(text) + 2))


class CollapsibleSection(ttk.Frame):
    def __init__(self, master, title, content_builder=None, open_by_default=False):
        super().__init__(master, style="Panel.TFrame")
        self.open = open_by_default
        self.header = ttk.Button(self, text=self._title(title), command=self.toggle)
        self.header.pack(fill="x")
        self.body = ttk.Frame(self, style="Panel.TFrame", padding=(12, 6, 12, 10))
        self.content_builder = content_builder
        self._built = False
        if open_by_default:
            self.show()

    def _title(self, title):
        return f"{'▼' if self.open else '▶'}  {title}"

    def toggle(self):
        if self.open:
            self.hide()
        else:
            self.show()

    def show(self):
        self.open = True
        self.header.configure(text=self.header.cget("text").replace("▶", "▼"))
        if not self._built and self.content_builder:
            self.content_builder(self.body)
            self._built = True
        self.body.pack(fill="x")

    def hide(self):
        self.open = False
        self.header.configure(text=self.header.cget("text").replace("▼", "▶"))
        self.body.pack_forget()


class MiniField(ttk.Frame):
    def __init__(self, master, label, value="", width=8):
        super().__init__(master, style="Panel.TFrame")
        ttk.Label(self, text=label, style="Panel.TLabel").pack(side="left", padx=(0, 6))
        self.var = tk.StringVar(value=value)
        ttk.Entry(self, textvariable=self.var, width=width).pack(side="left")


def draw_rounded_rect(canvas, x1, y1, x2, y2, radius=10, fill=PANEL, outline=BORDER):
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1,
        x2, y1 + radius, x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2, x1, y2,
        x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, fill=fill, outline=outline)


class FlowStrip(tk.Canvas):
    def __init__(self, master, labels):
        super().__init__(master, height=92, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.labels = labels
        self.bind("<Configure>", self.redraw)

    def redraw(self, _event=None):
        self.delete("all")
        w = self.winfo_width()
        step = max(90, (w - 80) / len(self.labels))
        self.create_text(22, 22, text="Workflow", fill=BLUE, font=(FONT_FAMILY, 13, "bold"), anchor="w")
        icons = ["▤", "□", "✎", "▤", "▦", "☁", "▣", "▥"]
        for i, label in enumerate(self.labels):
            x = 130 + i * step
            self.create_oval(x - 13, 12, x + 13, 38, fill=BLUE, outline=BLUE)
            self.create_text(x, 25, text=str(i + 1), fill="white", font=(FONT_FAMILY, 9, "bold"))
            self.create_text(x + 20, 54, text=icons[i], fill=BLUE, font=(FONT_FAMILY, 22), anchor="center")
            self.create_text(x, 78, text=label, fill=BLUE_DARK if False else TEXT, font=(FONT_FAMILY, 8), anchor="center")
            if i < len(self.labels) - 1:
                self.create_line(x + 48, 54, x + step - 48, 54, fill=BLUE, dash=(4, 3), arrow=tk.LAST)
