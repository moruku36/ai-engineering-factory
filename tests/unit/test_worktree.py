"""Unit tests for worktree management, path sanitization, and handoff recovery."""

import pytest

from orchestrator.core.worktree import (
    HandoffManager,
    HandoffVerificationError,
    PathSecurityError,
    sanitize_relative_path,
    validate_paths_against_policy,
)


def test_sanitize_relative_path_safety():
    # Valid relative paths
    assert sanitize_relative_path("orchestrator/core/state.py") == "orchestrator/core/state.py"
    assert sanitize_relative_path("foo/bar.txt") == "foo/bar.txt"

    # Reject traversal
    with pytest.raises(PathSecurityError, match="Path traversal detected"):
        sanitize_relative_path("../secret.txt")

    with pytest.raises(PathSecurityError, match="Path traversal detected"):
        sanitize_relative_path("orchestrator/../../etc/passwd")

    # Reject absolute and UNC
    with pytest.raises(PathSecurityError, match="Absolute or UNC"):
        sanitize_relative_path("C:/Windows/System32")

    with pytest.raises(PathSecurityError, match="Absolute or UNC"):
        sanitize_relative_path("\\\\server\\share\\data")


def test_validate_paths_deny_first():
    allowed = ["src/", "tests/"]
    prohibited = ["src/secrets/", ".github/"]

    # Valid change
    validate_paths_against_policy(["src/app.py", "tests/test_app.py"], allowed, prohibited)

    # Denied by prohibited rule despite being in allowed prefix
    with pytest.raises(PathSecurityError, match="matches prohibited path rule"):
        validate_paths_against_policy(["src/secrets/keys.txt"], allowed, prohibited)

    # Denied because not in allowed paths
    with pytest.raises(PathSecurityError, match="is not within any allowed paths"):
        validate_paths_against_policy(["README.md"], allowed, prohibited)


def test_handoff_save_and_resume_verification(tmp_path):
    mgr = HandoffManager(handoffs_dir=tmp_path / "handoffs")
    task_id = "TASK-001"
    spec_digest = "a" * 64
    base_sha = "b" * 40

    mgr.save_handoff(
        task_id=task_id,
        run_id="run-001",
        attempt=1,
        spec_digest=spec_digest,
        policy_digest="c" * 64,
        base_sha=base_sha,
        head_sha="d" * 40,
        completed_steps=["step-1"],
        pending_steps=["step-2"],
        changed_paths=["src/foo.py"],
        validations=[{"command_id": "pytest", "status": "PASS"}],
        artifacts={"report": "hash123"},
        is_dirty=False,
        lease_id="lease-001",
        blocked_reason=None,
        next_action="run step-2",
        required_approvals=[],
    )

    # Valid resume
    data = mgr.verify_resume_preflight(task_id, spec_digest, base_sha)
    assert data["task_id"] == task_id
    assert data["attempt"] == 1

    # Invalidate if spec digest changed
    with pytest.raises(HandoffVerificationError, match="Spec digest mismatch"):
        mgr.verify_resume_preflight(task_id, "different" + "a" * 55, base_sha)

    # Invalidate if base sha changed
    with pytest.raises(HandoffVerificationError, match="Base commit moved"):
        mgr.verify_resume_preflight(task_id, spec_digest, "different" + "b" * 31)

    # Candidate evaluation verification
    valid_res = mgr.verify_candidate_evaluation(task_id, head_sha)
    assert valid_res["head_sha"] == head_sha

    # Invalidate if candidate SHA changed (stale evidence)
    with pytest.raises(HandoffVerificationError, match="Stale evidence rejected"):
        mgr.verify_candidate_evaluation(task_id, "different" + "c" * 31)

