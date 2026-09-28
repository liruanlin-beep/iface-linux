from dataclasses import dataclass

from app.core.task_database import TaskDatabase, TaskState
from app.core.reliable_submission import SubmissionOutcomeUnknown
from app.core.slurm_automation import AutomationPolicy, decide_slurm_action


@dataclass
class DispatchResult:
    available_slots: int
    claimed: int
    submitted: int
    failed: int
    task_ids: tuple
    recovered_stale_claims: int = 0


class SubmissionQueue:
    """Server-aware local queue that never floods Slurm with every candidate."""

    def __init__(
        self,
        database=None,
        max_inflight=10,
        automation_policy=None,
        stale_claim_seconds=900,
    ):
        self.database = database or TaskDatabase()
        self.max_inflight = max(1, int(max_inflight))
        self.stale_claim_seconds = max(60, int(stale_claim_seconds))
        self.automation_policy = (
            automation_policy
            if isinstance(automation_policy, AutomationPolicy)
            else AutomationPolicy.from_mapping(automation_policy)
        )

    def available_slots(self, server_active_count=0, known_active_count=None):
        server_active_count = max(0, int(server_active_count or 0))
        if known_active_count is None:
            known_active_count = self.database.count_inflight()
        # Server state may include jobs submitted outside iface. Use the larger
        # count rather than adding both and double-counting iface jobs.
        occupied = max(server_active_count, known_active_count)
        return max(0, self.max_inflight - occupied)

    def dispatch_once(self, submitter, server_active_count=0):
        recovered = self.database.recover_stale_claims(
            self.stale_claim_seconds
        )
        self.database.refresh_dependency_states()
        known_active_count = self.database.count_inflight()
        slots = self.available_slots(server_active_count, known_active_count)
        # Reserve against the same snapshot inside the SQLite write transaction.
        # Another dispatcher may have consumed these slots since the read above.
        tasks = self.database.claim_ready_tasks(
            slots, inflight_limit=known_active_count + slots
        )
        submitted = 0
        failed = 0
        for task in tasks:
            try:
                job_id = str(submitter(task)).strip()
                if not job_id:
                    raise RuntimeError('sbatch returned no JobID')
                self.database.update_task(
                    task.id,
                    slurm_job_id=job_id,
                    attempts=task.attempts + 1,
                )
                self.database.set_state(
                    task.id,
                    TaskState.PENDING,
                    f'Submitted to Slurm, JobID={job_id}',
                )
                submitted += 1
            except SubmissionOutcomeUnknown as exc:
                attempts = task.attempts + 1
                self.database.update_task(task.id, attempts=attempts)
                self.database.set_state(
                    task.id,
                    TaskState.UNKNOWN_REMOTE_STATE,
                    'Submission result unknown; reconcile with squeue/sacct before retrying',
                    error=str(exc),
                )
                failed += 1
            except Exception as exc:
                attempts = task.attempts + 1
                self.database.update_task(task.id, attempts=attempts)
                if attempts <= task.max_retries:
                    self.database.set_state(
                        task.id,
                        TaskState.RETRY_WAIT,
                        f'Submission failed; waiting to retry ({attempts}/{task.max_retries}）',
                        error=str(exc),
                    )
                else:
                    self.database.set_state(
                        task.id,
                        TaskState.FAILED,
                        'Submission failed and the retry limit was reached',
                        error=str(exc),
                    )
                failed += 1
        return DispatchResult(
            available_slots=slots,
            claimed=len(tasks),
            submitted=submitted,
            failed=failed,
            task_ids=tuple(task.id for task in tasks),
            recovered_stale_claims=len(recovered),
        )

    def update_slurm_state(self, task_id, slurm_state):
        normalized = str(slurm_state or "").strip().upper().split("+", 1)[0]
        task = self.database.get_task(task_id)
        decision = decide_slurm_action(
            normalized,
            task.attempts if task else 0,
            self.automation_policy,
        )
        if decision.action == "retry" and task:
            self.database.update_task(task_id, slurm_job_id="")
            self.database.set_state(
                task_id,
                TaskState.RETRY_WAIT,
                f'Automatic recovery: {decision.reason}',
            )
            self.database.add_event(
                task_id,
                "automation",
                "INFO",
                decision.reason,
                {"slurm_state": normalized, "action": "retry"},
            )
            return TaskState.RETRY_WAIT.value
        mapping = {
            "PENDING": TaskState.PENDING,
            "CONFIGURING": TaskState.PENDING,
            "RUNNING": TaskState.RUNNING,
            "COMPLETING": TaskState.COMPLETING,
            "COMPLETED": TaskState.COMPLETED,
            "FAILED": TaskState.FAILED,
            "TIMEOUT": TaskState.FAILED,
            "NODE_FAIL": TaskState.FAILED,
            "OUT_OF_MEMORY": TaskState.FAILED,
            "CANCELLED": TaskState.CANCELLED,
        }
        state = mapping.get(normalized)
        if state:
            self.database.set_state(task_id, state, f'Slurm state: {normalized}')
            if decision.action == "diagnose":
                self.database.add_event(
                    task_id,
                    "automation",
                    "WARNING",
                    decision.reason,
                    {
                        "slurm_state": normalized,
                        "action": "diagnose",
                        "requires_approval": decision.requires_approval,
                    },
                )
        return state.value if state else ""
