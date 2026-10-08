"""Local in-process candidate. No IPC, authenticated identity, network or launcher.

Trusted code owns store, adapter, clock and grants. Public operation results and audit
use allowlists. Same-user arbitrary code can bypass this convenience boundary.
"""

import secrets
import threading

from orchestrator.windows_credential_store import StoreError, wipe

_EVENTS = frozenset({"enroll", "execute", "revoke", "delete"})
_STATUSES = frozenset({"ok", "denied", "failed"})


def redacted_event(event: str, status: str, **discarded: object) -> dict[str, str]:
    """Drop all supplied payloads, exceptions, identifiers and capability handles."""
    return {
        "event": event if event in _EVENTS else "redacted",
        "status": status if status in _STATUSES else "redacted",
    }


class MockCredentialStore:
    """Memory-only fake; tests must provide only synthetic values."""

    def __init__(self):
        self._value = bytearray()

    def write(self, value: bytearray) -> None:
        if not isinstance(value, bytearray) or not 0 < len(value) <= 2560:
            raise StoreError("invalid credential input")
        wipe(self._value)
        self._value = bytearray(value)

    def read(self) -> bytearray:
        if not self._value:
            raise StoreError("credential unavailable")
        return bytearray(self._value)

    def delete(self) -> None:
        wipe(self._value)
        self._value.clear()

    def __repr__(self) -> str:
        return "<MockCredentialStore redacted>"


class LocalCredentialBroker:
    """Fixed service.status adapter only. Management methods are trusted-only.

    Single process lock/replay state; restart invalidates every grant.
    Caller context is supplied by trusted harness here, NOT authenticated by this class.
    """

    def __init__(self, store, adapter, clock):
        self._store = store
        self._adapter = adapter
        self._clock = clock
        self._grants = {}
        self._lock = threading.Lock()
        self._audit = []

    def _record(self, event, status):
        self._audit.append(redacted_event(event, status))

    def enroll_trusted(self, value: bytearray) -> dict[str, str]:
        with self._lock:
            self._grants.clear()
            try:
                self._store.write(value)
            except Exception:  # noqa: BLE001 - redact untrusted adapter/store error text
                self._record("enroll", "failed")
                return {"status": "failed"}
            finally:
                if isinstance(value, bytearray):
                    wipe(value)
            self._record("enroll", "ok")
            return {"status": "ok"}

    def grant_trusted(self, *, task: str, ttl: int = 30) -> str:
        if not isinstance(task, str) or not task or type(ttl) is not int or not 0 < ttl <= 60:
            raise ValueError("invalid grant")
        with self._lock:
            handle = secrets.token_urlsafe(32)
            self._grants[handle] = (task, self._clock() + ttl)
            return handle

    def revoke_trusted(self, handle: str) -> None:
        with self._lock:
            self._grants.pop(handle, None)
            self._record("revoke", "ok")

    def execute(self, request, *, trusted_task: str) -> dict[str, str]:
        with self._lock:
            if (
                type(request) is not dict
                or set(request) != {"handle", "operation"}
                or type(request["handle"]) is not str
                or request["operation"] != "service.status"
            ):
                self._record("execute", "denied")
                return {"status": "denied"}
            handle = request["handle"]
            grant = self._grants.get(handle)
            if not grant or grant[0] != trusted_task or self._clock() >= grant[1]:
                self._record("execute", "denied")
                return {"status": "denied"}
            del self._grants[handle]  # consume before read/adapter; failures are not retried
            value = bytearray()
            try:
                value = self._store.read()
                result = self._adapter(value)
                status = "ok" if result is True else "failed"
            except Exception:  # noqa: BLE001 - redact untrusted adapter/store error text
                status = "failed"  # never relay exception text/traceback/provider response
            finally:
                wipe(value)
            self._record("execute", status)
            return {"status": status}

    def delete_trusted(self) -> dict[str, str]:
        with self._lock:
            self._grants.clear()
            try:
                self._store.delete()
                status = "ok"
            except Exception:  # noqa: BLE001 - redact untrusted adapter/store error text
                status = "failed"
            self._record("delete", status)
            return {"status": status}

    def audit_snapshot_trusted(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(event) for event in self._audit]

    def __repr__(self) -> str:
        return "<LocalCredentialBroker redacted>"
