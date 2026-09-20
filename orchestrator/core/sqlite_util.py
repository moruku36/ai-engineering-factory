"""Shared SQLite connection helpers for the control plane's transactional stores."""

import sqlite3
from pathlib import Path


def connect_wal(
    db_path: Path | str,
    *,
    timeout: float = 30.0,
    busy_timeout_ms: int | None = 30000,
) -> sqlite3.Connection:
    """Open a WAL-mode, autocommit (isolation_level=None) SQLite connection.

    Used by stores that manage their own explicit BEGIN/COMMIT/ROLLBACK rather than
    relying on the sqlite3 module's implicit transaction handling.
    """
    conn = sqlite3.connect(str(db_path), timeout=timeout, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    if busy_timeout_ms is not None:
        conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms};")
    return conn


def connect_exclusive(db_path: Path | str, *, timeout: float = 10.0) -> sqlite3.Connection:
    """Open an EXCLUSIVE-isolation SQLite connection with row access by column name.

    Used by the runtime lease manager, which needs the whole-file EXCLUSIVE lock
    (not just WAL's row-level concurrency) to make acquire/heartbeat/release atomic
    across separate worker processes.
    """
    conn = sqlite3.connect(str(db_path), timeout=timeout, isolation_level="EXCLUSIVE")
    conn.row_factory = sqlite3.Row
    return conn
