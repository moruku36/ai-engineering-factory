"""Regression coverage for the post-Phase-4 safety review."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from orchestrator.adapters.manual import AntigravityAdapter, GitHubStatePublisher, ManualAdapter
from orchestrator.core.lease import (
    LeaseAcquisitionError,
    LeaseExpiredError,
    RuntimeLeaseManager,
    is_process_alive,
)
from orchestrator.core.scheduler import DAGScheduler
from orchestrator.core.state import TaskStatus


def task(tid, **changes):
    return {"id": tid, "status": "READY", "dependencies": [],
            "parallelizable": True, "allowed_paths": [f"{tid}/"], **changes}


def test_liveness_check_does_not_terminate_child():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert is_process_alive(child.pid)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert not is_process_alive(child.pid)


def test_lease_epoch_survives_release(tmp_path):
    manager = RuntimeLeaseManager(tmp_path / "leases.sqlite")
    old = manager.acquire_lease("TSK-001", "worker", os.getpid())
    manager.release_lease("TSK-001", "worker", old)
    new = manager.acquire_lease("TSK-001", "worker", os.getpid())
    assert new > old
    with pytest.raises(LeaseExpiredError):
        manager.heartbeat("TSK-001", "worker", old)
    manager.release_lease("TSK-001", "worker", old)
    assert manager.get_active_lease("TSK-001")["epoch"] == new


def test_atomic_claim_across_connections(tmp_path):
    db = tmp_path / "leases.sqlite"
    managers = [RuntimeLeaseManager(db), RuntimeLeaseManager(db)]
    barrier = Barrier(2)

    def claim(index):
        barrier.wait(timeout=5)
        try:
            managers[index].acquire_lease("TSK-001", f"worker-{index}", os.getpid())
            return "acquired"
        except LeaseAcquisitionError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == ["acquired", "denied"]


def test_expired_heartbeat_cannot_revive_lease(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("orchestrator.core.lease.time.time", lambda: now[0])
    manager = RuntimeLeaseManager(tmp_path / "leases.sqlite")
    epoch = manager.acquire_lease("TSK-001", "worker", os.getpid(), 10)
    now[0] = 111.0
    with pytest.raises(LeaseExpiredError, match="expired"):
        manager.heartbeat("TSK-001", "worker", epoch)
    with pytest.raises(LeaseAcquisitionError):
        manager.acquire_lease("TSK-001", "new-worker", os.getpid())


def test_dispatch_cannot_bypass_dependencies_or_conflicts():
    scheduler = DAGScheduler([
        task("TSK-001", allowed_paths=["shared/"]),
        task("TSK-002", dependencies=["TSK-001"]),
        task("TSK-003", allowed_paths=["shared/"]),
    ])
    with pytest.raises(ValueError, match="not dispatchable"):
        scheduler.dispatch("TSK-002")
    scheduler.dispatch("TSK-001")
    with pytest.raises(ValueError, match="not dispatchable"):
        scheduler.dispatch("TSK-003")
    with pytest.raises(ValueError, match="not dispatchable"):
        scheduler.dispatch("TSK-001")


def test_proposed_and_duplicate_tasks_rejected():
    scheduler = DAGScheduler([task("TSK-001", status="PROPOSED")])
    assert scheduler.get_dispatchable_tasks() == []
    with pytest.raises(ValueError):
        scheduler.dispatch("TSK-001")
    with pytest.raises(ValueError, match="Duplicate"):
        DAGScheduler([task("TSK-001"), task("TSK-001")])


def test_retry_is_bounded():
    scheduler = DAGScheduler([task("TSK-001")])
    for attempt in range(3):
        scheduler.dispatch("TSK-001")
        scheduler.update_task_status("TSK-001", TaskStatus.FAILED)
        if attempt < 2:
            scheduler.retry_failed_task("TSK-001")
    with pytest.raises(ValueError, match="retry budget"):
        scheduler.retry_failed_task("TSK-001")


@pytest.mark.parametrize("mode", ["auto", "autonomous", "native"])
def test_native_execution_is_not_silently_simulated(mode):
    with pytest.raises(NotImplementedError):
        AntigravityAdapter(mode=mode)


def test_publisher_does_not_invent_push_or_pr_success(tmp_path):
    publisher = GitHubStatePublisher()
    with pytest.raises(NotImplementedError):
        publisher.publish_branch(tmp_path, "task/review")
    with pytest.raises(NotImplementedError):
        publisher.create_or_update_pr("title", "main", "task/review", "body")


def test_unrun_validation_does_not_pass(tmp_path):
    adapter = ManualAdapter()
    run = adapter.start_task({"id": "TSK-001", "output_artifacts": []}, str(tmp_path))
    assert adapter.collect_results(run)["status"] == "FAILED"


def test_required_validation_cannot_be_omitted(tmp_path):
    adapter = ManualAdapter()
    run = adapter.start_task({"id": "TSK-001", "output_artifacts": [],
                              "validation": [{"command_id": "pytest"}]}, str(tmp_path))
    adapter.execute_validation_step(run, "python", [sys.executable, "-c", "exit(0)"])
    assert adapter.collect_results(run)["status"] == "FAILED"


def test_artifact_cannot_escape_worktree(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("private fixture", encoding="utf-8")
    adapter = ManualAdapter()
    run = adapter.start_task({"id": "TSK-001", "output_artifacts": [
        {"path": "../outside.txt"}]}, str(root))
    with pytest.raises(ValueError, match="escapes"):
        adapter.collect_results(run)


def test_cancelled_run_cannot_execute(tmp_path):
    adapter = ManualAdapter()
    run = adapter.start_task({"id": "TSK-001"}, str(tmp_path))
    adapter.cancel_task(run)
    with pytest.raises(RuntimeError, match="inactive"):
        adapter.execute_validation_step(run, "python", [sys.executable, "-c", "exit(0)"])
