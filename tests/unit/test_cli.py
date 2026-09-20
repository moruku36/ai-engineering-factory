"""Unit tests for orchestrator.cli commands (AC-H06)."""

import re
import subprocess
import sys

import yaml

from orchestrator.cli import _parse_github_repository, main
from orchestrator.core.state import StateLedger, TaskStatus


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


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


def test_cli_cancel_running_task_with_confirmed_termination(tmp_path, capsys):
    """End-to-end: spawn a real long-running child process, cancel it via the CLI,
    and confirm the CLI actually kills it (not a mocked termination)."""
    import subprocess
    import time

    from orchestrator.core.lease import RuntimeLeaseManager, is_process_alive

    state_dir = tmp_path / "tasks"
    ledger = StateLedger(state_dir)
    ledger.initialize_task("RUN-001", "a" * 64, "b" * 64)
    ledger.transition("RUN-001", 0, TaskStatus.READY, "preflight")
    ledger.transition("RUN-001", 1, TaskStatus.RUNNING, "dispatched")

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lease_db = tmp_path / "leases.sqlite"
        lm = RuntimeLeaseManager(db_path=lease_db)
        lm.acquire_lease("RUN-001", "worker-RUN-001", pid=child.pid, timeout_seconds=60)

        assert is_process_alive(child.pid)

        sys.argv = [
            "orchestrator.cli", "cancel",
            "--task-id", "RUN-001",
            "--state-dir", str(state_dir),
            "--lease-db", str(lease_db),
        ]
        exit_code = main()
        captured = capsys.readouterr()
        assert exit_code == 0, captured.out
        assert "transitioned to CANCELLED" in captured.out
        assert ledger.get_state("RUN-001")["status"] == TaskStatus.CANCELLED.value

        # Give the OS a moment to reap; the CLI already confirmed termination above.
        for _ in range(20):
            if not is_process_alive(child.pid):
                break
            time.sleep(0.1)
        assert not is_process_alive(child.pid)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def test_cli_cancel_running_task_pid_reused_blocks_cancellation(tmp_path, capsys, monkeypatch):
    """A lease whose recorded process_start_time no longer matches the live PID's
    creation time (i.e. the PID was reused by an unrelated process) must not be
    terminated -- the CLI should block rather than kill the wrong process."""
    import subprocess

    from orchestrator.core.lease import RuntimeLeaseManager

    state_dir = tmp_path / "tasks"
    ledger = StateLedger(state_dir)
    ledger.initialize_task("RUN-002", "a" * 64, "b" * 64)
    ledger.transition("RUN-002", 0, TaskStatus.READY, "preflight")
    ledger.transition("RUN-002", 1, TaskStatus.RUNNING, "dispatched")

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lease_db = tmp_path / "leases.sqlite"
        lm = RuntimeLeaseManager(db_path=lease_db)
        lm.acquire_lease("RUN-002", "worker-RUN-002", pid=child.pid, timeout_seconds=60)

        # Simulate PID reuse: the stored creation time no longer matches the live process.
        monkeypatch.setattr(
            "orchestrator.core.sandbox._get_process_creation_time",
            lambda pid: 999999999.0,
        )

        sys.argv = [
            "orchestrator.cli", "cancel",
            "--task-id", "RUN-002",
            "--state-dir", str(state_dir),
            "--lease-db", str(lease_db),
        ]
        exit_code = main()
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "Cancellation blocked" in captured.out
    finally:
        child.kill()
        child.wait(timeout=5)


def test_cli_init_creates_runtime_root_and_local_config(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "target-repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    runtime_root = tmp_path / "runtime"
    sys.argv = [
        "orchestrator.cli", "init",
        "--repository", "someowner/somerepo",
        "--runtime-root", str(runtime_root),
    ]
    exit_code = main()
    assert exit_code == 0

    assert (runtime_root / "worktrees").is_dir()
    assert (runtime_root / "logs").is_dir()
    assert (runtime_root / "leases").is_dir()

    config_file = repo / ".ai-factory" / "config.yaml"
    assert config_file.is_file()
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert config["repository"] == "someowner/somerepo"
    assert config["runtime_root"] == str(runtime_root)

    captured = capsys.readouterr()
    assert "[*] Repository: someowner/somerepo" in captured.out


def test_cli_init_blocks_runtime_root_inside_git_repo(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "target-repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    runtime_root_inside = repo / "runtime-inside"
    sys.argv = [
        "orchestrator.cli", "init",
        "--repository", "someowner/somerepo",
        "--runtime-root", str(runtime_root_inside),
    ]
    exit_code = main()
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "is inside a git repository" in captured.out
    assert not runtime_root_inside.exists()
    assert not (repo / ".ai-factory").exists()


def test_cli_init_appends_to_git_info_exclude(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "target-repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.chdir(repo)

    runtime_root = tmp_path / "runtime"
    sys.argv = [
        "orchestrator.cli", "init",
        "--repository", "someowner/somerepo",
        "--runtime-root", str(runtime_root),
    ]
    exit_code = main()
    assert exit_code == 0

    exclude_file = repo / ".git" / "info" / "exclude"
    assert exclude_file.is_file()
    exclude_lines = exclude_file.read_text(encoding="utf-8").splitlines()
    assert "/.ai-factory/" in exclude_lines

    # The repo's tracked .gitignore must never be touched by init.
    assert not (repo / ".gitignore").exists()

    captured = capsys.readouterr()
    assert "Added to" in captured.out
    assert ".git/info/exclude" in captured.out


def test_cli_demo_rejects_invalid_task_schema(tmp_path, capsys):
    bad_task_file = tmp_path / "bad-task.yaml"
    bad_task_file.write_text(yaml.safe_dump({"id": "TASK-001", "title": "missing required fields"}))

    sys.argv = ["orchestrator.cli", "demo", "--task-file", str(bad_task_file)]
    exit_code = main()
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "demo blocked: task manifest failed schema validation" in captured.out


def test_cli_demo_end_to_end_produces_64_char_candidate_digest(tmp_path, capsys):
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    template = yaml.safe_load(
        (repo_root / "tasks" / "templates" / "basic-task.yaml").read_text(encoding="utf-8")
    )
    template["id"] = "TASK-900"
    template["repository"] = "https://github.com/example/demo-repo"

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_trivial.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    task_file = tmp_path / "task.yaml"
    task_file.write_text(yaml.safe_dump(template), encoding="utf-8")

    sys.argv = [
        "orchestrator.cli", "demo",
        "--task-file", str(task_file),
        "--worktree", str(worktree),
    ]
    exit_code = main()
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "=== Result: SUCCESS ===" in captured.out
    match = re.search(r"candidate_digest: ([0-9a-f]+)", captured.out)
    assert match is not None
    assert len(match.group(1)) == 64


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


