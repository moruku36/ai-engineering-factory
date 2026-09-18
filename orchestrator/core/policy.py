"""Security policy engine enforcing hard deny and human-approval contracts."""

import hashlib
import json
from pathlib import Path
from typing import Any

from orchestrator.core.schema import validate_against_schema

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "profiles" / "default_policy.json"


class HardDenyViolationError(Exception):
    """Raised when an operation violates an absolute hard deny rule."""


class ApprovalRequiredError(Exception):
    """Raised when an operation requires explicit human approval token."""


class CommandNotAllowedError(Exception):
    """Raised when a command is not in the allowed command registry."""


class BranchProtectionError(Exception):
    """Raised when attempting forbidden operations on protected branches."""


# Hard Deny actions: CANNOT be bypassed under any circumstances
HARD_DENY_ACTIONS = {
    "direct_push_protected_branch",
    "force_push_protected_branch",
    "production_resource_destroy",
    "cloud_infrastructure_destroy",
    "ci_test_bypass",
    "secret_credential_commit",
    "unrestricted_external_upload",
    "unrestricted_host_fs_escape",
    "automated_pr_merge",
}

# Actions that REQUIRE explicit human approval token
APPROVAL_REQUIRED_ACTIONS = {
    "non_production_destroy",
    "terraform_apply",
    "iam_permission_grant",
    "credential_provision",
    "public_network_access",
    "history_rewrite",
    "release_publish",
    "package_deployment",
    "merge_pull_request",
}

DEFAULT_ALLOWED_COMMANDS = {
    "pytest",
    "ruff",
    "python",
    "python3",
    "git",
    "npm",
    "node",
}

PROTECTED_BRANCHES = {"main", "master", "release"}


class PolicyEngine:
    """Evaluates operations against security guardrails."""

    def __init__(self, policy_data: dict[str, Any] | None = None):
        if policy_data is None:
            self.policy_data = {
                "schema_version": "2020-12",
                "policy_id": "DEFAULT-SEC-POLICY-V1",
                "hard_deny_actions": sorted(HARD_DENY_ACTIONS),
                "approval_required_actions": sorted(APPROVAL_REQUIRED_ACTIONS),
                "allowed_commands": sorted(DEFAULT_ALLOWED_COMMANDS),
                "protected_branches": sorted(PROTECTED_BRANCHES),
            }
        else:
            self.policy_data = policy_data

        validate_against_schema(self.policy_data, "policy.schema.json")
        self.hard_deny = set(self.policy_data["hard_deny_actions"])
        self.approval_required = set(self.policy_data["approval_required_actions"])
        self.allowed_commands = set(self.policy_data["allowed_commands"])
        self.protected_branches = set(self.policy_data["protected_branches"])

    def get_policy_digest(self) -> str:
        canonical = json.dumps(self.policy_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def evaluate_action(self, action: str, has_valid_approval: bool = False) -> None:
        """Evaluate an action against hard deny and approval requirements."""
        if action in self.hard_deny:
            raise HardDenyViolationError(
                f"Action '{action}' is strictly prohibited by Hard Deny policy and cannot be approved"
            )

        if action in self.approval_required and not has_valid_approval:
            raise ApprovalRequiredError(
                f"Action '{action}' requires explicit one-time Human Approval"
            )

    def evaluate_git_operation(self, target_branch: str, operation: str, is_force: bool = False) -> None:
        """Evaluate git push/branch operations."""
        if target_branch in self.protected_branches:
            if operation in ("push", "direct_commit"):
                raise HardDenyViolationError(
                    f"Direct push to protected branch '{target_branch}' is strictly prohibited"
                )
            if is_force:
                raise HardDenyViolationError(
                    f"Force push to protected branch '{target_branch}' is strictly prohibited"
                )

    def evaluate_command_id(self, command_id: str) -> None:
        """Evaluate whether a command is registered in allowed commands."""
        base_cmd = command_id.split()[0] if command_id else ""
        if base_cmd not in self.allowed_commands:
            raise CommandNotAllowedError(
                f"Command '{command_id}' is not in allowed command registry: {sorted(self.allowed_commands)}"
            )

    def evaluate_merge_operation(self, is_automated: bool = True, has_human_approval: bool = False) -> None:
        """Evaluate PR merge operation against Hard Deny and Human Approval policies."""
        if is_automated:
            raise HardDenyViolationError(
                "Action 'automated_pr_merge' is strictly prohibited by Hard Deny policy and cannot be approved"
            )
        if not has_human_approval:
            raise ApprovalRequiredError(
                "Action 'merge_pull_request' requires explicit one-time Human Approval"
            )

