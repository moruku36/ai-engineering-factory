# ManualAdapter

`orchestrator.adapters.manual.ManualAdapter` is the simplest adapter: it
runs a registered validation command as a real subprocess directly against a
worktree you give it, with no network or filesystem isolation. It is what
`python -m orchestrator.cli demo` uses under the hood (see
[Getting Started](../getting-started.md#5-run-it-end-to-end-local-demo)).

Use it when:

- You're trying the Factory out for the first time.
- The code you're validating is already trusted (e.g. your own worktree,
  CI on a repo you control).
- You want deterministic, fast local runs without Docker.

Do **not** use it for untrusted agent output — there is no isolation
boundary. Use `OfflineContainerRunner` for that.

## Minimal example

```python
from orchestrator.adapters.manual import ManualAdapter

manifest = {
    "id": "TASK-001",
    "validation": [{"command_id": "pytest", "timeout_seconds": 300}],
    "output_artifacts": [{"path": "reports/task-001-report.json"}],
}

adapter = ManualAdapter()
run_id = adapter.start_task(manifest, worktree_path="/path/to/worktree")

adapter.execute_validation_step(
    run_id, "pytest",
    argv=["python", "-m", "pytest", "tests/unit/", "-q"],
    timeout_seconds=300,
)

results = adapter.collect_results(run_id)
print(results["status"], results["artifact_hashes"])
```

Notes:

- `command_id` must be in the `PolicyEngine` allowed command registry
  (`pytest`, `ruff`, `python`, `python3`, `git`, `npm`, `node` by default —
  see `orchestrator/core/policy.py`).
- `argv` is validated against shell metacharacters and never passed through
  a shell (`subprocess.Popen(argv, ...)`, no `shell=True`).
- `collect_results` hashes every path in `output_artifacts` from the
  worktree; a missing artifact or a failed validation step makes the run
  `FAILED`.
