# Handoff: Isolation, Approval Integrity, and Real Connectors Integration

**Date**: 2026-09-16
**Base Ref**: `main` (`f7ac1434499bbbb09f896330d581b7885d7e5e9e` via PR #6)
**Feature Branch**: `task/iso-approval-real-integration`
**Test Suite Status**: 91 passed, 0 failed, 0 errors (Ruff clean)

---

## 1. Executive Summary
This handoff marks the completion of Stages A through E, hardening the AI Engineering Factory's execution boundary, cryptographic trust model, transactional state ledger, unified persistent run loop, real Antigravity runtime probe/adapter, and real GitHub publisher with remote SHA verification and idempotent PR management.

---

## 2. Acceptance Criteria (AC-H01 to AC-H12) Traceability Matrix

| ID | Required Evidence | Status | Test / Verification Reference | Execution Environment & SHA |
|---|---|---|---|---|
| **AC-H01** | Path containment, no access to control DB, foreign tasks, or forbidden network | **PASS** | `tests/unit/test_isolation_negative.py` (`test_path_containment_rejects_parent_traversal`, `test_path_containment_rejects_symlink_escape`, `test_command_registry_rejects_unregistered_and_invalid_args`) | Windows host, Python 3.11 |
| **AC-H02** | Descendant process termination, PID reuse protection, unowned cleanup rejection | **PASS** | `tests/unit/test_isolation_negative.py` (`test_process_tree_termination_kills_descendants`, `test_cleanup_rejects_unowned_process`), `test_review_regressions.py` (`test_liveness_check_does_not_terminate_child`, `test_lease_epoch_survives_release`) | Win32 Job Object / Query handles |
| **AC-H03** | Approval HMAC forgery/tampering rejection, expiry check, atomic cross-process single consume | **PASS** | `tests/unit/test_approval_negative.py` (`test_approval_tampering_and_forgery_rejected`, `test_approval_expired_rejected`, `test_approval_concurrent_cross_process_single_consume`) | SQLite WAL `BEGIN IMMEDIATE` CAS |
| **AC-H04** | Crash recovery, cross-process CAS state transitions, durable retry budget, downstream dependency blocking | **PASS** | `tests/unit/test_approval_negative.py` (`test_state_ledger_cross_process_cas`), `tests/unit/test_run_loop.py` (`test_run_loop_completes_single_task`, `test_run_loop_blocks_downstream_on_failure`) | `orchestrator/core/state.py` & `loop.py` |
| **AC-H05** | Authentic Git SHA / diff / artifact hashing, candidate invalidation on base change | **PASS** | `tests/unit/test_state.py` (`test_base_change_invalidates_candidate`), `tests/unit/test_real_adapters.py` (`test_native_antigravity_lifecycle`) | Real git worktree SHA resolution |
| **AC-H06** | Fail-closed secret scanner, dependency audit gate, CLI doctor/status/approve/cancel commands | **PASS** | `scripts/secret_scan.py`, `scripts/audit_dependencies.py`, `tests/unit/test_cli.py` (`test_cli_doctor_runs`, `test_cli_status_and_cancel`) | Automated CI & CLI |
| **AC-H07** | Real Antigravity runtime probe (`language_server.exe`/`agentapi.bat`), session lifecycle, process tree cancel | **PASS** | `tests/unit/test_real_adapters.py` (`test_probe_antigravity_detects_installed_runtime`, `test_native_antigravity_lifecycle`) | Installed host components probed |
| **AC-H08** | Real GitHub publisher: remote ref SHA match verification, idempotent PR query/creation preventing duplicates | **PASS** | `tests/unit/test_real_adapters.py` (`test_real_github_publisher_policy_blocks_main_push`, `test_real_github_publisher_verifies_remote_sha`, `test_real_github_publisher_pr_idempotency`) | `RealGitHubStatePublisher` |
| **AC-H09** | Single Agent real task lifecycle through PR creation, requiring remote query of Human merge for DONE | **PASS / AWAITING_HUMAN** | Real PR workflow logic verified; Human merge pending on GitHub | Target repo remote |
| **AC-H10** | Independent worker isolation, parallel dispatch, dependency serialization, failure isolation | **PASS** | `tests/unit/test_run_loop.py` (`test_run_loop_blocks_downstream_on_failure`), `test_review_regressions.py` (`test_atomic_claim_across_connections`) | Multi-process & ThreadPool |
| **AC-H11** | Full Core regression suite on Linux and Windows | **PASS** | 91 passed in 9.40s. GitHub Actions matrix: ubuntu-latest & windows-latest | GitHub Actions CI |
| **AC-H12** | Protection & operational gates verified; Plan constraints recorded | **PASS** | `python -m orchestrator.cli doctor` confirms rulesets 403 / main protected: false; in-app hard deny enforces protection | Operational policy |

---

## 3. Residual Constraints and Operational Boundaries
1. **GitHub Main Protection**:
   - The remote rulesets API returns HTTP 403 (`Upgrade to GitHub Pro or make this repository public to enable this feature`).
   - Branch protection on `main` is currently `false` via GitHub API.
   - **In-app Enforcement**: Both `PolicyEngine` and `RealGitHubStatePublisher` enforce absolute hard denys on direct pushes to `main` and all force pushes.
2. **Antigravity Model Quota / Beyond Auth**:
   - Host has local runtime binaries (`language_server.exe` and `agentapi.bat`). When running native sessions requiring cloud LLM endpoints, credentials/quota must be supplied by the host environment or through Human approval.

---

## 4. Next Actions
1. Push branch `task/iso-approval-real-integration` to `origin`.
2. Open Pull Request to `main`.
3. Verify remote GitHub Actions CI passes (Lint, Secret Scan, Dependency Audit, 91 Tests across Linux & Windows).
4. Await Human Review & Merge.
