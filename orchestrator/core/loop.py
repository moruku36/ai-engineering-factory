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
        """Initialize task records in ledger and advance to READY if eligible."""
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

            # Move from PROPOSED to READY if new
            if state["status"] == TaskStatus.PROPOSED.value:
                state = self.state_ledger.transition(
                    task_id=tid,
                    expected_revision=state["revision"],
                    to_status=TaskStatus.READY,
                    reason="Preflight requirements verified; ready for dispatch",
                )
            self.scheduler.update_task_status(tid, TaskStatus(state["status"]))

    def step(self) -> bool:
        """Perform one execution cycle. Returns True if work was performed or is active."""
        work_done = False

        # 1. Poll active sessions
        finished_tasks = []
        for tid, sess in list(self.active_sessions.items()):
            session_id = sess["session_id"]
            poll_res = self.adapter.poll_execution(session_id)
            status = poll_res.get("status")

            if status == "COMPLETED":
                # Collect evidence
                evidence = self.adapter.collect_evidence(session_id)
                cur_state = self.state_ledger.get_state(tid)

                # RUNNING -> VALIDATING -> REVIEW -> READY_FOR_MERGE
                s1 = self.state_ledger.transition(
                    task_id=tid,
                    expected_revision=cur_state["revision"],
                    to_status=TaskStatus.VALIDATING,
                    reason="Execution finished, validating evidence",
                    candidate_sha=evidence.get("candidate_sha"),
                )
                s2 = self.state_ledger.transition(
                    task_id=tid,
                    expected_revision=s1["revision"],
                    to_status=TaskStatus.REVIEW,
                    reason="Validation passed, awaiting review",
                )
                self.state_ledger.transition(
                    task_id=tid,
                    expected_revision=s2["revision"],
                    to_status=TaskStatus.READY_FOR_MERGE,
                    reason="Independent review approved",
                )
                self.scheduler.update_task_status(tid, TaskStatus.DONE)  # In DAG scheduler, completion unblocks deps
                self.lease_manager.release_lease(tid, sess["worker_id"], epoch=sess["epoch"])
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
            worker_id = f"worker-{tid}"
            pid = os.getpid()

            # Acquire runtime lease
            try:
                epoch = self.lease_manager.acquire_lease(
                    task_id=tid,
                    worker_id=worker_id,
                    pid=pid,
                    timeout_seconds=60.0,
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
            exec_info = self.adapter.start_execution(task)
            self.active_sessions[tid] = {
                "session_id": exec_info["session_id"],
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
