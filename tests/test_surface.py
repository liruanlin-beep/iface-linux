"""Analytical checks for the original slab surface-energy workflow."""

from pathlib import Path
import tempfile
import unittest

from iface.surface import calculate_surface_energy, surface_energy


def slab(cell="2 0 0\n0 3 0\n0 0 20", atoms=2):
    coordinates = "\n".join(f"0 0 {0.2 + i * 0.1}" for i in range(atoms))
    return f"Al slab\n1\n{cell}\nAl\n{atoms}\nDirect\n{coordinates}\n"


class SurfaceEnergy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "POSCAR").write_text(slab(), encoding="utf-8")

    def output(self, energy=-6, *, finished=False, converged=False, nions=2):
        text = f" NIONS = {nions}\n free energy TOTEN = {energy} eV\n"
        if converged:
            text += " reached required accuracy - stopping structural energy minimisation\n"
        if finished:
            text += " General timing and accounting informations for this job:\n"
        (self.root / "OUTCAR").write_text(text, encoding="utf-8")

    def test_analytic_formula_and_unit_conversion(self):
        gamma, si = calculate_surface_energy(-6, -4, 2, 6)
        self.assertAlmostEqual(gamma, 1 / 6)
        self.assertAlmostEqual(si, 2.67029439)
        self.assertEqual(calculate_surface_energy(-8, -4, 2, 6), (0, 0))

    def test_tilted_area_uses_cross_product_and_final_geometry(self):
        # (2, 0, 0) cross (0, 3, 4) = (0, -8, 6), with area 10.
        (self.root / "CONTCAR").write_text(slab("2 0 0\n0 3 4\n0 0 20"), encoding="utf-8")
        self.output(finished=True, converged=True)
        result = surface_energy(self.root, -4)
        self.assertEqual(result["geometry_source"], "CONTCAR")
        self.assertEqual(result["area_a2"], 10)
        self.assertAlmostEqual(result["gamma_ev_a2"], 0.1)
        self.assertEqual(result["surface_normal"], [0, -0.8, 0.6])
        self.assertFalse(result["provisional"])
        self.assertEqual(result["electronic_convergence"], "not_assessed")

    def test_missing_energy_rejected(self):
        with self.assertRaisesRegex(ValueError, "No slab total energy"):
            surface_energy(self.root, -4)

    def test_empty_or_invalid_contcar_falls_back_with_warning(self):
        self.output()
        for text in ("", "not a structure"):
            with self.subTest(text=text):
                (self.root / "CONTCAR").write_text(text, encoding="utf-8")
                result = surface_energy(self.root, -4)
                self.assertEqual(result["geometry_source"], "POSCAR")
                self.assertEqual(result["area_a2"], 6)
                self.assertTrue(any("Using POSCAR geometry" in message for message in result["warnings"]))

    def test_unfinished_and_normal_exit_without_convergence_are_provisional(self):
        for finished, converged in ((False, False), (True, False), (False, True)):
            with self.subTest(finished=finished, converged=converged):
                self.output(finished=finished, converged=converged)
                self.assertTrue(surface_energy(self.root, -4)["provisional"])

    def test_oszicar_energy_is_labeled_and_provisional(self):
        (self.root / "OSZICAR").write_text(" 1 F= -6.0 E0= -6.2\n", encoding="utf-8")
        result = surface_energy(self.root, -4)
        self.assertEqual(result["energy_source"], "OSZICAR:F")
        self.assertEqual(result["slab_energy_ev"], -6)
        self.assertTrue(result["provisional"])

    def test_counts_must_agree_between_geometry_and_output(self):
        self.output(nions=3)
        with self.assertRaisesRegex(ValueError, "NIONS"):
            surface_energy(self.root, -4)
        self.output()
        (self.root / "CONTCAR").write_text(slab(atoms=3), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "atom counts must match"):
            surface_energy(self.root, -4)

    def test_nonfinite_or_missing_numbers_rejected(self):
        for invalid in (float("inf"), float("-inf"), float("nan"), None, "", True):
            for index in range(5):
                arguments = [-6, -4, 2, 6, 2]
                arguments[index] = invalid
                with self.subTest(invalid=invalid, index=index):
                    with self.assertRaises(ValueError):
                        calculate_surface_energy(*arguments)

    def test_fractional_nonpositive_counts_and_area_rejected(self):
        for index in (2, 4):
            for invalid in (0, -1, 1.5):
                arguments = [-6, -4, 2, 6, 2]
                arguments[index] = invalid
                with self.subTest(index=index, invalid=invalid):
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        calculate_surface_energy(*arguments)
        for area in (0, -1):
            with self.assertRaisesRegex(ValueError, "area must be positive"):
                calculate_surface_energy(-6, -4, 2, area)

    def test_finite_inputs_cannot_silently_overflow(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            calculate_surface_energy(-1e308, 1e308, 2, 6)


if __name__ == "__main__":
    unittest.main()
