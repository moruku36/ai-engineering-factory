"""Single-dispatch offline adapter with bound approval and durable execution evidence.

Only the trusted controller constructs this adapter. ApprovalManager remains an
integrity primitive; this module does not authenticate a Human or issue approvals.
"""

import hashlib
import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from copy import copy, deepcopy
from pathlib import Path

from orchestrator.adapters.base import ExecutionAdapter
from orchestrator.core.approval import ApprovalManager
from orchestrator.core.artifacts import ArtifactCollector, ArtifactExtractionError
from orchestrator.core.container import OfflineContainerRunner
from orchestrator.core.sandbox import _get_process_creation_time, _is_process_alive
from orchestrator.core.verifier import IndependentVerifier, VerificationError


class ContainerAdmissionError(RuntimeError):
    """Admission/recovery is uncertain or forbidden; operator reconciliation required."""


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class ApprovedContainerAdapter(ExecutionAdapter):
    """Synchronous, single-worker bridge; one dispatch per task in this control DB.

    plans is a trusted task-ID mapping containing repository, head_sha, target_ref,
    policy_hash, plan_hash, command_id and an explicit inputs mapping of bytes.
    tokens maps task IDs to previously issued approval token IDs, never actor names.
    """

    synchronous = True

    def __init__(self, runner: OfflineContainerRunner, approvals: ApprovalManager,
                 plans: dict, tokens: dict[str, str], state_dir: Path):
        self.runner = runner
        self.approvals = approvals
        self.plans = deepcopy(plans)
        self.tokens = dict(tokens)
        self.root = Path(state_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if sys.platform == "linux":
            stat = self.root.stat()
            if stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
                raise ContainerAdmissionError("Adapter state must be controller-owned mode 0700")
        self.db = self.root / "executions.sqlite"
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS executions (
                task_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL,
                digest TEXT NOT NULL, token_id TEXT NOT NULL, status TEXT NOT NULL,
                owner_pid INTEGER NOT NULL, owner_start REAL NOT NULL,
                result TEXT
            )""")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def approval_context(self, manifest: dict, worktree_path: str) -> dict:
        """Preview the exact binding to be signed by an external trusted issuer."""
        return self._context(manifest, worktree_path, self.plans[manifest["id"]], self.runner)

    @staticmethod
    def _context(manifest: dict, worktree_path: str, plan: dict,
                 runner: OfflineContainerRunner) -> dict:
        task_id = manifest["id"]
        command = runner.commands[plan["command_id"]]
        context = {key: plan[key] for key in (
            "repository", "head_sha", "target_ref", "policy_hash", "plan_hash",
        )}
        context.update(action="task_execution", task_id=task_id)
        context["argv_digest"] = _digest({
            "profile": "offline-linux-v1", "image": runner.image_id,
            "runtime_root": str(runner.root),
            "command_id": plan["command_id"], "argv": command.argv,
            "timeout_sec": command.timeout_sec, "network": "NONE",
            "manifest": manifest, "worktree_reference": worktree_path,
            "inputs": {name: hashlib.sha256(data).hexdigest()
                       for name, data in plan["inputs"].items()},
        })
        return context

    def validate_task_context(self, manifest: dict, state: dict) -> None:
        context = self.approval_context(manifest, manifest["worktree"])
        if (context["head_sha"] != state.get("base_sha")
                or context["plan_hash"] != state.get("spec_digest")
                or context["policy_hash"] != state.get("policy_digest")):
            raise ContainerAdmissionError("Task ledger and approved execution context differ")

    def lease_timeout_seconds(self, manifest: dict) -> int:
        # Includes bounded Docker preflight/create/start/log/cleanup calls. Execution
        # is synchronous, so a worker heartbeat thread is not required in this profile.
        command = self.runner.commands[self.plans[manifest["id"]]["command_id"]]
        return command.timeout_sec + 600

    def _record(self, *, run_id=None, task_id=None) -> dict:
        column, value = ("run_id", run_id) if run_id else ("task_id", task_id)
        with self._connect() as connection:
            record = connection.execute(
                f"SELECT * FROM executions WHERE {column} = ?", (value,),
            ).fetchone()
        if record is None:
            raise ContainerAdmissionError("No durable execution record; do not redispatch")
        return dict(record)

    def _status(self, run_id: str, status: str, result=None) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE executions SET status = ?, result = ? WHERE run_id = ?",
                               (status, json.dumps(result) if result is not None else None, run_id))

    def start_task(self, task_manifest: dict, worktree_path: str) -> str:
        manifest = deepcopy(task_manifest)
        task_id = manifest["id"]
        plan = deepcopy(self.plans[task_id])
        runner = copy(self.runner)
        runner.commands = dict(self.runner.commands)
        context = self._context(manifest, worktree_path, plan, runner)
        token_id = self.tokens.get(task_id)
        if not token_id:
            raise ContainerAdmissionError("Approval token required before container execution")
        run_id = uuid.uuid4().hex
        started = _get_process_creation_time(os.getpid())
        if not started:
            raise ContainerAdmissionError("Controller process identity unavailable")
        try:
            with self._connect() as connection:
                connection.execute("INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                                   (task_id, run_id, _digest(context), token_id, "RESERVED",
                                    os.getpid(), started))
        except sqlite3.IntegrityError as exc:
            raise ContainerAdmissionError("Task already claimed; no automatic redispatch") from exc
        try:
            # Persist reservation before consume. A crash between the two databases
            # may require operator recovery, but can never silently reuse a token.
            self.approvals.verify_and_consume_token(token_id=token_id, **context)
            self._status(run_id, "ADMITTED")
            result = runner.run(plan["command_id"], plan["inputs"], run_id=run_id)
            if result.run_id != run_id:
                raise ContainerAdmissionError("Container result identity differs from admission")

            candidate_sha = None
            changed_paths = []
            if result.exit_code == 0 and result.artifacts_dir and result.artifacts_dir.exists():
                has_files = any(result.artifacts_dir.iterdir())
                if has_files:
                    try:
                        collector = ArtifactCollector(allowed_paths=plan.get("allowed_paths", ["*"]))
                        collected_dir = self.root / run_id / "collected_artifacts"
                        collection_res = collector.collect(result.artifacts_dir, collected_dir)
                        verifier = IndependentVerifier()
                        measured = verifier.verify_candidate(
                            task_id=task_id,
                            base_sha=context["head_sha"],
                            artifacts=collection_res,
                            execution_exit_code=result.exit_code,
                            execution_output=result.output,
                        )
                        candidate_sha = measured.candidate_sha
                        changed_paths = measured.changed_paths
                    except (ArtifactExtractionError, VerificationError) as exc:
                        raise ContainerAdmissionError(f"Artifact verification failed: {exc}") from exc

            evidence = {
                "status": "SUCCESS" if result.exit_code == 0 else "FAILED",
                "run_id": run_id,
                "exit_code": result.exit_code,
                "output": result.output,
                "execution_digest": context["argv_digest"],
                "candidate_sha": candidate_sha,
                "changed_paths": changed_paths,
            }
            self._status(run_id, evidence["status"], evidence)
            return run_id
        except Exception:
            self._status(run_id, "BLOCKED")
            raise

    def poll_task(self, run_id: str) -> dict:
        record = self._record(run_id=run_id)
        return {"status": record["status"], "run_id": run_id}

    def collect_results(self, run_id: str) -> dict:
        record = self._record(run_id=run_id)
        if record["status"] not in ("SUCCESS", "FAILED") or not record["result"]:
            raise ContainerAdmissionError("No verified execution result")
        return json.loads(record["result"])

    def cancel_task(self, run_id: str) -> bool:
        raise ContainerAdmissionError("Live cancellation is unavailable; reconcile a stopped controller")

    def recover_task(self, manifest: dict, worktree_path: str) -> str:
        """Recover a result or remove an orphan; never execute the command again."""
        record = self._record(task_id=manifest["id"])
        if record["digest"] != _digest(self.approval_context(manifest, worktree_path)):
            raise ContainerAdmissionError("Recovery context differs from admitted execution")
        if record["status"] in ("SUCCESS", "FAILED"):
            return record["run_id"]
        if _is_process_alive(record["owner_pid"]):
            actual_start = _get_process_creation_time(record["owner_pid"])
            if not actual_start or actual_start == record["owner_start"]:
                raise ContainerAdmissionError("Controller still alive or identity uncertain")
        journal = self.runner.root / record["run_id"] / "record.json"
        if journal.exists():
            self.runner.reconcile(record["run_id"])
        # No journal means the controller died before any Docker mutation. Either
        # way there is no proven result; retain the claim and require fresh planning.
        self._status(record["run_id"], "BLOCKED")
        return record["run_id"]
