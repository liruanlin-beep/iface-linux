import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from iface.interface_scan import interface_scan, inspect_interface_scan


class ScanInspection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = []

    def candidate(self, name, gap, energy, finished=True, element="Al", width=4, static=False):
        case = self.root / name
        case.mkdir()
        poscar = f"{name}\n1\n{width} 0 0\n0 4 0\n0 0 {10 + gap}\n{element}\n1\nDirect\n0 0 0\n"
        (case / "POSCAR").write_text(poscar, encoding="utf-8")
        result = case / "02_static" if static else case
        result.mkdir(exist_ok=True)
        text = f" free  energy   TOTEN  = {energy} eV\n"
        if finished:
            text += " General timing and accounting informations for this job:\n"
        (result / "OUTCAR").write_text(text, encoding="utf-8")
        self.rows.append({"directory": name, "pair_id": "A01_B01", "source_a": "Al-A.cif",
                          "source_b": "Al-B.cif", "substrate_layers": 2, "film_layers": 2,
                          "gap_a": gap, "atoms": 1, "termination": "Al / Al", "offset": [0, 0],
                          "score": 0.5})

    def report(self):
        (self.root / "manifest.json").write_text(json.dumps(
            {"kind": "interface_scan", "requested_gaps_a": [2.0, 2.5], "candidates": self.rows}),
            encoding="utf-8")
        return inspect_interface_scan(self.root)

    def test_completed_spacing_ranking_uses_static_and_keeps_matching_groups_separate(self):
        self.candidate("gap20", 2.0, -10)
        self.candidate("gap25", 2.5, -11, static=True)
        self.candidate("different_composition", 2.0, -99, element="Cu")
        self.candidate("different_matching_cell", 2.5, -100, width=8)
        report = self.report()
        rows = {row["directory"]: row for row in report["rows"]}
        self.assertEqual(len(report["groups"]), 3)
        self.assertTrue(rows["gap25"]["best_spacing"])
        self.assertEqual(rows["gap25"]["adjacent_delta_ev"], -1)
        self.assertEqual(rows["gap20"]["relative_energy_ev"], 1)
        self.assertFalse(rows["different_composition"]["best_spacing"])
        self.assertFalse(rows["different_matching_cell"]["best_spacing"])
        self.assertIn("02_static", rows["gap25"]["result_directory"])
        self.assertIn("energy_status", report["csv"])

    def test_unfinished_energy_cannot_be_a_final_best_spacing(self):
        self.candidate("gap20", 2.0, -10)
        self.candidate("gap25", 2.5, -11, finished=False)
        report = self.report()
        self.assertFalse(report["groups"][0]["complete"])
        self.assertTrue(all(not row["best_spacing"] for row in report["rows"]))
        self.assertTrue(all(row["relative_energy_ev"] is None for row in report["rows"]))
        self.assertTrue(report["rows"][1]["provisional_minimum"])
        self.assertEqual(report["rows"][1]["energy_status"], "provisional")

    def test_missing_identity_never_compares_unrelated_models(self):
        self.candidate("gap20", 2.0, -10)
        self.candidate("gap25", 2.5, -11)
        self.rows[1].pop("pair_id")
        report = self.report()
        self.assertIsNone(report["rows"][1]["comparison_group"])
        self.assertFalse(any(row["best_spacing"] for row in report["rows"]))

    def test_mismatched_outcar_atom_count_is_excluded_from_ranking(self):
        self.candidate("gap20", 2.0, -10)
        self.candidate("gap25", 2.5, -99)
        with (self.root / "gap25" / "OUTCAR").open("a", encoding="utf-8") as stream:
            stream.write(" NIONS = 2\n")
        report = self.report()
        row = report["rows"][1]
        self.assertFalse(row["ranking_valid"])
        self.assertTrue(any("NIONS" in error for error in row["errors"]))
        self.assertIsNone(row["provisional_relative_energy_ev"])
        self.assertFalse(any(row["best_spacing"] for row in report["rows"]))

    def test_contcar_species_change_is_excluded_from_ranking(self):
        self.candidate("gap20", 2.0, -10)
        self.candidate("gap25", 2.5, -99)
        case = self.root / "gap25"
        (case / "CONTCAR").write_text((case / "POSCAR").read_text().replace("Al", "Cu"))
        report = self.report()
        self.assertFalse(report["rows"][1]["ranking_valid"])
        self.assertTrue(report["rows"][1]["errors"])
        self.assertFalse(any(row["best_spacing"] for row in report["rows"]))

    def test_invalid_final_geometry_falls_back_but_keeps_energy_provisional(self):
        self.candidate("gap20", 2.0, -10)
        self.candidate("gap25", 2.5, -11)
        (self.root / "gap25" / "CONTCAR").write_text("invalid geometry")
        report = self.report()
        row = report["rows"][1]
        self.assertIsNotNone(row["comparison_group"])
        self.assertEqual(row["energy_per_atom_ev"], -11)
        self.assertEqual(row["energy_status"], "provisional")
        self.assertTrue(any("Invalid geometry" in warning for warning in row["warnings"]))
        self.assertFalse(row["ranking_valid"])
        self.assertFalse(any(row["best_spacing"] for row in report["rows"]))

    def test_manifest_cannot_escape_scan_directory(self):
        self.rows = [{"directory": "../outside"}]
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.report()

    def test_large_scan_is_rejected_before_structure_loading(self):
        with self.assertRaisesRegex(ValueError, "maximum is 300"):
            interface_scan(["missing.cif"], ["missing.cif"], self.root / "too_big",
                           substrate_layer_values=range(1, 302))


