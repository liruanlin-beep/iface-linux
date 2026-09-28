import unittest

from app.core.slurm_diagnostics import classify_submit_error, submit_error_hint


class SlurmDiagnosticsTests(unittest.TestCase):
    def test_classifies_missing_squeue(self):
        kind = classify_submit_error("zsh:1: command not found: squeue", "")
        self.assertEqual(kind, "SQUEUE_NOT_FOUND")
        self.assertIn("PATH", submit_error_hint(kind))


if __name__ == "__main__":
    unittest.main()
