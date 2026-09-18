"""Worktree governance, path inspection, and handoff resume engine."""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SAFE_RUNTIME_ROOT = Path(__file__).resolve().parent.parent.parent / "runtime-root"


class PathSecurityError(Exception):
    """Raised when path traversal, forbidden prefixes, or symlink escapes are detected."""


class HandoffVerificationError(Exception):
    """Raised when resuming from a handoff with invalid SHA, expired lease, or corrupted state."""


def sanitize_relative_path(path_str: str) -> str:
    """Validate and sanitize a path to ensure it is relative and does not escape via .. or UNC."""
    # Check for UNC or drive letters
    if path_str.startswith(("//", "\\\\")) or (len(path_str) > 1 and path_str[1] == ":"):
        raise PathSecurityError(f"Absolute or UNC paths are strictly forbidden: {path_str}")

    # Check for null bytes
    if "\0" in path_str:
        raise PathSecurityError(f"Null bytes in path detected: {path_str}")

    # Normalize to forward slashes
    normalized = path_str.replace("\\", "/")
    parts = PurePosixPath(normalized).parts

    if ".." in parts:
        raise PathSecurityError(f"Path traversal detected ('..'): {path_str}")

    if PurePosixPath(normalized).is_absolute():
        raise PathSecurityError(f"Absolute paths are forbidden: {path_str}")

    return normalized.lstrip("/")


def validate_paths_against_policy(
    changed_paths: list[str],
    allowed_paths: list[str],
    prohibited_paths: list[str],
) -> None:
    """Validate changed paths:
    1. Sanitize against traversal.
    2. Prohibited paths take precedence (deny-first).
    3. Must match at least one prefix in allowed_paths (if allowed_paths is specified).
    """
    clean_prohibited = [sanitize_relative_path(p) for p in prohibited_paths]
    clean_allowed = [sanitize_relative_path(p) for p in allowed_paths]

    for path in changed_paths:
        clean_path = sanitize_relative_path(path)

        # Deny-first check
        for denied in clean_prohibited:
            if clean_path == denied or clean_path.startswith(denied.rstrip("/") + "/"):
                raise PathSecurityError(
                    f"Path '{clean_path}' matches prohibited path rule '{denied}'"
                )

        # Allow-list check
        if clean_allowed:
            allowed = False
            for allowable in clean_allowed:
                if clean_path == allowable or clean_path.startswith(allowable.rstrip("/") + "/"):
                    allowed = True
                    break
            if not allowed:
                raise PathSecurityError(
                    f"Path '{clean_path}' is not within any allowed paths: {allowed_paths}"
                )


def snapshot_worktree(worktree_dir: Path | str, dest_dir: Path | str) -> tuple[Path, str, dict[str, str]]:
    """Export a read-only, git-tracked-only snapshot of a worktree for container mounting.

    Enumerates exactly the files git considers tracked at the worktree's current state
    (via `git ls-files --cached`), copies each into dest_dir with symlinks and any
    non-regular file rejected, and returns:
      - dest_dir itself,
      - a deterministic content digest over the whole snapshot (for future approval
        binding), and
      - a rel_path -> sha256 map of every snapshotted file, so a caller can compute a
        genuine diff (see IndependentVerifier.compute_diff / compute_base_file_digests)
        instead of treating the entire snapshot as "changed".

    This snapshot is what should be bind-mounted read-only into the container, rather
    than the live worktree path: it excludes .git and any ignored/untracked scratch
    content, and copying it (instead of bind-mounting the worktree itself) means the
    trusted controller, not the container, decides exactly what content is exposed.
    """
    src = Path(worktree_dir).resolve()
    dst = Path(dest_dir).resolve()
    if dst.exists():
        raise ValueError(f"Snapshot destination already exists: {dst}")
    if not src.is_dir():
        raise ValueError(f"Worktree directory does not exist: {src}")

    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--exclude-standard"],
        cwd=str(src), capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to list tracked worktree files: {result.stderr.decode('utf-8', 'replace').strip()}"
        )

    rel_paths = [p for p in result.stdout.decode("utf-8", "strict").split("\0") if p]
    dst.mkdir(parents=True, mode=0o755)

    file_digests: dict[str, str] = {}
    for rel in rel_paths:
        clean_rel = sanitize_relative_path(rel)
        source_file = src / clean_rel
        if source_file.is_symlink() or not source_file.is_file():
            raise PathSecurityError(f"Refusing to snapshot non-regular tracked path: {rel}")

        target_file = dst / clean_rel
        target_file.parent.mkdir(parents=True, exist_ok=True)
        content = source_file.read_bytes()
        target_file.write_bytes(content)
        target_file.chmod(0o444)
        file_digests[clean_rel] = hashlib.sha256(content).hexdigest()

    canonical = "\n".join(f"{path}:{sha}" for path, sha in sorted(file_digests.items()))
    snapshot_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return dst, snapshot_digest, file_digests


