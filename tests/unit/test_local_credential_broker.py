"""Synthetic-only contract tests: no enabled Windows backend, network or real keys."""

import pytest

from orchestrator.local_credential_broker import (
    LocalCredentialBroker,
    MockCredentialStore,
    redacted_event,
)
from orchestrator.windows_credential_store import StoreError, WindowsCredentialStore


def fixture(adapter=None):
    store = MockCredentialStore()
    now = [100]
    seen = []
    def fixed(value):
        seen.append(value)
        return value == bytearray(b"synthetic-fixture")
    broker = LocalCredentialBroker(store, adapter or fixed, lambda: now[0])
    value = bytearray(b"synthetic-fixture")
    assert broker.enroll_trusted(value) == {"status": "ok"}
    assert value == bytearray(len(value))
    return broker, store, now, seen


def request(broker):
    return {"handle": broker.grant_trusted(task="test"), "operation": "service.status"}


def test_enrollment_fixed_operation_wipes_input_and_adapter_buffer(capsys):
    broker, store, _, seen = fixture()
    req = request(broker)
    assert broker.execute(req, trusted_task="test") == {"status": "ok"}
    assert seen and seen[0] == bytearray(len(seen[0]))
    # Repeated requests do not require enrollment again.
    assert broker.execute(request(broker), trusted_task="test") == {"status": "ok"}
    audit = repr(broker.audit_snapshot_trusted())
    assert "synthetic-fixture" not in audit and req["handle"] not in audit
    assert capsys.readouterr() == ("", "")
    store.delete()


def test_replay_expiry_revocation_and_task():
    broker, _, now, _ = fixture()
    req = request(broker)
    assert broker.execute(req, trusted_task="wrong") == {"status": "denied"}
    assert broker.execute(req, trusted_task="test") == {"status": "ok"}
    assert broker.execute(req, trusted_task="test") == {"status": "denied"}
    req = request(broker)
    now[0] = 130
    assert broker.execute(req, trusted_task="test") == {"status": "denied"}
    req = request(broker)
    broker.revoke_trusted(req["handle"])
    assert broker.execute(req, trusted_task="test") == {"status": "denied"}


@pytest.mark.parametrize("mutation", [
    {"operation": "secret.read"},
    {"operation": "pod.start"},
    {"url": "https://example.invalid"},
    {"argv": ["echo"]},
    {"credential_target": "untrusted"},
    {"handle": []},
])
def test_unregistered_operations_and_extra_input_denied(mutation):
    broker, _, _, seen = fixture()
    req = request(broker)
    req.update(mutation)
    assert broker.execute(req, trusted_task="test") == {"status": "denied"}
    assert not seen


def test_deletion_revokes_all_handles_and_removes_value():
    broker, store, _, _ = fixture()
    req = request(broker)
    assert broker.delete_trusted() == {"status": "ok"}
    assert broker.execute(req, trusted_task="test") == {"status": "denied"}
    with pytest.raises(StoreError, match="credential unavailable"):
        store.read()
    assert broker.delete_trusted() == {"status": "ok"}


def test_rotation_revokes_old_grants():
    broker, _, _, _ = fixture()
    req = request(broker)
    assert broker.enroll_trusted(bytearray(b"replacement-fixture")) == {"status": "ok"}
    assert broker.execute(req, trusted_task="test") == {"status": "denied"}


def test_exception_and_provider_output_never_relayed(capsys):
    seen = []
    def fail(value):
        seen.append(value)
        raise RuntimeError("synthetic-fixture")
    broker, _, _, _ = fixture(fail)
    req = request(broker)
    assert broker.execute(req, trusted_task="test") == {"status": "failed"}
    assert broker.execute(req, trusted_task="test") == {"status": "denied"}
    assert seen[0] == bytearray(len(seen[0]))
    assert "synthetic-fixture" not in repr(broker.audit_snapshot_trusted())
    assert capsys.readouterr() == ("", "")
    broker, _, _, _ = fixture(lambda value: {"secret": value})
    assert broker.execute(request(broker), trusted_task="test") == {"status": "failed"}


def test_audit_redaction_allowlist():
    assert redacted_event(
        "execute", "ok", secret="synthetic-fixture", handle="capability",
        exception=RuntimeError("synthetic-fixture")
    ) == {"event": "execute", "status": "ok"}
    assert redacted_event("synthetic-fixture", "synthetic-fixture") == {
        "event": "redacted", "status": "redacted"
    }


def test_native_backend_default_disabled_without_loading_dll(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("native DLL must not load in these tests")
    monkeypatch.setattr("ctypes.WinDLL", forbidden, raising=False)
    with pytest.raises(StoreError, match="native backend disabled"):
        WindowsCredentialStore("synthetic-target")


def test_store_failure_wipes_enrollment_and_returns_safe_status():
    class FailingStore(MockCredentialStore):
        def write(self, value):
            raise RuntimeError("synthetic-fixture")
    broker = LocalCredentialBroker(FailingStore(), lambda value: True, lambda: 100)
    value = bytearray(b"synthetic-fixture")
    assert broker.enroll_trusted(value) == {"status": "failed"}
    assert value == bytearray(len(value))
    assert "synthetic-fixture" not in repr(broker.audit_snapshot_trusted())


def test_same_process_concurrent_replay_runs_adapter_once():
    from concurrent.futures import ThreadPoolExecutor

    broker, _, _, seen = fixture()
    req = request(broker)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: broker.execute(req, trusted_task="test"), range(4)
        ))
    assert results.count({"status": "ok"}) == 1
    assert results.count({"status": "denied"}) == 3
    assert len(seen) == 1


@pytest.mark.parametrize("ttl", [0, -1, 61, True])
def test_invalid_grant_lifetime(ttl):
    broker, _, _, _ = fixture()
    with pytest.raises(ValueError, match="invalid grant"):
        broker.grant_trusted(task="test", ttl=ttl)
