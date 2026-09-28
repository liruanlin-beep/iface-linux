import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from app.core.paths import DATABASE_DIR, ensure_dirs


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskState(str, Enum):
    LOCAL_WAITING = "LOCAL_WAITING"
    BLOCKED = "BLOCKED"
    READY = "READY"
    VALIDATING = "VALIDATING"
    UPLOADING = "UPLOADING"
    SUBMITTING = "SUBMITTING"
    UNKNOWN_REMOTE_STATE = "UNKNOWN_REMOTE_STATE"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    RETRY_WAIT = "RETRY_WAIT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


INFLIGHT_STATES = {
    TaskState.VALIDATING.value,
    TaskState.UPLOADING.value,
    TaskState.SUBMITTING.value,
    TaskState.UNKNOWN_REMOTE_STATE.value,
    TaskState.PENDING.value,
    TaskState.RUNNING.value,
    TaskState.COMPLETING.value,
}

TERMINAL_STATES = {
    TaskState.COMPLETED.value,
    TaskState.FAILED.value,
    TaskState.CANCELLED.value,
}


@dataclass
class TaskRecord:
    id: str
    name: str
    project_id: str
    task_type: str
    state: str
    local_path: str
    remote_path: str = ""
    slurm_job_id: str = ""
    priority: int = 100
    dependencies: tuple = ()
    config: dict = None
    attempts: int = 0
    max_retries: int = 3
    created_at: str = ""
    updated_at: str = ""
    submitted_at: str = ""
    completed_at: str = ""
    last_error: str = ""
    workflow_id: str = ""
    fingerprint: str = ""

    def to_dict(self):
        data = asdict(self)
        data["dependencies"] = list(self.dependencies)
        data["config"] = self.config or {}
        return data


