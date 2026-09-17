"""Persistent orchestration run loop coordinating Scheduler, StateLedger, Leases, and Adapters."""

import os
import time
from typing import Any

from orchestrator.core.lease import LeaseAcquisitionError, RuntimeLeaseManager
from orchestrator.core.scheduler import DAGScheduler
from orchestrator.core.state import StateLedger, TaskStatus


class RunLoopController:
    """Coordinates lifecycle transitions, lease allocations, execution, and evidence collection."""

    def __init__(
        self,
        task_manifests: list[dict[str, Any]],
        state_ledger: StateLedger,
        lease_manager: RuntimeLeaseManager,
        adapter: Any,
        spec_digest: str,
        policy_digest: str,
        base_sha: str | None = None,
        max_workers: int = 2,
    ):
        for method in ("start_task", "poll_task", "collect_results", "cancel_task"):
            if not callable(getattr(adapter, method, None)):
                raise TypeError(f"Execution adapter must implement {method}")
        if getattr(adapter, "synchronous", False) and max_workers != 1:
            raise ValueError("Synchronous execution requires max_workers=1")
        self.task_manifests = {t["id"]: t for t in task_manifests}
        self.state_ledger = state_ledger
        self.lease_manager = lease_manager
        self.adapter = adapter
        self.spec_digest = spec_digest
        self.policy_digest = policy_digest
        self.base_sha = base_sha
        self.scheduler = DAGScheduler(task_manifests, max_workers=max_workers)
        self.active_sessions: dict[str, dict[str, Any]] = {}  # task_id -> {session_id, lease_id}

    def initialize_tasks(self) -> None:
        """Load persisted states; adapter recovery never re-executes a task."""
        for tid in self.task_manifests:
            try:
                state = self.state_ledger.get_state(tid)
            except FileNotFoundError:
                state = self.state_ledger.initialize_task(
                    task_id=tid,
                    spec_digest=self.spec_digest,
                    policy_digest=self.policy_digest,
                    base_sha=self.base_sha,
                )

            # Initialization is not preflight or Human approval. Only a trusted
            # controller may advance persisted tasks to READY.
            if state["status"] == TaskStatus.RUNNING.value and tid not in self.active_sessions:
                recover = getattr(self.adapter, "recover_task", None)
                lease = self.lease_manager.get_active_lease(tid)
                if not callable(recover) or not lease:
                    raise RuntimeError("Active session recovery requires reconciliation before dispatch")
                task = self.task_manifests[tid]
                validator = getattr(self.adapter, "validate_task_context", None)
                if callable(validator):
                    validator(task, state)
                session_id = recover(task, task["worktree"])
                self.active_sessions[tid] = {
                    "session_id": session_id, "worker_id": lease["worker_id"], "epoch": lease["epoch"],
                }
            self.scheduler.update_task_status(tid, TaskStatus(state["status"]))

    def step(self) -> bool:
        """Perform one execution cycle. Returns True if work was performed or is active."""
        work_done = False

        # 1. Poll active sessions
        finished_tasks = []
        for tid, sess in list(self.active_sessions.items()):
            session_id = sess["session_id"]
            poll_res = self.adapter.poll_task(session_id)
            status = poll_res.get("status")

            if status in ("COMPLETED", "SUCCESS"):
                # Collect evidence
                evidence = self.adapter.collect_results(session_id)
                if evidence.get("status") not in ("COMPLETED", "SUCCESS"):
                    raise RuntimeError("Adapter completion disagrees with collected result; reconcile run")
                cur_state = self.state_ledger.get_state(tid)

                # RUNNING -> VALIDATING -> REVIEW -> READY_FOR_MERGE
                self.state_ledger.transition(
                    task_id=tid,
                    expected_revision=cur_state["revision"],
                    to_status=TaskStatus.VALIDATING,
                    reason="Execution finished, validating evidence",
                    candidate_digest=evidence.get("candidate_digest"),
                )
                # Worker completion is not independent validation/review or a
                # remotely observed Human merge. Keep dependencies blocked.
                self.scheduler.update_task_status(tid, TaskStatus.VALIDATING)
                self.lease_manager.release_lease(tid, sess["worker_id"], epoch=sess["epoch"])
                finished_tasks.append(tid)
                work_done = True

            elif status == "BLOCKED":
                current = self.state_ledger.get_state(tid)
                self.state_ledger.transition(
                    tid, current["revision"], TaskStatus.BLOCKED,
                    "Execution outcome requires operator reconciliation; do not redispatch",
                )
                self.scheduler.update_task_status(tid, TaskStatus.BLOCKED)
                # Keep the lease: BLOCKED is not proof of successful execution.
                finished_tasks.append(tid)
                work_done = True

            elif status in ("FAILED", "ERROR"):
                cur_state = self.state_ledger.get_state(tid)
                self.state_ledger.transition(
                    task_id=tid,
                    expected_revision=cur_state["revision"],
                    to_status=TaskStatus.FAILED,
                    reason=f"Execution failed with status: {status}",
                )
                self.scheduler.update_task_status(tid, TaskStatus.FAILED)
                # Downstream tasks become BLOCKED in ledger
                for dep_id in self.scheduler.dag.get_dependents(tid):
                    try:
                        dep_state = self.state_ledger.get_state(dep_id)
                        if dep_state["status"] not in (TaskStatus.FAILED.value, TaskStatus.DONE.value):
                            self.state_ledger.transition(
                                task_id=dep_id,
                                expected_revision=dep_state["revision"],
                                to_status=TaskStatus.BLOCKED,
                                reason=f"Upstream dependency {tid} failed",
                            )
                    except (KeyError, OSError, ValueError):
                        pass
                self.lease_manager.release_lease(tid, sess["worker_id"], epoch=sess["epoch"])
                finished_tasks.append(tid)
                work_done = True

        for tid in finished_tasks:
            del self.active_sessions[tid]

        # 2. Dispatch ready tasks
        dispatchable = self.scheduler.get_dispatchable_tasks()
        for tid in dispatchable:
            task = self.task_manifests[tid]
            if not task.get("worktree"):
                raise ValueError("A preflight-verified worktree is required")
            validator = getattr(self.adapter, "validate_task_context", None)
            if callable(validator):
                validator(task, self.state_ledger.get_state(tid))
            timeout = getattr(self.adapter, "lease_timeout_seconds", None)
            lease_timeout = timeout(task) if callable(timeout) else 60.0
            worker_id = f"worker-{tid}"
            pid = os.getpid()

            # Acquire runtime lease
            try:
                epoch = self.lease_manager.acquire_lease(
                    task_id=tid,
                    worker_id=worker_id,
                    pid=pid,
                    timeout_seconds=lease_timeout,
                )
            except (LeaseAcquisitionError, OSError):
                continue

            # Update scheduler and state ledger
            self.scheduler.dispatch(tid)
            cur_state = self.state_ledger.get_state(tid)
            self.state_ledger.transition(
                task_id=tid,
                expected_revision=cur_state["revision"],
                to_status=TaskStatus.RUNNING,
                reason="Task dispatched to worker",
            )

            # Start execution via adapter
            try:
                session_id = self.adapter.start_task(task, task["worktree"])
            except Exception:
                # A transport error may follow an external start. Retain the lease
                # until reconciliation proves that no worker remains active.
                current = self.state_ledger.get_state(tid)
                self.state_ledger.transition(
                    tid, current["revision"], TaskStatus.BLOCKED,
                    "Start outcome uncertain; reconcile worker and lease before retry",
                )
                self.scheduler.update_task_status(tid, TaskStatus.BLOCKED)
                raise
            self.active_sessions[tid] = {
                "session_id": session_id,
                "worker_id": worker_id,
                "epoch": epoch,
            }
            work_done = True

        return work_done or len(self.active_sessions) > 0

    def run_until_idle(self, max_iterations: int = 50, sleep_interval: float = 0.05) -> dict[str, Any]:
        """Run loop until all tasks reach terminal/blocked state or iteration limit is reached."""
        iterations = 0
        while iterations < max_iterations:
            iterations += 1
            has_activity = self.step()
            if not has_activity and len(self.active_sessions) == 0:
                break
            time.sleep(sleep_interval)

        summary = {}
        for tid in self.task_manifests:
            try:
                st = self.state_ledger.get_state(tid)
                summary[tid] = st["status"]
            except (KeyError, OSError, ValueError):
                summary[tid] = "UNKNOWN"
        return summary
