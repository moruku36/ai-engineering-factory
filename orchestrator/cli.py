"""Unified Operator CLI for AI Engineering Factory."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from orchestrator.adapters.antigravity import probe_antigravity_runtime
from orchestrator.core.state import StateLedger, TaskStatus


def _parse_github_repository(remote: str) -> str | None:
    """Extract owner/repository from common github.com remote URL forms."""
    value = remote.strip()
    if value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:")
    elif "github.com/" in value:
        value = value.split("github.com/", 1)[1]
    else:
        return None

    value = value.removesuffix(".git").strip("/")
    parts = value.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return value


def _detect_github_repository() -> str | None:
    """Detect the current GitHub owner/repository without repo-specific defaults."""
    env_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if len(env_repo.split("/")) == 2:
        return env_repo

    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    return _parse_github_repository(remote)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run environment, security, and integration diagnostics."""
    print("=== Factory System Doctor ===")
    all_ok = True

    # Python version
    py_ver = sys.version.split()[0]
    print(f"[*] Python: {py_ver} (OK)")

    # Git
    try:
        git_ver = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
        print(f"[*] Git: {git_ver} (OK)")
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[!] Git check failed: {e}")
        all_ok = False

    # GitHub API / Branch Protection
    repository = args.repository or _detect_github_repository()
    if repository:
        print(f"[*] GitHub repository: {repository}")
        try:
            res = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{repository}/branches/{args.branch}",
                    "--jq",
                    ".protected",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                is_protected = res.stdout.strip()
                print(f"[*] GitHub {args.branch} branch protected: {is_protected}")
            else:
                print("[!] GitHub CLI unreachable, unauthenticated, or repository inaccessible")
        except (subprocess.SubprocessError, OSError):
            print("[!] GitHub CLI not found")
    else:
        print("[!] GitHub repository not detected; pass --repository owner/repo to inspect it")

    # Antigravity Runtime
    probe = probe_antigravity_runtime()
    print(f"[*] Antigravity transport: {probe['status']}")
    print("[!] Native workers lack enforced OS isolation and authenticated Human approval")
    print("[*] Execution Mode: MANUAL_ONLY")
    return 2 if all_ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of tasks and active leases."""
    ledger = StateLedger(args.state_dir)
    print("=== Task States ===")
    task_files = list(Path(args.state_dir or "state/tasks").glob("*.json"))
    if not task_files:
        print("No tasks registered.")
    for tf in task_files:
        try:
            state = ledger.get_state(tf.stem)
            print(
                f"Task: {state['task_id']:<10} Status: {state['status']:<15} "
                f"Rev: {state['revision']:<3} Attempt: {state['attempt']}"
            )
        except (KeyError, OSError, ValueError) as e:
            print(f"Task file {tf.name}: Error reading state ({e})")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Do not interpret a caller-supplied name as authenticated Human approval."""
    print("Approval blocked: an authenticated, worker-inaccessible Human channel is required.")
    return 2


def cmd_cancel(args: argparse.Namespace) -> int:
    """Cancel a task and release its lease."""
    ledger = StateLedger(args.state_dir)
    state = ledger.get_state(args.task_id)
    if state["status"] in ("DONE", "CANCELLED"):
        print(f"Task {args.task_id} is already in terminal state: {state['status']}")
        return 0
    if state["status"] == "RUNNING":
        print("Cancellation blocked: active worker termination must be confirmed by its controller.")
        return 2

    new_state = ledger.transition(
        task_id=args.task_id,
        expected_revision=state["revision"],
        to_status=TaskStatus.CANCELLED,
        reason=args.reason or "Cancelled by operator via CLI",
    )
    print(f"Task {args.task_id} transitioned to CANCELLED (Rev {new_state['revision']}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator.cli", description="AI Engineering Factory CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # doctor
    p_doc = subparsers.add_parser("doctor", help="Run system health checks")
    p_doc.add_argument(
        "--repository",
        default=None,
        help="GitHub repository in owner/name form; auto-detected when omitted",
    )
    p_doc.add_argument("--branch", default="main", help="Branch to inspect for protection")
    p_doc.set_defaults(func=cmd_doctor)

    # status
    p_stat = subparsers.add_parser("status", help="Show task and lease status")
    p_stat.add_argument("--state-dir", default=None, help="Path to state/tasks directory")
    p_stat.set_defaults(func=cmd_status)

    # approve
    p_app = subparsers.add_parser("approve", help="Issue an approval token")
    p_app.add_argument(
        "--action", required=True, help="Approved action (e.g. task_execution, merge_pull_request)"
    )
    p_app.add_argument("--repository", required=True, help="Repository name")
    p_app.add_argument("--task-id", required=True, help="Task ID (e.g. FND-001)")
    p_app.add_argument("--head-sha", required=True, help="Head commit SHA")
    p_app.add_argument("--target-ref", required=True, help="Target git ref")
    p_app.add_argument("--command", required=True, help="Exact command string approved for execution")
    p_app.add_argument("--policy-hash", required=True, help="SHA256 of policy")
    p_app.add_argument("--plan-hash", required=True, help="SHA256 of plan")
    p_app.add_argument("--approved-by", required=True, help="Human operator username")
    p_app.add_argument("--expires-minutes", type=int, default=15, help="Token validity in minutes")
    p_app.add_argument("--approvals-dir", default=None, help="Path to approvals directory")
    p_app.set_defaults(func=cmd_approve)

    # cancel
    p_can = subparsers.add_parser("cancel", help="Cancel a task")
    p_can.add_argument("--task-id", required=True, help="Task ID to cancel")
    p_can.add_argument("--reason", default=None, help="Cancellation reason")
    p_can.add_argument("--state-dir", default=None, help="Path to state/tasks directory")
    p_can.set_defaults(func=cmd_cancel)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
