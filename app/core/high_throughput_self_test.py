"""Local orchestration stress test used by the UI and automated tests."""

import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.submission_queue import SubmissionQueue
from app.core.task_database import TaskDatabase, TaskState


@dataclass
class HighThroughputSelfTestReport:
    passed: bool
    workflows: int
    tasks: int
    submitted: int
    max_inflight_observed: int
    configured_max_inflight: int
    duplicate_tasks_prevented: int
    concurrent_claims_unique: bool
    stale_claims_recovered: int
    elapsed_seconds: float
    checks: tuple

    def to_dict(self):
        data = asdict(self)
        data["checks"] = list(self.checks)
        return data


def run_high_throughput_self_test(workflows=48, max_inflight=8):
    """Exercise deduplication, DAG ordering, bounded dispatch and crash recovery.

    This deliberately does not invoke VASP or a real scheduler. It validates the
    local high-throughput control plane without touching the user's task ledger.
    """
    started = time.perf_counter()
    workflows = max(4, int(workflows))
    max_inflight = max(2, int(max_inflight))
    checks = []
    with tempfile.TemporaryDirectory(prefix="iface-ht-selftest-") as temporary:
        root = Path(temporary)
        database = TaskDatabase(root / "selftest.sqlite3")
        duplicate_tasks_prevented = 0
        stage_ids = []
        for index in range(workflows):
            workflow_id = f"selftest-{index:04d}"
            relax = database.add_task(
                f"w{index:04d}-relax",
                "iface-selftest",
                "vasp:relax",
                root / workflow_id / "01_relax",
                workflow_id=workflow_id,
                fingerprint=f"{workflow_id}:relax",
            )
            duplicate = database.add_task(
                f"w{index:04d}-relax-duplicate",
                "iface-selftest",
                "vasp:relax",
                root / workflow_id / "01_relax",
                workflow_id=workflow_id,
                fingerprint=f"{workflow_id}:relax",
            )
            duplicate_tasks_prevented += int(duplicate == relax)
            static = database.add_task(
                f"w{index:04d}-static",
                "iface-selftest",
                "vasp:static",
                root / workflow_id / "02_static",
                dependencies=[relax],
                workflow_id=workflow_id,
                fingerprint=f"{workflow_id}:static",
            )
            pdos = database.add_task(
                f"w{index:04d}-pdos",
                "iface-selftest",
                "vasp:pdos",
                root / workflow_id / "03_pdos",
                dependencies=[static],
                workflow_id=workflow_id,
                fingerprint=f"{workflow_id}:pdos",
            )
            stage_ids.extend((relax, static, pdos))

        queue = SubmissionQueue(
            database,
            max_inflight=max_inflight,
            stale_claim_seconds=3600,
        )
        submitted_order = []
        dependency_violation = []

        def submitter(task):
            for dependency in task.dependencies:
                if database.get_task(dependency).state != TaskState.COMPLETED.value:
                    dependency_violation.append((task.id, dependency))
            submitted_order.append(task.id)
            return f"dry-{len(submitted_order):06d}"

        max_observed = 0
        for _wave in range(workflows * 4 + 10):
            queue.dispatch_once(submitter, server_active_count=0)
            max_observed = max(max_observed, database.count_inflight())
            for task in database.list_tasks(states=[TaskState.PENDING]):
                database.set_state(task.id, TaskState.COMPLETED, 'Self-test simulation complete')
            database.refresh_dependency_states()
            if all(
                database.get_task(task_id).state == TaskState.COMPLETED.value
                for task_id in stage_ids
            ):
                break

        completed_chain = all(
            database.get_task(task_id).state == TaskState.COMPLETED.value
            for task_id in stage_ids
        )
        bounded = max_observed <= max_inflight
        deduplicated = duplicate_tasks_prevented == workflows
        ordered = not dependency_violation
        checks.extend(
            (
                f"Dependency chain complete: {('Passed' if completed_chain else 'Failed')}",
                f"Concurrency limit: {('Passed' if bounded else 'Failed')}(peak {max_observed}/{max_inflight}）",
                f"Duplicate tasks blocked: {('Passed' if deduplicated else 'Failed')}（{duplicate_tasks_prevented}/{workflows}）",
                f"Dependency order: {('Passed' if ordered else 'Failed')}",
            )
        )

        claim_ids = []
        for index in range(30):
            task_id = database.add_task(
                f"claim-{index:03d}",
                "iface-selftest-claim",
                "vasp:static",
                root / "claim" / str(index),
                state=TaskState.READY.value,
                fingerprint=f"claim:{index}",
            )
            claim_ids.append(task_id)
        claimed = []
        claim_lock = threading.Lock()

        def claim_worker():
            rows = database.claim_ready_tasks(30)
            with claim_lock:
                claimed.extend(task.id for task in rows)

        threads = [threading.Thread(target=claim_worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        concurrent_unique = len(claimed) == 30 and len(set(claimed)) == 30
        checks += (
            f"Unique concurrent claims: {('Passed' if concurrent_unique else 'Failed')}（{len(set(claimed))}/30）",
        )
        for task_id in claim_ids:
            database.set_state(task_id, TaskState.COMPLETED, 'Concurrent-claim self-test complete')

        stale_ready = database.add_task(
            "stale-validation",
            "iface-selftest-recovery",
            "vasp:static",
            root / "stale-validation",
            state=TaskState.VALIDATING.value,
            fingerprint="stale:validation",
        )
        stale_unknown = database.add_task(
            "stale-submitting",
            "iface-selftest-recovery",
            "vasp:static",
            root / "stale-submitting",
            state=TaskState.SUBMITTING.value,
            fingerprint="stale:submitting",
        )
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(
            timespec="seconds"
        )
        with database.connect() as connection:
            connection.execute(
                "UPDATE tasks SET updated_at = ? WHERE id IN (?, ?)",
                (old, stale_ready, stale_unknown),
            )
        recovered = database.recover_stale_claims(60)
        recovered_ok = (
            set(recovered) == {stale_ready, stale_unknown}
            and database.get_task(stale_ready).state == TaskState.READY.value
            and database.get_task(stale_unknown).state
            == TaskState.UNKNOWN_REMOTE_STATE.value
        )
        checks += (
            f"Interrupted-run recovery: {('Passed' if recovered_ok else 'Failed')}（{len(recovered)}/2）",
        )

        passed = all(
            (
                completed_chain,
                bounded,
                deduplicated,
                ordered,
                concurrent_unique,
                recovered_ok,
            )
        )
        total_tasks = database.summarize()["total"]

    return HighThroughputSelfTestReport(
        passed=passed,
        workflows=workflows,
        tasks=total_tasks,
        submitted=len(submitted_order),
        max_inflight_observed=max_observed,
        configured_max_inflight=max_inflight,
        duplicate_tasks_prevented=duplicate_tasks_prevented,
        concurrent_claims_unique=concurrent_unique,
        stale_claims_recovered=len(recovered),
        elapsed_seconds=round(time.perf_counter() - started, 3),
        checks=tuple(checks),
    )
