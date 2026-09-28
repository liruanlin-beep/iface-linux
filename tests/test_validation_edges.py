"""Analytical regression fixtures for the independent offline audit findings."""

from pathlib import Path
import tempfile
import unittest

from iface.formats import Poscar
from iface.results import inspect_calculation, results_csv


CELL = "Analytical fixture\n1\n4 0 0\n0 4 0\n0 0 4\n"
FORCE_HEADER = " POSITION TOTAL-FORCE (eV/Angst)\n ----------------\n"
FINISHED = " General timing and accounting informations for this job:\n"


def structure(species="Al", counts="1", flags=None):
    count = sum(map(int, counts.split()))
    text = CELL + species + "\n" + counts + "\n"
    if flags is not None:
        text += "Selective dynamics\n"
    text += "Direct\n"
    for index in range(count):
        text += f"{index / count} 0 0" + (" " + flags[index] if flags is not None else "") + "\n"
    return text


class ValidationEdges(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def folder(self, name="case", poscar=structure()):
        directory = self.root / name
        directory.mkdir()
        if poscar is not None:
            (directory / "POSCAR").write_text(poscar, encoding="utf-8")
        return directory

    def test_fictitious_and_obsolete_element_symbols_rejected(self):
        path = self.root / "POSCAR"
        for symbol in ("Qq", "Xx", "Uuo", "al"):
            with self.subTest(symbol=symbol):
                path.write_text(structure(symbol), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "valid chemical element"):
                    Poscar.read(path)

    def test_first_last_and_transition_elements_accepted(self):
        path = self.root / "POSCAR"
        path.write_text(structure("H Fe Og", "1 1 1"), encoding="utf-8")
        parsed = Poscar.read(path)
        self.assertEqual(parsed.species, ["H", "Fe", "Og"])
        self.assertEqual(parsed.atom_count, 3)

    def test_empty_outcar_uses_last_oszicar_free_energy(self):
        directory = self.folder()
        (directory / "OUTCAR").write_text("", encoding="utf-8")
        (directory / "OSZICAR").write_text(" 1 F= -3.0 E0= -3.1\n 2 F= -4D0 E0= -4.2\n", encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertEqual(result["energy_ev"], -4.0)
        self.assertEqual(result["energy_source"], "OSZICAR:F")
        self.assertEqual(result["ionic_steps"], 2)
        self.assertIn("OSZICAR:F", results_csv([result]))

    def test_nonempty_outcar_without_energy_uses_oszicar(self):
        directory = self.folder()
        (directory / "OUTCAR").write_text(" NIONS = 1\n", encoding="utf-8")
        (directory / "OSZICAR").write_text(" 1 F= -7.25 E0= -7.5\n", encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertEqual(result["energy_ev"], -7.25)
        self.assertEqual(result["energy_source"], "OSZICAR:F")

    def test_last_outcar_toten_takes_precedence(self):
        directory = self.folder()
        (directory / "OUTCAR").write_text(" free energy TOTEN = -2\n free energy TOTEN = -3.5\n", encoding="utf-8")
        (directory / "OSZICAR").write_text(" 1 F= -8.0\n", encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertEqual(result["energy_ev"], -3.5)
        self.assertEqual(result["energy_source"], "OUTCAR:TOTEN")

    def test_absent_energy_remains_unknown_with_no_source(self):
        result = inspect_calculation(self.folder())
        self.assertIsNone(result["energy_ev"])
        self.assertIsNone(result["energy_source"])

    def test_complete_force_table_at_eof_uses_vector_norm(self):
        directory = self.folder(poscar=structure(counts="2"))
        (directory / "OUTCAR").write_text(
            FORCE_HEADER + " 0 0 0 0.03 0.04 0\n 0 0 0 0.05 0.12 0", encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertAlmostEqual(result["max_force_ev_a"], 0.13)
        self.assertEqual(result["force_table_rows"], 2)
        self.assertTrue(result["force_table_complete"])

    def test_outcar_nions_can_validate_force_table_without_poscar(self):
        directory = self.folder(poscar=None)
        (directory / "OUTCAR").write_text(
            " NIONS = 1\n" + FORCE_HEADER + " 0 0 0 0.03 0.04 0\n", encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertAlmostEqual(result["max_force_ev_a"], 0.05)
        self.assertEqual(result["atom_count"], 1)
        self.assertTrue(result["force_table_complete"])

    def test_short_force_table_is_unknown_even_after_normal_exit(self):
        directory = self.folder(poscar=structure(counts="2"))
        (directory / "OUTCAR").write_text(
            FORCE_HEADER + " 0 0 0 0.03 0.04 0\n ---\n" + FINISHED, encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertIsNone(result["max_force_ev_a"])
        self.assertFalse(result["force_table_complete"])
        self.assertIn("1 rows for 2 expected atoms", " ".join(result["warnings"]))
        self.assertTrue(result["finished"])

    def test_truncated_last_force_table_does_not_reuse_previous_maximum(self):
        directory = self.folder(poscar=structure(counts="2"))
        complete = FORCE_HEADER + " 0 0 0 0.03 0.04 0\n 0 0 0 0 0 0.2\n ---\n"
        partial = FORCE_HEADER + " 0 0 0 0.01 0 0\n"
        (directory / "OUTCAR").write_text(complete + partial, encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertIsNone(result["max_force_ev_a"])
        self.assertEqual(result["force_table_rows"], 1)

    def test_nions_poscar_mismatch_invalidates_force_table(self):
        directory = self.folder()
        (directory / "OUTCAR").write_text(
            " NIONS = 2\n" + FORCE_HEADER + " 0 0 0 0.03 0.04 0\n", encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertIsNone(result["max_force_ev_a"])
        self.assertIn("differs from the POSCAR atom count", " ".join(result["warnings"]))

    def test_force_table_without_atom_count_cannot_be_certified(self):
        directory = self.folder(poscar=None)
        (directory / "OUTCAR").write_text(
            FORCE_HEADER + " 0 0 0 0.03 0.04 0\n ---\n", encoding="utf-8")
        result = inspect_calculation(directory)
        self.assertIsNone(result["max_force_ev_a"])
        self.assertIn("Cannot verify", " ".join(result["warnings"]))

if __name__ == "__main__":
    unittest.main()
