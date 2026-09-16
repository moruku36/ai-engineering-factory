"""Unit and contract tests for real Antigravity and GitHub adapters (AC-H07, AC-H08)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.adapters.antigravity import NativeAntigravityAdapter, probe_antigravity_runtime
from orchestrator.adapters.github import GitHubPublishError, RealGitHubStatePublisher
from orchestrator.core.policy import HardDenyViolationError


def test_probe_antigravity_detects_installed_runtime():
    probe = probe_antigravity_runtime()
    assert "available" in probe
    assert "probe_timestamp" in probe
    if probe["available"]:
        assert probe["binary_path"] is not None
        assert Path(probe["binary_path"]).exists()
    else:
        assert probe["binary_path"] is None


def test_native_antigravity_lifecycle(tmp_path, monkeypatch):
    dummy_bin = tmp_path / "dummy_agentapi.bat"
    dummy_bin.write_text("@echo off\nexit /b 0\n", encoding="utf-8")

    monkeypatch.setattr(
        "orchestrator.adapters.antigravity.probe_antigravity_runtime",
        lambda: {
            "available": True,
            "binary_path": str(dummy_bin),
            "version": "0.1.0-test",
            "probe_timestamp": "2026-09-16T00:00:00Z",
        },
    )

    adapter = NativeAntigravityAdapter()
    manifest = {
        "id": "TASK-001",
        "spec": {"title": "Test Antigravity Task"},
        "allowed_paths": ["src/"],
    }
    run_id = adapter.start_task(manifest, str(tmp_path))
    assert run_id.startswith("agy-")

    poll = adapter.poll_task(run_id)
    assert poll["status"] == "RUNNING"

    results = adapter.collect_results(run_id)
    assert results["task_id"] == "TASK-001"
    assert results["adapter"] == "NativeAntigravityAdapter"
    assert results["status"] == "SUCCESS"

    # Cancel test
    run_id2 = adapter.start_task(manifest, str(tmp_path))
    assert adapter.cancel_task(run_id2) is True
    poll2 = adapter.poll_task(run_id2)
    assert poll2["status"] == "CANCELLED"


def test_real_github_publisher_policy_blocks_main_push(tmp_path):
    publisher = RealGitHubStatePublisher()
    # Policy must strictly reject pushing directly to main
    with pytest.raises(HardDenyViolationError, match="Direct push"):
        publisher.publish_branch(tmp_path, "main")

    # Policy must strictly reject force push
    with pytest.raises(HardDenyViolationError, match="Force push"):
        publisher.publish_branch(tmp_path, "task/foo", is_force=True)


def test_real_github_publisher_verifies_remote_sha(tmp_path):
    publisher = RealGitHubStatePublisher()

    # Mock subprocess.run to simulate git rev-parse and git push, then mismatched git ls-remote
    def mock_subprocess(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "rev-parse" in args:
            res.stdout = "a" * 40 + "\n"
        elif "push" in args:
            res.stdout = "pushed\n"
        elif "ls-remote" in args:
            res.stdout = ("b" * 40) + " refs/heads/task/test\n"  # Mismatch!
        return res

    with patch("subprocess.run", side_effect=mock_subprocess), pytest.raises(GitHubPublishError, match="Remote SHA mismatch"):
        publisher.publish_branch(tmp_path, "task/test")


def test_real_github_publisher_pr_idempotency():
    publisher = RealGitHubStatePublisher()

    # Mock gh pr list returning an existing PR
    existing_pr_json = '[{"number": 42, "url": "https://github.com/moruku36/ai-engineering-factory/pull/42", "headRefOid": "abc", "state": "OPEN"}]'

    def mock_gh(args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "list" in args:
            res.stdout = existing_pr_json
        return res

    with patch("subprocess.run", side_effect=mock_gh):
        res = publisher.create_or_update_pr(
            title="Feat",
            base_branch="main",
            head_branch="task/test",
            body="PR Description",
        )
        assert res["number"] == 42
        assert res["reused"] is True
        assert len(publisher.journal) == 1
