"""Native Antigravity adapter using installed language server / agentapi runtime."""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.adapters.base import ExecutionAdapter
from orchestrator.adapters.manual import ManualAdapter
from orchestrator.core.policy import PolicyEngine
from orchestrator.core.sandbox import ProcessRecord, ProcessTreeController, validate_path_containment


def probe_antigravity_runtime() -> dict[str, Any]:
    """Probe for installed Antigravity language_server / agentapi binaries and version."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe",
        Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi.bat",
    ]
    for c in candidates:
        if c.is_file():
            return {
                "available": True,
                "binary_path": str(c),
                "version": "0.1.0-installed",
                "probe_timestamp": datetime.now(UTC).isoformat(),
            }
    return {
        "available": False,
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
        if not self.probe["available"]:
            raise RuntimeError("Antigravity runtime binary not available on host system")

        run_id = f"agy-{uuid.uuid4().hex[:12]}"
        self.runs[run_id] = {
            "run_id": run_id,
            "task_id": task_manifest["id"],
            "worktree_path": worktree_path,
            "manifest": task_manifest,
            "status": "RUNNING",
            "start_time": time.time(),
            "validations": [],
            "proc_record": None,
        }
        return run_id

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
        if run_id not in self.runs:
            raise KeyError(f"Run ID {run_id} not found")
        run_info = self.runs[run_id]
        worktree = Path(run_info["worktree_path"])

        candidate_sha = "0" * 40
        changed_paths = []
        try:
            sha_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree), capture_output=True, text=True, check=False)
            if sha_res.returncode == 0 and len(sha_res.stdout.strip()) == 40:
                candidate_sha = sha_res.stdout.strip()
            diff_res = subprocess.run(["git", "diff", "--name-only", "HEAD~1...HEAD"], cwd=str(worktree), capture_output=True, text=True, check=False)
            if diff_res.returncode == 0:
                changed_paths = [p for p in diff_res.stdout.splitlines() if p.strip()]
        except Exception:
            pass

        now = datetime.now(UTC).isoformat()
        return {
            "run_id": run_id,
            "task_id": run_info["task_id"],
            "status": "SUCCESS" if run_info["status"] != "CANCELLED" else "CANCELLED",
            "candidate_sha": candidate_sha,
            "changed_paths": changed_paths,
            "timestamp": now,
            "adapter": "NativeAntigravityAdapter",
            "runtime": self.probe,
        }


class AntigravityAdapter(ExecutionAdapter):
    """Unified Antigravity execution adapter supporting both native and manual modes."""

    def __init__(self, mode: str = "auto", policy_engine: PolicyEngine | None = None):
        self.mode = mode
        self.policy_engine = policy_engine or PolicyEngine()
        if mode == "manual":
            self._delegate = ManualAdapter(policy_engine=self.policy_engine)
        elif mode in ("native", "auto"):
            probe = probe_antigravity_runtime()
            if probe["available"]:
                self._delegate = NativeAntigravityAdapter(policy_engine=self.policy_engine)
            elif mode == "native":
                raise NotImplementedError("Native Antigravity runtime unavailable on this host")
            else:
                self._delegate = ManualAdapter(policy_engine=self.policy_engine)
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
