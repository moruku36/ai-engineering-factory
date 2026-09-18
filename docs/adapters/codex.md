# Using Codex (or other CLI coding agents) with the Factory

The same pattern as [Claude Code](claude-code.md) applies to Codex, or any
other CLI/SDK-driven coding agent: the Factory does not run the agent for
you, it verifies and gates whatever the agent produced.

## Recommended flow

1. Create (or reuse) a worktree for the task:

   ```python
   from orchestrator.core.worktree import WorktreeManager

   manager = WorktreeManager(repo_root="/path/to/your/repo", runtime_root="/path/to/runtime-root")
   worktree_path = manager.create_worktree(task_id="TASK-001", branch="task/task-001", base_ref="main")
   ```

2. Run your Codex CLI/SDK against `worktree_path`, scoped to the task's
   `allowed_paths`. Let it exit when done — no live connection to the
   Factory is required.

3. Hand the resulting worktree to the Factory for verification:
   - Quick, non-isolated check while iterating: [`ManualAdapter`](manual.md).
   - Full isolated verification against untrusted output:
     [Getting Started §6](../getting-started.md#6-the-real-isolation--verification-path)
     (`OfflineContainerRunner` + `IndependentVerifier`, restricted to a
     read-only snapshot of the worktree).

4. If Codex can emit a JUnit XML test report, pass it as `junit_xml` to
   `IndependentVerifier.verify_candidate` — this is parsed structurally
   instead of falling back to a string heuristic over raw output, and is
   the stronger signal.

## Packaging this as an adapter

For repeated use, wrap the launch + poll + collect steps in your own
`ExecutionAdapter` subclass so the rest of the pipeline (worktree
provisioning, verification, approval) stays uniform across agents — see
[custom-adapter.md](custom-adapter.md).
