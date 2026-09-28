import sys


def enable_windows_dpi_awareness():
    """Keep text and icons sharp on high-DPI Windows displays."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def main(argv=None):
    enable_windows_dpi_awareness()
    # Support both ``python -m app.main`` and direct execution of this file.
    # The latter otherwise places ``app`` rather than the project root on
    # sys.path and fails before the window can be created.
    if __package__ in {None, ""}:
        from pathlib import Path

        project_root = str(Path(__file__).resolve().parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
    import argparse

    parser = argparse.ArgumentParser(description="iface desktop application")
    parser.add_argument("--self-test", metavar="REPORT", help="Run isolated offline acceptance and write JSON")
    args = parser.parse_args(argv)
    if args.self_test:
        from app.core.release_self_test import run_release_self_test

        return run_release_self_test(args.self_test)
    else:
        from app.ui.main_window import main as start_gui

        start_gui()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
