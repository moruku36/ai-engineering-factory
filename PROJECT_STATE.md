# Project State

## Overall Status: EXPERIMENTAL / INTEGRATION_VERIFIED

The major isolation, approval-integrity, validation, Antigravity-adapter, and GitHub-publisher stages have been merged into `main` through PR #7. The project is suitable for continued engineering validation, but it is **not presented as a production-certified autonomous development platform**.

This file is the current high-level status summary. Historical review and handoff documents under `docs/operations/` describe the state at the commit they reviewed; later integration work can supersede older readiness statements.

## Current Capability Milestones

- [x] **Execution Isolation & Boundaries**: registered-command execution, path containment, process-tree control, PID-reuse protection, task-scoped runtime resources, and ephemeral port allocation.
- [x] **Approval, Trust & State Ledger**: cryptographically bound approval tokens, atomic single-use consumption, persistent SQLite state, CAS-style transitions, retry budgets, and a persistent run-loop controller.
- [x] **Evidence & Quality Gates**: fail-closed secret scanning, dependency audit, lint/test CI, real Git/diff evidence paths, and operator CLI diagnostics/status/approval/cancellation commands.
- [x] **Antigravity Integration**: native runtime probing/adapter plus manual/test adapters behind an execution abstraction.
- [x] **GitHub Integration**: publisher path with remote SHA verification and idempotent PR query/creation behavior.
- [x] **Cross-platform CI**: Linux and Windows validation are configured in GitHub Actions.

## Current Operational Constraints

1. **Server-side protection is not currently enabled on `main`.** As of 2026-09-16, the GitHub branch API reports `protected: false`. Project policy and publisher code still hard-deny direct pushes to `main` and force pushes, but repository settings should be treated as a separate defense-in-depth control.
2. **The project remains experimental.** Passing unit/integration tests does not establish that every supported OS, Antigravity release, agent model, repository layout, or failure mode has been validated.
3. **Antigravity execution depends on the host environment.** Native sessions require compatible locally installed runtime components plus the host's own authentication/quota. The Factory must not fabricate unsupported SDK/CLI capabilities.
4. **High-impact operations remain approval-gated.** Cloud infrastructure apply/destroy, IAM or credential changes, public exposure, deployment, release, Git history rewriting, and merge require explicit Human approval.
5. **GitHub is the durable engineering source of truth, not the runtime scratch area.** Active databases, process metadata, leases, raw session logs, and credentials belong outside the repository runtime boundary.
6. **No explicit open-source license has been selected yet.** The repository is public, but reuse/redistribution terms should be decided before presenting it as a reusable open-source project.

## Documentation Precedence

When status documents disagree, use the following order:

1. current `main` implementation and CI results;
2. this `PROJECT_STATE.md` summary;
3. the newest dated handoff/review document for the subsystem in question;
4. older phase/review records as historical evidence only.

The earlier [`POST_PHASE4_REVIEW.md`](docs/operations/POST_PHASE4_REVIEW.md) intentionally records a stricter pre-integration checkpoint. The later [`ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md`](docs/operations/ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md) records the subsequent hardening and real-adapter work that was later merged.

## Next Public-Readiness Actions

- Choose and add an explicit software license if third-party reuse is intended.
- Enable server-side `main` protection / required checks when repository settings permit it.
- Keep the compatibility matrix tied to versions that have actually been exercised.
- Validate real agent runs first in disposable repositories before using the Factory against important projects.
- Add measured wall-clock, retry, CI-failure, human-review, and cost-per-merged-task evidence before claiming multi-agent productivity gains.
