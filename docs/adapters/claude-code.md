# Using Claude Code with the Factory

There is no native Claude Code adapter — and it doesn't need one. Claude
Code already runs as its own agent with its own tool loop; the Factory's
job starts once Claude Code has made its edits.

## Recommended flow

1. **Create an isolated worktree** for the task (or use a worktree path of
   your own):

   ```python
   from orchestrator.core.worktree import WorktreeManager

   manager = WorktreeManager(repo_root="/path/to/your/repo", runtime_root="/path/to/runtime-root")
   worktree_path = manager.create_worktree(task_id="TASK-001", branch="task/task-001", base_ref="main")
   ```

2. **Run Claude Code against that worktree** as you normally would — e.g.
   `claude` in that directory, or the Claude Agent SDK pointed at
   `worktree_path` as its working directory. Let it implement the task
   described in your task manifest's `allowed_paths` / `prohibited_paths`.

3. **Hand the worktree to the Factory for verification**, exactly like any
   other builder output — see
   [Getting Started §6](../getting-started.md#6-the-real-isolation--verification-path)
   for the full snapshot → diff → verify flow, or use `ManualAdapter` for a
   quicker, non-isolated check while iterating (`manual.md`).

4. Verification and approval proceed identically regardless of which agent
   produced the diff — the Factory does not distinguish "Claude Code" from
   any other source once the worktree is handed off.

## If you want a thin wrapper adapter

If you're scripting this repeatedly, wrap steps 1-2 in your own
`ExecutionAdapter` subclass (`start_task` launches Claude Code against a
fresh worktree, `poll_task` checks whether it has finished, `collect_results`
reports its exit status) — see [custom-adapter.md](custom-adapter.md). Keep
the actual verification (step 3) as-is; don't let the wrapper report its own
`candidate_digest`.
