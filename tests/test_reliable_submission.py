import tempfile
import unittest
from pathlib import Path

from app.core.reliable_submission import (
    ReliableSlurmSubmitter,
    SubmissionOutcomeUnknown,
    ensure_parsable_sbatch,
    parse_sbatch_job_id,
    parse_reconciliation_job_id,
)
from app.core.submission_queue import SubmissionQueue
from app.core.task_database import TaskDatabase, TaskState


class FakeSSH:
    username = "tester"

    def __init__(self, responses):
        self.responses = list(responses)

    def run_remote_command(self, *_args, **_kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ReliableSubmissionTests(unittest.TestCase):
    def test_reconciliation_requires_matching_name_and_unique_job(self):
        self.assertEqual(parse_reconciliation_job_id("123", "iface-demo"), "")
        self.assertEqual(
            parse_reconciliation_job_id("123|other|RUNNING", "iface-demo"), ""
        )
        self.assertEqual(
            parse_reconciliation_job_id(
                "123|iface-demo|PENDING\n123|iface-demo|RUNNING", "iface-demo"
            ),
            "123",
        )
        with self.assertRaises(SubmissionOutcomeUnknown):
            parse_reconciliation_job_id(
                "123|iface-demo|RUNNING\n456|iface-demo|PENDING", "iface-demo"
            )

    def test_ambiguous_queue_result_does_not_fall_back_to_history(self):
        ssh = FakeSSH([
            (0, "123|iface-demo|RUNNING\n456|iface-demo|PENDING", "", "squeue"),
            (0, "123|iface-demo|COMPLETED", "", "sacct"),
        ])
        self.assertEqual(ReliableSlurmSubmitter(ssh, "/tmp/task").reconcile("iface-demo"), "")
        self.assertEqual(len(ssh.responses), 1)

    def test_ambiguous_submission_remains_unknown(self):
        ssh = FakeSSH([
            TimeoutError("connection lost"),
            (0, "123|iface-demo|RUNNING\n456|iface-demo|PENDING", "", "squeue"),
        ])
        with self.assertRaises(SubmissionOutcomeUnknown):
            ReliableSlurmSubmitter(ssh, "/tmp/task").submit(
                "sbatch Svasp.sh", job_name="iface-demo"
            )

    def test_parses_standard_and_parsable_output(self):
        self.assertEqual(parse_sbatch_job_id("Submitted batch job 123"), "123")
        self.assertEqual(parse_sbatch_job_id("456;cluster"), "456")
        self.assertEqual(
            ensure_parsable_sbatch("sbatch Svasp.sh"),
            "sbatch --parsable Svasp.sh",
        )

    def test_reconciles_after_transport_error(self):
        ssh = FakeSSH(
            [
                TimeoutError("timeout"),
                (0, "778|iface-demo|PENDING\n", "", "squeue"),
            ]
        )
        result = ReliableSlurmSubmitter(ssh, "/tmp/task").submit(
            "sbatch Svasp.sh", "Svasp.sh", "iface-demo"
        )
        self.assertEqual(result[0], "778")

    def test_unknown_submission_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            database = TaskDatabase(Path(directory) / "tasks.sqlite3")
            task_id = database.add_task(
                "demo",
                "project",
                "vasp:relax",
                directory,
                state=TaskState.READY.value,
            )
            queue = SubmissionQueue(database)

            def unknown(_task):
                raise SubmissionOutcomeUnknown("ambiguous")

            queue.dispatch_once(unknown)
            task = database.get_task(task_id)
            self.assertEqual(task.state, TaskState.UNKNOWN_REMOTE_STATE.value)
            self.assertEqual(task.attempts, 1)
            queue.dispatch_once(lambda _task: "should-not-run")
            self.assertEqual(
                database.get_task(task_id).state,
                TaskState.UNKNOWN_REMOTE_STATE.value,
            )


if __name__ == "__main__":
    unittest.main()
