"""Default-OFF synthetic composition proposal; NOT connected to any live launcher.

BoundedMockBroker calls fixed_mock_adapter directly and has no adapter registration
hook, so this harness cannot bind a launcher to the broker and does not try to
(no monkeypatch, no subclass, no private access). It composes the unchanged PR31
pieces, then walks credential-free fake launcher lifecycle shapes ONLY after
broker.execute returned ok. That checks orchestration/cleanup ordering. It does NOT
check real secret handoff, real cancellation, real Pod deletion or real billing.

The fakes are NOT drop-in for the real launcher. The fake secret_reader hands back a
bytearray placeholder; the real provider expects str per role and hex-decodes the
journal signing key. That typed handoff is missing here and is not modelled.

Trusted local entry only. Never register anything here as a model tool. This API
cannot enforce identity against hostile same-process code and cannot hard-cancel:
cancellation and deadlines are cooperative. Wiping covers bytearray copies only;
the str returned by the hidden callback cannot be wiped.
"""

import argparse
import contextlib
import getpass
import sys
import threading
import time
from pathlib import Path

# Explicit trusted path (derived from this file, never cwd) so `python -I -B` works.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

import orchestrator.bounded_credential_mock as _bounded  # noqa: E402
import orchestrator.credential_enrollment_mock as _enrollment  # noqa: E402
import orchestrator.local_credential_broker as _local  # noqa: E402
import orchestrator.windows_credential_store as _native  # noqa: E402

for _module in (_bounded, _enrollment, _local, _native):
    if Path(_module.__file__).resolve().parent != _REPO_ROOT / "orchestrator":
        raise ImportError("unexpected orchestrator origin")

BoundedMockBroker = _bounded.BoundedMockBroker
TrialApproval = _bounded.TrialApproval
MockCredentialStore = _local.MockCredentialStore
run_mock_enrollment = _enrollment.run_mock_enrollment
wipe = _native.wipe

RUNPOD = "runpod.trial.once"
MATTERMOST = "mattermost.monitor.once"
_ORDER = (RUNPOD, MATTERMOST)
if set(_ORDER) != _bounded.OPERATIONS:
    raise ImportError("unexpected operation set")

SYNTHETIC_TARGET = "synthetic-target"
SYNTHETIC_PLAN = "synthetic-plan"

# Fixed synthetic fault selectors for the fakes; not callbacks, not a factory.
FAULTS = frozenset({
    "cancel", "runpod.run", "runpod.pod_cleanup", "mattermost.monitor", "mattermost.stop",
})

_EVENTS = frozenset({"enroll", "grant", "execute", "lifecycle", "cleanup", "delete"})
_STATUSES = frozenset({
    "disabled", "ok", "denied", "failed", "cancelled", "expired", "cleanup_incomplete",
})

# MM phases are capped separately; neither cap is a total-lifecycle cap.
MM_PREPARATION_CAP = 300
MM_MONITOR_CAP = 300
MM_MAX_READS = 60
MM_MAX_EVENTS = 5

_RUNPOD_CONFIG = "synthetic-config"
# Role names only; the last one is spelled exactly as the real reader is asked for it.
_RUNPOD_ROLES = ("provider", "model", "inference", "control", "journal signing key hex")


class _LifecycleContext:
    """Cooperative only: a fake that never polls stopped() is not interrupted."""

    def __init__(self, cancel, clock, deadline):
        self._cancel = cancel
        self._clock = clock
        self._deadline = deadline

    def stopped(self):
        return self._cancel.is_set() or self._clock() >= self._deadline

    def phase(self, cap):
        return _LifecycleContext(
            self._cancel, self._clock, min(self._deadline, self._clock() + cap)
        )

    def __repr__(self):
        return "<_LifecycleContext redacted>"


def _placeholder_reader(role):
    """Credential-free: fixed placeholder, never the enrolled store value.

    bytearray abstraction only. The real reader returns str (the journal role as hex
    that the provider decodes), so this is not the real typed handoff.
    """
    if role not in _RUNPOD_ROLES:
        raise ValueError("unknown role")
    return bytearray(b"synthetic-placeholder")


class _FakeInjection:
    def __init__(self, roles):
        self.roles = roles

    def __repr__(self):
        return "<_FakeInjection redacted>"


class _FakeRunPodLauncher:
    """Shape of open_injection -> run_injected only; imports no launcher code.

    Evidence flags are synthetic bookkeeping, not a live deletion guarantee.
    """

    def __init__(self, context, fault):
        self._context = context
        self._fault = fault
        self._pod_present = False
        self.evidence = {"journal_closed": False, "pod_absent": False}

    @contextlib.contextmanager
    def open_injection(self, config, *, owui=False, secret_reader):
        if config != _RUNPOD_CONFIG or owui is not False:
            raise ValueError("invalid synthetic config")
        try:
            roles = []
            for role in _RUNPOD_ROLES:
                value = bytearray()
                try:
                    value = secret_reader(role)
                    if type(value) is not bytearray or not value:
                        raise ValueError("invalid placeholder")
                    roles.append(role)
                finally:
                    wipe(value)
            yield _FakeInjection(tuple(roles))
        finally:
            self.evidence["journal_closed"] = True

    def run_injected(self, inputs, *, owner_start=True):
        if type(inputs) is not _FakeInjection or owner_start is not True:
            raise ValueError("invalid synthetic inputs")
        if self._context.stopped():
            return False
        try:
            self._pod_present = True
            if self._fault == "runpod.run":
                raise RuntimeError("synthetic-fixture provider payload")
            return not self._context.stopped()
        finally:
            if self._fault != "runpod.pod_cleanup":
                self._pod_present = False

    def confirm_absence(self):
        # Separate from journal close; a real adapter must reconcile create-unknown.
        self.evidence["pod_absent"] = not self._pod_present


