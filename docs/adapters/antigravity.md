# Antigravity Adapter

Two classes live in `orchestrator/adapters/antigravity.py`:

- `NativeAntigravityAdapter` — the real native execution path. **Currently
  `BLOCKED`**: `start_task` unconditionally raises
  `AntigravityTransportError`.
- `AntigravityAdapter(mode=...)` — a thin dispatcher. `mode="manual"`
  delegates to `ManualAdapter`; `mode="native"` / `mode="auto"` raise
  `NotImplementedError` rather than silently falling back.

## Why native mode is blocked

`probe_antigravity_runtime()` detects installed `language_server`/`agentapi`
binaries, but binary presence is not proof of a safe execution transport.
The officially available `agentapi` CLI only supports interactive
`new-conversation` / `send-message` calls — there is no verified headless
batch execution mode and no confirmed process/network isolation boundary
equivalent to `OfflineContainerRunner`. Rather than treat "binary found" as
"safe to run untrusted work", the Factory fails closed.

See
[ANTIGRAVITY_INTEGRATION_EVALUATION.md](../operations/ANTIGRAVITY_INTEGRATION_EVALUATION.md)
for the full evaluation and what would need to change for this to unblock
(an official headless batch/isolation SDK).

## Using it today

Select manual mode explicitly — this is the same code path as
[`ManualAdapter`](manual.md), just under the Antigravity-branded class:

```python
from orchestrator.adapters.antigravity import AntigravityAdapter

adapter = AntigravityAdapter(mode="manual")
run_id = adapter.start_task(manifest, worktree_path)
```

`mode="native"` and `mode="auto"` are intentionally not silent aliases for
`"manual"` — you must opt in explicitly so it's never ambiguous which
execution boundary a run went through.
