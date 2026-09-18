# Adapter Guide

An **adapter** connects an external agent runtime to the Factory's control
plane. The Factory never trusts an adapter's self-reported success — every
adapter's output still goes through the same `ArtifactCollector` +
`IndependentVerifier` pipeline before it counts as evidence.

All adapters implement one abstract interface,
`orchestrator.adapters.base.ExecutionAdapter`:

```python
class ExecutionAdapter(ABC):
    def start_task(self, task_manifest: dict, worktree_path: str) -> str: ...
    def poll_task(self, run_id: str) -> dict: ...
    def cancel_task(self, run_id: str) -> bool: ...
    def collect_results(self, run_id: str) -> dict: ...
```

## Which adapter do I want?

| Adapter | Use when | Isolation |
| :--- | :--- | :--- |
| [`ManualAdapter`](manual.md) | Fastest way to try the Factory, or CI-style deterministic runs | None — runs directly against the worktree |
| `OfflineContainerRunner` + `ApprovedContainerAdapter` | You need real isolation between the worker and the host | Network-cut Linux container, read-only snapshot mount |
| [Custom adapter](custom-adapter.md) | You're connecting a specific coding agent (Claude Code, Codex, ...) | Depends on what you build |
| [`NativeAntigravityAdapter`](antigravity.md) | You want native Google Antigravity execution | **Currently `BLOCKED`** — see below |

## "I want to connect Claude Code / Codex / another agent"

There is no first-party native adapter for these today. The supported path
is:

1. Run the agent yourself (interactively, or via its own CLI/SDK) against a
   worktree the Factory manages (`WorktreeManager.create_worktree`, or any
   worktree path you pass to `demo`/`ManualAdapter`).
2. Let the agent make its edits and stop.
3. Hand the resulting worktree to the Factory for **verification and
   approval** — either `ManualAdapter` (no isolation, fast) or
   `OfflineContainerRunner` (isolated, for untrusted output).

This is deliberate: the Factory's job is to independently verify and gate
*any* agent's output, not to re-implement each agent's own execution
transport. See [claude-code.md](claude-code.md) and [codex.md](codex.md) for
worked examples, and [custom-adapter.md](custom-adapter.md) if you want to
wrap that hand-off in your own `ExecutionAdapter` subclass instead of
calling the pieces directly.

## Why Antigravity is `BLOCKED`

`NativeAntigravityAdapter.start_task` unconditionally raises
`AntigravityTransportError`. This is intentional, not a bug: the officially
available Antigravity transport (`agentapi`) only supports interactive
`new-conversation`/`send-message` calls, with no verified headless batch
execution and no confirmed process/network isolation boundary. Rather than
silently falling back to a lower-safety execution mode, the Factory fails
closed and requires you to select `ManualAdapter` explicitly. See
[antigravity.md](antigravity.md) and
[ANTIGRAVITY_INTEGRATION_EVALUATION.md](../operations/ANTIGRAVITY_INTEGRATION_EVALUATION.md)
for the full evaluation.
