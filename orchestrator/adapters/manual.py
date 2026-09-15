"""Manual execution adapter for deterministic local and CI runs."""

import hashlib
import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from orchestrator.adapters.base import ExecutionAdapter


class ManualAdapter(ExecutionAdapter):
    """Executes pre-registered validation commands synchronously without shell=True."""

    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}

    def start_task(self, task_manifest: dict[str, Any], worktree_path: str) -> str:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        self.runs[run_id] = {
            "run_id": run_id,
            "task_id": task_manifest["id"],
            "worktree_path": worktree_path,
            "manifest": task_manifest,
            "status": "RUNNING",
            "start_time": time.time(),
            "validations": [],
            "artifacts": {},
        }
        return run_id

    def execute_validation_step(
        self,
        run_id: str,
        command_id: str,
        argv: list[str],
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Execute a typed command without shell=True."""
        if run_id not in self.runs:
            raise KeyError(f"Run ID {run_id} not found")

        worktree = self.runs[run_id]["worktree_path"]
        try:
            res = subprocess.run(
                argv,
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            val_status = "PASS" if res.returncode == 0 else "FAIL"
            exit_code = res.returncode
        except subprocess.TimeoutExpired:
            val_status = "ERROR"
            exit_code = -1
        except OSError:
            val_status = "ERROR"
            exit_code = -2

        val_record = {
            "command_id": command_id,
            "exit_code": exit_code,
            "status": val_status,
            "tool_version": "manual-runner-1.0",
        }
        self.runs[run_id]["validations"].append(val_record)
        return val_record

    def poll_task(self, run_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise KeyError(f"Run ID {run_id} not found")
        return self.runs[run_id]

    def cancel_task(self, run_id: str) -> bool:
        if run_id in self.runs:
            self.runs[run_id]["status"] = "CANCELLED"
            return True
        return False

    def collect_results(self, run_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise KeyError(f"Run ID {run_id} not found")

        run_info = self.runs[run_id]
        manifest = run_info["manifest"]

        # Calculate dummy or real artifact hashes
        artifact_hashes = {}
        for out in manifest.get("output_artifacts", []):
            artifact_hashes[out["path"]] = hashlib.sha256(out["path"].encode("utf-8")).hexdigest()

        # Any failure in validations results in FAILED
        all_passed = all(v["status"] == "PASS" for v in run_info["validations"]) if run_info["validations"] else True
        final_status = "SUCCESS" if all_passed else "FAILED"

        now = datetime.now(UTC).isoformat()
        return {
            "run_id": run_id,
            "task_id": manifest["id"],
            "attempt": 1,
            "spec_sha": "0" * 64,
            "policy_sha": "0" * 64,
            "base_sha": "0" * 40,
            "candidate_sha": "0" * 40,
            "changed_paths": ["orchestrator/adapters/manual.py"],
            "validations": run_info["validations"],
            "artifact_hashes": artifact_hashes,
            "timestamp": now,
            "status": final_status,
            "usage": {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "wall_time_seconds": round(time.time() - run_info["start_time"], 2),
            },
        }
