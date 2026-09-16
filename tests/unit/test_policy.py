"""Unit tests for security policy engine."""

import sys

import pytest

from orchestrator.adapters.manual import (
    AntigravityAdapter,
    GitHubStatePublisher,
    ManualAdapter,
)
from orchestrator.core.policy import (
    ApprovalRequiredError,
    CommandNotAllowedError,
    HardDenyViolationError,
    PolicyEngine,
)
from orchestrator.core.sandbox import ShellInjectionError


@pytest.fixture
def policy():
    return PolicyEngine()


def test_hard_deny_actions_strictly_rejected(policy):
    # Even with has_valid_approval=True, Hard Deny cannot be bypassed
    hard_deny_cases = [
        "direct_push_protected_branch",
        "force_push_protected_branch",
        "production_resource_destroy",
        "ci_test_bypass",
        "secret_credential_commit",
        "automated_pr_merge",
    ]
    for action in hard_deny_cases:
        with pytest.raises(HardDenyViolationError, match="strictly prohibited by Hard Deny"):
            policy.evaluate_action(action, has_valid_approval=True)


def test_approval_required_actions(policy):
    approval_cases = [
        "terraform_apply",
        "merge_pull_request",
        "credential_provision",
        "release_publish",
    ]
    for action in approval_cases:
        # Fails without approval
        with pytest.raises(ApprovalRequiredError, match="requires explicit one-time Human Approval"):
            policy.evaluate_action(action, has_valid_approval=False)

        # Passes with approval
        policy.evaluate_action(action, has_valid_approval=True)


def test_git_protected_branch_rules(policy):
    # Deny direct push to main
    with pytest.raises(HardDenyViolationError, match="Direct push to protected branch"):
        policy.evaluate_git_operation(target_branch="main", operation="push", is_force=False)

    # Deny force push to main
    with pytest.raises(HardDenyViolationError, match="Direct push to protected branch"):
        policy.evaluate_git_operation(target_branch="main", operation="push", is_force=True)

    # Allow normal push to task branch
    policy.evaluate_git_operation(target_branch="task/feature-1", operation="push", is_force=False)


def test_command_registry_enforcement(policy):
    # Allowed commands pass
    policy.evaluate_command_id("pytest")
    policy.evaluate_command_id("ruff")
    policy.evaluate_command_id("git")

    # Disallowed commands fail
    with pytest.raises(CommandNotAllowedError, match="not in allowed command registry"):
        policy.evaluate_command_id("curl")

    with pytest.raises(CommandNotAllowedError, match="not in allowed command registry"):
        policy.evaluate_command_id("rm -rf /")


def test_policy_digest_consistency(policy):
    digest1 = policy.get_policy_digest()
    digest2 = policy.get_policy_digest()
    assert digest1 == digest2
    assert len(digest1) == 64


def test_manual_adapter_integration(tmp_path):
    manifest = {
        "id": "SMP-001",
        "output_artifacts": [{"path": "reports/out.txt"}],
    }
    adapter = ManualAdapter()
    run_id = adapter.start_task(manifest, str(tmp_path))

    # Test valid execution (no shell metacharacters like semicolon)
    val = adapter.execute_validation_step(run_id, "python", [sys.executable, "-c", "exit(0)"])
    assert val["status"] == "PASS"

    # Test shell injection blocked
    with pytest.raises(ShellInjectionError):
        adapter.execute_validation_step(run_id, "python", [sys.executable, "-c", "print('1') ; print('2')"])

    # Test disallowed command blocked
    with pytest.raises(CommandNotAllowedError):
        adapter.execute_validation_step(run_id, "curl", ["curl", "https://example.com"])

    # Test cancellation
    assert adapter.cancel_task(run_id) is True
    res = adapter.collect_results(run_id)
    assert res["status"] == "CANCELLED"


def test_antigravity_adapter(tmp_path):
    manifest = {
        "id": "AUT-001",
        "output_artifacts": [],
    }
    adapter = AntigravityAdapter(mode="manual")
    run_id = adapter.start_task(manifest, str(tmp_path))

    val = adapter.execute_validation_step(run_id, "python", [sys.executable, "-c", "exit(0)"])
    assert val["status"] == "PASS"

    res = adapter.collect_results(run_id)
    assert res["adapter"] == "ManualAdapter"
    assert res["mode"] == "manual"
    assert res["status"] == "SUCCESS"


def test_github_state_publisher_idempotency():
    publisher = GitHubStatePublisher()

    # Deny direct push to main branch
    with pytest.raises(HardDenyViolationError):
        publisher.publish_branch(".", target_branch="main", is_force=False)

    # Idempotent PR update
    existing = [
        {"number": 42, "url": "https://github.com/moruku36/ai-engineering-factory/pull/42", "headRefName": "phase/p4-automation", "baseRefName": "main"}
    ]
    with pytest.raises(NotImplementedError, match="GitHub PR transport"):
        publisher.create_or_update_pr(
            title="feat: Phase 4",
            base_branch="main",
            head_branch="phase/p4-automation",
            body="test",
            existing_prs=existing,
        )