class _FakeMattermostMonitor:
    """Shape of preparation -> bounded monitor -> stop cleanup; no waits, no I/O."""

    def __init__(self, context, fault):
        self._context = context
        self._fault = fault
        self._active = 0
        self._protected = 0
        self.reads = 0
        self.events = 0
        self.evidence = {"active_zero": False, "protected_zero": False}

    def prepare(self):
        phase = self._context.phase(MM_PREPARATION_CAP)
        if phase.stopped():
            return False
        self._active = 1
        self._protected = 1
        return not phase.stopped()

    def monitor(self):
        phase = self._context.phase(MM_MONITOR_CAP)
        while self.reads < MM_MAX_READS and self.events < MM_MAX_EVENTS:
            if phase.stopped():
                return False
            self.reads += 1
            if self._fault == "mattermost.monitor":
                raise RuntimeError("synthetic-fixture provider payload")
            if self.reads % (MM_MAX_READS // MM_MAX_EVENTS) == 0:
                self.events += 1
        return not phase.stopped()

    def stop(self):
        self._active = 0
        if self._fault != "mattermost.stop":
            self._protected = 0
        self.evidence["active_zero"] = self._active == 0
        self.evidence["protected_zero"] = self._protected == 0


def _runpod_shape(context, fault):
    fake = _FakeRunPodLauncher(context, fault)
    ok = False
    try:
        with fake.open_injection(
            _RUNPOD_CONFIG, owui=False, secret_reader=_placeholder_reader
        ) as inputs:
            ok = fake.run_injected(inputs, owner_start=True) is True
    except Exception:  # noqa: BLE001 - drop all fake exception content
        ok = False
    finally:
        fake.confirm_absence()
    return ok, dict(fake.evidence)


def _mattermost_shape(context, fault):
    fake = _FakeMattermostMonitor(context, fault)
    ok = False
    try:
        ok = fake.prepare() is True and fake.monitor() is True
    except Exception:  # noqa: BLE001 - drop all fake exception content
        ok = False
    finally:
        fake.stop()
    evidence = dict(fake.evidence)
    evidence["read_cap_respected"] = fake.reads <= MM_MAX_READS
    evidence["event_cap_respected"] = fake.events <= MM_MAX_EVENTS
    return ok, evidence


_SHAPES = {RUNPOD: _runpod_shape, MATTERMOST: _mattermost_shape}


class TrustedLauncherBridgeMock:
    """Trusted composition harness; callbacks and clock come from trusted local code.

    One synthetic owner enrollment (hidden callback called at most once) fills one
    in-memory MockCredentialStore shared by both fixed operations. Every run needs
    its own one-use TrialApproval. Public results are {"status": <allowlisted>} only.
    """

    def __init__(self, *, enabled=False, read_hidden=None, write_safe=None, clock=None):
        self._enabled = enabled is True
        self._read_hidden = read_hidden
        self._write_safe = write_safe if callable(write_safe) else (lambda text: None)
        self._clock = clock if callable(clock) else time.monotonic
        self._store = MockCredentialStore()
        self._broker = None
        self._enroll_attempted = False
        self._closed = False
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._audit = []
        self._cleanup = {}

    def _result(self, event, status):
        status = status if status in _STATUSES else "failed"
        self._audit.append({
            "event": event if event in _EVENTS else "redacted", "status": status,
        })
        return {"status": status}

    def enroll_once(self):
        with self._lock:
            if not self._enabled:
                return {"status": "disabled"}
            if self._closed or self._enroll_attempted or not callable(self._read_hidden):
                return self._result("enroll", "denied")
            self._enroll_attempted = True
            calls = []

            def hidden_once(prompt):
                calls.append(None)
                if len(calls) != 1:
                    raise RuntimeError("hidden callback limit")
                return self._read_hidden(prompt)

            try:
                status = run_mock_enrollment(
                    hidden_once, self._write_safe, self._store
                )["status"]
            except Exception:  # noqa: BLE001 - never echo callback errors
                status = "failed"
            if status == "ok":
                # Transfer check on a mutable copy, wiped immediately.
                probe = bytearray()
                try:
                    probe = self._store.read()
                except Exception:  # noqa: BLE001
                    status = "failed"
                finally:
                    wipe(probe)
            if status == "ok":
                self._broker = BoundedMockBroker(
                    {operation: self._store for operation in _ORDER}, self._clock
                )
            else:
                self._store.delete()
            return self._result("enroll", status)

    def run_once(self, approval, *, trusted_task, fault=None):
        with self._lock:
            if not self._enabled:
                return {"status": "disabled"}
            if self._closed or self._broker is None:
                return self._result("grant", "denied")
            # Synthetic pins on top of the broker's own validation; fail closed.
            if (
                type(approval) is not TrialApproval
                or approval.target_ref != SYNTHETIC_TARGET
                or approval.plan_digest != SYNTHETIC_PLAN
                or type(approval.budget_cap) not in (int, float) or approval.budget_cap != 0
                or not (fault is None or (type(fault) is str and fault in FAULTS))
            ):
                return self._result("grant", "denied")
            # Publish cancellation before preflight so an in-flight cancel is not lost.
            cancel = self._cancel = threading.Event()
            issued_at = self._clock()
            try:
                handle = self._broker.grant_trusted(approval)
            except Exception:  # noqa: BLE001 - invalid/expired/replayed approval
                return self._result("grant", "denied")
            try:
                executed = self._broker.execute(
                    {"handle": handle, "operation": approval.operation},
                    trusted_task=trusted_task,
                )["status"]
            except Exception:  # noqa: BLE001
                executed = "failed"
            finally:
                self._broker.cancel_trusted(handle)  # no pending handle survives
                del handle
            if executed != "ok":
                return self._result("execute", executed)
            self._result("execute", "ok")

            # Fake lifecycle starts only here, with its own cooperative context.
            # The broker's AdapterContext is not reachable and is not reused.
            deadline = approval.deadline
            if approval.operation == MATTERMOST:
                deadline = min(deadline, issued_at + MM_MONITOR_CAP)
            context = _LifecycleContext(cancel, self._clock, deadline)
            if fault == "cancel":
                cancel.set()
            ok, evidence = False, {}
            try:
                ok, evidence = _SHAPES[approval.operation](context, fault)
            except Exception:  # noqa: BLE001
                ok = False
            self._cleanup = {
                key: value for key, value in evidence.items() if type(value) is bool
            }
            clean = bool(evidence) and all(self._cleanup.values())
            self._result("cleanup", "ok" if clean else "failed")
            if not clean:
                status = "cleanup_incomplete"
            elif cancel.is_set():
                status = "cancelled"
            elif self._clock() >= deadline:
                status = "expired"
            else:
                status = "ok" if ok else "failed"
            return self._result("lifecycle", status)

    def cancel_trusted(self):
        """Cooperative request only; cannot interrupt a fake that does not poll."""
        self._cancel.set()

    def close(self):
        self._cancel.set()
        with self._lock:
            status = "ok"
            try:
                if self._broker is not None:
                    for operation in _ORDER:
                        if self._broker.delete_trusted(operation) != {"status": "ok"}:
                            status = "failed"
            except Exception:  # noqa: BLE001
                status = "failed"
            finally:
                try:
                    self._store.delete()
                except Exception:  # noqa: BLE001
                    status = "failed"
                self._broker = None
                self._closed = True
            if not self._enabled:
                return {"status": "disabled"}
            return self._result("delete", status)

    def store_available_trusted(self):
        probe = bytearray()
        try:
            probe = self._store.read()
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            wipe(probe)

    def cleanup_snapshot_trusted(self):
        """Synthetic booleans from the last fake lifecycle; not live evidence."""
        with self._lock:
            return dict(self._cleanup)

    def audit_snapshot_trusted(self):
        with self._lock:
            return [dict(item) for item in self._audit]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def __repr__(self):
        return "<TrustedLauncherBridgeMock redacted>"


def run_demo(*, enabled=False):
    """Manual local demo. The only exposed option is the mock enable switch."""
    if enabled is not True:
        print("launcher bridge mock disabled; nothing enrolled or granted")
        return 0
    # Refuse getpass fallback: it may echo input on a noninteractive stream.
    if not sys.stdin.isatty():
        print("interactive mock input required; no registration performed")
        return 2
    harness = TrustedLauncherBridgeMock(
        enabled=True, read_hidden=getpass.getpass, write_safe=print, clock=time.monotonic
    )
    code = 0
    try:
        if harness.enroll_once()["status"] != "ok":
            return 1
        for operation in _ORDER:
            approval = TrialApproval(
                "synthetic-approval-" + operation, "synthetic-task", operation,
                SYNTHETIC_TARGET, 0.0, time.monotonic() + 60, SYNTHETIC_PLAN,
            )
            status = harness.run_once(approval, trusted_task="synthetic-task")["status"]
            print(f"{operation}: {status} (fake lifecycle shape, no live launcher)")
            if status != "ok":
                code = 1
        return code
    finally:
        harness.close()
        print("mock data deleted")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic launcher bridge mock")
    parser.add_argument("--mock-enabled", action="store_true")
    return run_demo(enabled=parser.parse_args(argv).mock_enabled)


if __name__ == "__main__":
    raise SystemExit(main())
