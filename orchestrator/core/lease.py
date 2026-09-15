"""SQLite-backed transactional runtime leases with heartbeat, epoch, and process liveness tracking."""

import os
import ctypes
import sqlite3
import time
from pathlib import Path


class LeaseAcquisitionError(Exception):
    """Raised when a task lease cannot be acquired due to an active valid lease."""


class LeaseExpiredError(Exception):
    """Raised when operating on a lease that has expired."""


def is_process_alive(pid: int) -> bool:
    """Check if process with given PID is still running on the host OS."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) terminates processes on Windows. Query only.
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
        if not handle:
            # Access denied/unknown errors must not authorize reassignment.
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no PID
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True  # Unknown/access denied is not proof that the process exited.


class RuntimeLeaseManager:
    """Manages exclusive execution leases for tasks using transactional SQLite in runtime-root."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            runtime_dir = Path(__file__).resolve().parent.parent.parent.parent / "runtime-root"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = runtime_dir / "leases.sqlite"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level="EXCLUSIVE")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leases (
                    task_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL,
                    heartbeat_ts REAL NOT NULL,
                    pid INTEGER NOT NULL,
                    acquired_at REAL NOT NULL,
                    timeout_seconds REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS lease_epochs (task_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL)"
            )
            conn.commit()

    def acquire_lease(
        self,
        task_id: str,
        worker_id: str,
        pid: int,
        timeout_seconds: float = 60.0,
    ) -> int:
        """Acquire an exclusive lease for task_id. Returns epoch on success."""
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leases WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()

            if row is not None:
                # Existing lease found
                active_pid = row["pid"]
                last_hb = row["heartbeat_ts"]
                lease_timeout = row["timeout_seconds"]
                is_stale = (now - last_hb) > lease_timeout

                # Check if old process is still alive
                if is_process_alive(active_pid) and not is_stale:
                    raise LeaseAcquisitionError(
                        f"Task '{task_id}' is already leased to worker '{row['worker_id']}' (PID {active_pid})"
                    )

                # If process is still alive even though stale, do NOT reassign before old process termination
                if is_process_alive(active_pid):
                    raise LeaseAcquisitionError(
                        f"Cannot reassign lease for task '{task_id}': old process PID {active_pid} is still alive"
                    )

                # Old process confirmed dead or lease expired: increment epoch
                new_epoch = row["epoch"] + 1
                cursor.execute(
                    """
                    UPDATE leases
                    SET worker_id = ?, epoch = ?, heartbeat_ts = ?, pid = ?, acquired_at = ?, timeout_seconds = ?
                    WHERE task_id = ?
                    """,
                    (worker_id, new_epoch, now, pid, now, timeout_seconds, task_id),
                )
            else:
                prior = cursor.execute(
                    "SELECT epoch FROM lease_epochs WHERE task_id = ?", (task_id,)
                ).fetchone()
                new_epoch = prior["epoch"] + 1 if prior else 1
                cursor.execute(
                    """
                    INSERT INTO leases (task_id, worker_id, epoch, heartbeat_ts, pid, acquired_at, timeout_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, worker_id, new_epoch, now, pid, now, timeout_seconds),
                )

            cursor.execute(
                "INSERT OR REPLACE INTO lease_epochs (task_id, epoch) VALUES (?, ?)",
                (task_id, new_epoch),
            )
            conn.commit()
            return new_epoch

    def heartbeat(self, task_id: str, worker_id: str, epoch: int) -> None:
        """Update lease heartbeat timestamp."""
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT epoch, worker_id, heartbeat_ts, timeout_seconds FROM leases WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            if row is None or row["epoch"] != epoch or row["worker_id"] != worker_id:
                raise LeaseExpiredError(f"Heartbeat rejected for task {task_id}: lease lost or epoch mismatch")
            if now - row["heartbeat_ts"] > row["timeout_seconds"]:
                raise LeaseExpiredError(f"Heartbeat rejected for task {task_id}: lease expired")

            cursor.execute(
                "UPDATE leases SET heartbeat_ts = ? WHERE task_id = ?",
                (now, task_id),
            )
            conn.commit()

    def release_lease(self, task_id: str, worker_id: str, epoch: int) -> None:
        """Voluntarily release a lease upon task completion."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM leases WHERE task_id = ? AND worker_id = ? AND epoch = ?",
                (task_id, worker_id, epoch),
            )
            conn.commit()

    def get_active_lease(self, task_id: str) -> dict | None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leases WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None


class TaskRuntimeEnvironment:
    """Represents an isolated filesystem and resource workspace in runtime-root for a task attempt."""

    def __init__(
        self,
        runtime_root: Path,
        task_id: str,
        attempt: int,
        base_port: int = 18000,
    ):
        self.task_id = task_id
        self.attempt = attempt
        self.task_root = runtime_root / f"runs_{task_id}_attempt_{attempt}"
        self.tmp_dir = self.task_root / "tmp"
        self.cache_dir = self.task_root / "cache"
        self.test_db_dir = self.task_root / "test_db"
        self.allocated_port = base_port + (hash(task_id) % 1000)

    def provision(self) -> None:
        """Create isolated directories for task execution."""
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.test_db_dir.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        """Teardown task-specific temporary and cache resources."""
        import shutil
        if self.task_root.exists():
            shutil.rmtree(self.task_root, ignore_errors=True)

    def get_isolated_env(self) -> dict[str, str]:
        """Return environment variables directing temp and cache to this task's isolated directories."""
        return {
            "FACTORY_TASK_ID": self.task_id,
            "FACTORY_ATTEMPT": str(self.attempt),
            "TMP": str(self.tmp_dir),
            "TEMP": str(self.tmp_dir),
            "FACTORY_CACHE_DIR": str(self.cache_dir),
            "FACTORY_TEST_DB_PATH": str(self.test_db_dir / "test.db"),
            "FACTORY_ALLOCATED_PORT": str(self.allocated_port),
        }

