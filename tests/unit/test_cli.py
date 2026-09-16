"""Unit tests for orchestrator.cli commands (AC-H06)."""

import sys

from orchestrator.cli import _parse_github_repository, main
from orchestrator.core.state import StateLedger, TaskStatus


def test_parse_github_repository():
    assert _parse_github_repository("https://github.com/example/factory.git") == "example/factory"
    assert _parse_github_repository("git@github.com:example/factory.git") == "example/factory"
    assert _parse_github_repository("ssh://git@github.com/example/factory.git") == "example/factory"
    assert _parse_github_repository("https://gitlab.com/example/factory.git") is None


def test_cli_doctor_runs(capsys):
    sys.argv = ["orchestrator.cli", "doctor"]
    exit_code = main()
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "=== Factory System Doctor ===" in captured.out
    assert "Python:" in captured.out
    assert "MANUAL_ONLY" in captured.out


def test_cli_status_and_cancel(tmp_path, capsys):
    state_dir = tmp_path / "tasks"
    ledger = StateLedger(state_dir)
    ledger.initialize_task("FND-001", "a" * 64, "b" * 64)

    # Status check
    sys.argv = ["orchestrator.cli", "status", "--state-dir", str(state_dir)]
    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "FND-001" in captured.out
    assert "PROPOSED" in captured.out

    # Cancel check
    sys.argv = ["orchestrator.cli", "cancel", "--task-id", "FND-001", "--state-dir", str(state_dir)]
    exit_code = main()
    assert exit_code == 0
    state = ledger.get_state("FND-001")
    assert state["status"] == TaskStatus.CANCELLED.value


def test_cli_approve_blocked_without_credentials(capsys):
    sys.argv = [
        "orchestrator.cli", "approve",
        "--action", "task_execution",
        "--repository", "repo",
        "--task-id", "TASK-001",
        "--head-sha", "a" * 40,
        "--target-ref", "refs/heads/main",
        "--command", "pytest",
        "--policy-hash", "b" * 64,
        "--plan-hash", "c" * 64,
        "--approved-by", "alice",
    ]
    exit_code = main()
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Approval blocked" in captured.out


def test_cli_approve_authenticated_success(tmp_path, capsys, monkeypatch):
    import json

    from orchestrator.core.auth import derive_key_fingerprint

    key_bytes = b"super-secret-operator-key-32bytes"
    key_file = tmp_path / "operator.key"
    key_file.write_bytes(key_bytes)

    fp = derive_key_fingerprint(key_bytes)
    config_file = tmp_path / "approvers.json"
    config_file.write_text(
        json.dumps([{"user_id": "alice", "role": "operator", "key_fingerprint": fp, "allowed_actions": ["*"]}])
    )

    monkeypatch.setenv("AI_FACTORY_APPROVERS_CONFIG", str(config_file))
    monkeypatch.setenv("AI_FACTORY_APPROVAL_SECRET", "control-plane-secret-signing-key-32bytes")

    approvals_dir = tmp_path / "approvals"

    sys.argv = [
        "orchestrator.cli", "approve",
        "--action", "task_execution",
        "--repository", "repo",
        "--task-id", "TASK-001",
        "--head-sha", "a" * 40,
        "--target-ref", "refs/heads/main",
        "--command", "pytest",
        "--policy-hash", "b" * 64,
        "--plan-hash", "c" * 64,
        "--approved-by", "alice",
        "--key-file", str(key_file),
        "--approvals-dir", str(approvals_dir),
    ]
    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Approval token issued: tok-" in captured.out


def test_cli_cancel_running_task_with_confirmed_termination(tmp_path, capsys, monkeypatch):
    from unittest.mock import MagicMock

    from orchestrator.core.lease import RuntimeLeaseManager

    state_dir = tmp_path / "tasks"
    ledger = StateLedger(state_dir)
    ledger.initialize_task("RUN-001", "a" * 64, "b" * 64)
    ledger.transition("RUN-001", 0, TaskStatus.READY, "preflight")
    ledger.transition("RUN-001", 1, TaskStatus.RUNNING, "dispatched")

    lease_db = tmp_path / "leases.sqlite"
    lm = RuntimeLeaseManager(db_path=lease_db)
    lm.acquire_lease("RUN-001", "worker-RUN-001", pid=999999, timeout_seconds=60)

    # Mock process liveness and termination
    monkeypatch.setattr("orchestrator.core.lease.is_process_alive", lambda pid: False)
    mock_term = MagicMock(return_value=True)
    monkeypatch.setattr("orchestrator.core.sandbox.ProcessTreeController.terminate_tree", mock_term)

    sys.argv = [
        "orchestrator.cli", "cancel",
        "--task-id", "RUN-001",
        "--state-dir", str(state_dir),
        "--lease-db", str(lease_db),
    ]
    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "transitioned to CANCELLED" in captured.out
    assert ledger.get_state("RUN-001")["status"] == TaskStatus.CANCELLED.value


def test_cli_cancel_running_task_blocked_when_termination_fails(tmp_path, capsys, monkeypatch):
    from unittest.mock import MagicMock

    from orchestrator.core.lease import RuntimeLeaseManager

    state_dir = tmp_path / "tasks"
    ledger = StateLedger(state_dir)
    ledger.initialize_task("RUN-002", "a" * 64, "b" * 64)
    ledger.transition("RUN-002", 0, TaskStatus.READY, "preflight")
    ledger.transition("RUN-002", 1, TaskStatus.RUNNING, "dispatched")

    lease_db = tmp_path / "leases.sqlite"
    lm = RuntimeLeaseManager(db_path=lease_db)
    lm.acquire_lease("RUN-002", "worker-RUN-002", pid=999999, timeout_seconds=60)

    # Mock process still alive after termination attempt
    monkeypatch.setattr("orchestrator.core.lease.is_process_alive", lambda pid: True)
    mock_term = MagicMock(return_value=False)
    monkeypatch.setattr("orchestrator.core.sandbox.ProcessTreeController.terminate_tree", mock_term)

    sys.argv = [
        "orchestrator.cli", "cancel",
        "--task-id", "RUN-002",
        "--state-dir", str(state_dir),
        "--lease-db", str(lease_db),
    ]
    exit_code = main()
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Cancellation blocked" in captured.out
    assert ledger.get_state("RUN-002")["status"] == TaskStatus.RUNNING.value


