# Writing a Custom Adapter

If you're wiring a specific agent runtime (your own agent, an internal
tool, or a transport not covered by `manual.md`/`claude-code.md`/`codex.md`)
into the Factory, subclass `ExecutionAdapter`:

```python
from typing import Any
from orchestrator.adapters.base import ExecutionAdapter


class MyAgentAdapter(ExecutionAdapter):
    """Runs MyAgent against a worktree and reports results for verification."""

    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}

    def start_task(self, task_manifest: dict[str, Any], worktree_path: str) -> str:
        # Kick off your agent/process here. Do not block indefinitely —
        # start it and return a run_id; poll_task checks progress later.
        run_id = f"run-{task_manifest['id']}"
        self.runs[run_id] = {"worktree": worktree_path, "manifest": task_manifest}
        # ... launch your agent process/API call, store its handle ...
        return run_id

    def poll_task(self, run_id: str) -> dict[str, Any]:
        # Return current status. The Factory polls this rather than blocking.
        return {"run_id": run_id, "status": "RUNNING"}

    def cancel_task(self, run_id: str) -> bool:
        # Terminate your agent's process/session. Confirm termination before
        # returning True — the Factory treats True as "safe to reuse the lease".
        return True

    def collect_results(self, run_id: str) -> dict[str, Any]:
        # Return what your agent produced (exit code, raw output, changed
        # paths if you can determine them cheaply). Do NOT report a
        # candidate_digest yourself — that must come from IndependentVerifier
        # over the real worktree diff, not from adapter/agent self-report.
        return {
            "run_id": run_id,
            "exit_code": 0,
            "output": "...",
        }
```

## What the Factory does with your adapter's output

Your adapter's `collect_results` is treated as an **unverified claim**, not
evidence. The control plane still:

1. Snapshots the worktree's git-tracked files
   (`orchestrator.core.worktree.snapshot_worktree`).
2. Computes a genuine diff against `base_sha`
   (`orchestrator.core.worktree.compute_base_file_digests` +
   `IndependentVerifier.compute_diff`).
3. Independently parses test results — prefer producing a JUnit XML report
   from your agent's test run and passing it as `junit_xml` to
   `IndependentVerifier.verify_candidate`, rather than relying on the raw
   log heuristic fallback (`parse_test_output`), which can be fooled by log
   content.
4. Computes `candidate_digest` from the measured diff, never from anything
   your adapter reports.

If your adapter can produce a JUnit XML report, do so — it is a strictly
stronger verification signal than raw stdout/stderr.

## Guardrails your adapter must not bypass

- Never build `argv` from unsanitized agent output and pass it to a shell.
  Use `orchestrator.core.sandbox.validate_command_argv` and
  `PolicyEngine.evaluate_command_id` the way `ManualAdapter` does.
- Never write outside `allowed_paths` — enforce or at least check this
  before handing a worktree off for verification
  (`orchestrator.core.worktree.validate_paths_against_policy`).
- Never fabricate or forward a `candidate_digest` from the agent; it must
  come from `IndependentVerifier`.
- If your transport can't yet guarantee an isolation boundary (process,
  network, filesystem), say so in your adapter's docstring and require an
  explicit `mode="manual"`-style opt-in, the way `AntigravityAdapter` does —
  don't silently degrade to a lower-safety mode.

See `tests/unit/test_approved_container_adapter.py` for a complete worked
example of an adapter feeding a real git worktree through snapshot → diff →
verification.
