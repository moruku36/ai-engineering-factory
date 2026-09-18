"""Unit tests for worktree management, path sanitization, and handoff recovery."""

import subprocess

import pytest

from orchestrator.core.worktree import (
    HandoffManager,
    HandoffVerificationError,
    PathSecurityError,
    compute_base_file_digests,
    sanitize_relative_path,
    snapshot_worktree,
    validate_paths_against_policy,
)


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)


def _commit_all(path, message):
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", message], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()


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
    head_sha = "d" * 40

    mgr.save_handoff(
        task_id=task_id,
        run_id="run-001",
        attempt=1,
        spec_digest=spec_digest,
        policy_digest="c" * 64,
        base_sha=base_sha,
        head_sha=head_sha,
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


def test_snapshot_worktree_copies_only_tracked_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "tracked.py").write_text("x = 1", encoding="utf-8")
    _commit_all(repo, "initial")
    (repo / "untracked.py").write_text("should not appear", encoding="utf-8")

    dst, digest, files = snapshot_worktree(repo, tmp_path / "snapshot")

    assert (dst / "tracked.py").read_text(encoding="utf-8") == "x = 1"
    assert not (dst / "untracked.py").exists()
    assert not (dst / ".git").exists()
    assert files == {"tracked.py": files["tracked.py"]}
    assert len(digest) == 64


def test_snapshot_worktree_rejects_existing_destination(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.py").write_text("a", encoding="utf-8")
    _commit_all(repo, "initial")

    dest = tmp_path / "already-here"
    dest.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        snapshot_worktree(repo, dest)


def test_compute_base_file_digests_matches_git_show(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "orchestrator").mkdir()
    (repo / "orchestrator" / "a.py").write_text("base", encoding="utf-8")
    (repo / "orchestrator" / "b.py").write_text("unchanged", encoding="utf-8")
    base_sha = _commit_all(repo, "base")

    digests = compute_base_file_digests(repo, base_sha, allowed_paths=["orchestrator/"])
    assert set(digests) == {"orchestrator/a.py", "orchestrator/b.py"}

    # Now mutate and confirm the base digests still describe the original content,
    # regardless of what the worktree currently holds.
    (repo / "orchestrator" / "a.py").write_text("changed", encoding="utf-8")
    unchanged_digests = compute_base_file_digests(repo, base_sha, allowed_paths=["orchestrator/"])
    assert unchanged_digests == digests


def test_snapshot_and_base_digests_reveal_genuine_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "orchestrator").mkdir()
    (repo / "orchestrator" / "a.py").write_text("base", encoding="utf-8")
    (repo / "orchestrator" / "b.py").write_text("unchanged", encoding="utf-8")
    base_sha = _commit_all(repo, "base")

    (repo / "orchestrator" / "a.py").write_text("changed by agent", encoding="utf-8")
    _commit_all(repo, "agent change")

    base_files = compute_base_file_digests(repo, base_sha, allowed_paths=["orchestrator/"])
    _, _, snapshot_files = snapshot_worktree(repo, tmp_path / "snapshot")

    changed = sorted(p for p, d in snapshot_files.items() if base_files.get(p) != d)
    assert changed == ["orchestrator/a.py"]

