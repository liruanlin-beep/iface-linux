"""Geometry contracts use exported coordinates, not the builder's summary."""
import unittest
import numpy as np
from pymatgen.core import Lattice, Structure
from pymatgen.io.vasp import Poscar
from app.core.slab_builder import generate_slab
from app.core.interface_builder import search_interface_candidates


class SurfaceGeometryTests(unittest.TestCase):
    def setUp(self):
        self.bulk = Structure(Lattice.cubic(4.05), ['Al'] * 4,
                              [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]])

    def test_atomic_planes_and_normal_vacuum_for_three_faces(self):
        for hkl in [(1, 0, 0), (1, 1, 0), (1, 1, 1)]:
            for count in [4, 6, 8]:
                for vacuum in [10., 15., 20.]:
                    with self.subTest(hkl=hkl, count=count, vacuum=vacuum):
                        made = generate_slab(self.bulk, hkl, count, vacuum).structure
                        slab = Poscar.from_str(Poscar(made).get_str()).structure
                        a, b, c = slab.lattice.matrix
                        n = np.cross(a, b); n /= np.linalg.norm(n)
                        h = slab.cart_coords @ n
                        self.assertEqual(len(np.unique(np.round(h, 5))), count)
                        self.assertAlmostEqual(min(h), vacuum, places=6)
                        self.assertAlmostEqual(c @ n - max(h), vacuum, places=6)

    def test_independent_interface_planes_gap_and_external_vacuum(self):
        for hkl in [(1, 0, 0), (1, 1, 1)]:
            for na, nb in [(2, 2), (3, 4), (4, 4)]:
                for gap in [1.5, 2.5, 3.5]:
                    with self.subTest(hkl=hkl, na=na, nb=nb, gap=gap):
                        found = search_interface_candidates(self.bulk, self.bulk, hkl, hkl,
                            na, nb, gap=gap, max_area=30, max_atoms=200,
                            lateral_offsets=((0., 0.),), limit=1)
                        self.assertTrue(found)
                        s = found[0].structure
                        a, b, c = s.lattice.matrix
                        n = np.cross(a, b); n /= np.linalg.norm(n)
                        h = s.cart_coords @ n
                        labels = np.array(s.site_properties['interface_label'])
                        ah, bh = h[labels == 'substrate'], h[labels == 'film']
                        self.assertEqual(len(np.unique(np.round(ah, 5))), na)
                        self.assertEqual(len(np.unique(np.round(bh, 5))), nb)
                        self.assertAlmostEqual(min(bh) - max(ah), gap, places=6)
                        self.assertAlmostEqual(c @ n - np.ptp(h), 15., places=6)


if __name__ == '__main__':
    unittest.main()
