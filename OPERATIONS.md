# Operations Guide

## 1. Runtime Isolation
- All runtime transient state (active SQLite DB, worker PID files, distributed leases, raw execution logs) must be placed in `runtime-root`, completely isolated from the git repository.
- Default runtime root location: `~/.gemini/antigravity/scratch/ai-engineering-factory-runtime/`.

## 2. Crash Recovery & Resumption
- The Control Plane maintains a persistent state ledger using Compare-And-Swap (CAS) revision numbers.
- If a worker crashes or is abruptly interrupted:
  1. Inspect `state/handoffs/<task-id>.json` for the last committed state, spec hash, candidate SHA, and dirty working tree status.
  2. The scheduler validates lease expiration against active process verification.
  3. Re-dispatch requires re-verifying preflight checks and unexpired approval tokens.
  4. Never blindly trust unvalidated stale sessions.

## 3. Inspection Commands
- Inspect state ledger: `python -m orchestrator.cli state status`
- Validate task schema: `python -m orchestrator.cli validate <task.yaml>`
- Check active leases: `python -m orchestrator.cli lease list`
