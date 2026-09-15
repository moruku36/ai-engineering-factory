"""Unit tests for approval token lifecycle and security bindings."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.core.approval import (
    ApprovalExpiredError,
    ApprovalManager,
    ApprovalReplayError,
    ApprovalVerificationError,
    compute_argv_digest,
)


@pytest.fixture
def approval_mgr(tmp_path):
    return ApprovalManager(approvals_dir=tmp_path / "approvals")


def test_approval_happy_path(approval_mgr):
    action = "merge_pull_request"
    repo = "https://github.com/moruku36/ai-engineering-factory"
    task_id = "TASK-001"
    head_sha = "a" * 40
    target_ref = "refs/heads/main"
    argv = ["gh", "pr", "merge", "1"]
    argv_digest = compute_argv_digest(argv)
    policy_hash = "b" * 64
    plan_hash = "c" * 64
    expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()

    token = approval_mgr.issue_token(
        action=action,
        repository=repo,
        task_id=task_id,
        head_sha=head_sha,
        target_ref=target_ref,
        argv_digest=argv_digest,
        policy_hash=policy_hash,
        plan_hash=plan_hash,
        approved_by="human_lead",
        expires_at=expires_at,
    )
    assert token["token_id"].startswith("tok-")
    assert not token["consumed"]

    # Verify and consume
    approval_mgr.verify_and_consume_token(
        token_id=token["token_id"],
        action=action,
        repository=repo,
        task_id=task_id,
        head_sha=head_sha,
        target_ref=target_ref,
        argv_digest=argv_digest,
        policy_hash=policy_hash,
        plan_hash=plan_hash,
    )

    # Replay attack: second consumption MUST fail
    with pytest.raises(ApprovalReplayError, match="has already been consumed"):
        approval_mgr.verify_and_consume_token(
            token_id=token["token_id"],
            action=action,
            repository=repo,
            task_id=task_id,
            head_sha=head_sha,
            target_ref=target_ref,
            argv_digest=argv_digest,
            policy_hash=policy_hash,
            plan_hash=plan_hash,
        )


def test_approval_binding_mismatch_rejected(approval_mgr):
    token = approval_mgr.issue_token(
        action="terraform_apply",
        repository="repo",
        task_id="TASK-002",
        head_sha="1" * 40,
        target_ref="refs/heads/main",
        argv_digest="2" * 64,
        policy_hash="3" * 64,
        plan_hash="4" * 64,
        approved_by="admin",
        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    )

    # Tampered head_sha
    with pytest.raises(ApprovalVerificationError, match="Token binding mismatch on 'head_sha'"):
        approval_mgr.verify_and_consume_token(
            token_id=token["token_id"],
            action="terraform_apply",
            repository="repo",
            task_id="TASK-002",
            head_sha="different_head_sha" + "0" * 22,
            target_ref="refs/heads/main",
            argv_digest="2" * 64,
            policy_hash="3" * 64,
            plan_hash="4" * 64,
        )


def test_approval_expired_rejected(approval_mgr):
    # Already expired token
    expired_time = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    token = approval_mgr.issue_token(
        action="release_publish",
        repository="repo",
        task_id="TASK-003",
        head_sha="5" * 40,
        target_ref="refs/heads/main",
        argv_digest="6" * 64,
        policy_hash="7" * 64,
        plan_hash="8" * 64,
        approved_by="admin",
        expires_at=expired_time,
    )

    with pytest.raises(ApprovalExpiredError, match="expired at"):
        approval_mgr.verify_and_consume_token(
            token_id=token["token_id"],
            action="release_publish",
            repository="repo",
            task_id="TASK-003",
            head_sha="5" * 40,
            target_ref="refs/heads/main",
            argv_digest="6" * 64,
            policy_hash="7" * 64,
            plan_hash="8" * 64,
        )
