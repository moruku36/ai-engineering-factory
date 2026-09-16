"""Negative and boundary tests for worker isolation (AC-H01, AC-H02)."""

import subprocess
import sys
import time

import pytest

from orchestrator.core.sandbox import (
    CommandRegistry,
    CommandRegistryError,
    PathContainmentError,
    ProcessOwnershipError,
    ProcessTreeController,
    reserve_ephemeral_port,
    validate_path_containment,
)


def test_path_containment_rejects_parent_traversal(tmp_path):
    root = tmp_path / "sandbox_root"
    root.mkdir()
    outside = tmp_path / "control_db"
    outside.mkdir()
    (outside / "control.db").write_text("secret")

    # Direct relative traversal
    with pytest.raises(PathContainmentError):
        validate_path_containment(root / ".." / "control_db" / "control.db", root)

    # Absolute path pointing outside
    with pytest.raises(PathContainmentError):
        validate_path_containment(outside / "control.db", root)


def test_path_containment_rejects_symlink_escape(tmp_path):
    root = tmp_path / "sandbox_root"
    root.mkdir()
    outside = tmp_path / "host_secrets"
    outside.mkdir()
    secret_file = outside / "token.txt"
    secret_file.write_text("sensitive_token")

    symlink_file = root / "symlink_secret"
    try:
        symlink_file.symlink_to(secret_file)
    except OSError:
        pytest.skip("Symlink creation not permitted in this environment")

    with pytest.raises(PathContainmentError):
        validate_path_containment(symlink_file, root)


def test_command_registry_rejects_unregistered_and_invalid_args():
    registry = CommandRegistry()
    registry.register(
        command_id="run_tests",
        executable="pytest",
        allowed_flags=["-q", "-v", "--tb=short"],
        max_positional_args=2,
        network_profile="NONE",
        timeout_sec=30,
    )

    # Unregistered command
    with pytest.raises(CommandRegistryError, match="Unregistered command"):
        registry.resolve_and_validate("arbitrary_bash", ["rm", "-rf", "/"])

    # Disallowed flag
    with pytest.raises(CommandRegistryError, match="Disallowed argument"):
        registry.resolve_and_validate("run_tests", ["--import-mode=importlib", "--capture=no"])

    # Too many positional arguments
    with pytest.raises(CommandRegistryError, match="Too many positional arguments"):
        registry.resolve_and_validate("run_tests", ["test1.py", "test2.py", "test3.py"])

    # Disallowed network profile
    with pytest.raises(CommandRegistryError, match="Network profile mismatch"):
        registry.resolve_and_validate("run_tests", ["-q"], requested_network="INTERNET")


def test_port_reservation_provides_distinct_bound_ports():
    from contextlib import ExitStack

    with ExitStack() as stack:
        reservations = [stack.enter_context(reserve_ephemeral_port()) for _ in range(5)]
        ports = [reservation.port for reservation in reservations]
        assert len(ports) == len(set(ports))
        for p in ports:
            assert 1024 <= p <= 65535


def test_process_tree_termination_kills_descendants(tmp_path):
    """Verify that canceling or terminating a process tree stops child processes."""
    controller = ProcessTreeController()

    # Launch a Python script that spawns a child and sleeps
    script = (
        "import subprocess, time, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n"
    )
    test_script_path = tmp_path / "spawn_child.py"
    test_script_path.write_text(script)

    proc_record = controller.spawn(
        argv=[sys.executable, str(test_script_path)],
        cwd=tmp_path,
        run_id="run-001",
        worker_id="worker-001",
    )

    assert proc_record.is_alive()
    time.sleep(1.0)  # Give time for child to spawn

    # Terminate process tree
    controller.terminate_tree(proc_record)

    # Wait a short duration to verify it is completely dead
    time.sleep(0.5)
    assert not proc_record.is_alive()


def test_cleanup_rejects_unowned_process(tmp_path):
    """Verify that a worker cannot terminate or cleanup a process owned by another run/worker."""
    controller = ProcessTreeController()

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        # Pretend an attacker tries to register this PID with a forged start_time / run_id
        from orchestrator.core.sandbox import ProcessRecord
        fake_record = ProcessRecord(
            pid=proc.pid,
            start_time=0.0,  # Deliberately bogus start time
            run_id="run-attacker",
            worker_id="worker-attacker",
        )
        with pytest.raises(ProcessOwnershipError, match="Process ownership verification failed"):
            controller.verify_ownership(fake_record)
    finally:
        proc.terminate()
        proc.wait()
