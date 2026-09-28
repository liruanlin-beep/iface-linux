import unittest
from unittest.mock import Mock, patch

from app.ui.window_geometry import fit_window_to_workarea


class WindowGeometryTests(unittest.TestCase):
    def test_small_work_area_keeps_window_and_minimum_inside_taskbar(self):
        window = Mock()
        with patch("app.ui.window_geometry.get_work_area", return_value=(0, 0, 1024, 728)):
            size = fit_window_to_workarea(window, (1240, 780), (900, 700))
        self.assertEqual(size, (992, 664))
        window.minsize.assert_called_once_with(900, 664)
        window.geometry.assert_called_once_with("992x664+8+12")

    def test_secondary_monitor_with_negative_origin_is_preserved(self):
        window = Mock()
        with patch("app.ui.window_geometry.get_work_area", return_value=(-1920, 0, 0, 1040)):
            size = fit_window_to_workarea(window, (1100, 720), (820, 560))
        self.assertEqual(size, (1100, 720))
        window.geometry.assert_called_once_with("1100x720+-1518+140")

    def test_requested_minimum_cannot_make_dialog_larger_than_small_display(self):
        window = Mock()
        with patch("app.ui.window_geometry.get_work_area", return_value=(0, 0, 800, 560)):
            fit_window_to_workarea(window, (1160, 720), (900, 600))
        window.minsize.assert_called_once_with(768, 496)


if __name__ == "__main__":
    unittest.main()
