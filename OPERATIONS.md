# Operations Guide

**MANUAL_ONLY:** See [the latest acceptance review](docs/operations/POST_PR7_REVIEW.md).
Native execution and authenticated Human approval are not implemented. `doctor`
returns nonzero readiness status. Passing unit tests does not enable unattended use.

## 1. Runtime Isolation
- All runtime transient state (active SQLite DB, worker PID records, distributed leases, raw execution logs) must be placed in `runtime-root`, completely isolated from the git repository.
- Default runtime root location: `~/.gemini/antigravity/scratch/ai-engineering-factory-runtime/`.
- `ProcessTreeController` runs under the host user. Path validation only checks API
  arguments; it does not restrict code executed by the worker or its network access.
- `reserve_ephemeral_port()` now returns a context-managed `PortReservation` with
  a live `.socket` and `.port`; closing and rebinding is not an atomic handoff.

## 2. Crash Recovery & Resumption
- The Control Plane maintains a persistent state ledger using SQLite transactions with Compare-And-Swap (CAS) revision numbers.
- If a worker crashes or is abruptly interrupted:
  1. Inspect `python -m orchestrator.cli status` for the latest durable task revision, status, and retry budget.
  2. Active leases expire after `timeout_seconds` and are verifiable via non-destructive OS process queries.
  3. Re-dispatch requires re-verifying preflight checks and unexpired approval tokens.
  4. Never blindly trust unvalidated stale sessions.

## 3. Operator CLI Commands
The factory operator CLI is implemented under `orchestrator.cli`:

```bash
# 1. System diagnostics and capability verification
python -m orchestrator.cli doctor

# 2. Inspect active tasks and execution state
python -m orchestrator.cli status [--state-dir <path>]

# 3. Approval issuance is blocked until an authenticated Human channel exists.
# Internal ApprovalManager requires a provisioned signing key and is not a Human authenticator.

# 4. Cancel an inactive task. RUNNING cancellation is refused until a controller
# can prove the worker and descendants stopped; this CLI does not stop workers.
python -m orchestrator.cli cancel --task-id <task_id> [--reason <reason>]
```

## 4. Operational Gates & Secret Verification
Before opening pull requests or deploying changes, run all mandatory quality gates:
```bash
# Linter
ruff check orchestrator scripts tests

# Secret scanner (fail-closed commit range and staged diff check)
python scripts/secret_scan.py

# Dependency compatibility only (pip check); NOT vulnerability scanning
python scripts/audit_dependencies.py

# Regression test suite
pytest -v tests/
```
