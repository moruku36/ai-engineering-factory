# Operations Guide

**MANUAL_ONLY:** Offline container isolation, authenticated Human approval
(HMAC-SHA256 signed, single-use tokens), independent artifact verification,
and durable GitHub operation journaling are implemented — see
[PROJECT_STATE.md](PROJECT_STATE.md) for the current capability milestone.
What remains unimplemented is native Antigravity execution, which is
`BLOCKED` pending an official batch/isolation SDK (see
[ANTIGRAVITY_INTEGRATION_EVALUATION.md](docs/operations/ANTIGRAVITY_INTEGRATION_EVALUATION.md)).
`doctor` therefore still reports `Execution Mode: MANUAL_ONLY` and a
nonzero readiness status by design. Passing unit tests does not by itself
enable unattended use; see `docs/operations/POST_PR7_REVIEW.md` for the
now-superseded historical baseline this guide has moved past.

## 1. Runtime Isolation
- All runtime transient state (active SQLite DB, worker PID records, distributed leases, raw execution logs) must be placed in `runtime-root`, completely isolated from the git repository.
- Default runtime root location: `~/.gemini/antigravity/scratch/ai-engineering-factory-runtime/`.
- `ProcessTreeController` runs under the host user. Path validation only checks API
  arguments; it does not restrict code executed by the worker or its network access.
- `reserve_ephemeral_port()` now returns a context-managed `PortReservation` with
  a live `.socket` and `.port`; closing and rebinding is not an atomic handoff.

## 2. Crash Recovery & Resumption
- The Control Plane maintains a persistent state ledger using SQLite transactions with Compare-And-Swap (CAS) revision numbers.
- GitHub operations use a 2-phase durable journal (`github_operations.sqlite`) preventing duplicate PR/push operations.
- If a worker crashes or is abruptly interrupted:
  1. Run `python -m orchestrator.cli status` to inspect durable task revisions, lease owners, and heartbeat timestamps.
  2. For stalled GitHub operations, call `GitHubPublisher.reconcile_pending_operations()` to sync uncommitted intents with remote state.
  3. Active leases expire after `timeout_seconds` and are verified via OS process existence checks (`is_process_alive`).
  4. Stale leases are automatically reclaimed upon the next lease acquisition.

## 3. Operator CLI Commands
The factory operator CLI is implemented under `orchestrator.cli`:

```bash
# 1. System diagnostics and capability verification.
python -m orchestrator.cli doctor

# 2. Inspect active tasks and execution state
python -m orchestrator.cli status [--state-dir <path>]

# 3. Authenticated Approval Issuance
# Requires provisioned operator signing key and approval registry.
python -m orchestrator.cli approve \
  --action <action> \
  --repository <owner/repo> \
  --task-id <task_id> \
  --head-sha <commit_sha> \
  --target-ref <target_ref> \
  --command "<approved_command>" \
  --policy-hash <policy_sha256> \
  --plan-hash <plan_sha256> \
  --approved-by <operator_id> \
  --key-file /path/to/operator.key \
  [--expires-minutes 15]

# 4. Safe Cancellation of Running/Queued Tasks
# Terminate worker process tree and confirm exit before transitioning status.
python -m orchestrator.cli cancel --task-id <task_id> [--reason <reason>]
```

## 4. Operational Gates & Secret Verification
Before opening pull requests or deploying changes, run all mandatory quality gates:
```bash
# Linter
ruff check orchestrator scripts tests

# Secret scanner (fail-closed commit range and staged diff check)
python scripts/secret_scan.py

# Dependency consistency check (pip check)
python scripts/audit_dependencies.py


# Regression test suite
pytest -v tests/
```


## 5. Public Repository Safety
- Never place credentials, approval secrets, raw session logs, runtime databases, or private environment files in Git.
- Treat Issues, Pull Requests, task manifests, repository documents, and generated agent instructions as potentially untrusted input.
- A public example is not an authorization boundary. Infrastructure apply/destroy, IAM changes, deployment, release, public exposure, credential operations, and merge still require explicit Human approval.
- Do not assume server-side branch protection is configured. Verify it with `doctor` or the GitHub UI and keep Factory policy checks as a separate defense-in-depth layer.
