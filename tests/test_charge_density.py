import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.core.charge_density import calculate_charge_difference


class ChargeDensityTests(unittest.TestCase):
    def test_three_system_difference_and_grid_validation(self):
        from pymatgen.core import Lattice, Structure
        from pymatgen.io.vasp.outputs import Chgcar

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            structure = Structure(Lattice.cubic(4), ["Fe"], [[0, 0, 0]])
            substrate = np.ones((2, 2, 2)) * 2
            film = np.ones((2, 2, 2)) * 3
            difference = np.arange(8, dtype=float).reshape(2, 2, 2) / 10
            interface = substrate + film + difference
            paths = []
            for name, data in (
                ("interface", interface),
                ("substrate", substrate),
                ("film", film),
            ):
                path = root / name
                Chgcar(structure, {"total": data}).write_file(path)
                paths.append(path)
            result = calculate_charge_difference(*paths, root / "CHGDIFF.vasp")
            self.assertEqual(result.grid, (2, 2, 2))
            np.testing.assert_allclose(result.raw_total, difference, atol=1e-10)
            self.assertTrue(result.difference_path.is_file())

    def test_rejects_mismatched_grid(self):
        from pymatgen.core import Lattice, Structure
        from pymatgen.io.vasp.outputs import Chgcar

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            structure = Structure(Lattice.cubic(4), ["Fe"], [[0, 0, 0]])
            paths = []
            for index, shape in enumerate(((2, 2, 2), (3, 2, 2), (2, 2, 2))):
                path = root / str(index)
                Chgcar(structure, {"total": np.ones(shape)}).write_file(path)
                paths.append(path)
            with self.assertRaisesRegex(ValueError, "FFT grid mismatch"):
                calculate_charge_difference(*paths, root / "CHGDIFF")


if __name__ == "__main__":
    unittest.main()
