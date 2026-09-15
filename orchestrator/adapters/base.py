"""Abstract base execution adapter."""

from abc import ABC, abstractmethod
from typing import Any


class ExecutionAdapter(ABC):
    """Abstract interface for agent execution engines."""

    @abstractmethod
    def start_task(self, task_manifest: dict[str, Any], worktree_path: str) -> str:
        """Start task execution and return a run_id."""

    @abstractmethod
    def poll_task(self, run_id: str) -> dict[str, Any]:
        """Poll current execution status and progress."""

    @abstractmethod
    def cancel_task(self, run_id: str) -> bool:
        """Request task cancellation."""

    @abstractmethod
    def collect_results(self, run_id: str) -> dict[str, Any]:
        """Collect execution results and candidate changes."""