def compute_base_file_digests(
    repo_root: Path | str,
    base_sha: str,
    allowed_paths: list[str] | None = None,
) -> dict[str, str]:
    """Compute rel_path -> sha256 content digest for tracked files at base_sha.

    Reads content directly from git history (git worktrees share the same object
    store as their originating repository, so this also works from a worktree path),
    so it reflects the pre-task commit regardless of what the worktree currently
    contains. Pass this as IndependentVerifier.verify_candidate's base_files so
    changed_paths reflects a genuinely measured diff rather than every collected file.

    allowed_paths, when given, restricts which base paths are fetched (the same
    prefixes the task's ArtifactCollector is restricted to) to bound the number of
    `git show` calls on large repositories.
    """
    repo = Path(repo_root).resolve()
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", base_sha],
        cwd=str(repo), capture_output=True, check=False,
    )
    if listing.returncode != 0:
        raise RuntimeError(
            f"Failed to list base tree {base_sha}: {listing.stderr.decode('utf-8', 'replace').strip()}"
        )

    clean_allowed = [p.replace("\\", "/").strip("/") for p in (allowed_paths or [])]

    def _in_scope(rel: str) -> bool:
        if not clean_allowed:
            return True
        return any(rel == p or rel.startswith(p.rstrip("/") + "/") or "*" in p for p in clean_allowed)

    digests: dict[str, str] = {}
    for rel in (p for p in listing.stdout.decode("utf-8", "strict").split("\0") if p):
        if not _in_scope(rel):
            continue
        clean_rel = sanitize_relative_path(rel)
        show = subprocess.run(
            ["git", "show", f"{base_sha}:{rel}"],
            cwd=str(repo), capture_output=True, check=False,
        )
        if show.returncode != 0:
            # E.g. a submodule gitlink entry with no blob content; skip rather than
            # fail the whole diff for a path the collector will not produce anyway.
            continue
        digests[clean_rel] = hashlib.sha256(show.stdout).hexdigest()
    return digests


