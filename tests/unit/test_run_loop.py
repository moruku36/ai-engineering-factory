"""Unit tests for persistent orchestration RunLoop (AC-H04, AC-H10)."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.core.approval import ApprovalManager
from orchestrator.core.lease import RuntimeLeaseManager
from orchestrator.core.loop import RunLoopController
from orchestrator.core.state import StateLedger, TaskStatus


class MockAdapter:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.started = []
        self.released = []

    def start_execution(self, task_manifest, worktree_path=None):
        tid = task_manifest["id"]
        self.started.append(tid)
        return {"session_id": f"sess-{tid}", "status": "RUNNING"}

    def poll_execution(self, session_id):
        tid = session_id.replace("sess-", "")
        outcome = self.outcomes.get(tid, "COMPLETED")
        return {"status": outcome, "exit_code": 0 if outcome == "COMPLETED" else 1}

    def collect_evidence(self, session_id):
        tid = session_id.replace("sess-", "")
        return {
            "candidate_sha": "a" * 40,
            "changed_paths": ["src/app.py"],
            "test_summary": {"passed": 5, "failed": 0},
        }

    def cancel_execution(self, session_id):
        self.released.append(session_id)


def test_run_loop_completes_single_task(tmp_path):
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "runtime"
    state_dir.mkdir()
    runtime_dir.mkdir()

    ledger = StateLedger(state_dir)
    leases = RuntimeLeaseManager(runtime_dir / "leases.sqlite")
    adapter = MockAdapter()

    tasks = [
        {
            "id": "TASK-001",
            "spec": {"title": "Task 1"},
            "dependencies": [],
            "allowed_paths": ["src/"],
        }
    ]

    controller = RunLoopController(
        task_manifests=tasks,
        state_ledger=ledger,
        lease_manager=leases,
        adapter=adapter,
        spec_digest="a" * 64,
        policy_digest="b" * 64,
        base_sha="c" * 40,
    )

    # Initialize and run
    controller.initialize_tasks()
    summary = controller.run_until_idle(max_iterations=10)

    assert "TASK-001" in adapter.started
    state = ledger.get_state("TASK-001")
    assert state["status"] == TaskStatus.READY_FOR_MERGE.value
    assert state["candidate_sha"] == "a" * 40


def test_run_loop_blocks_downstream_on_failure(tmp_path):
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "runtime"
    state_dir.mkdir()
    runtime_dir.mkdir()

    ledger = StateLedger(state_dir)
    leases = RuntimeLeaseManager(runtime_dir / "leases.sqlite")
    # TASK-001 fails, TASK-002 depends on TASK-001
    adapter = MockAdapter(outcomes={"TASK-001": "FAILED", "TASK-002": "COMPLETED"})

    tasks = [
        {
            "id": "TASK-001",
            "spec": {"title": "Task 1"},
            "dependencies": [],
            "allowed_paths": ["src/a/"],
            "retry": {"max_attempts": 1},
        },
        {
            "id": "TASK-002",
            "spec": {"title": "Task 2"},
            "dependencies": ["TASK-001"],
            "allowed_paths": ["src/b/"],
        },
    ]

    controller = RunLoopController(
        task_manifests=tasks,
        state_ledger=ledger,
        lease_manager=leases,
        adapter=adapter,
        spec_digest="a" * 64,
        policy_digest="b" * 64,
        base_sha="c" * 40,
    )

    controller.initialize_tasks()
    controller.run_until_idle(max_iterations=10)

    state1 = ledger.get_state("TASK-001")
    state2 = ledger.get_state("TASK-002")

    assert state1["status"] == TaskStatus.FAILED.value
    assert state2["status"] == TaskStatus.BLOCKED.value
    assert "TASK-002" not in adapter.started
