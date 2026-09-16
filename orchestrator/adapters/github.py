"""Real GitHub state publisher with git transport, remote ref verification, and idempotent PR management."""

import json
import subprocess
from pathlib import Path
from typing import Any

from orchestrator.core.policy import PolicyEngine


class GitHubPublishError(Exception):
    """Raised when git push or remote ref verification fails."""


class GitHubPRError(Exception):
    """Raised when GitHub PR query or creation fails."""


class RealGitHubStatePublisher:
    """Publishes branches to remote and manages PRs with strict idempotency and SHA verification."""

    def __init__(self, repo_slug: str = "moruku36/ai-engineering-factory", policy_engine: PolicyEngine | None = None):
        self.repo_slug = repo_slug
        self.policy_engine = policy_engine or PolicyEngine()
        self.journal: list[dict[str, Any]] = []

    def publish_branch(self, repo_root: Path | str, target_branch: str, is_force: bool = False) -> str:
        """Push branch to approved origin and verify remote ref matches local HEAD SHA."""
        root = Path(repo_root)
        # Policy enforcement
        if is_force:
            from orchestrator.core.policy import HardDenyViolationError
            raise HardDenyViolationError("Force push is strictly prohibited across all branches")

        self.policy_engine.evaluate_git_operation(target_branch, "push", is_force=is_force)

        # 1. Get local HEAD SHA
        local_sha_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if local_sha_res.returncode != 0:
            raise GitHubPublishError(f"Failed to get local HEAD SHA: {local_sha_res.stderr}")
        local_sha = local_sha_res.stdout.strip()

        # 2. Push to remote
        push_cmd = ["git", "push", "origin", f"HEAD:{target_branch}"]
        if is_force:
            push_cmd.append("--force")

        push_res = subprocess.run(push_cmd, cwd=str(root), capture_output=True, text=True, check=False)
        if push_res.returncode != 0:
            raise GitHubPublishError(f"git push failed: {push_res.stderr}")

        # 3. Verify remote ref matches local SHA
        ls_res = subprocess.run(
            ["git", "ls-remote", "origin", f"refs/heads/{target_branch}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if ls_res.returncode != 0:
            raise GitHubPublishError(f"git ls-remote failed: {ls_res.stderr}")

        lines = ls_res.stdout.strip().splitlines()
        if not lines:
            raise GitHubPublishError(f"Remote ref refs/heads/{target_branch} not found after push")

        remote_sha = lines[0].split()[0]
        if remote_sha != local_sha:
            raise GitHubPublishError(
                f"Remote SHA mismatch: local is {local_sha}, but remote is {remote_sha}"
            )

        self.journal.append({
            "action": "publish_branch",
            "branch": target_branch,
            "sha": local_sha,
            "status": "PUBLISHED",
        })
        return local_sha

    def create_or_update_pr(
        self,
        title: str,
        base_branch: str,
        head_branch: str,
        body: str,
    ) -> dict[str, Any]:
        """Idempotently create or retrieve PR using gh CLI."""
        # 1. Check if PR already exists for head_branch -> base_branch
        list_cmd = [
            "gh",
            "pr",
            "list",
            "--repo",
            self.repo_slug,
            "--head",
            head_branch,
            "--base",
            base_branch,
            "--state",
            "all",
            "--json",
            "number,url,headRefOid,state,title",
        ]
        list_res = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
        if list_res.returncode == 0:
            try:
                prs = json.loads(list_res.stdout)
                if prs:
                    existing = prs[0]
                    record = {
                        "number": existing["number"],
                        "url": existing["url"],
                        "head_sha": existing.get("headRefOid"),
                        "state": existing["state"],
                        "reused": True,
                    }
                    self.journal.append({"action": "pr_reused", **record})
                    return record
            except (json.JSONDecodeError, KeyError, IndexError):
                pass

        # 2. Create new PR
        create_cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            self.repo_slug,
            "--head",
            head_branch,
            "--base",
            base_branch,
            "--title",
            title,
            "--body",
            body,
        ]
        create_res = subprocess.run(create_cmd, capture_output=True, text=True, check=False)
        if create_res.returncode != 0:
            # Check again in case it was created concurrently or timed out
            retry_list = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
            if retry_list.returncode == 0:
                try:
                    prs = json.loads(retry_list.stdout)
                    if prs:
                        existing = prs[0]
                        record = {
                            "number": existing["number"],
                            "url": existing["url"],
                            "head_sha": existing.get("headRefOid"),
                            "state": existing["state"],
                            "reused": True,
                        }
                        self.journal.append({"action": "pr_reused_after_error", **record})
                        return record
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
            raise GitHubPRError(f"gh pr create failed: {create_res.stderr}")

        pr_url = create_res.stdout.strip()
        # Parse PR number from URL
        pr_number = None
        try:
            pr_number = int(pr_url.rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            pass

        record = {
            "number": pr_number,
            "url": pr_url,
            "head_sha": None,
            "state": "OPEN",
            "reused": False,
        }
        self.journal.append({"action": "pr_created", **record})
        return record
