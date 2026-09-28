import unittest

from app.core.incar_presets import PRESET_LABELS, get_incar_preset


class IncarPresetTests(unittest.TestCase):
    def test_every_calculation_module_has_valid_single_line_values(self):
        for name in PRESET_LABELS:
            params = get_incar_preset(name, ["Fe", "Fe", "Ni"])
            self.assertEqual(params["ENCUT"], "520")
            self.assertNotIn("IALGO", params)
            self.assertNotIn("NPAR", params)
            self.assertNotIn("NCORE", params)
            for key, value in params.items():
                self.assertEqual(key, key.strip())
                self.assertNotIn("\n", str(value))
                self.assertNotIn(" eV", str(value))

    def test_bader_and_pdos_require_the_expected_outputs(self):
        bader = get_incar_preset("bader", ["Fe"])
        self.assertEqual(bader["LAECHG"], ".TRUE.")
        self.assertEqual(bader["LCHARG"], ".TRUE.")
        pdos = get_incar_preset("pdos", ["Fe"])
        self.assertEqual(pdos["ICHARG"], "11")
        self.assertEqual(pdos["LORBIT"], "11")
        self.assertGreaterEqual(int(pdos["NEDOS"]), 3000)


if __name__ == "__main__":
    unittest.main()
