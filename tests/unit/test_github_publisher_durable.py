"""Unit tests for GitHub durable operations journal, crash reconciliation, and human merge verification."""

import json
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.adapters.github import GitHubPRError, RealGitHubStatePublisher


@pytest.fixture
def publisher(tmp_path):
    return RealGitHubStatePublisher(
        repo_slug="moruku36/ai-engineering-factory",
        state_dir=tmp_path / "github_state",
    )


def test_durable_journal_records_publish_intent_and_confirm(publisher, tmp_path):
    # Mock successful git push and ls-remote
    local_sha = "a" * 40

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "get-url" in args:
            res.stdout = "https://github.com/moruku36/ai-engineering-factory.git\n"
        elif "rev-parse" in args:
            res.stdout = local_sha + "\n"
        elif "push" in args:
            res.stdout = "pushed\n"
        elif "ls-remote" in args:
            res.stdout = f"{local_sha} refs/heads/feature/test\n"
        return res

    with patch("subprocess.run", side_effect=mock_sub):
        sha = publisher.publish_branch(tmp_path, "feature/test")
        assert sha == local_sha

    with publisher._get_connection() as conn:
        row = conn.execute("SELECT action, target_branch, head_sha, status FROM operations;").fetchone()
        assert row is not None
        assert row[0] == "publish_branch"
        assert row[1] == "feature/test"
        assert row[2] == local_sha
        assert row[3] == "PUBLISHED"


def test_crash_reconciliation_recovers_pending_publish(publisher, tmp_path):
    # Simulate a crash: an operation was recorded as PENDING but controller died before confirming
    local_sha = "b" * 40
    publisher._record_intent("pub-crash-1", "publish_branch", "feature/crash", head_sha=local_sha)

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "ls-remote" in args:
            res.stdout = f"{local_sha} refs/heads/feature/crash\n"
        return res

    with patch("subprocess.run", side_effect=mock_sub):
        reconciled = publisher.reconcile_pending_operations(tmp_path)
        assert len(reconciled) == 1
        assert reconciled[0]["op_id"] == "pub-crash-1"
        assert reconciled[0]["status"] == "RECONCILED"

    with publisher._get_connection() as conn:
        status = conn.execute("SELECT status FROM operations WHERE op_id = 'pub-crash-1';").fetchone()[0]
        assert status == "RECONCILED"


def test_get_pr_merge_status_read_only(publisher):
    open_pr_json = json.dumps({
        "number": 10,
        "state": "OPEN",
        "headRefOid": "c" * 40,
    })

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = open_pr_json
        return res

    with patch("subprocess.run", side_effect=mock_sub):
        res = publisher.get_pr_merge_status(10)
        assert res["merged"] is False
        assert res["state"] == "OPEN"
        assert res["head_sha"] == "c" * 40


def test_verify_human_merge_detects_unmerged_state(publisher):
    open_pr_json = json.dumps({
        "number": 10,
        "state": "OPEN",
        "headRefOid": "c" * 40,
    })

    mock_approvals = MagicMock()
    mock_approvals.verify_consumed_token_binding.return_value = {"token_id": "tok-ok", "consumed": True}

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = open_pr_json
        return res

    with patch("subprocess.run", side_effect=mock_sub):
        res = publisher.verify_human_merge(
            10, expected_head_sha="c" * 40,
            approval_manager=mock_approvals, approval_token_id="tok-ok",
        )
        assert res["merged"] is False
        assert res["state"] == "OPEN"


def test_verify_human_merge_rejects_sha_mismatch(publisher):
    merged_pr_json = json.dumps({
        "number": 11,
        "state": "MERGED",
        "mergedAt": "2026-09-16T12:00:00Z",
        "mergeCommit": {"oid": "d" * 40},
        "headRefOid": "different" + "0" * 31,
    })

    mock_approvals = MagicMock()
    mock_approvals.verify_consumed_token_binding.return_value = {"token_id": "tok-ok", "consumed": True}

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = merged_pr_json
        return res

    with patch("subprocess.run", side_effect=mock_sub), pytest.raises(GitHubPRError, match="differs from expected"):
        publisher.verify_human_merge(
            11, expected_head_sha="expected" + "0" * 32,
            approval_manager=mock_approvals, approval_token_id="tok-ok",
        )