class TaskDatabase:
    """Durable SQLite ledger for high-throughput and Slurm task state."""

    def __init__(self, path=None):
        ensure_dirs()
        self.path = Path(path or DATABASE_DIR / "tasks.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    remote_path TEXT NOT NULL DEFAULT '',
                    slurm_job_id TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 100,
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    submitted_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    workflow_id TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_state_priority
                    ON tasks(state, priority, created_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_slurm_job
                    ON tasks(slurm_job_id);

                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS task_progress (
                    task_id TEXT PRIMARY KEY,
                    ionic_step INTEGER NOT NULL DEFAULT 0,
                    max_ionic_steps INTEGER NOT NULL DEFAULT 0,
                    electronic_step INTEGER NOT NULL DEFAULT 0,
                    max_electronic_steps INTEGER NOT NULL DEFAULT 0,
                    energy_ev REAL,
                    delta_e_ev REAL,
                    rms REAL,
                    max_force_ev_a REAL,
                    electronic_converged INTEGER NOT NULL DEFAULT 0,
                    ionic_converged INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "workflow_id" not in columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN workflow_id TEXT NOT NULL DEFAULT ''"
                )
            if "fingerprint" not in columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_workflow ON tasks(workflow_id)"
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_fingerprint_unique
                ON tasks(fingerprint) WHERE fingerprint <> ''
                """
            )

    def add_task(
        self,
        name,
        project_id,
        task_type,
        local_path,
        remote_path="",
        priority=100,
        dependencies=None,
        config=None,
        max_retries=3,
        state=TaskState.LOCAL_WAITING.value,
        task_id=None,
        workflow_id="",
        fingerprint="",
    ):
        task_id = task_id or uuid.uuid4().hex
        now = utc_now()
        dependencies = tuple(dependencies or ())
        workflow_id = str(workflow_id or "")
        fingerprint = str(fingerprint or "")
        with self.connect() as connection:
            if fingerprint:
                existing = connection.execute(
                    "SELECT id FROM tasks WHERE fingerprint = ?", (fingerprint,)
                ).fetchone()
                if existing:
                    return str(existing["id"])
            try:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        id, name, project_id, task_type, state, local_path, remote_path,
                        priority, dependencies_json, config_json, max_retries,
                        created_at, updated_at, workflow_id, fingerprint
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        str(name).strip(),
                        str(project_id).strip(),
                        str(task_type).strip(),
                        state,
                        str(Path(local_path)),
                        str(remote_path),
                        int(priority),
                        json.dumps(dependencies, ensure_ascii=False),
                        json.dumps(config or {}, ensure_ascii=False),
                        max(0, int(max_retries)),
                        now,
                        now,
                        workflow_id,
                        fingerprint,
                    ),
                )
            except sqlite3.IntegrityError:
                if not fingerprint:
                    raise
                existing = connection.execute(
                    "SELECT id FROM tasks WHERE fingerprint = ?", (fingerprint,)
                ).fetchone()
                if not existing:
                    raise
                return str(existing["id"])
        self.add_event(task_id, "created", "INFO", f'Task created: {name}')
        return task_id

    def get_task(self, task_id):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def list_tasks(self, states=None, project_id=None):
        clauses = []
        values = []
        if states:
            states = [state.value if isinstance(state, TaskState) else str(state) for state in states]
            clauses.append("state IN (" + ",".join("?" for _ in states) + ")")
            values.extend(states)
        if project_id:
            clauses.append("project_id = ?")
            values.append(project_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = "SELECT * FROM tasks" + where + " ORDER BY priority ASC, created_at ASC"
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._row_to_record(row) for row in rows]

    def find_task_by_local_path(self, local_path):
        normalized = str(Path(local_path))
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE local_path = ? ORDER BY created_at DESC LIMIT 1",
                (normalized,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def find_by_local_path(self, local_path):
        """Backward-compatible name used by the workspace Agent context."""
        return self.find_task_by_local_path(local_path)

    def find_task_by_fingerprint(self, fingerprint):
        fingerprint = str(fingerprint or "")
        if not fingerprint:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def count_inflight(self):
        placeholders = ",".join("?" for _ in INFLIGHT_STATES)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total FROM tasks
                WHERE state IN ({placeholders}) AND task_type NOT LIKE 'local:%'
                """,
                tuple(INFLIGHT_STATES),
            ).fetchone()
        return int(row["total"])

    def update_task(self, task_id, **changes):
        allowed = {
            "name", "state", "remote_path", "slurm_job_id", "priority", "attempts",
            "max_retries", "submitted_at", "completed_at", "last_error",
        }
        updates = {key: value for key, value in changes.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = utc_now()
        columns = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE tasks SET {columns} WHERE id = ?",
                [*updates.values(), task_id],
            )

    def set_state(self, task_id, state, message="", error=""):
        state = state.value if isinstance(state, TaskState) else str(state)
        changes = {"state": state, "last_error": str(error or "")}
        if state == TaskState.PENDING.value:
            changes["submitted_at"] = utc_now()
        if state in TERMINAL_STATES:
            changes["completed_at"] = utc_now()
        self.update_task(task_id, **changes)
        self.add_event(
            task_id,
            "state",
            "ERROR" if state == TaskState.FAILED.value else "INFO",
            message or f'Task state changed to {state}',
            {"state": state, "error": str(error or "")},
        )

    def refresh_dependency_states(self):
        tasks = self.list_tasks(
            states=[
                TaskState.LOCAL_WAITING,
                TaskState.BLOCKED,
                TaskState.RETRY_WAIT,
            ]
        )
        states = {task.id: task.state for task in self.list_tasks()}
        changed = 0
        for task in tasks:
            dependency_states = [states.get(dep) for dep in task.dependencies]
            if any(state in {TaskState.FAILED.value, TaskState.CANCELLED.value} for state in dependency_states):
                desired = TaskState.BLOCKED.value
            elif all(state == TaskState.COMPLETED.value for state in dependency_states):
                desired = TaskState.READY.value
            else:
                desired = TaskState.BLOCKED.value
            if task.state != desired:
                self.set_state(task.id, desired, 'Task dependency states recalculated')
                changed += 1
        return changed

    def recover_stale_claims(self, stale_after_seconds=900, now=None):
        """Recover abandoned queue claims after an application interruption.

        A remote task interrupted while SUBMITTING is intentionally moved to
        UNKNOWN_REMOTE_STATE: the scheduler may already have accepted it and a
        blind retry could submit the same calculation twice.
        """
        stale_after_seconds = max(0, int(stale_after_seconds))
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(seconds=stale_after_seconds)
        claim_states = (
            TaskState.VALIDATING.value,
            TaskState.UPLOADING.value,
            TaskState.SUBMITTING.value,
        )
        placeholders = ",".join("?" for _ in claim_states)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE state IN ({placeholders})",
                claim_states,
            ).fetchall()
        recovered = []
        for row in rows:
            try:
                updated = datetime.fromisoformat(row["updated_at"])
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                updated = datetime.min.replace(tzinfo=timezone.utc)
            if updated > cutoff:
                continue
            is_remote_submit = (
                row["state"] == TaskState.SUBMITTING.value
                and not str(row["task_type"]).startswith("local:")
            )
            desired = (
                TaskState.UNKNOWN_REMOTE_STATE
                if is_remote_submit
                else TaskState.READY
            )
            self.set_state(
                row["id"],
                desired,
                (
                    'Detected an interrupted submission; remote reconciliation is required before resubmission'
                    if is_remote_submit
                    else 'Expired task lease detected and returned to the waiting queue'
                ),
            )
            self.add_event(
                row["id"],
                "stale_claim_recovered",
                "WARNING" if is_remote_submit else "INFO",
                'High-throughput queue recovered expired task leases',
                {
                    "previous_state": row["state"],
                    "new_state": desired.value,
                    "stale_after_seconds": stale_after_seconds,
                },
            )
            recovered.append(row["id"])
        return tuple(recovered)

    def summarize(self, project_id=None):
        clauses = " WHERE project_id = ?" if project_id else ""
        values = (str(project_id),) if project_id else ()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT state, COUNT(*) AS total FROM tasks"
                + clauses
                + " GROUP BY state",
                values,
            ).fetchall()
        by_state = {row["state"]: int(row["total"]) for row in rows}
        return {
            "project_id": str(project_id or ""),
            "total": sum(by_state.values()),
            "by_state": by_state,
            "inflight": sum(by_state.get(state, 0) for state in INFLIGHT_STATES),
            "terminal": sum(by_state.get(state, 0) for state in TERMINAL_STATES),
        }

    def claim_ready_tasks(self, limit, inflight_limit=None):
        limit = max(0, int(limit))
        if limit == 0:
            return []
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if inflight_limit is not None:
                placeholders = ",".join("?" for _ in INFLIGHT_STATES)
                occupied = connection.execute(
                    f"SELECT COUNT(*) FROM tasks WHERE state IN ({placeholders}) "
                    "AND task_type NOT LIKE 'local:%'",
                    tuple(INFLIGHT_STATES),
                ).fetchone()[0]
                limit = min(limit, max(0, int(inflight_limit) - occupied))
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE state = ? AND task_type NOT LIKE 'local:%'
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
                """,
                (TaskState.READY.value, limit),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"UPDATE tasks SET state = ?, updated_at = ? WHERE id IN ({placeholders})",
                    (TaskState.VALIDATING.value, now, *ids),
                )
        return [self.get_task(task_id) for task_id in ids]

    def claim_ready_local_tasks(self, limit=2):
        limit = max(0, int(limit))
        if limit == 0:
            return []
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE state = ? AND task_type LIKE 'local:%'
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
                """,
                (TaskState.READY.value, limit),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"UPDATE tasks SET state = ?, updated_at = ? WHERE id IN ({placeholders})",
                    (TaskState.SUBMITTING.value, now, *ids),
                )
        return [self.get_task(task_id) for task_id in ids]

    def add_event(self, task_id, event_type, level, message, payload=None):
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO task_events (
                    task_id, event_type, level, message, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    str(event_type),
                    str(level),
                    str(message),
                    json.dumps(payload or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def list_events(self, task_id, limit=100):
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, level, message, payload_json, created_at
                FROM task_events
                WHERE task_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (task_id, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_progress(self, task_id):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_progress WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row else {}

    def delete_task(self, task_id):
        """Delete only the database record; calculation files are never removed here."""
        with self.connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def update_progress(self, task_id, progress):
        fields = {
            "ionic_step": int(progress.get("ionic_step") or 0),
            "max_ionic_steps": int(progress.get("max_ionic_steps") or 0),
            "electronic_step": int(progress.get("electronic_step") or 0),
            "max_electronic_steps": int(progress.get("max_electronic_steps") or 0),
            "energy_ev": progress.get("energy_ev"),
            "delta_e_ev": progress.get("delta_e_ev"),
            "rms": progress.get("rms"),
            "max_force_ev_a": progress.get("max_force_ev_a"),
            "electronic_converged": int(bool(progress.get("electronic_converged"))),
            "ionic_converged": int(bool(progress.get("ionic_converged"))),
            "updated_at": utc_now(),
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO task_progress (
                    task_id, ionic_step, max_ionic_steps, electronic_step,
                    max_electronic_steps, energy_ev, delta_e_ev, rms,
                    max_force_ev_a, electronic_converged, ionic_converged, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    ionic_step=excluded.ionic_step,
                    max_ionic_steps=excluded.max_ionic_steps,
                    electronic_step=excluded.electronic_step,
                    max_electronic_steps=excluded.max_electronic_steps,
                    energy_ev=excluded.energy_ev,
                    delta_e_ev=excluded.delta_e_ev,
                    rms=excluded.rms,
                    max_force_ev_a=excluded.max_force_ev_a,
                    electronic_converged=excluded.electronic_converged,
                    ionic_converged=excluded.ionic_converged,
                    updated_at=excluded.updated_at
                """,
                (task_id, *fields.values()),
            )

    @staticmethod
    def _row_to_record(row):
        return TaskRecord(
            id=row["id"],
            name=row["name"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            state=row["state"],
            local_path=row["local_path"],
            remote_path=row["remote_path"],
            slurm_job_id=row["slurm_job_id"],
            priority=row["priority"],
            dependencies=tuple(json.loads(row["dependencies_json"] or "[]")),
            config=json.loads(row["config_json"] or "{}"),
            attempts=row["attempts"],
            max_retries=row["max_retries"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            submitted_at=row["submitted_at"],
            completed_at=row["completed_at"],
            last_error=row["last_error"],
            workflow_id=row["workflow_id"] if "workflow_id" in row.keys() else "",
            fingerprint=row["fingerprint"] if "fingerprint" in row.keys() else "",
        )
