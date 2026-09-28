import unittest
import tempfile
from pathlib import Path

from app.core.slurm_manager import SlurmManager, sanitize_job_name


class SlurmManagerTests(unittest.TestCase):
    def test_existing_directory_with_decimal_gap_is_not_treated_as_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'gap_2.25'
            target.mkdir()
            script=SlurmManager().write(target)
            self.assertEqual(script,target/'Svasp.sh')
            self.assertTrue(script.is_file())

    def test_job_name_is_shell_safe(self):
        self.assertEqual(sanitize_job_name("界面 task; rm -rf /"), "task_rm_-rf")

    def test_renders_v643_slurm_script(self):
        script = SlurmManager(
            {
                "vasp_version": "6.4.3",
                "nodes": 2,
                "ntasks_per_node": 32,
                "cpus_per_task": 1,
                "time": "1-12:00:00",
                "partition": "compute",
                "environment_init": "module load vasp/6.4.3",
                "run_command": "srun vasp_std",
            },
            job_name="alloy interface 01",
        ).render()
        self.assertIn("#SBATCH --job-name=alloy_interface_01", script)
        self.assertIn("#SBATCH --partition=compute", script)
        self.assertIn("#SBATCH --time=1-12:00:00", script)
        self.assertIn("module load vasp/6.4.3", script)
        self.assertIn("srun vasp_std", script)


if __name__ == "__main__":
    unittest.main()
