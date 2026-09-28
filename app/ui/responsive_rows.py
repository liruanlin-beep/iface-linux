"""Small layout helpers for controls displayed in resizable workbench panes."""

import tkinter as tk
from tkinter import ttk


def flow_layout(sizes, available_width, gap=6, row_gap=5):
    """Return nonoverlapping positions and height for a wrapping control row."""
    available_width = max(1, int(available_width))
    positions = []
    x = y = row_height = 0
    for requested_width, requested_height in sizes:
        width = min(available_width, max(1, int(requested_width)))
        height = max(1, int(requested_height))
        if x and x + width > available_width:
            x = 0
            y += row_height + row_gap
            row_height = 0
        positions.append((x, y, width, height))
        x += width + gap
        row_height = max(row_height, height)
    return positions, max(1, y + row_height)


class WrappingRow(ttk.Frame):
    """Wrap child widgets by their requested sizes without forcing a wider pane."""

    def __init__(self, master, gap=6, row_gap=5, **kwargs):
        super().__init__(master, height=1, **kwargs)
        self._items = []
        self._gap = gap
        self._row_gap = row_gap
        self._pending = None
        self.bind("<Configure>", self._queue_layout, add="+")
        self.bind("<Destroy>", self._dispose, add="+")

    def add(self, widget):
        self._items.append(widget)
        self._queue_layout()
        return widget

    def _queue_layout(self, _event=None):
        if self._pending is None:
            self._pending = self.after_idle(self._layout)

    def _layout(self):
        self._pending = None
        if not self.winfo_exists():
            return
        sizes = [(item.winfo_reqwidth(), item.winfo_reqheight()) for item in self._items]
        positions, height = flow_layout(sizes, self.winfo_width(), self._gap, self._row_gap)
        for item, (x, y, width, item_height) in zip(self._items, positions):
            item.place(x=x, y=y, width=width, height=item_height)
        if self.winfo_reqheight() != height:
            self.configure(height=height)

    def _dispose(self, event):
        if event.widget is self and self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None


class WidthLabel(ttk.Label):
    """Wrap long status text to the width assigned by its containing pane."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("justify", "left")
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("width", 1)
        super().__init__(master, **kwargs)
        self.bind("<Configure>", self._fit, add="+")

    def _fit(self, event):
        width = max(1, event.width - 4)
        if int(float(self.cget("wraplength") or 0)) != width:
            self.configure(wraplength=width)


class VerticalScrolledFrame(ttk.Frame):
    """A narrow form keeps its controls reachable when its host becomes short."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, width=1, height=1)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.body = ttk.Frame(self.canvas, style="Card.TFrame", padding=10)
        self._window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", self._update_region)
        self._wheel_tag = "iface_scroll_" + str(id(self))
        self.bind_class(self._wheel_tag, "<MouseWheel>", self._wheel)
        self.bind_class(self._wheel_tag, "<Button-4>", self._wheel)
        self.bind_class(self._wheel_tag, "<Button-5>", self._wheel)
        self.bind("<Destroy>", self._dispose, add="+")

    def finish(self):
        """Route scrolling from this form's children without a global binding."""
        def attach(widget):
            # Editors and file tables retain their own native scroll behavior.
            if not isinstance(widget, (tk.Text, ttk.Treeview)):
                widget.bindtags((self._wheel_tag,) + tuple(tag for tag in widget.bindtags() if tag != self._wheel_tag))
            for child in widget.winfo_children():
                attach(child)
        attach(self.body)

    def _resize(self, event):
        self.canvas.itemconfigure(self._window, width=max(1, event.width))

    def _update_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _wheel(self, event):
        if self.canvas.yview() == (0.0, 1.0):
            return None
        units = -1 if getattr(event, "num", None) == 4 else 1
        if getattr(event, "delta", 0):
            units = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(units * 3, "units")
        return "break"

    def _dispose(self, event):
        if event.widget is self:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.unbind_class(self._wheel_tag, sequence)
