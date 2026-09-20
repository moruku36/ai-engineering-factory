"""Real GitHub state publisher with git transport, remote ref verification, and idempotent PR management."""

import json
import re
import sqlite3
import subprocess
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.core.policy import PolicyEngine
from orchestrator.core.sqlite_util import connect_wal


class GitHubPublishError(Exception):
    """Raised when git push or remote ref verification fails."""


class GitHubPRError(Exception):
    """Raised when GitHub PR query or creation fails."""


_SUBPROCESS_TIMEOUT_SECONDS = 120


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run wrapper with a mandatory timeout.

    A hung `git`/`gh` invocation (stalled network, auth prompt) would otherwise block
    the control plane indefinitely. A timeout is surfaced as a synthetic non-zero
    returncode so existing `returncode != 0` checks handle it like any other failure.
    """
    kwargs.setdefault("timeout", _SUBPROCESS_TIMEOUT_SECONDS)
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            cmd,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\nCommand timed out after {kwargs['timeout']}s",
        )


class RealGitHubStatePublisher:
    """Publishes branches to remote and manages PRs with strict idempotency, durable journaling, and SHA verification."""

    def __init__(
        self,
        repo_slug: str = "moruku36/ai-engineering-factory",
        policy_engine: PolicyEngine | None = None,
        state_dir: Path | str | None = None,
    ):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_slug):
            raise ValueError("Invalid approved repository slug")
        self.repo_slug = repo_slug
        self.policy_engine = policy_engine or PolicyEngine()
        self.journal: list[dict[str, Any]] = []

        if state_dir:
            self.state_dir = Path(state_dir)
        else:
            self.state_dir = Path(__file__).resolve().parent.parent.parent / "state" / "github"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "github_operations.sqlite"
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return connect_wal(self.db_path, busy_timeout_ms=None)

    def _init_db(self) -> None:
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    op_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    repo_slug TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    head_sha TEXT,
                    base_branch TEXT,
                    pr_number INTEGER,
                    pr_url TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    details TEXT
                );
                """
            )

    def _record_intent(
        self,
        op_id: str,
        action: str,
        target_branch: str,
        head_sha: str | None = None,
        base_branch: str | None = None,
        details: str | None = None,
    ) -> None:
        now_iso = datetime.now(UTC).isoformat()
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                INSERT INTO operations (
                    op_id, action, repo_slug, target_branch, head_sha,
                    base_branch, status, created_at, details
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?);
                """,
                (op_id, action, self.repo_slug, target_branch, head_sha, base_branch, now_iso, details),
            )

    def _confirm_operation(
        self,
        op_id: str,
        status: str,
        pr_number: int | None = None,
        pr_url: str | None = None,
        details: str | None = None,
    ) -> None:
        now_iso = datetime.now(UTC).isoformat()
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                UPDATE operations
                SET status = ?, confirmed_at = ?, pr_number = COALESCE(?, pr_number),
                    pr_url = COALESCE(?, pr_url), details = COALESCE(?, details)
                WHERE op_id = ?;
                """,
                (status, now_iso, pr_number, pr_url, details, op_id),
            )

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
        destination = _run(
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
        local_sha_res = _run(
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

        op_id = f"pub-{uuid.uuid4().hex}"
        self._record_intent(op_id, "publish_branch", target_branch, head_sha=local_sha)

        # 2. Push to remote
        push_cmd = ["git", "push", "origin", f"{local_sha}:refs/heads/{target_branch}"]

        push_res = _run(push_cmd, cwd=str(root), capture_output=True, text=True, check=False)
        if push_res.returncode != 0:
            self._confirm_operation(op_id, "FAILED", details=push_res.stderr)
            raise GitHubPublishError(f"git push failed: {push_res.stderr}")

        # 3. Verify remote ref matches local SHA
        ls_res = _run(
            ["git", "ls-remote", urls[0], f"refs/heads/{target_branch}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if ls_res.returncode != 0:
            self._confirm_operation(op_id, "FAILED", details=ls_res.stderr)
            raise GitHubPublishError(f"git ls-remote failed: {ls_res.stderr}")

        lines = ls_res.stdout.strip().splitlines()
        if len(lines) != 1 or lines[0].split()[1:] != [f"refs/heads/{target_branch}"]:
            self._confirm_operation(op_id, "FAILED", details="Ref not found")
            raise GitHubPublishError(f"Remote ref refs/heads/{target_branch} not found after push")

        remote_sha = lines[0].split()[0]
        if remote_sha != local_sha:
            self._confirm_operation(op_id, "FAILED", details="SHA mismatch")
            raise GitHubPublishError(
                f"Remote SHA mismatch: local is {local_sha}, but remote is {remote_sha}"
            )

        self._confirm_operation(op_id, "PUBLISHED", details=f"SHA {local_sha}")
        self.journal.append({
            "op_id": op_id,
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

        op_id = f"pr-{uuid.uuid4().hex}"
        self._record_intent(op_id, "create_or_update_pr", head_branch, base_branch=base_branch)

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
        list_res = _run(list_cmd, capture_output=True, text=True, check=False)
        if list_res.returncode != 0:
            self._confirm_operation(op_id, "FAILED", details="PR lookup failed")
            raise GitHubPRError("PR lookup failed; refusing an uncertain create")
        try:
            prs = json.loads(list_res.stdout)
            if not isinstance(prs, list):
                self._confirm_operation(op_id, "FAILED", details="Malformed response")
                raise GitHubPRError("PR lookup returned a malformed response")
            if prs:
                existing = prs[0]
                record = {
                    **self._verified_pr(existing),
                    "reused": True,
                }
                self._confirm_operation(op_id, "REUSED", pr_number=record["number"], pr_url=record["url"])
                self.journal.append({"op_id": op_id, "action": "pr_reused", **record})
                return record
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            self._confirm_operation(op_id, "FAILED", details="Malformed evidence")
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
        create_res = _run(create_cmd, capture_output=True, text=True, check=False)
        if create_res.returncode != 0:
            # Check again in case it was created concurrently or timed out
            retry_list = _run(list_cmd, capture_output=True, text=True, check=False)
            if retry_list.returncode == 0:
                try:
                    prs = json.loads(retry_list.stdout)
                    if prs:
                        existing = prs[0]
                        record = {
                            **self._verified_pr(existing),
                            "reused": True,
                        }
                        self._confirm_operation(op_id, "REUSED_AFTER_ERROR", pr_number=record["number"], pr_url=record["url"])
                        self.journal.append({"op_id": op_id, "action": "pr_reused_after_error", **record})
                        return record
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
            self._confirm_operation(op_id, "FAILED", details=create_res.stderr)
            raise GitHubPRError(f"gh pr create failed: {create_res.stderr}")

        # Even a zero exit code is insufficient: re-query durable remote evidence.
        verified = _run(list_cmd, capture_output=True, text=True, check=False)
        if verified.returncode != 0:
            self._confirm_operation(op_id, "UNCERTAIN", details="Verify query failed")
            raise GitHubPRError("PR creation outcome unknown; reconcile before retry")
        try:
            prs = json.loads(verified.stdout)
            if not isinstance(prs, list) or len(prs) != 1:
                self._confirm_operation(op_id, "UNCERTAIN", details="Ambiguous evidence")
                raise GitHubPRError("PR creation outcome ambiguous; reconcile before retry")
            record = {**self._verified_pr(prs[0]), "reused": False}
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            self._confirm_operation(op_id, "UNCERTAIN", details="Invalid evidence")
            raise GitHubPRError("Invalid PR evidence after creation; reconcile before retry") from exc

        self._confirm_operation(op_id, "CREATED", pr_number=record["number"], pr_url=record["url"])
        self.journal.append({"op_id": op_id, "action": "pr_created", **record})
        return record

    def reconcile_pending_operations(self, repo_root: Path | str) -> list[dict[str, Any]]:
        """Reconcile unconfirmed PENDING operations after crash using durable remote evidence."""
        reconciled = []
        with closing(self._get_connection()) as conn:
            cursor = conn.execute(
                "SELECT op_id, action, target_branch, head_sha, base_branch FROM operations WHERE status = 'PENDING';"
            )
            pending = cursor.fetchall()
            for op_id, action, target_branch, head_sha, base_branch in pending:
                if action == "publish_branch":
                    ls_res = _run(
                        ["git", "ls-remote", f"https://github.com/{self.repo_slug}.git", f"refs/heads/{target_branch}"],
                        cwd=str(repo_root), capture_output=True, text=True, check=False,
                    )
                    if ls_res.returncode == 0:
                        lines = ls_res.stdout.strip().splitlines()
                        if lines and lines[0].split()[0] == head_sha:
                            conn.execute("UPDATE operations SET status = 'RECONCILED' WHERE op_id = ?;", (op_id,))
                            reconciled.append({"op_id": op_id, "action": action, "status": "RECONCILED"})
                elif action == "create_or_update_pr":
                    list_res = _run(
                        [
                            "gh", "pr", "list", "--repo", self.repo_slug, "--head", target_branch,
                            "--state", "all", "--json", "number,url,headRefOid,state",
                        ],
                        capture_output=True, text=True, check=False,
                    )
                    if list_res.returncode == 0:
                        try:
                            prs = json.loads(list_res.stdout)
                            if prs:
                                pr = prs[0]
                                conn.execute(
                                    "UPDATE operations SET status = 'RECONCILED', pr_number = ?, pr_url = ? WHERE op_id = ?;",
                                    (pr["number"], pr["url"], op_id),
                                )
                                reconciled.append({
                                    "op_id": op_id, "action": action, "status": "RECONCILED", "pr_number": pr["number"],
                                })
                        except (json.JSONDecodeError, KeyError, IndexError, sqlite3.Error):
                            pass
        return reconciled

    def _fetch_pr_view(self, pr_number: int) -> dict[str, Any]:
        """Query gh pr view for merge-status fields and parse the JSON response."""
        cmd = [
            "gh", "pr", "view", str(pr_number),
            "--repo", self.repo_slug,
            "--json", "number,state,mergedAt,mergeCommit,headRefOid,mergedBy",
        ]
        res = _run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise GitHubPRError(f"Failed to query PR #{pr_number} status from GitHub: {res.stderr}")

        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubPRError(f"Invalid JSON response from gh pr view #{pr_number}") from exc

    def get_pr_merge_status(
        self,
        pr_number: int,
    ) -> dict[str, Any]:
        """Read-only query of remote GitHub PR merge status without approval or human actor gate."""
        data = self._fetch_pr_view(pr_number)

        state = data.get("state")
        head_oid = data.get("headRefOid")
        merged_by = data.get("mergedBy") or {}
        actor_login = merged_by.get("login", "") if isinstance(merged_by, dict) else str(merged_by)
        merge_commit = data.get("mergeCommit", {})
        oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else merge_commit

        return {
            "number": pr_number,
            "merged": state == "MERGED",
            "state": state,
            "head_sha": head_oid,
            "merged_by": actor_login or "unknown",
            "merged_at": data.get("mergedAt"),
            "merge_commit": oid,
        }

    def verify_human_merge(
        self,
        pr_number: int,
        expected_head_sha: str,
        approval_manager: Any,
        approval_token_id: str,
        task_id: str,
        policy_hash: str,
        plan_hash: str,
        target_ref: str = "refs/heads/main",
    ) -> dict[str, Any]:
        """Verify remote GitHub PR state for verified human merge with matching head SHA.

        Security Path: Human approval verification and human actor verification cannot be bypassed.
        """
        if not approval_manager or not approval_token_id:
            raise GitHubPRError(
                f"Human approval token is mandatory for verifying PR #{pr_number} merge, but approval data was omitted"
            )

        from orchestrator.core.approval import ApprovalVerificationError
        try:
            if not task_id or not policy_hash or not plan_hash:
                raise GitHubPRError(
                    f"Complete approval binding attributes (task_id, policy_hash, plan_hash) are required "
                    f"for verifying PR #{pr_number} merge"
                )
            approval_manager.verify_consumed_token_binding(
                token_id=approval_token_id,
                action="merge_pull_request",
                repository=self.repo_slug,
                task_id=task_id,
                head_sha=expected_head_sha,
                target_ref=target_ref,
                policy_hash=policy_hash,
                plan_hash=plan_hash,
            )
        except ApprovalVerificationError as exc:
            raise GitHubPRError(f"Approval token verification failed for PR #{pr_number} merge: {exc}") from exc

        data = self._fetch_pr_view(pr_number)

        state = data.get("state")
        head_oid = data.get("headRefOid")

        if state != "MERGED":
            return {
                "merged": False,
                "state": state,
                "reason": f"PR #{pr_number} is not merged (current state: {state})",
            }

        if head_oid != expected_head_sha:
            raise GitHubPRError(
                f"Merged PR #{pr_number} head SHA '{head_oid}' differs from expected '{expected_head_sha}'"
            )

        merged_by = data.get("mergedBy")
        if not merged_by:
            raise GitHubPRError(
                f"PR #{pr_number} mergedBy information is missing or unavailable: fail-closed on unverified merge actor"
            )
        actor_login = merged_by.get("login", "") if isinstance(merged_by, dict) else str(merged_by)
        actor_login = actor_login.strip()
        if not actor_login or actor_login.lower() == "none":
            raise GitHubPRError(
                f"PR #{pr_number} mergedBy actor is empty or malformed: fail-closed on unverified merge actor"
            )
        if (
            actor_login.endswith("[bot]")
            or actor_login in ("github-actions", "dependabot", "coderabbitai")
        ):
            raise GitHubPRError(
                f"PR #{pr_number} was merged by automated bot '{actor_login}', not a verified human operator"
            )

        merge_commit = data.get("mergeCommit", {})
        oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else merge_commit

        return {
            "merged": True,
            "state": "MERGED",
            "merged_at": data.get("mergedAt"),
            "merge_commit": oid,
            "head_sha": head_oid,
            "merged_by": actor_login or "unknown",
        }

    def attempt_automated_merge(self, pr_number: int) -> None:
        """Attempt automated PR merge - strictly prohibited by Hard Deny policy."""
        from orchestrator.core.policy import HardDenyViolationError
        raise HardDenyViolationError(
            f"Automated merge of PR #{pr_number} is strictly prohibited by Hard Deny policy. "
            "All merges must be authorized and performed by a verified Human Operator."
        )


