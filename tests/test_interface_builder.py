import unittest

from app.core.interface_builder import HARD_MAX_ATOMS, calculate_2d_mismatch, interface_score


class InterfaceBuilderTests(unittest.TestCase):
    def test_two_dimensional_mismatch(self):
        result = calculate_2d_mismatch(
            [[2.02, 0, 0], [0, 3.0, 0]],
            [[2.0, 0, 0], [0, 3.0, 0]],
        )
        self.assertAlmostEqual(result[0], 0.01)
        self.assertAlmostEqual(result[1], 0.0)
        self.assertAlmostEqual(result[2], 0.0)

    def test_score_penalizes_strain_and_atom_count(self):
        low = interface_score(0.01, 0.01, 0.0, 0.0, 100, 50, 0.05, HARD_MAX_ATOMS, 500)
        high = interface_score(0.04, 0.04, 0.0, 1.0, 900, 450, 0.05, HARD_MAX_ATOMS, 500)
        self.assertLess(low, high)


if __name__ == "__main__":
    unittest.main()
