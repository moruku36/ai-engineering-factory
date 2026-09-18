"""Admission uses real approval/SQLite primitives; Docker is mocked in unit tests."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from orchestrator.adapters.container import ApprovedContainerAdapter, ContainerAdmissionError
from orchestrator.core.approval import ApprovalManager, ApprovalVerificationError
from orchestrator.core.container import ContainerCommand, ContainerResult, OfflineContainerRunner
from orchestrator.core.lease import RuntimeLeaseManager
from orchestrator.core.loop import RunLoopController
from orchestrator.core.state import StateLedger, TaskStatus


def make_adapter(tmp_path):
    task = {"id": "TASK-001", "worktree": "unmounted-reference", "dependencies": [],
            "allowed_paths": ["src/"]}
    runner = OfflineContainerRunner(tmp_path / "workers", "sha256:" + "a" * 64, {
        "probe": ContainerCommand(("/usr/local/bin/python", "/inputs/probe.py"), 2),
    })
    runner.run = Mock(side_effect=lambda _cmd, _inputs, run_id: ContainerResult(run_id, 0, "ok"))
    approvals = ApprovalManager(tmp_path / "approvals")
    plans = {task["id"]: {
        "repository": "example/factory", "head_sha": "c" * 40, "target_ref": "task/one",
        "policy_hash": "b" * 64, "plan_hash": "a" * 64, "command_id": "probe",
        "inputs": {"probe.py": b"print('ok')"},
    }}
    adapter = ApprovedContainerAdapter(runner, approvals, plans, {}, tmp_path / "adapter")
    return adapter, task


def approve(adapter, task):
    token = adapter.approvals.issue_token(
        **adapter.approval_context(task, task["worktree"]), approved_by="fixture-only",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    adapter.tokens[task["id"]] = token["token_id"]
    return token


def make_loop(tmp_path, adapter, task):
    ledger = StateLedger(tmp_path / "state")
    leases = RuntimeLeaseManager(tmp_path / "leases.sqlite")
    loop = RunLoopController([task], ledger, leases, adapter, "a" * 64, "b" * 64,
                             base_sha="c" * 40, max_workers=1)
    return loop


def test_missing_approval_never_runs(tmp_path):
    adapter, task = make_adapter(tmp_path)
    with pytest.raises(ContainerAdmissionError, match="Approval token"):
        adapter.start_task(task, task["worktree"])
    adapter.runner.run.assert_not_called()


@pytest.mark.parametrize("change", ["input", "manifest", "worktree", "image", "command",
                                     "timeout", "repository", "head_sha", "target_ref",
                                     "policy_hash", "plan_hash"])
def test_context_change_rejected_before_execution(tmp_path, change):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)
    plan = adapter.plans[task["id"]]
    if change == "input":
        plan["inputs"]["probe.py"] = b"print('changed')"
    elif change == "manifest":
        task["allowed_paths"] = ["/"]
    elif change == "worktree":
        task["worktree"] = "different-reference"
    elif change == "image":
        adapter.runner.image_id = "sha256:" + "d" * 64
    elif change in ("command", "timeout"):
        adapter.runner.commands["probe"] = ContainerCommand(
            ("/bin/false",) if change == "command" else ("/usr/local/bin/python", "/inputs/probe.py"), 3,
        )
    else:
        plan[change] = "different"
    with pytest.raises(ApprovalVerificationError):
        adapter.start_task(task, task["worktree"])
    adapter.runner.run.assert_not_called()


def test_concurrent_dispatch_executes_once(tmp_path):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)

    def start(_index):
        try:
            return adapter.start_task(task, task["worktree"])
        except ContainerAdmissionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, [0, 1]))
    assert sum(value is not None for value in results) == 1
    assert adapter.runner.run.call_count == 1


def test_token_cannot_replay_through_another_control_database(tmp_path):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)
    adapter.start_task(task, task["worktree"])
    second = ApprovedContainerAdapter(adapter.runner, adapter.approvals, adapter.plans,
                                      adapter.tokens, tmp_path / "another-controller")
    with pytest.raises(ApprovalVerificationError):
        second.start_task(task, task["worktree"])
    assert adapter.runner.run.call_count == 1


def test_completed_session_survives_restart_without_redispatch(tmp_path):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)
    loop = make_loop(tmp_path, adapter, task)
    loop.initialize_tasks()
    loop.state_ledger.transition(task["id"], 0, TaskStatus.READY, "fixture preflight")
    loop.initialize_tasks()
    loop.step()  # Result is persisted, while ledger is still RUNNING.
    fresh = ApprovedContainerAdapter(adapter.runner, adapter.approvals, adapter.plans,
                                     adapter.tokens, adapter.root)
    restarted = make_loop(tmp_path, fresh, task)
    restarted.initialize_tasks()
    restarted.step()
    assert restarted.state_ledger.get_state(task["id"])["status"] == "VALIDATING"
    assert restarted.state_ledger.get_state(task["id"])["candidate_digest"] is None
    assert adapter.runner.run.call_count == 1
    assert restarted.lease_manager.get_active_lease(task["id"]) is None


def test_live_controller_never_reconciled(tmp_path):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)
    session = adapter.start_task(task, task["worktree"])
    adapter._status(session, "ADMITTED")  # Crash-window fixture before result commit.
    with pytest.raises(ContainerAdmissionError, match="still alive"):
        adapter.recover_task(task, task["worktree"])


def test_dead_controller_without_result_blocks_instead_of_restarting(tmp_path, monkeypatch):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)
    session = adapter.start_task(task, task["worktree"])
    adapter._status(session, "ADMITTED")
    monkeypatch.setattr("orchestrator.adapters.container._is_process_alive", lambda _pid: False)
    assert adapter.recover_task(task, task["worktree"]) == session
    assert adapter.poll_task(session)["status"] == "BLOCKED"
    with pytest.raises(ContainerAdmissionError, match="No verified"):
        adapter.collect_results(session)
    with pytest.raises(ContainerAdmissionError, match="already claimed"):
        adapter.start_task(task, task["worktree"])
    assert adapter.runner.run.call_count == 1


def test_loop_rejects_ledger_drift_before_dispatch(tmp_path):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)
    loop = make_loop(tmp_path, adapter, task)
    loop.initialize_tasks()
    loop.state_ledger.transition(task["id"], 0, TaskStatus.READY, "fixture", base_sha="d" * 40)
    loop.initialize_tasks()
    with pytest.raises(ContainerAdmissionError, match="ledger"):
        loop.step()
    adapter.runner.run.assert_not_called()


def test_context_preview_does_not_consume_or_execute(tmp_path):
    adapter, task = make_adapter(tmp_path)
    first = adapter.approval_context(task, task["worktree"])
    assert first == adapter.approval_context(task, task["worktree"])
    assert len(first["argv_digest"]) == 64
    adapter.runner.run.assert_not_called()


def test_loop_rejects_parallel_mode_for_synchronous_adapter(tmp_path):
    adapter, task = make_adapter(tmp_path)
    with pytest.raises(ValueError, match="max_workers=1"):
        RunLoopController([task], StateLedger(tmp_path / "state"),
                          RuntimeLeaseManager(tmp_path / "leases.sqlite"), adapter, "a" * 64, "b" * 64)


def test_input_snapshot_cannot_change_during_approval_consumption(tmp_path):
    adapter, task = make_adapter(tmp_path)
    approve(adapter, task)
    consume = adapter.approvals.verify_and_consume_token

    def mutate_after_verification(**kwargs):
        consume(**kwargs)
        adapter.plans[task["id"]]["inputs"]["probe.py"] = b"print('changed')"

    adapter.approvals.verify_and_consume_token = mutate_after_verification
    adapter.start_task(task, task["worktree"])
    assert adapter.runner.run.call_args.args[1]["probe.py"] == b"print('ok')"


def test_start_task_verifies_real_worktree_diff_and_junit_report(tmp_path):
    """Regression test: previously the container's /workspace was always an empty
    tmpfs, so verify_candidate ran against nothing. This proves start_task now
    mounts a real snapshot of the (already builder-edited) worktree, computes a
    genuine diff against base_sha, and uses an independently-parsed JUnit report.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("base", encoding="utf-8")
    (repo / "src" / "b.py").write_text("unchanged", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    # Simulate the builder having already edited the worktree before verification.
    (repo / "src" / "a.py").write_text("changed by agent", encoding="utf-8")

    task = {"id": "TASK-201", "worktree": str(repo), "dependencies": [], "allowed_paths": ["src/"]}
    runner = OfflineContainerRunner(tmp_path / "workers", "sha256:" + "a" * 64, {
        "probe": ContainerCommand(("/usr/local/bin/python", "/inputs/probe.py"), 2),
    })

    def fake_run(_cmd, _inputs, run_id, workspace_mount=None):
        assert workspace_mount is not None, "adapter must pass a real workspace snapshot"
        artifacts_dir = tmp_path / "fake-artifacts" / run_id
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "report.xml").write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0"></testsuite>', encoding="utf-8",
        )
        return ContainerResult(run_id, 0, "1 passed", artifacts_dir)

    runner.run = Mock(side_effect=fake_run)
    approvals = ApprovalManager(tmp_path / "approvals")
    plans = {task["id"]: {
        "repository": "example/factory", "head_sha": base_sha, "target_ref": "task/diff",
        "policy_hash": "b" * 64, "plan_hash": "a" * 64, "command_id": "probe",
        "inputs": {"probe.py": b"print('ok')"},
    }}
    adapter = ApprovedContainerAdapter(runner, approvals, plans, {}, tmp_path / "adapter")
    token = adapter.approvals.issue_token(
        **adapter.approval_context(task, task["worktree"]), approved_by="fixture-only",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    adapter.tokens[task["id"]] = token["token_id"]

    run_id = adapter.start_task(task, task["worktree"])
    result = adapter.collect_results(run_id)

    assert result["status"] == "SUCCESS"
    assert result["changed_paths"] == ["src/a.py"]  # not src/b.py: it never changed
    assert len(result["candidate_digest"]) == 64
