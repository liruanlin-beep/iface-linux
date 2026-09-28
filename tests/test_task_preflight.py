import tempfile
import unittest
from pathlib import Path

from app.core.input_generators import write_incar, write_kpoints, write_poscar
from app.core.structure_model import Atom, Structure
from app.core.task_preflight import validate_task_preflight


class TaskPreflightTests(unittest.TestCase):
    def _write_valid(self, root):
        structure = Structure(
            "Fe",
            [Atom("Fe", 0, 0, 0)],
            ((3, 0, 0), (0, 3, 0), (0, 0, 3)),
        )
        write_poscar(root / "POSCAR", structure)
        write_incar(root / "INCAR", {"ENCUT": "520", "ISPIN": "2", "MAGMOM": "1*2.0"})
        write_kpoints(root / "KPOINTS", (5, 5, 5))
        (root / "POTCAR").write_text(
            "TITEL  = PAW_PBE Fe 06Sep2000\nVRHFIN =Fe: s2p6d6s2\n",
            encoding="utf-8",
        )
        (root / "Svasp.sh").write_text(
            "#!/bin/bash\n#SBATCH --job-name=test\nsrun vasp_std\n",
            encoding="utf-8",
            newline="\n",
        )

    def test_valid_task_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid(root)
            report = validate_task_preflight(root)
            self.assertTrue(report.ok, report.errors)
            self.assertEqual(report.elements, ("Fe",))

    def test_rejects_potcar_order_and_incar_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid(root)
            (root / "POTCAR").write_text("VRHFIN =Al: s2p1\n", encoding="utf-8")
            (root / "INCAR").write_text("LDAU = .TRUE.\nLDAUU = 请填写\n", encoding="utf-8")
            report = validate_task_preflight(root)
            self.assertFalse(report.ok)
            self.assertTrue(any("element order" in error for error in report.errors))
            self.assertTrue(any("placeholder" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()
