"""Synthetic bounded adapter contract; not connected to any live launcher."""

import math
import secrets
import threading
from dataclasses import dataclass, field

from orchestrator.local_credential_broker import redacted_event
from orchestrator.windows_credential_store import wipe

OPERATIONS = frozenset({"runpod.trial.once", "mattermost.monitor.once"})


@dataclass(frozen=True, repr=False)
class TrialApproval:
    approval_id: str
    task: str
    operation: str
    target_ref: str
    budget_cap: float
    deadline: float
    plan_digest: str

    def __repr__(self):
        return "<TrialApproval redacted>"


@dataclass(frozen=True, repr=False)
class AdapterContext:
    approval: TrialApproval
    deadline: float
    cancel: threading.Event = field(repr=False)
    clock: object = field(repr=False)

    def stopped(self) -> bool:
        return self.cancel.is_set() or self.clock() >= self.deadline

    def __repr__(self):
        return "<AdapterContext redacted>"


def fixed_mock_adapter(value: bytearray, context: AdapterContext) -> bool:
    """No screen, network, subprocess, provider mutation, billing or real key."""
    return not context.stopped() and value == bytearray(b"synthetic-fixture")


class BoundedMockBroker:
    """Trusted test harness only; mock identity, no OS isolation or durable ledger.

    Each approval can issue exactly one handle in this broker lifetime. A retry needs
    separate approval, never an automatic grant refresh. Adapters must cooperate with
    cancellation/deadline; a live adapter must add actual bounded cleanup/reconciliation.
    """

    def __init__(self, stores, clock):
        if set(stores) != OPERATIONS:
            raise ValueError("both synthetic stores required")
        self._stores = dict(stores)
        self._clock = clock
        self._pending = {}
        self._active = {}
        self._issued = set()
        self._lock = threading.Lock()
        self._audit = []

    def grant_trusted(self, approval: TrialApproval, *, ttl=30):
        now = self._clock()
        if (
            type(approval) is not TrialApproval
            or type(approval.operation) is not str or approval.operation not in OPERATIONS
            or not all(type(x) is str and x for x in (
                approval.approval_id, approval.task, approval.target_ref, approval.plan_digest
            ))
            or type(ttl) is not int or not 0 < ttl <= 60
            or type(approval.budget_cap) not in (int, float)
            or not math.isfinite(approval.budget_cap) or approval.budget_cap < 0
            or type(approval.deadline) not in (int, float)
            or not math.isfinite(approval.deadline) or approval.deadline <= now
        ):
            raise ValueError("invalid bounded approval")
        with self._lock:
            if approval.approval_id in self._issued:
                raise ValueError("approval already issued")
            # Grant entry lifetime and operation deadline are separate:
            # entry expires <=60s; MM execution ends <=5min from issuance.
            deadline = approval.deadline
            if approval.operation == "mattermost.monitor.once":
                deadline = min(deadline, now + 300)
            context = AdapterContext(approval, deadline, threading.Event(), self._clock)
            handle = secrets.token_urlsafe(32)
            self._pending[handle] = (context, min(now + ttl, deadline))
            self._issued.add(approval.approval_id)
            return handle

    def execute(self, request, *, trusted_task):
        with self._lock:
            if (
                type(request) is not dict or set(request) != {"handle", "operation"}
                or type(request["handle"]) is not str
                or type(request["operation"]) is not str or request["operation"] not in OPERATIONS
            ):
                return {"status": "denied"}
            handle = request["handle"]
            item = self._pending.get(handle)
            if not item:
                return {"status": "denied"}
            context, entry_deadline = item
            if (
                context.approval.task != trusted_task
                or context.approval.operation != request["operation"]
                or context.stopped() or self._clock() >= entry_deadline
            ):
                return {"status": "denied"}
            del self._pending[handle]
            self._active[handle] = context
        value = bytearray()
        try:
            value = self._stores[context.approval.operation].read()
            # Fixed stub only: no externally supplied function or executable.
            result = fixed_mock_adapter(value, context)
            status = "ok" if result is True else "failed"
        except Exception:  # noqa: BLE001 - drop all store/adapter exception content
            status = "failed"
        finally:
            wipe(value)
            with self._lock:
                self._active.pop(handle, None)
                if context.cancel.is_set():
                    status = "cancelled"
                elif self._clock() >= context.deadline:
                    status = "expired"
                self._audit.append(redacted_event("execute", (
                    status if status in {"ok", "failed"} else "denied"
                )))
        return {"status": status}

    def cancel_trusted(self, handle):
        with self._lock:
            pending = self._pending.pop(handle, None)
            context = self._active.get(handle)
            if pending:
                pending[0].cancel.set()
            if context:
                context.cancel.set()
            self._audit.append(redacted_event("revoke", "ok"))

    def delete_trusted(self, operation):
        if operation not in OPERATIONS:
            return {"status": "denied"}
        with self._lock:
            for handle, (context, _) in list(self._pending.items()):
                if context.approval.operation == operation:
                    context.cancel.set()
                    del self._pending[handle]
            for context in self._active.values():
                if context.approval.operation == operation:
                    context.cancel.set()
            try:
                self._stores[operation].delete()
                status = "ok"
            except Exception:  # noqa: BLE001 - never expose deletion errors
                status = "failed"
            self._audit.append(redacted_event("delete", status))
            return {"status": status}

    def audit_snapshot_trusted(self):
        with self._lock:
            return [dict(item) for item in self._audit]
