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


DEFAULT_DEMO_ARGV = {
    "pytest": [sys.executable, "-m", "pytest", "tests/unit/", "-q"],
}


def cmd_init(args: argparse.Namespace) -> int:
    """Bootstrap a local config and an isolated runtime root for a target repository."""
    import yaml

    repository = args.repository or _detect_github_repository()
    if not repository:
        print("init blocked: pass --repository owner/repo (auto-detection failed)")
        return 2

    runtime_root = (
        Path(args.runtime_root).expanduser()
        if args.runtime_root
        else Path.home() / ".ai-engineering-factory" / "runtime" / repository.replace("/", "__")
    )
    for sub in ("worktrees", "logs", "leases"):
        (runtime_root / sub).mkdir(parents=True, exist_ok=True)

    config_path = Path(args.config_path) if args.config_path else Path(".ai-factory") / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "repository": repository,
        "runtime": "manual",
        "runtime_root": str(runtime_root),
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    print(f"[*] Repository: {repository}")
    print(f"[*] Runtime root (outside the git repo, holds transient state): {runtime_root}")
    print(f"[*] Local config written: {config_path}")
    print()
    print("Next steps:")
    print("  1. Copy tasks/templates/basic-task.yaml, fill in your task, and point")
    print("     'repository' at the value above.")
    print("  2. python -m orchestrator.cli demo --task-file <your-task.yaml>")
    print("  See docs/getting-started.md for the full walkthrough.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Run one task through ManualAdapter end-to-end as a non-isolated local demo."""
    import yaml

    from orchestrator.adapters.manual import ManualAdapter

    task_file = Path(args.task_file)
    if not task_file.is_file():
        print(f"demo blocked: task file not found: {task_file}")
        return 2
    manifest = yaml.safe_load(task_file.read_text(encoding="utf-8"))

    worktree = str(Path(args.worktree or ".").resolve())
    print(f"=== Demo: task {manifest.get('id')} via ManualAdapter (worktree={worktree}) ===")
    print("[!] Local, non-isolated demo run for evaluation only. This is NOT the offline")
    print("    container boundary (OfflineContainerRunner) and must not be used on")
    print("    untrusted code; it exists to show the task -> validation -> evidence flow.")

    adapter = ManualAdapter()
    run_id = adapter.start_task(manifest, worktree)
    for step in manifest.get("validation", []):
        command_id = step["command_id"]
        argv = DEFAULT_DEMO_ARGV.get(command_id)
        if argv is None:
            print(f"demo blocked: no built-in argv for command_id '{command_id}'; "
                  "add it to DEFAULT_DEMO_ARGV or run this step manually")
            return 2
        print(f"[*] Executing validation step: {command_id}")
        record = adapter.execute_validation_step(run_id, command_id, argv, step.get("timeout_seconds", 300))
        print(f"    -> {record['status']} (exit={record['exit_code']})")

    try:
        results = adapter.collect_results(run_id)
    except ValueError as e:
        print(f"demo failed: {e}")
        return 1

    print(f"=== Result: {results['status']} ===")
    for path, digest in results["artifact_hashes"].items():
        print(f"  artifact: {path} -> {digest}")
    print("This is a local demo, not signed Evidence: real runs go through")
    print("OfflineContainerRunner + IndependentVerifier (see docs/getting-started.md).")
    return 0 if results["status"] == "SUCCESS" else 1


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
    print()
    if all_ok:
        print("=== Summary: environment OK. Exit code 2 is EXPECTED, not a failure: ===")
        print("    it signals Execution Mode: MANUAL_ONLY (every merge still needs a Human")
        print("    approval token). See docs/getting-started.md to run your first task.")
        return 2
    print("=== Summary: one or more checks above failed (see '[!]' lines). ===")
    return 1


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
    """Issue an authenticated approval token if operator credentials and registry are valid."""
    from datetime import UTC, datetime, timedelta

    from orchestrator.core.approval import (
        ApprovalManager,
        ApprovalVerificationError,
        compute_argv_digest,
    )
    from orchestrator.core.auth import AuthenticationError, AuthorizationError

    operator_key = os.environ.get("AI_FACTORY_OPERATOR_KEY", "").encode("utf-8")
    if getattr(args, "key_file", None):
        try:
            with open(args.key_file, "rb") as f:
                operator_key = f.read().strip()
        except OSError as e:
            print(f"Approval blocked: failed to read operator key file ({e})")
            return 2

    if not operator_key:
        print("Approval blocked: an authenticated, worker-inaccessible Human channel is required.")
        return 2

    try:
        mgr = ApprovalManager(approvals_dir=args.approvals_dir, enforce_authentication=True)
        expires_at = (datetime.now(UTC) + timedelta(minutes=args.expires_minutes)).isoformat()
        argv_digest = compute_argv_digest(args.command.split())
        token = mgr.issue_authenticated_token(
            action=args.action,
            repository=args.repository,
            task_id=args.task_id,
            head_sha=args.head_sha,
            target_ref=args.target_ref,
            argv_digest=argv_digest,
            policy_hash=args.policy_hash,
            plan_hash=args.plan_hash,
            approved_by=args.approved_by,
            operator_key=operator_key,
            expires_at=expires_at,
        )
        print(f"Approval token issued: {token['token_id']}")
        return 0
    except (AuthenticationError, AuthorizationError, ApprovalVerificationError, OSError, ValueError) as e:
        print(f"Approval blocked: {e}")
        return 2


def cmd_cancel(args: argparse.Namespace) -> int:
    """Cancel a task and release its lease after strictly verifying worker termination."""
    from orchestrator.core.lease import LeaseExpiredError, RuntimeLeaseManager, is_process_alive
    from orchestrator.core.sandbox import ProcessTreeController

    ledger = StateLedger(args.state_dir)
    state = ledger.get_state(args.task_id)
    if state["status"] in ("DONE", "CANCELLED"):
        print(f"Task {args.task_id} is already in terminal state: {state['status']}")
        return 0

    lease_manager = RuntimeLeaseManager(db_path=getattr(args, "lease_db", None))
    active_lease = lease_manager.get_active_lease(args.task_id)

    if state["status"] == "RUNNING":
        if not active_lease:
            print("Cancellation blocked: active worker identity and lease not found.")
            return 2
        pid = active_lease["pid"]
        if is_process_alive(pid):
            controller = ProcessTreeController()
            terminated = controller.terminate_tree({"pid": pid, "start_time": active_lease.get("heartbeat_ts", 0.0)})
            if not terminated or is_process_alive(pid):
                print(f"Cancellation blocked: active worker termination of PID {pid} could not be confirmed.")
                return 2
        try:
            lease_manager.release_lease(args.task_id, active_lease["worker_id"], epoch=active_lease["epoch"])
        except (OSError, LeaseExpiredError):
            pass
    elif active_lease:
        try:
            lease_manager.release_lease(args.task_id, active_lease["worker_id"], epoch=active_lease["epoch"])
        except (OSError, LeaseExpiredError):
            pass

    new_state = ledger.transition(
        task_id=args.task_id,
        expected_revision=state["revision"],
        to_status=TaskStatus.CANCELLED,
        reason=args.reason or "Cancelled by operator via CLI with confirmed worker termination",
    )
    print(f"Task {args.task_id} transitioned to CANCELLED (Rev {new_state['revision']}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator.cli", description="AI Engineering Factory CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Bootstrap local config and runtime root for a repository")
    p_init.add_argument(
        "--repository",
        default=None,
        help="GitHub repository in owner/name form; auto-detected when omitted",
    )
    p_init.add_argument(
        "--runtime-root",
        default=None,
        help="Directory for transient runtime state, outside the git repo "
             "(default: ~/.ai-engineering-factory/runtime/<owner>__<repo>)",
    )
    p_init.add_argument(
        "--config-path",
        default=None,
        help="Where to write the local config file (default: .ai-factory/config.yaml)",
    )
    p_init.set_defaults(func=cmd_init)

    # demo
    p_demo = subparsers.add_parser(
        "demo", help="Run one task end-to-end via ManualAdapter as a local, non-isolated demo"
    )
    p_demo.add_argument("--task-file", required=True, help="Path to a task manifest YAML")
    p_demo.add_argument("--worktree", default=None, help="Worktree to run the task against (default: cwd)")
    p_demo.set_defaults(func=cmd_demo)

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
    p_app.add_argument("--key-file", default=None, help="Path to operator secret key file for authentication")
    p_app.set_defaults(func=cmd_approve)

    # cancel
    p_can = subparsers.add_parser("cancel", help="Cancel a task")
    p_can.add_argument("--task-id", required=True, help="Task ID to cancel")
    p_can.add_argument("--reason", default=None, help="Cancellation reason")
    p_can.add_argument("--state-dir", default=None, help="Path to state/tasks directory")
    p_can.add_argument("--lease-db", default=None, help="Path to leases.sqlite database")
    p_can.set_defaults(func=cmd_cancel)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
