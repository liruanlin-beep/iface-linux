import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.submission_queue import SubmissionQueue
from app.core.task_database import TaskDatabase, TaskState


class TaskDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = TaskDatabase(Path(self.temp.name) / "tasks.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_dependencies_and_server_aware_limit(self):
        parent = self.db.add_task("bulk", "p1", "relax", self.temp.name)
        child = self.db.add_task(
            "pdos",
            "p1",
            "pdos",
            self.temp.name,
            dependencies=[parent],
        )
        self.db.refresh_dependency_states()
        self.assertEqual(self.db.get_task(parent).state, TaskState.READY.value)
        self.assertEqual(self.db.get_task(child).state, TaskState.BLOCKED.value)

        queue = SubmissionQueue(self.db, max_inflight=10)
        result = queue.dispatch_once(lambda task: "1001", server_active_count=9)
        self.assertEqual(result.submitted, 1)
        self.assertEqual(self.db.get_task(parent).state, TaskState.PENDING.value)
        self.assertEqual(self.db.get_task(child).state, TaskState.BLOCKED.value)

        self.db.set_state(parent, TaskState.COMPLETED)
        self.db.refresh_dependency_states()
        self.assertEqual(self.db.get_task(child).state, TaskState.READY.value)

    def test_never_dispatches_more_than_ten_inflight(self):
        for index in range(15):
            self.db.add_task(f"task-{index}", "p1", "relax", self.temp.name)
        queue = SubmissionQueue(self.db, max_inflight=10)
        first = queue.dispatch_once(lambda task: f"job-{task.name}", server_active_count=0)
        second = queue.dispatch_once(lambda task: "unexpected", server_active_count=10)
        self.assertEqual(first.submitted, 10)
        self.assertEqual(second.submitted, 0)
        self.assertEqual(self.db.count_inflight(), 10)

    def test_concurrent_dispatchers_share_capacity(self):
        for server_active, expected in ((0, 10), (9, 1)):
            with self.subTest(server_active=server_active):
                db = TaskDatabase(Path(self.temp.name) / f"concurrent-{server_active}.sqlite3")
                for index in range(25):
                    db.add_task(
                        f"task-{index}", "p1", "vasp:relax", self.temp.name,
                        state=TaskState.READY.value,
                    )
                db.add_task(
                    "local", "p1", "local:charge_prepare", self.temp.name,
                    state=TaskState.SUBMITTING.value,
                )
                barrier = threading.Barrier(2)
                count_inflight = db.count_inflight

                def simultaneous_snapshot():
                    count = count_inflight()
                    barrier.wait(timeout=10)
                    return count

                def dispatch():
                    return SubmissionQueue(db, max_inflight=10).dispatch_once(
                        lambda task: f"job-{task.id}", server_active_count=server_active
                    )

                with patch.object(db, "count_inflight", side_effect=simultaneous_snapshot):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        futures = [executor.submit(dispatch) for _ in range(2)]
                        results = [future.result(timeout=20) for future in futures]
                self.assertEqual(sum(result.submitted for result in results), expected)
                self.assertEqual(db.count_inflight(), expected)
                self.assertEqual(len({task for result in results for task in result.task_ids}), expected)

    def test_submission_retries_then_fails(self):
        task_id = self.db.add_task(
            "bad",
            "p1",
            "relax",
            self.temp.name,
            max_retries=1,
        )
        queue = SubmissionQueue(self.db, max_inflight=10)

        def fail(_task):
            raise RuntimeError("network")

        queue.dispatch_once(fail)
        self.assertEqual(self.db.get_task(task_id).state, TaskState.RETRY_WAIT.value)
        queue.dispatch_once(fail)
        self.assertEqual(self.db.get_task(task_id).state, TaskState.FAILED.value)

    def test_local_tasks_are_not_claimed_for_slurm(self):
        local_id = self.db.add_task(
            "prepare",
            "p1",
            "local:charge_prepare",
            Path(self.temp.name) / "prepare",
            state=TaskState.READY.value,
        )
        remote_id = self.db.add_task(
            "relax",
            "p1",
            "vasp:relax",
            Path(self.temp.name) / "relax",
            state=TaskState.READY.value,
        )
        remote = self.db.claim_ready_tasks(10)
        self.assertEqual([task.id for task in remote], [remote_id])
        local = self.db.claim_ready_local_tasks(2)
        self.assertEqual([task.id for task in local], [local_id])

    def test_agent_can_find_task_by_local_path_with_compatibility_name(self):
        local_path = Path(self.temp.name) / "agent-task"
        task_id = self.db.add_task(
            "agent-task",
            "p1",
            "vasp:relax",
            local_path,
        )
        canonical = self.db.find_task_by_local_path(local_path)
        compatible = self.db.find_by_local_path(local_path)
        self.assertEqual(canonical.id, task_id)
        self.assertEqual(compatible.id, task_id)

    def test_fingerprint_deduplicates_tasks(self):
        first = self.db.add_task(
            "same-stage",
            "p1",
            "vasp:relax",
            Path(self.temp.name) / "same-stage",
            workflow_id="workflow-1",
            fingerprint="workflow-1:relax",
        )
        second = self.db.add_task(
            "same-stage-again",
            "p1",
            "vasp:relax",
            Path(self.temp.name) / "same-stage",
            workflow_id="workflow-1",
            fingerprint="workflow-1:relax",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.list_tasks()), 1)
        self.assertEqual(
            self.db.find_task_by_fingerprint("workflow-1:relax").id,
            first,
        )

    def test_recovers_stale_claims_without_blind_remote_resubmit(self):
        validation = self.db.add_task(
            "validation",
            "p1",
            "vasp:relax",
            self.temp.name,
            state=TaskState.VALIDATING.value,
        )
        submitting = self.db.add_task(
            "submitting",
            "p1",
            "vasp:relax",
            self.temp.name,
            state=TaskState.SUBMITTING.value,
        )
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(
            timespec="seconds"
        )
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE tasks SET updated_at = ? WHERE id IN (?, ?)",
                (old, validation, submitting),
            )
        recovered = self.db.recover_stale_claims(60)
        self.assertEqual(set(recovered), {validation, submitting})
        self.assertEqual(self.db.get_task(validation).state, TaskState.READY.value)
        self.assertEqual(
            self.db.get_task(submitting).state,
            TaskState.UNKNOWN_REMOTE_STATE.value,
        )


if __name__ == "__main__":
    unittest.main()
