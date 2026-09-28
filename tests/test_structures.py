import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

from iface import api


HAS_PYMATGEN = importlib.util.find_spec("pymatgen") is not None


@unittest.skipUnless(HAS_PYMATGEN, "Install the structures extra for these integration tests")
class StructureIntegration(unittest.TestCase):
    def setUp(self):
        from pymatgen.core import Lattice, Structure
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bulk = Structure(Lattice.cubic(4.05), ["Al"] * 4,
                              [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]])
        self.path = self.root / "Al.cif"
        self.bulk.to(filename=str(self.path))

    def test_cif_conversion(self):
        output = self.root / "POSCAR"
        api.convert_structure(self.path, output)
        self.assertEqual(api.Poscar.read(output).atom_count, 4)

    def test_slab_has_vacuum_on_both_sides(self):
        output = self.root / "slab"
        report = api.slab(self.path, output, miller=(1, 1, 1), layers=4, vacuum=12)
        poscar = api.Poscar.read(output / "POSCAR")
        normal = np.cross(poscar.cell[0], poscar.cell[1])
        normal /= np.linalg.norm(normal)
        heights = (poscar.fractional @ poscar.cell) @ normal
        self.assertAlmostEqual(float(heights.min()), 12, places=6)
        self.assertAlmostEqual(float(poscar.cell[2] @ normal - heights.max()), 12, places=6)
        self.assertLessEqual(report["summary"]["Layers"], 4)

    def test_interface_candidates_reuse_existing_engine(self):
        output = self.root / "interfaces"
        report = api.interfaces(self.path, self.path, output, substrate_layers=2,
                                film_layers=2, gaps=[2.5], max_area=40, limit=2)
        self.assertGreater(len(report["candidates"]), 0)
        self.assertLessEqual(len(report["candidates"]), 2)
        for candidate in report["candidates"]:
            structure = api.Poscar.read(output / candidate["directory"] / "POSCAR")
            self.assertLessEqual(structure.atom_count, 1000)
            self.assertAlmostEqual(candidate["gap_a"], 2.5)

    def test_partial_occupancy_rejected(self):
        from pymatgen.core import Lattice, Structure
        structure = Structure(Lattice.cubic(4), [{"Al": 0.5, "Cu": 0.5}], [[0, 0, 0]])
        structure.to(filename=str(self.path))
        with self.assertRaisesRegex(ValueError, "occupied"):
            api.convert_structure(self.path, self.root / "POSCAR")

    def test_tilted_slab_normal_vacuum(self):
        from pymatgen.core import Lattice, Structure
        from iface.core.slab_builder import _center_with_vacuum
        structure = Structure(Lattice([[3, 0, 1], [0, 3, 0], [2, 0, 10]]),
                              ["Al", "Al"], [[0, 0, .2], [.5, .5, .4]])
        slab = _center_with_vacuum(structure, 10)
        normal = np.cross(slab.lattice.matrix[0], slab.lattice.matrix[1])
        normal /= np.linalg.norm(normal)
        heights = slab.cart_coords @ normal
        self.assertAlmostEqual(float(heights.min()), 10)
        self.assertAlmostEqual(float(slab.lattice.matrix[2] @ normal - heights.max()), 10)


if __name__ == "__main__":
    unittest.main()
