import unittest

from app.ui.responsive_rows import flow_layout


class FlowLayoutTests(unittest.TestCase):
    def test_narrow_sidebar_wraps_controls_without_overlap_or_clipping(self):
        sizes = [(70, 28), (70, 28), (70, 28), (130, 28), (95, 28), (65, 28)]
        positions, height = flow_layout(sizes, 302)
        self.assertGreater(height, 28)
        for index, (x, y, width, item_height) in enumerate(positions):
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x + width, 302)
            self.assertLessEqual(y + item_height, height)
            for other_x, other_y, other_width, other_height in positions[index + 1:]:
                self.assertTrue(
                    x + width <= other_x or other_x + other_width <= x
                    or y + item_height <= other_y or other_y + other_height <= y
                )

    def test_controls_return_to_one_row_when_pane_expands(self):
        sizes = [(210, 30), (130, 28), (115, 28)]
        narrow, narrow_height = flow_layout(sizes, 380)
        wide, wide_height = flow_layout(sizes, 800)
        self.assertGreater(narrow_height, wide_height)
        self.assertTrue(any(y > 0 for _, y, _, _ in narrow))
        self.assertTrue(all(y == 0 for _, y, _, _ in wide))

    def test_tall_parameter_fields_and_oversized_control_stay_contained(self):
        positions, height = flow_layout([(180, 55), (180, 55), (600, 30)], 390, gap=10, row_gap=8)
        self.assertEqual(positions[2], (0, 63, 390, 30))
        self.assertEqual(height, 93)
        self.assertEqual(flow_layout([], 0), ([], 1))


if __name__ == "__main__":
    unittest.main()
