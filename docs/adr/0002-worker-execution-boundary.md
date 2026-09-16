# ADR-0002: Worker Execution Boundary and Sandbox Architecture

## Status
Accepted

## Context
In Phase 1-4, sandboxing relied on environment variable sanitization, worktree directories, and shell metacharacter checking. As detailed in `docs/operations/POST_PHASE4_REVIEW.md`, this does not constitute a hardened execution boundary:
1. Worker processes inherit the host OS user credentials and filesystem access.
2. Direct Python/test execution is arbitrary code execution.
3. Simple kill does not guarantee process-tree termination or guard against PID reuse.
4. Path traversals, symlinks, and junction points can leak outside the allocated worktree.
5. Command validation was by executable name rather than strict Command Registry.

## Decisions
1. **Command Registry Enforcement**:
   - Commands are invoked solely via registered Command IDs.
   - Each registry entry specifies: exact binary path, argument schema/types, working directory constraints, timeout, and network isolation profile.
   - Arbitrary shell strings and unverified binary executions are strictly rejected.
2. **Process Tree & Lifecycle Management**:
   - On Windows: Use Win32 Job Objects (`AssignProcessToJobObject` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) or process group termination to guarantee that child and descendant processes are forcefully stopped on timeout or cancellation.
   - Process ownership tracking binds `(pid, start_time, run_id, worker_id)` rather than bare PIDs to prevent PID reuse hazards.
3. **Filesystem & Worktree Containment**:
   - Strict root-path validation ensuring all reads, writes, and artifact collections resolve inside normalized, designated scratch/worktree roots.
   - Symlinks, junctions, and relative parent references (`..`) escaping the worktree root cause immediate hard errors.
   - Control plane credentials, SSH keys, cloud configs, Git config with tokens, and SQLite control databases are segregated and never exposed to worker directories.
4. **Network & Port Isolation**:
   - Network profile enforcement (e.g. `BLOCKED`, `LOCAL_ONLY`, `MODEL_API_ONLY`).
   - Dynamic port reservation uses OS kernel ephemeral bind (`bind(0)`) rather than predictable hashing to prevent race windows.
5. **Execution Profiles**:
   - `restricted_process`: Windows Job Object / process-tree isolation with strict command registry and sanitized runtime environment.
   - `container_linux`: Containerized execution (UNAVAILABLE if engine absent; fallback to UNAVAILABLE, never silently downgraded to unisolated execution).

## Consequences
- Guaranteed cleanup of rogue descendant processes.
- Immune to PID reuse attacks and worktree escape.
- Verified execution boundary without requiring heavy virtual machine infrastructure.
