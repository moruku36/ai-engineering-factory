"""Unit tests for SQLite runtime lease manager."""

import os

import pytest

from orchestrator.core.lease import (
    LeaseAcquisitionError,
    LeaseExpiredError,
    RuntimeLeaseManager,
)


@pytest.fixture
def lease_mgr(tmp_path):
    return RuntimeLeaseManager(db_path=tmp_path / "runtime" / "leases.sqlite")


def test_lease_acquire_and_release(lease_mgr):
    task_id = "TASK-001"
    worker_id = "worker-1"
    current_pid = os.getpid()

    epoch = lease_mgr.acquire_lease(task_id, worker_id, current_pid, timeout_seconds=30.0)
    assert epoch == 1

    lease_info = lease_mgr.get_active_lease(task_id)
    assert lease_info["worker_id"] == worker_id
    assert lease_info["epoch"] == 1

    # Heartbeat
    lease_mgr.heartbeat(task_id, worker_id, epoch)

    # Release
    lease_mgr.release_lease(task_id, worker_id, epoch)
    assert lease_mgr.get_active_lease(task_id) is None


def test_lease_collision_rejected_while_alive(lease_mgr):
    task_id = "TASK-002"
    current_pid = os.getpid()

    epoch1 = lease_mgr.acquire_lease(task_id, "worker-1", current_pid, timeout_seconds=30.0)
    assert epoch1 == 1

    # Worker 2 tries to acquire while Worker 1 (current_pid) is alive
    with pytest.raises(LeaseAcquisitionError, match="is already leased"):
        lease_mgr.acquire_lease(task_id, "worker-2", 999999, timeout_seconds=30.0)


def test_lease_heartbeat_epoch_mismatch(lease_mgr):
    task_id = "TASK-003"
    current_pid = os.getpid()

    epoch = lease_mgr.acquire_lease(task_id, "worker-1", current_pid, timeout_seconds=30.0)

    # Heartbeat with wrong epoch
    with pytest.raises(LeaseExpiredError, match="lease lost or epoch mismatch"):
        lease_mgr.heartbeat(task_id, "worker-1", epoch + 99)


def test_reassignment_allowed_when_old_process_dead(lease_mgr):
    task_id = "TASK-004"
    # Use a non-existent PID (e.g. 99999999)
    dead_pid = 99999999

    epoch1 = lease_mgr.acquire_lease(task_id, "worker-1", dead_pid, timeout_seconds=0.01)
    assert epoch1 == 1

    import time

    time.sleep(0.05)

    # Old process is dead and timeout expired -> reassign with epoch increment
    epoch2 = lease_mgr.acquire_lease(task_id, "worker-2", os.getpid(), timeout_seconds=30.0)
    assert epoch2 == 2
    lease = lease_mgr.get_active_lease(task_id)
    assert lease["worker_id"] == "worker-2"
    assert lease["epoch"] == 2


def test_task_runtime_environment_isolation(tmp_path):
    from orchestrator.core.lease import TaskRuntimeEnvironment

    runtime = TaskRuntimeEnvironment(runtime_root=tmp_path / "runtime-root", task_id="ORC-002", attempt=1)
    runtime.provision()

    assert runtime.tmp_dir.is_dir()
    assert runtime.cache_dir.is_dir()
    assert runtime.test_db_dir.is_dir()

    env = runtime.get_isolated_env()
    assert env["FACTORY_TASK_ID"] == "ORC-002"
    assert env["FACTORY_ATTEMPT"] == "1"
    assert str(runtime.tmp_dir) in env["TMP"]
    assert str(runtime.cache_dir) in env["FACTORY_CACHE_DIR"]

    runtime.cleanup()
    assert not runtime.task_root.exists()