def test_verify_human_merge_success(publisher):
    target_sha = "e" * 40
    merge_sha = "f" * 40
    merged_pr_json = json.dumps({
        "number": 12,
        "state": "MERGED",
        "mergedAt": "2026-09-16T12:30:00Z",
        "mergeCommit": {"oid": merge_sha},
        "headRefOid": target_sha,
        "mergedBy": {"login": "human-operator"},
    })

    mock_approvals = MagicMock()
    mock_approvals.verify_consumed_token_binding.return_value = {"token_id": "tok-ok", "consumed": True}

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = merged_pr_json
        return res

    with patch("subprocess.run", side_effect=mock_sub):
        res = publisher.verify_human_merge(
            12, expected_head_sha=target_sha,
            approval_manager=mock_approvals, approval_token_id="tok-ok",
        )
        assert res["merged"] is True
        assert res["state"] == "MERGED"
        assert res["head_sha"] == target_sha
        assert res["merged_by"] == "human-operator"


def test_verify_human_merge_rejects_bot_actor(publisher):
    merged_pr_json = json.dumps({
        "number": 13,
        "state": "MERGED",
        "mergedAt": "2026-09-16T12:30:00Z",
        "mergeCommit": {"oid": "1" * 40},
        "headRefOid": "2" * 40,
        "mergedBy": {"login": "github-actions[bot]"},
    })

    mock_approvals = MagicMock()
    mock_approvals.verify_consumed_token_binding.return_value = {"token_id": "tok-ok", "consumed": True}

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = merged_pr_json
        return res

    with patch("subprocess.run", side_effect=mock_sub), pytest.raises(GitHubPRError, match="merged by automated bot"):
        publisher.verify_human_merge(
            13, expected_head_sha="2" * 40,
            approval_manager=mock_approvals, approval_token_id="tok-ok",
        )


def test_verify_human_merge_validates_consumed_approval_token(publisher):
    from orchestrator.core.approval import ApprovalVerificationError
    target_sha = "3" * 40
    merged_pr_json = json.dumps({
        "number": 14,
        "state": "MERGED",
        "mergedAt": "2026-09-16T12:30:00Z",
        "mergeCommit": {"oid": "4" * 40},
        "headRefOid": target_sha,
        "mergedBy": {"login": "human-operator"},
    })

    mock_approvals = MagicMock()
    # Case 0: omitted approval data fails closed
    with pytest.raises(GitHubPRError, match="Human approval token is mandatory"):
        publisher.verify_human_merge(
            14, expected_head_sha=target_sha,
            approval_manager=None, approval_token_id=None,
        )

    # Case 1: unconsumed or invalid binding token
    mock_approvals.verify_consumed_token_binding.side_effect = ApprovalVerificationError(
        "Approval token 'tok-1' has not been consumed yet"
    )

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = merged_pr_json
        return res

    with patch("subprocess.run", side_effect=mock_sub), pytest.raises(GitHubPRError, match="has not been consumed yet"):
        publisher.verify_human_merge(
            14, expected_head_sha=target_sha,
            approval_manager=mock_approvals, approval_token_id="tok-1",
        )

    # Case 2: valid consumed token succeeds
    mock_approvals.verify_consumed_token_binding.side_effect = None
    mock_approvals.verify_consumed_token_binding.return_value = {
        "token_id": "tok-1",
        "action": "merge_pull_request",
        "head_sha": target_sha,
        "consumed": True,
    }
    with patch("subprocess.run", side_effect=mock_sub):
        res = publisher.verify_human_merge(
            14, expected_head_sha=target_sha,
            approval_manager=mock_approvals, approval_token_id="tok-1",
        )
        assert res["merged"] is True
        assert res["merged_by"] == "human-operator"


def test_attempt_automated_merge_blocked_by_hard_deny(publisher):
    from orchestrator.core.policy import HardDenyViolationError
    with pytest.raises(HardDenyViolationError, match="Automated merge of PR #99 is strictly prohibited"):
        publisher.attempt_automated_merge(99)