class WorktreeManager:
    """Manages isolated git worktrees inside the runtime-root directory."""

    def __init__(self, repo_root: Path | str, runtime_root: Path | str | None = None):
        self.repo_root = Path(repo_root).resolve()
        self.runtime_root = (
            Path(runtime_root).resolve() if runtime_root else self.repo_root.parent / "runtime-root"
        )
        self.worktrees_dir = self.runtime_root / "worktrees"
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

    def create_worktree(self, task_id: str, branch: str, base_ref: str) -> Path:
        """Create a dedicated git worktree inside runtime-root."""
        worktree_path = self.worktrees_dir / task_id
        if worktree_path.exists():
            raise FileExistsError(f"Worktree path already exists: {worktree_path}")

        cmd = [
            "git",
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            base_ref,
        ]
        result = subprocess.run(cmd, cwd=str(self.repo_root), capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create git worktree: {result.stderr.strip()}")

        return worktree_path

    def remove_worktree(self, task_id: str) -> None:
        """Prune and remove worktree."""
        worktree_path = self.worktrees_dir / task_id
        if worktree_path.exists():
            cmd = ["git", "worktree", "remove", "--force", str(worktree_path)]
            subprocess.run(cmd, cwd=str(self.repo_root), capture_output=True, text=True, check=False)
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

    def check_dirty_status(self, worktree_path: Path) -> tuple[bool, list[str]]:
        """Check whether worktree has uncommitted modifications and return changed paths."""
        cmd = ["git", "status", "--porcelain"]
        res = subprocess.run(cmd, cwd=str(worktree_path), capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to inspect git status: {res.stderr.strip()}")

        changed_files: list[str] = []
        for line in res.stdout.splitlines():
            if line.strip():
                # Format: XY <file> or XY <file1> -> <file2>
                parts = line[3:].strip().split(" -> ")
                changed_files.extend(parts)

        is_dirty = len(changed_files) > 0
        return is_dirty, changed_files


class HandoffManager:
    """Manages durable resumption states and handoffs."""

    def __init__(self, handoffs_dir: Path | str | None = None):
        if handoffs_dir is None:
            self.handoffs_dir = Path(__file__).resolve().parent.parent.parent / "state" / "handoffs"
        else:
            self.handoffs_dir = Path(handoffs_dir)
        self.handoffs_dir.mkdir(parents=True, exist_ok=True)

    def save_handoff(
        self,
        task_id: str,
        run_id: str,
        attempt: int,
        spec_digest: str,
        policy_digest: str,
        base_sha: str,
        head_sha: str | None,
        completed_steps: list[str],
        pending_steps: list[str],
        changed_paths: list[str],
        validations: list[dict[str, Any]],
        artifacts: dict[str, str],
        is_dirty: bool,
        lease_id: str | None,
        blocked_reason: str | None,
        next_action: str,
        required_approvals: list[str],
    ) -> Path:
        handoff_path = self.handoffs_dir / f"{task_id}.json"
        now = datetime.now(UTC).isoformat()
        handoff_data = {
            "task_id": task_id,
            "run_id": run_id,
            "attempt": attempt,
            "spec_digest": spec_digest,
            "policy_digest": policy_digest,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "completed_steps": completed_steps,
            "pending_steps": pending_steps,
            "changed_paths": changed_paths,
            "validations": validations,
            "artifacts": artifacts,
            "is_dirty": is_dirty,
            "lease_id": lease_id,
            "blocked_reason": blocked_reason,
            "next_action": next_action,
            "required_approvals": required_approvals,
            "saved_at": now,
        }
        temp_file = handoff_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(handoff_data, f, indent=2)
        os.replace(temp_file, handoff_path)
        return handoff_path

    def load_handoff(self, task_id: str) -> dict[str, Any]:
        handoff_path = self.handoffs_dir / f"{task_id}.json"
        if not handoff_path.exists():
            raise FileNotFoundError(f"Handoff record not found for task {task_id}")
        with open(handoff_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def verify_resume_preflight(
        self,
        task_id: str,
        expected_spec_digest: str,
        current_base_sha: str,
    ) -> dict[str, Any]:
        """Preflight verification prior to resuming:
        - Must exist
        - Spec digest must match
        - Base SHA must match (if base changed, cannot blindly resume)
        """
        data = self.load_handoff(task_id)
        if data["spec_digest"] != expected_spec_digest:
            raise HandoffVerificationError(
                f"Spec digest mismatch on resume for task {task_id}: {data['spec_digest']} != {expected_spec_digest}"
            )
        if data["base_sha"] != current_base_sha:
            raise HandoffVerificationError(
                f"Base commit moved for task {task_id}: handoff base was {data['base_sha']}, current is {current_base_sha}"
            )
        return data

    def verify_candidate_evaluation(
        self,
        task_id: str,
        expected_candidate_sha: str,
    ) -> dict[str, Any]:
        """Verify that testing/review evidence belongs strictly to expected_candidate_sha.
        Rejects stale test or review evaluations if candidate SHA changed.
        """
        data = self.load_handoff(task_id)
        recorded_head = data.get("head_sha")
        if recorded_head != expected_candidate_sha:
            raise HandoffVerificationError(
                f"Stale evidence rejected for task {task_id}: recorded evaluation candidate {recorded_head} does not match expected {expected_candidate_sha}"
            )
        return data

