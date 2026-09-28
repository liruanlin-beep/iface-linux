import unittest

from app.core.vasp_progress import (
    calculate_progress_percent,
    detect_vasp_errors,
    parse_vasp_progress,
)


class VaspProgressTests(unittest.TestCase):
    def test_parses_electronic_and_ionic_steps(self):
        incar = "NELM = 200\nNSW = 100\nEDIFF = 1E-5\nEDIFFG = -0.02\n"
        oszicar = """
 DAV:   1    -1.000000E+01   -1.00000E+01   -1.00000E+01  128   1.000E-01
 DAV:   2    -1.050000E+01   -5.00000E-01   -4.90000E-01  128   2.000E-02
   1 F= -.10500000E+02 E0= -.10400000E+02  d E =-.500000E+00
 RMM:   1    -1.060000E+01   -1.00000E-01   -1.00000E-01   80   5.000E-03
 RMM:   2    -1.060001E+01   -1.00000E-05   -1.00000E-05   80   1.000E-05
   2 F= -.10600010E+02 E0= -.10500010E+02  d E =-.100010E+00
"""
        outcar = """
 free  energy   TOTEN  =       -10.600010 eV
 FORCES: max atom, RMS = 0.015 0.004
 reached required accuracy - stopping structural energy minimisation
 General timing and accounting informations for this job:
"""
        progress = parse_vasp_progress(oszicar, outcar, incar)
        self.assertEqual(progress.ionic_step, 2)
        self.assertEqual(progress.max_ionic_steps, 100)
        self.assertEqual(progress.electronic_step, 2)
        self.assertEqual(progress.max_electronic_steps, 200)
        self.assertEqual(progress.electronic_algorithm, "RMM")
        self.assertAlmostEqual(progress.energy_ev, -10.600010)
        self.assertAlmostEqual(progress.max_force_ev_a, 0.015)
        self.assertTrue(progress.electronic_converged)
        self.assertTrue(progress.ionic_converged)
        self.assertTrue(progress.finished)

    def test_detects_known_errors(self):
        findings = detect_vasp_errors("BRMIX: very serious problems\nDUE TO TIME LIMIT")
        self.assertEqual({item["code"] for item in findings}, {"BRMIX", "TIME_LIMIT"})

    def test_calculates_percentage(self):
        self.assertAlmostEqual(
            calculate_progress_percent({
                "ionic_step": 24,
                "max_ionic_steps": 100,
                "electronic_step": 30,
                "max_electronic_steps": 60,
            }),
            24.5,
        )
        self.assertEqual(calculate_progress_percent({"finished": True}), 100.0)


if __name__ == "__main__":
    unittest.main()
