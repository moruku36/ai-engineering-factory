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
