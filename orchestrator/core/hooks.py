"""Lifecycle verification hooks with Factory-specific contract."""

import subprocess
import time
from collections.abc import Callable
from enum import Enum
from typing import Any


class HookEvent(str, Enum):
    """Factory-specific hook lifecycle events (not vendor events)."""

    BEFORE_TASK = "before_task"
    BEFORE_ACTION = "before_action"
    AFTER_ACTION = "after_action"
    BEFORE_COMMIT = "before_commit"
    BEFORE_PUSH = "before_push"
    BEFORE_REVIEW = "before_review"
    BEFORE_MERGE_READY = "before_merge_ready"
    ON_FAILURE = "on_failure"
    ON_STOP = "on_stop"


class HookExecutionError(Exception):
    """Raised when a hook fails, times out, or emits invalid results (causes DENY)."""


class HookMissingError(HookExecutionError):
    """Raised when a mandatory hook is missing."""


class HookTimeoutError(HookExecutionError):
    """Raised when a hook exceeds allowed execution timeout."""


class HookEngine:
    """Manages and executes lifecycle verification hooks strictly under control plane."""

    def __init__(self):
        self.handlers: dict[HookEvent, list[Callable[[dict[str, Any]], dict[str, Any]]]] = {
            ev: [] for ev in HookEvent
        }

    def register_hook(
        self,
        event: HookEvent,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        """Register a trusted hook handler in control plane."""
        self.handlers[event].append(handler)

    def execute_hook(
        self,
        event: HookEvent,
        context: dict[str, Any],
        required: bool = False,
        timeout_seconds: int = 30,
    ) -> list[dict[str, Any]]:
        """Execute all registered handlers for an event.
        - If required and no handlers registered: raises HookMissingError (DENY)
        - If handler returns status != 'PASS' or errors: raises HookExecutionError (DENY)
        - If handler times out: raises HookTimeoutError (DENY)
        """
        handlers = self.handlers.get(event, [])
        if required and not handlers:
            raise HookMissingError(f"Mandatory hook '{event.value}' has no registered handler (DENIED)")

        results = []
        for handler in handlers:
            start_time = time.time()
            try:
                res = handler(context)
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    raise HookTimeoutError(
                        f"Hook '{event.value}' exceeded timeout of {timeout_seconds}s (took {elapsed:.2f}s) (DENIED)"
                    )

                if not isinstance(res, dict) or res.get("status") != "PASS":
                    reason = res.get("reason", "Unknown hook failure") if isinstance(res, dict) else "Invalid hook return type"
                    raise HookExecutionError(f"Hook '{event.value}' returned non-PASS status: {reason} (DENIED)")

                results.append(res)
            except (HookTimeoutError, HookExecutionError):
                raise
            except Exception as e:
                raise HookExecutionError(f"Hook '{event.value}' failed with exception: {e} (DENIED)") from e

        return results


def run_command_hook(argv: list[str], cwd: str, timeout_seconds: int = 30) -> dict[str, Any]:
    """Helper to run an external command hook synchronously with typed argv."""
    try:
        res = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if res.returncode == 0:
            return {"status": "PASS", "output": res.stdout}
        return {"status": "FAIL", "reason": res.stderr.strip() or res.stdout.strip()}
    except subprocess.TimeoutExpired:
        raise HookTimeoutError(f"Command hook timed out after {timeout_seconds}s")
    except OSError as e:
        return {"status": "ERROR", "reason": str(e)}
