"""Manual execution adapter for deterministic local and CI runs."""

import hashlib
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.adapters.base import ExecutionAdapter
from orchestrator.core.policy import CommandNotAllowedError, PolicyEngine
from orchestrator.core.sandbox import sanitize_worker_environment, validate_command_argv


class ManualAdapter(ExecutionAdapter):
    """Executes pre-registered validation commands synchronously without shell=True."""

    def __init__(self, policy_engine: PolicyEngine | None = None):
        self.runs: dict[str, dict[str, Any]] = {}
        self.active_processes: dict[str, subprocess.Popen] = {}
        self.policy_engine = policy_engine or PolicyEngine()

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
        """Execute a typed command without shell=True enforcing sandbox and policy checks."""
        if run_id not in self.runs:
            raise KeyError(f"Run ID {run_id} not found")

        # 1. Validate argv against shell metacharacters
        validate_command_argv(argv)

        # 2. Verify command_id and base executable against policy registry
        self.policy_engine.evaluate_command_id(command_id)
        exe_name = Path(argv[0]).name
        # Strip Windows .exe extension if present
        if exe_name.lower().endswith(".exe"):
            exe_name = exe_name[:-4]
        self.policy_engine.evaluate_command_id(exe_name)

        # 3. Sanitize environment
        safe_env = sanitize_worker_environment()

        worktree = self.runs[run_id]["worktree_path"]
        try:
            proc = subprocess.Popen(
                argv,
                cwd=worktree,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
            )
            self.active_processes[run_id] = proc
            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
                exit_code = proc.returncode
                val_status = "PASS" if exit_code == 0 else "FAIL"
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                val_status = "ERROR"
                exit_code = -1
        except OSError:
            val_status = "ERROR"
            exit_code = -2
        finally:
            self.active_processes.pop(run_id, None)

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
            # Terminate active process if running
            proc = self.active_processes.pop(run_id, None)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2.0)
                except OSError:
                    pass
            return True
        return False

    def collect_results(self, run_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise KeyError(f"Run ID {run_id} not found")

        run_info = self.runs[run_id]
        manifest = run_info["manifest"]
        worktree = Path(run_info["worktree_path"])

        # Calculate real artifact hashes from worktree filesystem
        artifact_hashes = {}
        all_artifacts_found = True
        for out in manifest.get("output_artifacts", []):
            artifact_rel = out["path"]
            artifact_file = worktree / artifact_rel
            if artifact_file.is_file():
                hasher = hashlib.sha256()
                with open(artifact_file, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
                artifact_hashes[artifact_rel] = hasher.hexdigest()
            else:
                all_artifacts_found = False
                artifact_hashes[artifact_rel] = None

        # Any failure in validations or missing required artifact results in FAILED
        all_passed = all(v["status"] == "PASS" for v in run_info["validations"]) if run_info["validations"] else True
        if run_info.get("status") == "CANCELLED":
            final_status = "CANCELLED"
        elif all_passed and all_artifacts_found:
            final_status = "SUCCESS"
        else:
            final_status = "FAILED"

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

