"""Exercise layout transitions without opening a second application window."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.ui.main_window import MainWindow


class PaneHost:
    def __init__(self, name):
        self.name = name
        self.destroy = Mock()

    def __str__(self):
        return self.name


class PaneManager:
    def __init__(self):
        self.managed = []
        self.options = {}

    def panes(self):
        return tuple(self.managed)

    def forget(self, host):
        self.managed.remove(host)

    def add(self, host, **options):
        self.managed.append(host)
        self.options[host] = options


class WorkspaceHarness:
    _visible_sidebar = MainWindow._visible_sidebar
    _apply_workspace_layout = MainWindow._apply_workspace_layout
    toggle_sidebar = MainWindow.toggle_sidebar
    show_remote_panel = MainWindow.show_remote_panel
    download_results = MainWindow.download_results

    def __init__(self, width=1440, data=None):
        self.width = width
        self.config_manager = SimpleNamespace(data=data or {}, save=Mock())
        layout = self.config_manager.data.get("workspace_layout", {})
        self._panel_preferences = {
            "left": layout.get("left_visible", True),
            "right": layout.get("right_visible", True),
        }
        self._sidebar_priority = layout.get("sidebar_priority", "left")
        self._layout_signature = None
        self.left_host = PaneHost("project-and-server")
        self.center_host = PaneHost("structure-and-inputs")
        self.right_host = PaneHost("inspector")
        self.main_panes = PaneManager()
        self.sidebar_toggle = Mock()
        self.inspector_toggle = Mock()
        self.left_tabs = Mock()
        self.remote_panel = SimpleNamespace(host="ssh.example", user="researcher",
                                            download_results=Mock())
        self.project_panel = SimpleNamespace(export_dir="D:/science/exports")
        self.after_idle = Mock()
        self._position_workspace_panes = Mock()
        self._layout_toolbar = Mock()

    def winfo_width(self):
        return self.width


class WorkspaceLayoutTests(unittest.TestCase):
    def test_hide_and_restore_reuses_panels_and_preserves_connection_fields(self):
        app = WorkspaceHarness()
        app._apply_workspace_layout()
        original_hosts = app.main_panes.panes()
        remote = app.remote_panel
        project = app.project_panel
        app.toggle_sidebar("left")
        self.assertNotIn(app.left_host, app.main_panes.panes())
        self.assertFalse(app.config_manager.data["workspace_layout"]["left_visible"])
        app.toggle_sidebar("left")
        self.assertEqual(app.main_panes.panes(), original_hosts)
        self.assertIs(app.remote_panel, remote)
        self.assertIs(app.project_panel, project)
        self.assertEqual(app.remote_panel.host, "ssh.example")
        self.assertEqual(app.remote_panel.user, "researcher")
        for host in original_hosts:
            host.destroy.assert_not_called()
        self.assertEqual(app.config_manager.save.call_count, 2)

    def test_1024_width_retains_center_and_one_sidebar_without_losing_wide_preferences(self):
        app = WorkspaceHarness(width=1024)
        app._apply_workspace_layout()
        self.assertEqual(app.main_panes.panes(), (app.left_host, app.center_host))
        self.assertEqual(app._panel_preferences, {"left": True, "right": True})
        app.config_manager.save.assert_not_called()
        self.assertLess(sum(app.main_panes.options[p]["minsize"] for p in app.main_panes.panes()), 1000)
        app.width = 1440
        app._apply_workspace_layout()
        self.assertEqual(app.main_panes.panes(), (app.left_host, app.center_host, app.right_host))

    def test_explicit_right_panel_choice_is_saved_for_narrow_screen_reopen(self):
        app = WorkspaceHarness(width=1024, data={"workspace_layout": {"left_width": 370}})
        app._apply_workspace_layout()
        app.toggle_sidebar("right")
        self.assertEqual(app.main_panes.panes(), (app.center_host, app.right_host))
        saved = app.config_manager.data["workspace_layout"]
        self.assertEqual(saved["sidebar_priority"], "right")
        self.assertEqual(saved["left_width"], 370)
        reopened = WorkspaceHarness(width=1024, data=app.config_manager.data)
        reopened._apply_workspace_layout()
        self.assertEqual(reopened.main_panes.panes(), (reopened.center_host, reopened.right_host))

    def test_remote_action_restores_hidden_existing_panel_and_saves_choice(self):
        app = WorkspaceHarness(width=1024, data={"workspace_layout": {
            "left_visible": False, "right_visible": True,
            "sidebar_priority": "right", "right_width": 315,
        }})
        app._apply_workspace_layout()
        remote = app.remote_panel
        app.show_remote_panel()
        self.assertEqual(app.main_panes.panes(), (app.left_host, app.center_host))
        self.assertIs(app.remote_panel, remote)
        app.left_tabs.select.assert_called_once_with(1)
        saved = app.config_manager.data["workspace_layout"]
        self.assertTrue(saved["left_visible"])
        self.assertEqual(saved["sidebar_priority"], "left")
        self.assertEqual(saved["right_width"], 315)
        app.config_manager.save.assert_called_once()

    def test_download_opens_remote_panel_before_requesting_transfer(self):
        app = WorkspaceHarness()
        order = []
        app.show_remote_panel = lambda: order.append("show")
        app.remote_panel.download_results = lambda: order.append("download")
        app.download_results()
        self.assertEqual(order, ["show", "download"])


class StructureExportDirectoryTests(unittest.TestCase):
    def export_app(self, project_dir, remembered=None):
        data = {"dialog_directories": {"structure_export": remembered}} if remembered else {}
        return SimpleNamespace(
            project_dir=project_dir,
            structure=SimpleNamespace(atoms=[object()], name="Al"),
            config_manager=SimpleNamespace(data=data, get_dialog_directory=Mock(return_value=str(project_dir)),
                                           remember_dialog_path=Mock()),
            project_panel=SimpleNamespace(export_dir=Mock()),
            write_current_poscar=Mock(),
        )

    @patch("app.ui.main_window.messagebox.showinfo")
    def test_fresh_default_creates_exports_subdirectory_instead_of_existing_ancestor(self, _message):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.export_app(Path(temporary))
            MainWindow.export_structure(app, "POSCAR")
            destination = Path(temporary) / "exports"
            self.assertTrue(destination.is_dir())
            app.write_current_poscar.assert_called_once_with(destination / "POSCAR")

    @patch("app.ui.main_window.messagebox.showinfo")
    def test_saved_future_directory_remains_actual_export_destination(self, _message):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "new" / "exports"
            app = self.export_app(Path(temporary), str(destination))
            MainWindow.export_structure(app, "POSCAR")
            app.write_current_poscar.assert_called_once_with(destination / "POSCAR")
            self.assertTrue(destination.is_dir())


class ToolbarOverflowTests(unittest.TestCase):
    def test_commands_move_into_more_menu_and_return_when_width_is_available(self):
        buttons = []
        for label in ("导入结构", "任务中心", "下载结果"):
            button = Mock()
            button.winfo_reqwidth.return_value = 80
            buttons.append((button, label, Mock(name=label)))
        menu = Mock()
        more = Mock()
        more.winfo_reqwidth.return_value = 50
        actions = Mock()
        actions.winfo_width.return_value = 170
        app = SimpleNamespace(
            _toolbar_buttons=buttons, _toolbar_actions=actions,
            _toolbar_visible_count=-1, _more_menu=menu, _more_button=more,
        )
        MainWindow._layout_toolbar(app)
        self.assertEqual(app._toolbar_visible_count, 1)
        self.assertEqual([call.kwargs["label"] for call in menu.add_command.call_args_list],
                         ["任务中心", "下载结果"])
        for call, (_, _, original_callback) in zip(menu.add_command.call_args_list, buttons[1:]):
            self.assertIs(call.kwargs["command"], original_callback)
        more.pack.assert_called_once()
        menu.reset_mock()
        actions.winfo_width.return_value = 600
        MainWindow._layout_toolbar(app)
        self.assertEqual(app._toolbar_visible_count, 3)
        menu.add_command.assert_not_called()
        for button, _, _ in buttons:
            button.pack.assert_called()


if __name__ == "__main__":
    unittest.main()
