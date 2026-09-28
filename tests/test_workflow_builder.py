import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.structure_model import Atom, Structure
from app.core.input_generators import write_poscar
from app.core.task_database import TaskDatabase
from app.core.workflow_builder import (
    build_adaptive_interface_workflow,
    build_candidate_workflow,
)


class WorkflowBuilderTests(unittest.TestCase):
    def test_builds_dependency_chain_without_potcar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = TaskDatabase(root / "tasks.sqlite3")
            structure = Structure(
                "Fe_surface",
                atoms=[Atom("Fe", 0, 0, 0), Atom("Fe", 1, 1, 1)],
                cell=((3, 0, 0), (0, 3, 0), (0, 0, 15)),
            )
            candidate = SimpleNamespace(
                lightweight=structure,
                area=9.0,
                gap=2.0,
                strain=0.01,
                compatibility_percent=90.0,
                source_a="Fe_A.cif",
                source_b="Fe_B.cif",
                scan_pair_id="A01 × B01",
                substrate_layers=4,
                film_layers=6,
            )
            config = {
                "potcar_root": str(root / "missing"),
                "default_remote_root": "/home/test/iface",
                "submit_script": "Svasp.sh",
                "slurm": {"run_command": "srun vasp_std"},
                "high_throughput": {"hard_max_atoms": 1000, "max_automatic_retries": 3},
            }
            result = build_candidate_workflow(
                candidate, root / "output", "demo", config, database=database
            )
            tasks = database.list_tasks()
            self.assertEqual(len(tasks), 3)
            self.assertFalse(tasks[0].dependencies)
            self.assertEqual(tasks[1].dependencies, (tasks[0].id,))
            self.assertTrue((result.root / "01_relax" / "INCAR").is_file())
            self.assertTrue((result.root / "workflow.json").is_file())
            manifest = __import__("json").loads(
                (result.root / "workflow.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["substrate_layers"], 4)
            self.assertEqual(manifest["film_layers"], 6)
            self.assertEqual(manifest["source_a"], "Fe_A.cif")
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(len(manifest["workflow_fingerprint"]), 64)
            self.assertTrue(result.warnings)

            repeated = build_candidate_workflow(
                candidate, root / "output", "demo", config, database=database
            )
            self.assertEqual(repeated.task_ids, result.task_ids)
            self.assertEqual(len(database.list_tasks()), 3)

    def test_builds_adaptive_bulk_then_rebuild_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = TaskDatabase(root / "tasks.sqlite3")
            structure = Structure(
                "Fe_bulk",
                atoms=[Atom("Fe", 0, 0, 0), Atom("Fe", 1.5, 1.5, 1.5)],
                cell=((3, 0, 0), (0, 3, 0), (0, 0, 3)),
            )
            substrate = root / "A.vasp"
            film = root / "B.vasp"
            write_poscar(substrate, structure, "Direct", False)
            write_poscar(film, structure, "Direct", False)
            config = {
                "potcar_root": str(root / "missing"),
                "default_remote_root": "/home/test/iface",
                "submit_script": "Svasp.sh",
                "slurm": {"run_command": "srun vasp_std"},
                "high_throughput": {
                    "hard_max_atoms": 1000,
                    "max_automatic_retries": 3,
                    "adaptive_candidate_limit": 3,
                },
            }
            result = build_adaptive_interface_workflow(
                substrate,
                film,
                root / "output",
                "adaptive-demo",
                config,
                {
                    "substrate_hkl": (1, 0, 0),
                    "film_hkl": (1, 0, 0),
                    "limit": 12,
                },
                database=database,
            )
            tasks = database.list_tasks()
            self.assertEqual(len(tasks), 3)
            self.assertEqual(tasks[2].task_type, "local:interface_rebuild")
            self.assertEqual(set(tasks[2].dependencies), {tasks[0].id, tasks[1].id})
            incar = (result.root / "01_bulk_A_relax" / "INCAR").read_text(
                encoding="utf-8"
            )
            self.assertIn("ISIF = 3", incar)
            kpoints = (result.root / "01_bulk_A_relax" / "KPOINTS").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("\n1 1 1\n", kpoints)
            self.assertTrue((result.root / "adaptive_workflow.json").is_file())


if __name__ == "__main__":
    unittest.main()
