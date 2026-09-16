# ADR-0003: Control Plane Trust, Approval Integrity, and State Ledger

## Status
Accepted

## Context
In previous phases, approval tokens were stored as simple JSON files in `state/approvals/`. State transitions used Python's `threading.Lock` within a single process. As documented in `docs/operations/POST_PHASE4_REVIEW.md`:
1. JSON approval files can be forged or modified if filesystem permissions are shared.
2. Token consumption lacked atomic cross-process transactions, risking double-consumption.
3. Approval records lacked cryptographic verification of the signer and context integrity (HMAC/signatures).
4. `StateLedger` in-memory lock does not protect against concurrent worker or CLI processes.
5. Crash during external irreversible operations could lead to unsafe token resurrection or double execution.

## Decisions
1. **Control Plane Trust & Storage Segregation**:
   - Approvals and control plane ledger are stored in a dedicated SQLite database located in `state/control.db` (outside worker reach).
   - Approvals are cryptographically signed using HMAC-SHA256 with a dedicated control plane secret key not accessible to workers.
2. **Atomic Token Lifecycle**:
   - Token status (`ISSUED`, `CONSUMED`, `REVOKED`, `EXPIRED`) is tracked in SQLite with `BEGIN IMMEDIATE` transactions.
   - Consumption enforces an atomic CAS transition: `UPDATE approvals SET status = 'CONSUMED' WHERE token_id = ? AND status = 'ISSUED'`. If 0 rows affected, consume fails immediately.
   - Tokens are bound to `(action, repository, task_id, run_id, candidate_sha, target_ref, argv_digest, policy_digest, plan_digest, expires_at, nonce)`. Any deviation in parameters causes verification failure.
3. **Persistent Inter-Process State Ledger**:
   - `StateLedger` is upgraded to use SQLite with WAL mode and transactional CAS updates for task state transitions.
   - Task attempt counts, retry budgets, and lease epochs are persisted durably so that process restarts do not reset budgets.
4. **Failure & Crash Recovery (Operation Journal)**:
   - External mutation intents (e.g. Git push, PR creation) write an `operation_intent` record before executing.
   - Upon crash or network timeout, the reconciliation engine queries external remote status using idempotency keys. If remote state is ambiguous, state is transitioned to `NEEDS_HUMAN` rather than re-executing blind side-effects.

## Consequences
- Complete defense against approval forgery, tampering, replay, and race conditions.
- Reliable crash recovery without phantom duplicate actions.
- Strict multi-process concurrency safety.
