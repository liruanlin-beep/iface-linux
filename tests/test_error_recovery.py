import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.error_recovery import create_recovery_attempt, suggest_recovery


class ErrorRecoveryTests(unittest.TestCase):
    def test_brmix_plan_is_allowlisted_and_audited(self):
        progress = SimpleNamespace(
            errors=[{"code": "BRMIX"}],
            max_electronic_steps=60,
            electronic_step=10,
            electronic_converged=False,
        )
        plan = suggest_recovery(progress, "ALGO = Fast\n")
        self.assertEqual(plan.incar_patch["ALGO"], "Normal")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "INCAR").write_text("ALGO = Fast\n", encoding="utf-8")
            (root / "POSCAR").write_text("old\n", encoding="utf-8")
            (root / "CONTCAR").write_text("new\n", encoding="utf-8")
            attempt, changes = create_recovery_attempt(
                root, plan, 2, root / "CONTCAR"
            )
            self.assertTrue((attempt / "recovery.json").is_file())
            self.assertIn("ALGO = Normal", (root / "INCAR").read_text(encoding="utf-8"))
            self.assertEqual((root / "POSCAR").read_text(encoding="utf-8"), "new\n")
            self.assertEqual(changes["ALGO"]["before"], "Fast")

    def test_high_risk_error_never_gets_parameter_patch(self):
        progress = SimpleNamespace(
            errors=[{"code": "OUT_OF_MEMORY"}],
            max_electronic_steps=0,
            electronic_step=0,
            electronic_converged=False,
        )
        plan = suggest_recovery(progress)
        self.assertEqual(plan.risk, "manual")
        self.assertFalse(plan.incar_patch)


if __name__ == "__main__":
    unittest.main()
