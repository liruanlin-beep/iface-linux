import json
import tempfile
import unittest
from pathlib import Path

from app.core.task_bundle import create_task_bundle, verify_task_bundle


class TaskBundleTests(unittest.TestCase):
    def _make_files(self, root):
        for name in ("POSCAR", "INCAR", "KPOINTS", "POTCAR"):
            (root / name).write_text(f"{name}\n", encoding="utf-8")
        (root / "Svasp.sh").write_bytes(b"#!/bin/bash\r\nsrun vasp_std\r\n")

    def test_creates_verifiable_manifest_and_normalizes_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_files(root)
            bundle = create_task_bundle(root, "demo", bundle_id="fixed-id")
            manifest = verify_task_bundle(root)
            self.assertEqual(manifest["bundle_id"], "fixed-id")
            self.assertEqual((root / "Svasp.sh").read_bytes(), b"#!/bin/bash\nsrun vasp_std\n")
            self.assertEqual(bundle.files[-1], "task.json")

    def test_detects_changed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_files(root)
            create_task_bundle(root, "demo")
            (root / "INCAR").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_task_bundle(root)


if __name__ == "__main__":
    unittest.main()
