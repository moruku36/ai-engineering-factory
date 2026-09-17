"""Safety regressions for PR #7; mocks are not real integration acceptance."""

import argparse
import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.adapters.antigravity import AntigravityAdapter, NativeAntigravityAdapter
from orchestrator.adapters.github import GitHubPRError, GitHubPublishError, RealGitHubStatePublisher
from orchestrator.cli import cmd_approve, cmd_cancel
from orchestrator.core.approval import ApprovalManager, ApprovalVerificationError
from orchestrator.core.lease import RuntimeLeaseManager
from orchestrator.core.loop import RunLoopController
from orchestrator.core.sandbox import (
    ProcessOwnershipError,
    ProcessRecord,
    ProcessTreeController,
    reserve_ephemeral_port,
)
from orchestrator.core.state import StateLedger, TaskStatus


def test_missing_or_short_signing_key_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_FACTORY_APPROVAL_SECRET")
    with pytest.raises(ApprovalVerificationError, match="signing key"):
        ApprovalManager(tmp_path)
    monkeypatch.setenv("AI_FACTORY_APPROVAL_SECRET", "short")
    with pytest.raises(ApprovalVerificationError, match="signing key"):
        ApprovalManager(tmp_path)
    assert not list(tmp_path.iterdir())


def test_user_supplied_actor_does_not_issue_approval(tmp_path):
    args = argparse.Namespace(approved_by="claimed-human", approvals_dir=str(tmp_path))
    assert cmd_approve(args) == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mode", ["native", "auto"])
def test_no_silent_manual_fallback(mode):
    with pytest.raises(NotImplementedError):
        AntigravityAdapter(mode=mode)


def test_detected_binary_cannot_produce_a_success(tmp_path):
    with patch("orchestrator.adapters.antigravity.probe_antigravity_runtime",
               return_value={"available": True}):
        adapter = NativeAntigravityAdapter()
    with pytest.raises(NotImplementedError):
        adapter.start_task({"id": "TSK-001"}, str(tmp_path))
    with pytest.raises(NotImplementedError):
        adapter.collect_results("fake-run")


def test_destructive_process_api_rejects_unowned_record():
    controller = ProcessTreeController()
    record = ProcessRecord(pid=12345, start_time=0, run_id="foreign", worker_id="foreign")
    with patch("subprocess.run") as run:
        with pytest.raises(ProcessOwnershipError):
            controller.terminate_tree(record)
        run.assert_not_called()


def test_port_is_reserved_until_owner_closes():
    with (
        reserve_ephemeral_port() as reservation,
        socket.socket() as competitor,
        pytest.raises(OSError),
    ):
        competitor.bind(("127.0.0.1", reservation.port))
    with socket.socket() as next_owner:
        next_owner.bind(("127.0.0.1", reservation.port))


def completed(stdout="", returncode=0):
    return MagicMock(stdout=stdout, stderr="fixture error", returncode=returncode)


@pytest.mark.parametrize("branch", ["refs/heads/main", "+main", "task/x:main", "--all"])
def test_branch_ref_cannot_bypass_main_policy(tmp_path, branch):
    with patch("subprocess.run") as run:
        with pytest.raises(GitHubPublishError):
            RealGitHubStatePublisher().publish_branch(tmp_path, branch)
        run.assert_not_called()


def test_wrong_push_destination_stops_before_push(tmp_path):
    with patch("subprocess.run", return_value=completed("https://github.com/other/repo.git")) as run:
        with pytest.raises(GitHubPublishError, match="destination"):
            RealGitHubStatePublisher().publish_branch(tmp_path, "task/test")
        assert run.call_count == 1


@pytest.mark.parametrize("response", [completed(returncode=1), completed("bad-json"), completed("{}")])
def test_uncertain_pr_lookup_does_not_create(response):
    with patch("subprocess.run", return_value=response) as run:
        with pytest.raises(GitHubPRError):
            RealGitHubStatePublisher().create_or_update_pr("t", "main", "task/test", "b")
        assert run.call_count == 1


def test_closed_pr_is_not_reported_as_new_success():
    pr = {"number": 42, "url": "https://github.com/moruku36/ai-engineering-factory/pull/42",
          "headRefOid": "a" * 40, "state": "MERGED"}
    with patch("subprocess.run", return_value=completed(json.dumps([pr]))) as run:
        with pytest.raises(GitHubPRError, match="no longer open"):
            RealGitHubStatePublisher().create_or_update_pr("t", "main", "task/test", "b")
        assert run.call_count == 1


def test_pr_create_zero_exit_still_requires_remote_evidence():
    with (
        patch("subprocess.run", side_effect=[completed("[]"), completed("not-a-url"),
                                             completed("[]")]),
        pytest.raises(GitHubPRError, match="ambiguous"),
    ):
        RealGitHubStatePublisher().create_or_update_pr("t", "main", "task/test", "b")


class FixtureAdapter:
    def __init__(self):
        self.started = []

    def start_task(self, manifest, worktree_path):
        self.started.append(manifest["id"])
        return manifest["id"]

    def poll_task(self, run_id):
        return {"status": "SUCCESS"}

    def collect_results(self, run_id):
        return {"status": "SUCCESS", "candidate_digest": "a" * 40}

    def cancel_task(self, run_id):
        return True


def controller_fixture(tmp_path):
    tasks = [
        {"id": "TSK-001", "dependencies": [], "worktree": str(tmp_path)},
        {"id": "TSK-002", "dependencies": ["TSK-001"], "worktree": str(tmp_path)},
    ]
    ledger = StateLedger(tmp_path / "state")
    adapter = FixtureAdapter()
    controller = RunLoopController(tasks, ledger, RuntimeLeaseManager(tmp_path / "leases.sqlite"),
                                   adapter, "a" * 64, "b" * 64, "c" * 40)
    controller.initialize_tasks()
    return controller, ledger, adapter


def test_loop_does_not_invent_preflight(tmp_path):
    controller, ledger, adapter = controller_fixture(tmp_path)
    controller.run_until_idle(2)
    assert adapter.started == []
    assert ledger.get_state("TSK-001")["status"] == "PROPOSED"


def test_execution_success_is_not_review_or_merge(tmp_path):
    controller, ledger, adapter = controller_fixture(tmp_path)
    for tid in ("TSK-001", "TSK-002"):
        ledger.transition(tid, 0, TaskStatus.READY, "Trusted fixture preflight")
    controller.initialize_tasks()
    controller.run_until_idle(3)
    assert adapter.started == ["TSK-001"]
    assert ledger.get_state("TSK-001")["status"] == "VALIDATING"
    assert ledger.get_state("TSK-002")["status"] == "READY"


def test_cli_cancel_does_not_claim_active_worker_stopped(tmp_path):
    ledger = StateLedger(tmp_path)
    ledger.initialize_task("TSK-001", "a" * 64, "b" * 64)
    ledger.transition("TSK-001", 0, TaskStatus.READY, "fixture")
    ledger.transition("TSK-001", 1, TaskStatus.RUNNING, "fixture")
    args = argparse.Namespace(state_dir=str(tmp_path), task_id="TSK-001", reason=None)
    assert cmd_cancel(args) == 2
    assert ledger.get_state("TSK-001")["status"] == "RUNNING"
