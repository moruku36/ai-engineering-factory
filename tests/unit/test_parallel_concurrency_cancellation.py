"""Tests for parallel worker execution, crash recovery, independent cancellation, and artifact isolation."""

import os
import time

import pytest

from orchestrator.core.artifacts import ArtifactCollector
from orchestrator.core.lease import (
    LeaseAcquisitionError,
    LeaseExpiredError,
    RuntimeLeaseManager,
)
from orchestrator.core.scheduler import DAGScheduler
from orchestrator.core.state import StateLedger, TaskStatus


@pytest.fixture
def parallel_setup(tmp_path):
    state_dir = tmp_path / "tasks"
    lease_db = tmp_path / "leases.sqlite"
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()

    ledger = StateLedger(state_dir)
    lease_mgr = RuntimeLeaseManager(db_path=lease_db)

    # Manifests for two independent parallel tasks
    manifests = [
        {"id": "TASK-001", "dependencies": [], "allowed_paths": ["out_a/*"]},
        {"id": "TASK-002", "dependencies": [], "allowed_paths": ["out_b/*"]},
    ]
    scheduler = DAGScheduler(manifests, max_workers=2)

    return {
        "ledger": ledger,
        "lease_mgr": lease_mgr,
        "scheduler": scheduler,
        "artifacts_root": artifacts_root,
        "manifests": manifests,
    }


def test_parallel_dispatch_and_artifact_isolation(parallel_setup):
    setup = parallel_setup
    ledger = setup["ledger"]
    lease_mgr = setup["lease_mgr"]
    scheduler = setup["scheduler"]
    art_root = setup["artifacts_root"]

    # Initialize both tasks
    for tid in ("TASK-001", "TASK-002"):
        ledger.initialize_task(tid, "a" * 64, "b" * 64)
        ledger.transition(tid, 0, TaskStatus.READY, "ready")
        scheduler.update_task_status(tid, TaskStatus.READY)

    # 1. Dispatch both concurrently
    dispatchable = scheduler.get_dispatchable_tasks()
    assert set(dispatchable) == {"TASK-001", "TASK-002"}

    # Acquire distinct leases
    epoch_a = lease_mgr.acquire_lease("TASK-001", "worker-A", pid=os.getpid(), timeout_seconds=30)
    epoch_b = lease_mgr.acquire_lease("TASK-002", "worker-B", pid=os.getpid(), timeout_seconds=30)
    assert epoch_a > 0
    assert epoch_b > 0

    scheduler.dispatch("TASK-001")
    scheduler.dispatch("TASK-002")
    ledger.transition("TASK-001", 1, TaskStatus.RUNNING, "running")
    ledger.transition("TASK-002", 1, TaskStatus.RUNNING, "running")

    # 2. Verify mutual exclusion: duplicate dispatch must be rejected
    with pytest.raises(LeaseAcquisitionError):
        lease_mgr.acquire_lease("TASK-001", "worker-A-duplicate", pid=os.getpid(), timeout_seconds=30)

    # 3. Create isolated artifacts in separate worker dirs
    dir_a = art_root / "worker_a"
    dir_b = art_root / "worker_b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "out_a").mkdir()
    (dir_b / "out_b").mkdir()
    (dir_a / "out_a" / "result_a.txt").write_text("output A", encoding="utf-8")
    (dir_b / "out_b" / "result_b.txt").write_text("output B", encoding="utf-8")

    col_a = ArtifactCollector(allowed_paths=["out_a/*"]).collect(dir_a, art_root / "collected_a")
    col_b = ArtifactCollector(allowed_paths=["out_b/*"]).collect(dir_b, art_root / "collected_b")

    # Verify no artifact cross-contamination
    assert "out_a/result_a.txt" in col_a.collected_files
    assert "out_b/result_b.txt" not in col_a.collected_files
    assert "out_b/result_b.txt" in col_b.collected_files
    assert "out_a/result_a.txt" not in col_b.collected_files


def test_parallel_independent_cancellation_and_crash(parallel_setup, monkeypatch):
    setup = parallel_setup
    ledger = setup["ledger"]
    lease_mgr = setup["lease_mgr"]
    scheduler = setup["scheduler"]

    for tid in ("TASK-001", "TASK-002"):
        ledger.initialize_task(tid, "c" * 64, "d" * 64)
        ledger.transition(tid, 0, TaskStatus.READY, "ready")
        scheduler.update_task_status(tid, TaskStatus.READY)

    # Worker A and Worker B acquire leases
    epoch_a = lease_mgr.acquire_lease("TASK-001", "worker-A", pid=os.getpid(), timeout_seconds=30)
    epoch_b = lease_mgr.acquire_lease("TASK-002", "worker-B", pid=os.getpid(), timeout_seconds=30)
    ledger.transition("TASK-001", 1, TaskStatus.RUNNING, "running")
    ledger.transition("TASK-002", 1, TaskStatus.RUNNING, "running")
    scheduler.dispatch("TASK-001")
    scheduler.dispatch("TASK-002")

    # Cancel TASK-001 independently
    lease_mgr.release_lease("TASK-001", "worker-A", epoch=epoch_a)
    ledger.transition("TASK-001", 2, TaskStatus.CANCELLED, "operator cancel")
    scheduler.update_task_status("TASK-001", TaskStatus.CANCELLED)

    # Verify TASK-002 is completely unaffected and continues running
    assert ledger.get_state("TASK-002")["status"] == TaskStatus.RUNNING.value
    assert lease_mgr.get_active_lease("TASK-002")["worker_id"] == "worker-B"

    # Complete TASK-002
    lease_mgr.release_lease("TASK-002", "worker-B", epoch=epoch_b)
    ledger.transition("TASK-002", 2, TaskStatus.VALIDATING, "completed")
    scheduler.update_task_status("TASK-002", TaskStatus.VALIDATING)

    assert ledger.get_state("TASK-001")["status"] == TaskStatus.CANCELLED.value
    assert ledger.get_state("TASK-002")["status"] == TaskStatus.VALIDATING.value


def test_stale_epoch_and_reassigned_lease_rejection(parallel_setup, monkeypatch):
    setup = parallel_setup
    lease_mgr = setup["lease_mgr"]

    # Worker 1 gets lease at epoch 1 with a simulated PID
    worker_1_pid = 88888
    monkeypatch.setattr("orchestrator.core.lease.is_process_alive", lambda pid: pid != worker_1_pid)

    epoch_1 = lease_mgr.acquire_lease("TASK-003", "worker-1", pid=worker_1_pid, timeout_seconds=0.1)
    time.sleep(0.15)  # Wait for lease to expire

    # Worker 2 acquires new lease at epoch 2 (allowed because worker_1_pid is dead)
    epoch_2 = lease_mgr.acquire_lease("TASK-003", "worker-2", pid=os.getpid(), timeout_seconds=30)
    assert epoch_2 > epoch_1

    # Old Worker 1 attempts to heartbeat with stale epoch_1: MUST fail
    with pytest.raises(LeaseExpiredError, match="epoch mismatch"):
        lease_mgr.heartbeat("TASK-003", "worker-1", epoch=epoch_1)

    # Old Worker 1 attempts to release with stale epoch_1: MUST not affect active lease
    lease_mgr.release_lease("TASK-003", "worker-1", epoch=epoch_1)
    active = lease_mgr.get_active_lease("TASK-003")
    assert active is not None
    assert active["epoch"] == epoch_2
