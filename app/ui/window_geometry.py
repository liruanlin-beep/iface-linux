"""Screen-aware sizing shared by desktop workspaces and utility windows."""

import sys


def get_work_area(window):
    """Return the owner monitor's usable bounds, excluding the Windows taskbar."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
            owner = getattr(window, "master", None) or window
            monitor = user32.MonitorFromWindow(owner.winfo_id(), 2)
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = info.rcWork
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
    return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())


def fit_window_to_workarea(window, preferred_size=(1160, 720), minimum_size=(760, 480)):
    """Keep the initial client area plus window decorations inside the work area."""
    left, top, right, bottom = get_work_area(window)
    available_width = max(240, right - left - 32)
    available_height = max(180, bottom - top - 64)
    width = min(int(preferred_size[0]), available_width)
    height = min(int(preferred_size[1]), available_height)
    window.minsize(min(int(minimum_size[0]), width), min(int(minimum_size[1]), height))
    x = left + max(0, (right - left - width - 16) // 2)
    y = top + max(0, (bottom - top - height - 40) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    return width, height


def bind_wraplength(label, minimum=120):
    """Wrap explanatory copy to its allocated width rather than a fixed desktop size."""
    label.bind("<Configure>", lambda event: label.configure(
        wraplength=max(minimum, event.width - 4)), add="+")
    return label
