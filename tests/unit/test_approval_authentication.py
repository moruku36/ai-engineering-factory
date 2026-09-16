"""Tests for human approver cryptographic authentication, authorization, and revocation."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.core.approval import (
    ApprovalManager,
    ApprovalReplayError,
    ApprovalRevokedError,
    ApprovalVerificationError,
    compute_argv_digest,
)
from orchestrator.core.auth import (
    ApproverIdentity,
    ApproverRegistry,
    AuthenticationError,
    AuthorizationError,
    derive_key_fingerprint,
)


@pytest.fixture
def test_keys():
    # Deterministic 32-byte secret keys for testing
    lead_key = b"operator-secret-key-for-alice-32b"
    dev_key = b"operator-secret-key-for-bob-lead-32b"
    unregistered_key = b"unregistered-attacker-key-32bytes"
    return {
        "alice_key": lead_key,
        "alice_fp": derive_key_fingerprint(lead_key),
        "bob_key": dev_key,
        "bob_fp": derive_key_fingerprint(dev_key),
        "attacker_key": unregistered_key,
    }


@pytest.fixture
def approver_registry(test_keys):
    reg = ApproverRegistry()
    reg.register(
        ApproverIdentity(
            user_id="alice",
            role="security_lead",
            key_fingerprint=test_keys["alice_fp"],
            allowed_actions=["*"],
        )
    )
    reg.register(
        ApproverIdentity(
            user_id="bob",
            role="developer",
            key_fingerprint=test_keys["bob_fp"],
            allowed_actions=["task_execution"],
        )
    )
    return reg


@pytest.fixture
def auth_mgr(tmp_path, approver_registry):
    return ApprovalManager(
        approvals_dir=tmp_path / "approvals",
        registry=approver_registry,
        enforce_authentication=True,
    )


def test_authenticated_approval_happy_path(auth_mgr, test_keys):
    action = "task_execution"
    repo = "https://github.com/moruku36/ai-engineering-factory"
    task_id = "TASK-001"
    head_sha = "a" * 40
    target_ref = "refs/heads/feature"
    argv_digest = compute_argv_digest(["python", "run.py"])
    policy_hash = "b" * 64
    plan_hash = "c" * 64
    expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()

    token = auth_mgr.issue_authenticated_token(
        action=action,
        repository=repo,
        task_id=task_id,
        head_sha=head_sha,
        target_ref=target_ref,
        argv_digest=argv_digest,
        policy_hash=policy_hash,
        plan_hash=plan_hash,
        approved_by="bob",
        operator_key=test_keys["bob_key"],
        expires_at=expires_at,
    )

    assert token["token_id"].startswith("tok-")
    assert token["key_id"] == test_keys["bob_fp"]
    assert "operator_signature" in token

    # Verification and atomic consumption succeeds
    auth_mgr.verify_and_consume_token(
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

    # Replay rejected
    with pytest.raises(ApprovalReplayError):
        auth_mgr.verify_and_consume_token(
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


def test_unregistered_key_rejected(auth_mgr, test_keys):
    with pytest.raises(AuthenticationError, match="not in the authorized approvers registry"):
        auth_mgr.issue_authenticated_token(
            action="task_execution",
            repository="repo",
            task_id="TASK-001",
            head_sha="a" * 40,
            target_ref="refs/heads/main",
            argv_digest="d" * 64,
            policy_hash="b" * 64,
            plan_hash="c" * 64,
            approved_by="attacker",
            operator_key=test_keys["attacker_key"],
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )


def test_key_impersonation_mismatch_rejected(auth_mgr, test_keys):
    # Attacker tries to approve as alice using their own key
    with pytest.raises(AuthenticationError, match="key fingerprint mismatch"):
        auth_mgr.issue_authenticated_token(
            action="task_execution",
            repository="repo",
            task_id="TASK-001",
            head_sha="a" * 40,
            target_ref="refs/heads/main",
            argv_digest="d" * 64,
            policy_hash="b" * 64,
            plan_hash="c" * 64,
            approved_by="alice",
            operator_key=test_keys["attacker_key"],
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )


def test_unauthorized_action_rejected(auth_mgr, test_keys):
    # Bob is only allowed 'task_execution', tries 'release_publish'
    with pytest.raises(AuthorizationError, match="lacks authorization for action 'release_publish'"):
        auth_mgr.issue_authenticated_token(
            action="release_publish",
            repository="repo",
            task_id="TASK-001",
            head_sha="a" * 40,
            target_ref="refs/heads/main",
            argv_digest="d" * 64,
            policy_hash="b" * 64,
            plan_hash="c" * 64,
            approved_by="bob",
            operator_key=test_keys["bob_key"],
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )


def test_token_revocation_prevents_consumption(auth_mgr, test_keys):
    action = "task_execution"
    repo = "repo"
    task_id = "TASK-001"
    head_sha = "a" * 40
    target_ref = "refs/heads/main"
    argv_digest = "d" * 64
    policy_hash = "b" * 64
    plan_hash = "c" * 64

    token = auth_mgr.issue_authenticated_token(
        action=action,
        repository=repo,
        task_id=task_id,
        head_sha=head_sha,
        target_ref=target_ref,
        argv_digest=argv_digest,
        policy_hash=policy_hash,
        plan_hash=plan_hash,
        approved_by="alice",
        operator_key=test_keys["alice_key"],
        expires_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    )

    # Revoke before consumption
    auth_mgr.revoke_token(token["token_id"], reason="Security incident alert")

    # Consumption must fail with ApprovalRevokedError
    with pytest.raises(ApprovalRevokedError, match="has been revoked"):
        auth_mgr.verify_and_consume_token(
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


def test_legacy_unauthenticated_token_rejected_in_enforced_mode(tmp_path, approver_registry):
    mgr_unauthenticated = ApprovalManager(
        approvals_dir=tmp_path / "approvals",
        enforce_authentication=False,
    )
    legacy_token = mgr_unauthenticated.issue_token(
        action="task_execution",
        repository="repo",
        task_id="TASK-001",
        head_sha="a" * 40,
        target_ref="refs/heads/main",
        argv_digest="d" * 64,
        policy_hash="b" * 64,
        plan_hash="c" * 64,
        approved_by="arbitrary_string",
        expires_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    )

    # When validated under an enforced manager with registry
    mgr_enforced = ApprovalManager(
        approvals_dir=tmp_path / "approvals",
        registry=approver_registry,
        enforce_authentication=True,
    )
    with pytest.raises(ApprovalVerificationError, match="Unauthenticated legacy approval token .* rejected"):
        mgr_enforced.verify_and_consume_token(
            token_id=legacy_token["token_id"],
            action="task_execution",
            repository="repo",
            task_id="TASK-001",
            head_sha="a" * 40,
            target_ref="refs/heads/main",
            argv_digest="d" * 64,
            policy_hash="b" * 64,
            plan_hash="c" * 64,
        )


def test_unconfigured_auth_blocks_approval(tmp_path):
    empty_reg = ApproverRegistry()  # not configured
    mgr = ApprovalManager(
        approvals_dir=tmp_path / "approvals",
        registry=empty_reg,
        enforce_authentication=True,
    )
    with pytest.raises(ApprovalVerificationError, match="authentication infrastructure is not configured \\(BLOCKED\\)"):
        mgr.issue_authenticated_token(
            action="task_execution",
            repository="repo",
            task_id="TASK-001",
            head_sha="a" * 40,
            target_ref="refs/heads/main",
            argv_digest="d" * 64,
            policy_hash="b" * 64,
            plan_hash="c" * 64,
            approved_by="alice",
            operator_key=b"1" * 32,
            expires_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        )
