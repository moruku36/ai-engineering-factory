"""Real GitHub state publisher with git transport, remote ref verification, and idempotent PR management."""

import json
import re
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
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_slug):
            raise ValueError("Invalid approved repository slug")
        self.repo_slug = repo_slug
        self.policy_engine = policy_engine or PolicyEngine()
        self.journal: list[dict[str, Any]] = []

    @staticmethod
    def _validate_branch(branch: str) -> None:
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_.-]*", branch)
                or branch.startswith("refs/") or ".." in branch or "//" in branch
                or branch.endswith(("/", ".", ".lock"))):
            raise GitHubPublishError("Invalid or fully qualified branch name")

    def _verified_pr(self, pr: dict[str, Any]) -> dict[str, Any]:
        number = pr.get("number")
        expected_url = f"https://github.com/{self.repo_slug}/pull/{number}"
        if (type(number) is not int or number <= 0 or pr.get("url") != expected_url
                or pr.get("state") != "OPEN"
                or not re.fullmatch(r"[a-f0-9]{40}", pr.get("headRefOid") or "")):
            raise GitHubPRError("Remote PR evidence is invalid or no longer open")
        return {"number": number, "url": expected_url, "head_sha": pr["headRefOid"], "state": "OPEN"}

    def publish_branch(self, repo_root: Path | str, target_branch: str, is_force: bool = False) -> str:
        """Push branch to approved origin and verify remote ref matches local HEAD SHA."""
        root = Path(repo_root)
        # Policy enforcement
        if is_force:
            from orchestrator.core.policy import HardDenyViolationError
            raise HardDenyViolationError("Force push is strictly prohibited across all branches")

        self.policy_engine.evaluate_git_operation(target_branch, "push", is_force=is_force)
        self._validate_branch(target_branch)
        # Verify the push destination, not merely the fetch URL or a default slug.
        destination = subprocess.run(
            ["git", "remote", "get-url", "--push", "--all", "origin"],
            cwd=str(root), capture_output=True, text=True, check=False, timeout=30,
        )
        approved_urls = {
            f"https://github.com/{self.repo_slug}", f"https://github.com/{self.repo_slug}.git",
            f"git@github.com:{self.repo_slug}.git", f"ssh://git@github.com/{self.repo_slug}.git",
        }
        urls = destination.stdout.strip().splitlines()
        if destination.returncode != 0 or len(urls) != 1 or urls[0] not in approved_urls:
            raise GitHubPublishError("Origin push destination does not match the approved repository")

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
        if not re.fullmatch(r"[a-f0-9]{40}", local_sha):
            raise GitHubPublishError("Invalid local commit SHA")

        # 2. Push to remote
        push_cmd = ["git", "push", "origin", f"{local_sha}:refs/heads/{target_branch}"]

        push_res = subprocess.run(push_cmd, cwd=str(root), capture_output=True, text=True, check=False)
        if push_res.returncode != 0:
            raise GitHubPublishError(f"git push failed: {push_res.stderr}")

        # 3. Verify remote ref matches local SHA
        ls_res = subprocess.run(
            ["git", "ls-remote", urls[0], f"refs/heads/{target_branch}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if ls_res.returncode != 0:
            raise GitHubPublishError(f"git ls-remote failed: {ls_res.stderr}")

        lines = ls_res.stdout.strip().splitlines()
        if len(lines) != 1 or lines[0].split()[1:] != [f"refs/heads/{target_branch}"]:
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
        self._validate_branch(head_branch)
        self._validate_branch(base_branch)
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
        if list_res.returncode != 0:
            raise GitHubPRError("PR lookup failed; refusing an uncertain create")
        if list_res.returncode == 0:
            try:
                prs = json.loads(list_res.stdout)
                if not isinstance(prs, list):
                    raise GitHubPRError("PR lookup returned a malformed response")
                if prs:
                    existing = prs[0]
                    record = {
                        **self._verified_pr(existing),
                        "reused": True,
                    }
                    self.journal.append({"action": "pr_reused", **record})
                    return record
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise GitHubPRError("PR lookup returned malformed evidence; refusing create") from exc

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
                            **self._verified_pr(existing),
                            "reused": True,
                        }
                        self.journal.append({"action": "pr_reused_after_error", **record})
                        return record
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
            raise GitHubPRError(f"gh pr create failed: {create_res.stderr}")

        # Even a zero exit code is insufficient: re-query durable remote evidence.
        verified = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
        if verified.returncode != 0:
            raise GitHubPRError("PR creation outcome unknown; reconcile before retry")
        try:
            prs = json.loads(verified.stdout)
            if not isinstance(prs, list) or len(prs) != 1:
                raise GitHubPRError("PR creation outcome ambiguous; reconcile before retry")
            record = {**self._verified_pr(prs[0]), "reused": False}
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise GitHubPRError("Invalid PR evidence after creation; reconcile before retry") from exc
        self.journal.append({"action": "pr_created", **record})
        return record