@unittest.skipUnless(importlib.util.find_spec("pymatgen"), "Install the structures extra")
class ScanGeometry(unittest.TestCase):
    def test_real_al_scan_exports_each_pair_layer_and_gap(self):
        import numpy as np
        from pymatgen.core import Lattice, Structure
        from pymatgen.io.vasp import Poscar
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bulk = Structure(Lattice.cubic(4.05), ["Al"] * 4,
                             [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]])
            source = root / "Al.cif"
            bulk.to(filename=str(source))
            output = root / "scan"
            report = interface_scan([source, source], [source], output,
                                    substrate_layer_values=(2, 3), film_layer_values=(2,),
                                    gaps=(2.0, 2.5), max_area=40, limit_per_gap=1)
            self.assertEqual(report["models"], 8)
            combinations = {(row["pair_id"], row["substrate_layers"], row["gap_a"])
                            for row in report["candidates"]}
            self.assertEqual(len(combinations), 8)
            for row in report["candidates"]:
                structure = Poscar.from_file(output / row["directory"] / "POSCAR").structure
                self.assertEqual(len(structure), row["atoms"])
                self.assertEqual(set(row["composition"]), {"Al"})
                self.assertTrue((output / row["directory"] / "model.json").is_file())
                normal = np.cross(structure.lattice.matrix[0], structure.lattice.matrix[1])
                normal /= np.linalg.norm(normal)
                heights = structure.cart_coords @ normal
                actual_gap = min(heights[row["film_atom_indices"]]) - max(heights[row["substrate_atom_indices"]])
                self.assertAlmostEqual(float(actual_gap), row["gap_a"], places=7)
                self.assertAlmostEqual(row["measured_gap_a"], row["gap_a"], places=7)
            inspection = inspect_interface_scan(output)
            self.assertTrue(all(row["energy_ev"] is None for row in inspection["rows"]))
            self.assertFalse(any(row["best_spacing"] for row in inspection["rows"]))
            from iface.structures import interfaces
            direct = interfaces(source, source, root / "direct", substrate_layers=2,
                                film_layers=2, gaps=(2.0, 2.5), max_area=40, limit=2,
                                lateral_offsets=((0.25, 0.0),))
            self.assertEqual({row["gap_a"] for row in direct["candidates"]}, {2.0, 2.5})
            self.assertEqual(len(direct["candidates"]), 2)
            self.assertTrue(all(row["offset"] == [0.25, 0.0] for row in direct["candidates"]))


if __name__ == "__main__":
    unittest.main()
