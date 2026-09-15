# Post-Phase-4 safety review

Reviewed 2026-09-16, base `7abea0e811622c7cf962a07e645de625fe509eea`.
Disposition: **MANUAL_ONLY; not ready for unattended agents or cloud operations.**

## Corrections in this change

| Priority | Finding | Correction |
|---|---|---|
| P0 | `os.kill(pid, 0)` can terminate the target on Windows | Use query-only Windows handles; unknown/access-denied means potentially alive |
| P1 | Antigravity adapter silently executes manual code in auto mode | Require explicit manual mode; reject native/auto mode until implemented |
| P1 | GitHub publisher fabricates PR number 999 and a URL without network I/O | Refuse publication with NotImplementedError; preserve deny checks |
| P1 | Isolation is always reported VERIFIED | Report MANUAL_ONLY, and binary discovery as UNVERIFIED |
| P1 | Direct dispatch bypasses dependency/resource checks and accepts PROPOSED | Recheck eligibility at dispatch; require READY; reject duplicate IDs; bound retries |
| P1 | Lease SELECT occurs outside its write transaction; release resets epoch | BEGIN IMMEDIATE before claim/heartbeat; durable epoch counter; expired heartbeat denied |
| P1 | Missing validation can pass, artifact paths escape, cancelled run can execute | Require executed required checks, contain artifact reads, reject inactive execution |

Regression coverage includes a real child-process liveness check, competing SQLite
connections, stale epochs/heartbeats, direct dispatch bypass, bounded retries,
missing checks, outside-worktree artifacts, and unsupported external operations.
CI runs on Linux and Windows. These tests do not establish native-agent acceptance.

Python documents the Windows signal behavior in
[os.kill](https://docs.python.org/3.11/library/os.html#os.kill).

## Outstanding operational gates

These are not fixed by the narrow safety patch. Do not equate unit-test success with
completion of the original architecture acceptance criteria.

1. **Native integration / AUT-003–005:** the compatibility adapter has no SDK/CLI
   transport. GitHubStatePublisher has no remote transport, persistent idempotency,
   or reconciliation after uncertain writes. Implement these behind explicit
   capabilities, then verify against a disposable repository with Human merge.
2. **Execution boundary:** environment filtering and shell-character checks are not
   OS isolation. Command policy only checks names, not exact registry-bound argv.
   Worker code can execute arbitrary Python and inherits host-user filesystem access.
   Cancel/timeout handling does not prove that every descendant process has stopped.
   Implement a restricted execution identity/container/VM and process-tree control.
3. **Approval / state integrity:** approval JSON is stored in the repository and is
   not an authenticated Human-signature service. Consumption is not a cross-process
   transaction. StateLedger's threading lock is not an inter-process writer lock.
   Separate the trusted control identity and persist approvals/state atomically.
4. **Evidence:** ManualAdapter still supplies placeholder commit hashes and a fixed
   changed_paths value. Bind real base/head/policy/spec data before any merge-ready
   decision. Current integration tests inject fixtures; they do not verify real
   Human merge, independent reviews, native workers, or real publication.
5. **Runtime orchestration:** scheduler/lease/adapter components are not a persistent
   production agent loop. Scheduler state/attempt counts are in memory; resource
   ports use a hash rather than an OS reservation. Path conflict normalization,
   cleanup ownership, PID reuse, and process-stop-before-release need hardening.
6. **GitHub gates:** main reported `protected: false`; rulesets API returned HTTP 403
   with a plan/visibility restriction. No settings were changed. Resolve protection
   availability with the owner; do not change visibility or billing automatically.
7. **CI scope:** the secret scanner scans only the last diff, skips tests and treats
   Git errors as empty success. Add a fail-closed scan of the complete proposed
   commit range/tree, dependency audit, and independently enforced required checks.
8. **CLI / docs:** OPERATIONS advertises `python -m orchestrator.cli`, but that module
   is absent. Implement and test actual entrypoints before publishing run instructions.

## What to do next

1. Review/merge this patch; retain MANUAL_ONLY. Do not start a new feature phase.
2. Recover any genuine native implementation from the previous Antigravity local
   workspace, if it exists. Preserve dirty/unpushed files; compare with the reviewed
   main before deciding to implement missing transport code.
3. Complete gates 2–5 and 7–8 with negative tests and crash recovery. Decide the
   GitHub protection limitation with the owner. No cloud credentials are needed.
4. Complete gate 1 and run one real task in a disposable repo: approved task → real
   candidate → independent checks → actual PR → Human merge → observed DONE.
5. Only then test two independent tasks with real worker isolation and crash/cancel
   injection. Measure actual overlap and compare repeated single-worker runs.
6. Cloud validation starts with credential-free Terraform fmt/static validation.
   Any plan credentials, apply, deployment, or destroy require separate scope.

Acceptance evidence must record exact head/base, tool versions, command/results,
remote URLs, and unverified items. Preserve historical handoffs as historical claims;
this review supersedes their operational-readiness assertions.
