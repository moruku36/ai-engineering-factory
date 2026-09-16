"""State lifecycle engine and single-writer state ledger with cross-process CAS revision."""

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from orchestrator.core.schema import validate_against_schema


class TaskStatus(str, Enum):
    PROPOSED = "PROPOSED"
    READY = "READY"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    REVIEW = "REVIEW"
    READY_FOR_MERGE = "READY_FOR_MERGE"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    CANCELLED = "CANCELLED"


# Allowed state transitions: from_status -> set of allowed to_statuses
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PROPOSED: {TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.VALIDATING, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.VALIDATING: {TaskStatus.REVIEW, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.REVIEW: {
        TaskStatus.READY_FOR_MERGE,
        TaskStatus.READY,  # Changes requested -> back to READY
        TaskStatus.FAILED,
        TaskStatus.NEEDS_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.READY_FOR_MERGE: {
        TaskStatus.DONE,  # Remote merge verified
        TaskStatus.FAILED,
        TaskStatus.NEEDS_HUMAN,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {
        TaskStatus.READY,  # Retry within budget
        TaskStatus.CANCELLED,
    },
    TaskStatus.BLOCKED: {
        TaskStatus.PROPOSED,  # Preflight restart
        TaskStatus.CANCELLED,
    },
    TaskStatus.NEEDS_HUMAN: {
        TaskStatus.PROPOSED,  # Preflight restart
        TaskStatus.READY,
        TaskStatus.CANCELLED,
    },
    TaskStatus.DONE: set(),  # Terminal state
    TaskStatus.CANCELLED: set(),  # Terminal state
}

TERMINAL_STATES = {TaskStatus.DONE, TaskStatus.CANCELLED}
MAX_RETRY_ATTEMPTS = 3


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


class CASConflictError(Exception):
    """Raised when revision numbers do not match during write."""


class SingleWriterLockError(Exception):
    """Raised when another writer holds the exclusive state lock."""


class StateLedger:
    """Thread-safe and multi-process transactional state ledger managing task transitions with CAS."""

    _global_thread_lock = threading.Lock()

    def __init__(self, state_dir: Path | str | None = None):
        if state_dir is None:
            self.state_dir = Path(__file__).resolve().parent.parent.parent / "state" / "tasks"
        else:
            self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "ledger.sqlite"
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_states (
                    task_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _get_task_file(self, task_id: str) -> Path:
        return self.state_dir / f"{task_id}.json"

    def initialize_task(
        self,
        task_id: str,
        spec_digest: str,
        policy_digest: str,
        base_sha: str | None = None,
    ) -> dict[str, Any]:
        with self._global_thread_lock:
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE;")
                cursor = conn.execute("SELECT task_id FROM task_states WHERE task_id = ?;", (task_id,))
                if cursor.fetchone():
                    conn.execute("ROLLBACK;")
                    raise StateTransitionError(f"Task {task_id} already exists in ledger")

                now = datetime.now(UTC).isoformat()
                state_data: dict[str, Any] = {
                    "task_id": task_id,
                    "revision": 0,
                    "status": TaskStatus.PROPOSED.value,
                    "spec_digest": spec_digest,
                    "policy_digest": policy_digest,
                    "base_sha": base_sha,
                    "candidate_sha": None,
                    "attempt": 0,
                    "updated_at": now,
                    "history": [
                        {
                            "from_status": "NONE",
                            "to_status": TaskStatus.PROPOSED.value,
                            "revision": 0,
                            "timestamp": now,
                            "reason": "Task initialized",
                        }
                    ],
                }
                validate_against_schema(state_data, "state.schema.json")

                conn.execute(
                    """
                    INSERT INTO task_states (task_id, revision, status, attempt, data, updated_at)
                    VALUES (?, 0, ?, 0, ?, ?);
                    """,
                    (task_id, TaskStatus.PROPOSED.value, json.dumps(state_data), now),
                )
                conn.execute("COMMIT;")

            # Write JSON file
            task_file = self._get_task_file(task_id)
            self._write_state(task_file, state_data)
            return state_data

    def get_state(self, task_id: str) -> dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT data FROM task_states WHERE task_id = ?;", (task_id,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])

        task_file = self._get_task_file(task_id)
        if not task_file.exists():
            raise FileNotFoundError(f"No state record found for task {task_id}")
        with open(task_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def transition(
        self,
        task_id: str,
        expected_revision: int,
        to_status: TaskStatus,
        reason: str,
        candidate_sha: str | None = None,
        base_sha: str | None = None,
    ) -> dict[str, Any]:
        """Atomically transition task state with cross-process CAS check."""
        with self._global_thread_lock:
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE;")
                cursor = conn.execute(
                    "SELECT revision, status, attempt, data FROM task_states WHERE task_id = ?;",
                    (task_id,),
                )
                row = cursor.fetchone()
                if not row:
                    task_file = self._get_task_file(task_id)
                    if not task_file.exists():
                        conn.execute("ROLLBACK;")
                        raise FileNotFoundError(f"No state record found for task {task_id}")
                    with open(task_file, "r", encoding="utf-8") as f:
                        current_state = json.load(f)
                    actual_revision = current_state["revision"]
                    current_status = TaskStatus(current_state["status"])
                    attempt = current_state.get("attempt", 0)
                else:
                    actual_revision, cur_status_str, attempt, data_json = row
                    current_status = TaskStatus(cur_status_str)
                    current_state = json.loads(data_json)

                if actual_revision != expected_revision:
                    conn.execute("ROLLBACK;")
                    raise CASConflictError(
                        f"CAS conflict for task {task_id}: expected revision {expected_revision}, found {actual_revision}"
                    )

                if current_status in TERMINAL_STATES:
                    conn.execute("ROLLBACK;")
                    raise StateTransitionError(f"Cannot transition from terminal state {current_status.value}")

                allowed = ALLOWED_TRANSITIONS.get(current_status, set())
                if to_status not in allowed:
                    conn.execute("ROLLBACK;")
                    raise StateTransitionError(
                        f"Invalid transition for task {task_id}: {current_status.value} -> {to_status.value}"
                    )

                # Handle retry budget check
                if current_status == TaskStatus.FAILED and to_status == TaskStatus.READY:
                    if attempt >= MAX_RETRY_ATTEMPTS:
                        conn.execute("ROLLBACK;")
                        raise StateTransitionError(
                            f"Cannot retry task {task_id}: exceeded max attempts ({MAX_RETRY_ATTEMPTS})"
                        )
                    attempt += 1

                if current_status == TaskStatus.READY and to_status == TaskStatus.RUNNING and attempt == 0:
                    attempt = 1

                # Invalidate candidate evidence if base_sha or spec changed
                final_candidate_sha = candidate_sha if candidate_sha is not None else current_state.get("candidate_sha")
                final_base_sha = base_sha if base_sha is not None else current_state.get("base_sha")

                if base_sha is not None and base_sha != current_state.get("base_sha"):
                    final_candidate_sha = None

                now = datetime.now(UTC).isoformat()
                new_revision = actual_revision + 1
                new_state: dict[str, Any] = dict(current_state)
                new_state["revision"] = new_revision
                new_state["status"] = to_status.value
                new_state["candidate_sha"] = final_candidate_sha
                new_state["base_sha"] = final_base_sha
                new_state["attempt"] = attempt
                new_state["updated_at"] = now
                new_state["history"] = current_state.get("history", []) + [
                    {
                        "from_status": current_status.value,
                        "to_status": to_status.value,
                        "revision": new_revision,
                        "timestamp": now,
                        "reason": reason,
                    }
                ]

                validate_against_schema(new_state, "state.schema.json")

                cursor = conn.execute(
                    """
                    UPDATE task_states
                    SET revision = ?, status = ?, attempt = ?, data = ?, updated_at = ?
                    WHERE task_id = ? AND revision = ?;
                    """,
                    (new_revision, to_status.value, attempt, json.dumps(new_state), now, task_id, actual_revision),
                )
                if cursor.rowcount == 0:
                    conn.execute("ROLLBACK;")
                    raise CASConflictError(f"CAS conflict during commit for task {task_id}")

                conn.execute("COMMIT;")

            # Write JSON file
            task_file = self._get_task_file(task_id)
            self._write_state(task_file, new_state)
            return new_state

    def _write_state(self, task_file: Path, state_data: dict[str, Any]) -> None:
        temp_file = task_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)
        os.replace(temp_file, task_file)
