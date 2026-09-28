import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.input_generators import write_cif, write_poscar
from app.core.structure_model import Atom, Structure


class LatticeWriteTests(unittest.TestCase):
    def test_interleaved_species_match_potcar_order_and_keep_fixed_sites(self):
        from pymatgen.io.vasp import Poscar
        model = Structure('layers', [Atom('Y', 0, 0, 0), Atom('Al', 1, 1, 1), Atom('Y', 2, 2, 2)],
                          ((4,0,0),(0,4,0),(0,0,4)))
        model.atoms[2].fixed = True
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'POSCAR'
            write_poscar(target, model)
            parsed = Poscar.from_file(target, check_for_potcar=False)
            self.assertEqual(parsed.site_symbols, ['Y', 'Al'])
            self.assertEqual(parsed.natoms, [2,1])
            self.assertEqual([list(row) for row in parsed.selective_dynamics], [[True]*3,[False]*3,[True]*3])
            self.assertEqual(parsed.structure.cart_coords.tolist(), [[0.,0.,0.],[2.,2.,2.],[1.,1.,1.]])

    def setUp(self):
        self.cell = (
            (2.0, 0.0, 0.0),
            (1.0, 2.0, 0.0),
            (0.5, 0.25, 3.0),
        )
        # Cartesian position obtained from fractional (0.25, 0.5, 0.75).
        self.structure = Structure(
            "skew-cell",
            [Atom("Al", 1.375, 1.1875, 2.25)],
            self.cell,
        )

    def test_poscar_fallback_preserves_full_lattice_and_fractional_coordinates(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "POSCAR"
            with patch(
                "app.core.structure_model.to_pymatgen_structure",
                side_effect=RuntimeError("force safe fallback"),
            ):
                write_poscar(target, self.structure, "Direct", False)
            lines = target.read_text(encoding="utf-8").splitlines()

        self.assertEqual(lines[2], "2.00000000 0.00000000 0.00000000")
        self.assertEqual(lines[3], "1.00000000 2.00000000 0.00000000")
        self.assertEqual(lines[4], "0.50000000 0.25000000 3.00000000")
        self.assertEqual(lines[-1], "0.25000000 0.50000000 0.75000000")

    def test_cif_fallback_preserves_non_right_angles(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "skew.cif"
            write_cif(target, self.structure)
            text = target.read_text(encoding="utf-8")

        self.assertIn("_cell_length_b 2.23606798", text)
        self.assertNotIn("_cell_angle_gamma 90\n", text)
        self.assertIn("Al1 Al 0.250000 0.500000 0.750000", text)


if __name__ == "__main__":
    unittest.main()
