"""Native Antigravity adapter using installed language server / agentapi runtime."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.adapters.base import ExecutionAdapter
from orchestrator.adapters.manual import ManualAdapter
from orchestrator.core.policy import PolicyEngine
from orchestrator.core.sandbox import ProcessTreeController


def probe_antigravity_runtime() -> dict[str, Any]:
    """Probe for installed Antigravity language_server / agentapi binaries and version."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe",
        Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi.bat",
    ]
    for c in candidates:
        if c.is_file():
            return {
                "available": False,
                "detected": True,
                "status": "UNVERIFIED",
                "binary_path": str(c),
                "version": None,
                "probe_timestamp": datetime.now(UTC).isoformat(),
            }
    return {
        "available": False,
        "detected": False,
        "status": "UNAVAILABLE",
        "binary_path": None,
        "version": None,
        "probe_timestamp": datetime.now(UTC).isoformat(),
    }


class NativeAntigravityAdapter(ExecutionAdapter):
    """Native Antigravity agent execution adapter with process-tree lifecycle management."""

    def __init__(self, policy_engine: PolicyEngine | None = None):
        self.policy_engine = policy_engine or PolicyEngine()
        self.probe = probe_antigravity_runtime()
        self.runs: dict[str, dict[str, Any]] = {}
        self.controller = ProcessTreeController()

    def start_task(self, task_manifest: dict[str, Any], worktree_path: str) -> str:
        raise NotImplementedError("Native task transport and OS isolation have not been implemented")

    def poll_task(self, run_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise KeyError(f"Run ID {run_id} not found")
        run_info = self.runs[run_id]
        return {
            "run_id": run_id,
            "task_id": run_info["task_id"],
            "status": run_info["status"],
        }

    def cancel_task(self, run_id: str) -> bool:
        if run_id not in self.runs:
            return False
        run_info = self.runs[run_id]
        run_info["status"] = "CANCELLED"
        if run_info.get("proc_record"):
            self.controller.terminate_tree(run_info["proc_record"])
        return True

    def collect_results(self, run_id: str) -> dict[str, Any]:
        raise NotImplementedError("Native task results require a verified execution transport")


class AntigravityAdapter(ExecutionAdapter):
    """Unified Antigravity execution adapter supporting both native and manual modes."""

    def __init__(self, mode: str = "auto", policy_engine: PolicyEngine | None = None):
        self.mode = mode
        self.policy_engine = policy_engine or PolicyEngine()
        if mode == "manual":
            self._delegate = ManualAdapter(policy_engine=self.policy_engine)
        elif mode in ("native", "auto"):
            raise NotImplementedError("Native transport unavailable; manual mode requires explicit selection")
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def start_task(self, task_manifest: dict[str, Any], worktree_path: str) -> str:
        return self._delegate.start_task(task_manifest, worktree_path)

    def poll_task(self, run_id: str) -> dict[str, Any]:
        return self._delegate.poll_task(run_id)

    def cancel_task(self, run_id: str) -> bool:
        return self._delegate.cancel_task(run_id)

    def collect_results(self, run_id: str) -> dict[str, Any]:
        res = self._delegate.collect_results(run_id)
        res["mode"] = self.mode
        return res
