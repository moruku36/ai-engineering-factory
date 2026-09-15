"""DAG scheduler and resource conflict engine for multi-agent dispatch."""

from typing import Any

from orchestrator.core.schema import check_circular_dependencies
from orchestrator.core.state import TaskStatus


class ResourceConflictError(Exception):
    """Raised when tasks conflict on paths, exclusive locks, or ports."""


def check_path_overlap(paths_a: list[str], paths_b: list[str]) -> bool:
    """Check if any path in paths_a overlaps or shares a common prefix with paths_b."""
    for pa in paths_a:
        pa_clean = pa.replace("\\", "/").rstrip("/") + "/"
        for pb in paths_b:
            pb_clean = pb.replace("\\", "/").rstrip("/") + "/"
            if pa_clean.startswith(pb_clean) or pb_clean.startswith(pa_clean):
                return True
    return False


class TaskDAG:
    """Represents the directed acyclic graph of task dependencies."""

    def __init__(self, task_manifests: list[dict[str, Any]]):
        self.tasks: dict[str, dict[str, Any]] = {t["id"]: t for t in task_manifests}
        check_circular_dependencies(self.tasks)

    def get_dependents(self, task_id: str) -> list[str]:
        """Return all tasks that depend directly or indirectly on task_id."""
        dependents: list[str] = []
        for tid, task in self.tasks.items():
            if task_id in task.get("dependencies", []):
                dependents.append(tid)
                dependents.extend(self.get_dependents(tid))
        return list(dict.fromkeys(dependents))


class DAGScheduler:
    """Schedules and dispatches tasks based on DAG dependencies, resource locks, and concurrency limits."""

    def __init__(self, task_manifests: list[dict[str, Any]], max_workers: int = 2):
        if max_workers < 1 or max_workers > 3:
            raise ValueError(f"max_workers must be between 1 and 3 in Phase 3 (got {max_workers})")

        self.dag = TaskDAG(task_manifests)
        self.max_workers = max_workers
        self.task_statuses: dict[str, TaskStatus] = {
            t["id"]: TaskStatus(t.get("status", TaskStatus.PROPOSED.value)) for t in task_manifests
        }
        self.active_tasks: set[str] = set()

    def update_task_status(self, task_id: str, new_status: TaskStatus) -> None:
        """Update task status in scheduler."""
        if task_id not in self.dag.tasks:
            raise KeyError(f"Task {task_id} not found in plan")

        old_status = self.task_statuses[task_id]
        self.task_statuses[task_id] = new_status

        if old_status == TaskStatus.RUNNING and new_status != TaskStatus.RUNNING:
            self.active_tasks.discard(task_id)

        # If task FAILED, mark all downstream dependents as BLOCKED
        if new_status == TaskStatus.FAILED:
            dependents = self.dag.get_dependents(task_id)
            for dep in dependents:
                self.task_statuses[dep] = TaskStatus.BLOCKED

    def retry_failed_task(self, task_id: str) -> None:
        """Reset a failed task back to READY if eligible for retry."""
        if self.task_statuses.get(task_id) != TaskStatus.FAILED:
            raise ValueError(f"Task {task_id} is not in FAILED state (status={self.task_statuses.get(task_id)})")
        self.task_statuses[task_id] = TaskStatus.READY


    def get_dispatchable_tasks(self) -> list[str]:
        """Calculate tasks that are ready to be dispatched:
        1. Current status is PROPOSED or READY.
        2. All dependencies are DONE.
        3. No resource conflict with currently active tasks.
        4. Respect max_workers concurrency.
        """
        available_slots = self.max_workers - len(self.active_tasks)
        if available_slots <= 0:
            return []

        ready_candidates: list[str] = []

        for tid, task in self.dag.tasks.items():
            if tid in self.active_tasks:
                continue

            status = self.task_statuses[tid]
            if status not in (TaskStatus.PROPOSED, TaskStatus.READY):
                continue

            # Check dependencies: must ALL be DONE
            deps = task.get("dependencies", [])
            deps_done = all(self.task_statuses.get(d) == TaskStatus.DONE for d in deps)
            if not deps_done:
                continue

            # Check conflicts against currently active tasks
            has_conflict = False
            for active_id in self.active_tasks:
                active_task = self.dag.tasks[active_id]
                if self._check_task_conflict(task, active_task):
                    has_conflict = True
                    break

            if not has_conflict:
                ready_candidates.append(tid)

        # Further filter candidates to ensure they don't conflict with each other
        dispatchable: list[str] = []
        for candidate_id in ready_candidates:
            if len(dispatchable) >= available_slots:
                break
            candidate_task = self.dag.tasks[candidate_id]
            conflict_with_selected = any(
                self._check_task_conflict(candidate_task, self.dag.tasks[sel]) for sel in dispatchable
            )
            if not conflict_with_selected:
                dispatchable.append(candidate_id)

        return dispatchable

    def dispatch(self, task_id: str) -> None:
        """Mark task as actively dispatched and running."""
        if len(self.active_tasks) >= self.max_workers:
            raise RuntimeError(f"Cannot dispatch {task_id}: reached max workers limit ({self.max_workers})")

        self.active_tasks.add(task_id)
        self.task_statuses[task_id] = TaskStatus.RUNNING

    def _check_task_conflict(self, task_a: dict[str, Any], task_b: dict[str, Any]) -> bool:
        """Check if two tasks cannot run concurrently:
        - Non-parallelizable tasks cannot run with any other task.
        - Overlapping allowed_paths.
        - Shared exclusive keys.
        - Overlapping ports.
        """
        # Non-parallelizable check
        if not task_a.get("parallelizable", True) or not task_b.get("parallelizable", True):
            return True

        # Path overlap check
        paths_a = task_a.get("allowed_paths", [])
        paths_b = task_b.get("allowed_paths", [])
        if check_path_overlap(paths_a, paths_b):
            return True

        # Exclusive keys check
        res_a = task_a.get("resources", {})
        res_b = task_b.get("resources", {})
        keys_a = set(res_a.get("exclusive_keys", []))
        keys_b = set(res_b.get("exclusive_keys", []))
        if keys_a.intersection(keys_b):
            return True

        # Port conflict check
        ports_a = set(res_a.get("ports", []))
        ports_b = set(res_b.get("ports", []))
        return bool(ports_a.intersection(ports_b))
