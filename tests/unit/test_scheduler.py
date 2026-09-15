"""Unit tests for DAG scheduler, dependency resolution, and resource conflicts."""

from orchestrator.core.scheduler import DAGScheduler, check_path_overlap
from orchestrator.core.state import TaskStatus


def make_task(
    tid: str,
    deps: list[str] | None = None,
    parallelizable: bool = True,
    paths: list[str] | None = None,
    keys: list[str] | None = None,
    ports: list[str] | None = None,
) -> dict:
    return {
        "id": tid,
        "dependencies": deps or [],
        "parallelizable": parallelizable,
        "allowed_paths": paths or [f"sub_{tid.lower()}/"],
        "resources": {
            "ports": ports or [],
            "test_db": False,
            "exclusive_keys": keys or [],
        },
        "status": "READY",
    }


def test_path_overlap_logic():
    assert check_path_overlap(["src/"], ["src/core/"])
    assert check_path_overlap(["docs/"], ["docs/"])
    assert not check_path_overlap(["src/"], ["tests/"])
    assert not check_path_overlap(["frontend/"], ["backend/"])


def test_dag_dependency_ordering():
    # TASK-A -> TASK-B (B depends on A)
    tasks = [
        make_task("TASK-A"),
        make_task("TASK-B", deps=["TASK-A"]),
    ]
    scheduler = DAGScheduler(tasks, max_workers=2)

    # Initially only TASK-A can be dispatched
    ready = scheduler.get_dispatchable_tasks()
    assert ready == ["TASK-A"]

    # Dispatch and complete TASK-A
    scheduler.dispatch("TASK-A")
    assert scheduler.get_dispatchable_tasks() == []

    scheduler.update_task_status("TASK-A", TaskStatus.DONE)

    # Now TASK-B is ready
    ready = scheduler.get_dispatchable_tasks()
    assert ready == ["TASK-B"]


def test_independent_tasks_dispatched_in_parallel():
    # 3 independent tasks, max_workers=2
    tasks = [
        make_task("TASK-1"),
        make_task("TASK-2"),
        make_task("TASK-3"),
    ]
    scheduler = DAGScheduler(tasks, max_workers=2)

    ready = scheduler.get_dispatchable_tasks()
    assert len(ready) == 2
    assert set(ready) == {"TASK-1", "TASK-2"}

    scheduler.dispatch("TASK-1")
    scheduler.dispatch("TASK-2")
    assert scheduler.get_dispatchable_tasks() == []

    # Finish TASK-1 -> TASK-3 becomes ready
    scheduler.update_task_status("TASK-1", TaskStatus.DONE)
    assert scheduler.get_dispatchable_tasks() == ["TASK-3"]


def test_path_conflict_serialization():
    # TASK-1 and TASK-2 share overlapping paths
    tasks = [
        make_task("TASK-1", paths=["shared_code/"]),
        make_task("TASK-2", paths=["shared_code/submodule/"]),
    ]
    scheduler = DAGScheduler(tasks, max_workers=2)

    ready = scheduler.get_dispatchable_tasks()
    # Cannot dispatch both concurrently
    assert len(ready) == 1
    assert ready == ["TASK-1"]


def test_exclusive_key_serialization():
    # TASK-1 and TASK-2 share database lock
    tasks = [
        make_task("TASK-1", keys=["postgres_db"]),
        make_task("TASK-2", keys=["postgres_db"]),
    ]
    scheduler = DAGScheduler(tasks, max_workers=2)

    ready = scheduler.get_dispatchable_tasks()
    assert len(ready) == 1
    assert ready == ["TASK-1"]


def test_failure_blocks_dependents_preserves_independent():
    # TASK-A -> TASK-B (dependent)
    # TASK-C (independent)
    tasks = [
        make_task("TASK-A"),
        make_task("TASK-B", deps=["TASK-A"]),
        make_task("TASK-C"),
    ]
    scheduler = DAGScheduler(tasks, max_workers=2)

    scheduler.dispatch("TASK-A")
    scheduler.dispatch("TASK-C")

    # TASK-A fails!
    scheduler.update_task_status("TASK-A", TaskStatus.FAILED)

    # TASK-B must be blocked
    assert scheduler.task_statuses["TASK-B"] == TaskStatus.BLOCKED

    # TASK-C continues and completes
    scheduler.update_task_status("TASK-C", TaskStatus.DONE)
    assert scheduler.task_statuses["TASK-C"] == TaskStatus.DONE
    assert scheduler.get_dispatchable_tasks() == []


def test_retry_failed_task_allows_redispatch():
    tasks = [
        make_task("TASK-A"),
    ]
    scheduler = DAGScheduler(tasks, max_workers=2)
    scheduler.dispatch("TASK-A")
    scheduler.update_task_status("TASK-A", TaskStatus.FAILED)
    assert scheduler.get_dispatchable_tasks() == []

    # Retry resets to READY
    scheduler.retry_failed_task("TASK-A")
    assert scheduler.get_dispatchable_tasks() == ["TASK-A"]

