import json
import tempfile
import unittest
from pathlib import Path

from app.core.interface_scan import (
    analyze_interface_project,
    estimate_scan_models,
    inclusive_float_range,
    inclusive_integer_range,
)


POSCAR = """Fe
1.0
3 0 0
0 3 0
0 0 15
Fe
2
Direct
0 0 0
0.5 0.5 0.5
"""


class InterfaceScanTests(unittest.TestCase):
    def test_inclusive_axes_and_model_estimate(self):
        self.assertEqual(inclusive_integer_range(4, 8, 2), [4, 6, 8])
        self.assertEqual(
            inclusive_float_range(1.8, 3.2, 0.5),
            [1.8, 2.3, 2.8, 3.2],
        )
        self.assertEqual(
            estimate_scan_models(2, 3, [4, 6], [4, 6], [2.0, 2.5], 1),
            48,
        )

    def test_energy_ranking_and_best_structure_export(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "demo"
            self._candidate(project, "gap_20", 2.0, -10.0, 2, 4, 4)
            self._candidate(project, "gap_25", 2.5, -11.0, 2, 4, 4)
            self._candidate(project, "layers_66", 2.5, -18.0, 4, 6, 6)

            result = analyze_interface_project(project)

            self.assertEqual(result["completed"], 3)
            by_name = {row["candidate"]: row for row in result["rows"]}
            self.assertTrue(by_name["gap_25"]["best_spacing"])
            self.assertAlmostEqual(by_name["gap_25"]["relative_energy_ev"], 0.0)
            self.assertAlmostEqual(by_name["gap_25"]["adjacent_delta_ev"], -1.0)
            self.assertTrue(by_name["gap_25"]["best_layer_screening"])
            self.assertTrue(Path(result["csv"]).is_file())
            self.assertTrue(Path(result["json"]).is_file())
            self.assertTrue(result["best_structures"])

    @staticmethod
    def _candidate(project, name, gap, energy, atoms, a_layers, b_layers):
        root = project / name
        static = root / "02_static"
        static.mkdir(parents=True)
        (static / "OUTCAR").write_text(
            f" free  energy   TOTEN  =       {energy:.8f} eV\n",
            encoding="utf-8",
        )
        (static / "POSCAR").write_text(POSCAR, encoding="utf-8")
        (root / "workflow.json").write_text(
            json.dumps(
                {
                    "candidate": name,
                    "atoms": atoms,
                    "gap_a": gap,
                    "source_a": "A.cif",
                    "source_b": "B.cif",
                    "scan_pair_id": "A01:A.cif × B01:B.cif",
                    "substrate_layers": a_layers,
                    "film_layers": b_layers,
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
