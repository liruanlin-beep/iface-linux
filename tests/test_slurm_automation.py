import tempfile
import unittest
from pathlib import Path

from app.core.slurm_automation import AutomationPolicy, decide_slurm_action
from app.core.submission_queue import SubmissionQueue
from app.core.task_database import TaskDatabase, TaskState


class SlurmAutomationTests(unittest.TestCase):
    def test_only_transient_failure_is_automatically_retried(self):
        policy = AutomationPolicy(enabled=True, max_attempts=3)
        node = decide_slurm_action("NODE_FAIL", 1, policy)
        oom = decide_slurm_action("OUT_OF_MEMORY", 1, policy)
        self.assertEqual(node.action, "retry")
        self.assertEqual(oom.action, "diagnose")
        self.assertTrue(oom.requires_approval)

    def test_attempt_limit_stops_retry(self):
        decision = decide_slurm_action(
            "PREEMPTED",
            3,
            AutomationPolicy(enabled=True, max_attempts=3),
        )
        self.assertEqual(decision.action, "stop")

    def test_queue_moves_node_failure_to_retry_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            database = TaskDatabase(Path(directory) / "tasks.sqlite3")
            task_id = database.add_task(
                "job",
                "project",
                "vasp:relax",
                directory,
                state=TaskState.PENDING.value,
            )
            database.update_task(task_id, attempts=1, slurm_job_id="101")
            queue = SubmissionQueue(
                database,
                automation_policy={"enabled": True, "max_attempts": 3},
            )
            state = queue.update_slurm_state(task_id, "NODE_FAIL")
            self.assertEqual(state, TaskState.RETRY_WAIT.value)
            self.assertEqual(database.get_task(task_id).slurm_job_id, "")


if __name__ == "__main__":
    unittest.main()
