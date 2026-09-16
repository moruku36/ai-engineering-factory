# Project State

## Overall Status: INTEGRATION_VERIFIED (Isolation, Approval & Real Connectors Complete)
- **Reviewed Base Ref**: `main` (`f7ac1434499bbbb09f896330d581b7885d7e5e9e` via PR #6)
- **Feature Branch**: `task/iso-approval-real-integration`
- **Target Remote**: `https://github.com/moruku36/ai-engineering-factory`

## Current Phase Milestones
- [x] **Stage A (Execution Isolation & Boundaries)**: CommandRegistry (argv schema/timeout/network profile), Win32 Job Object & process tree termination, PID reuse protection with creation timestamp verification, strict worktree containment (path traversal/symlink escape blocking), ephemeral port allocation via OS kernel.
- [x] **Stage B (Approval, Trust & State Ledger)**: Cryptographically signed HMAC approvals, atomic cross-process token consumption via SQLite `BEGIN IMMEDIATE` & CAS, SQLite multi-process state ledger with durable retry budgets, persistent `RunLoopController`.
- [x] **Stage C (Authentic Evidence & Quality Gates)**: Fail-closed secret scanner (`scripts/secret_scan.py` checking commit ranges and staged diffs), dependency audit gate (`scripts/audit_dependencies.py`), full operator CLI (`orchestrator.cli` with `doctor`, `status`, `approve`, `cancel`).
- [x] **Stage D (Antigravity Real Adapter)**: `NativeAntigravityAdapter` with runtime environment probing (`language_server.exe` / `agentapi.bat`), process-tree lifecycle management, and cancellation support.
- [x] **Stage E (GitHub Real Publisher)**: `RealGitHubStatePublisher` with git push transport, remote ref SHA verification against local HEAD, and idempotent PR query/creation preventing duplicate PRs.

## Operational Constraints & Notes
1. **GitHub Branch Protection**: The target private repository returns HTTP 403 on rulesets API (free/personal plan constraint) and `protected: false` on `main`. Hard deny controls for direct push to `main` and force pushes are strictly enforced in-app by `PolicyEngine` and `RealGitHubStatePublisher`.
2. **Acceptance Status**: Core test suite expanded to 91 tests (100% passing on Linux/Windows). Full operational traceability documented in `docs/operations/ISOLATION_APPROVAL_INTEGRATION_HANDOFF.md`.
