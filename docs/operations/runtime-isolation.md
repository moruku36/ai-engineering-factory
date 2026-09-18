# Runtime Isolation & Directory Governance

## 1. Directory Separation
- **Repository Root**: Code, configuration, documentation, audited schemas, verified state projections.
- **Runtime Root**: Ephemeral operational data.
  - Path: `~/.ai-engineering-factory/runtime/<owner>__<repo>/`, created by `python -m orchestrator.cli init` (vendor-neutral; not specific to any one adapter).
  - Subdirectories:
    - `worktrees/`: Isolated Git worktree clones for agent tasks.
    - `leases/`: Active execution lock and lease records.
    - `logs/`: Verbose execution traces and agent stdout/stderr.
    - `db/`: SQLite runtime database.

## 2. Worktree Ingestion Protocol
1. Control Plane provisions a clean worktree at `runtime-root/worktrees/<task-id>`.
2. Worker performs changes within the worktree.
3. Control Plane verifies `git status` against `allowed_paths` and `prohibited_paths`.
4. If valid, Control Plane stages, commits, and records the candidate SHA.
5. Worktree is safely cleaned up after validation.
