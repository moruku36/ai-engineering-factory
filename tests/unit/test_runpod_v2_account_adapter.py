"""Synthetic-only adapter checks. No real credential read, HTTP, or GPU."""
from types import SimpleNamespace

from orchestrator.runpod_local_credential import LocalScope
from orchestrator.runpod_v2_account_adapter import read_account_once


def fixture(allowed=True):
    buffer = bytearray(b"synthetic-provider-key-not-real")
    calls = []
    def read():
        calls.append("read")
        return buffer
    flow = SimpleNamespace(_allowed=lambda: allowed, _backing_store=lambda: SimpleNamespace(read=read))
    scope = LocalScope("synthetic", "synthetic", {}, 200, True)
    return scope, flow, buffer, calls


def test_default_and_unapproved_never_read_or_send():
    scope, flow, _, calls = fixture()
    def forbidden(_):
        raise AssertionError("no external send")
    assert read_account_once(scope, flow=flow, lookup=forbidden) == {"status": "disabled"}
    assert read_account_once(scope, enabled=True, flow=flow, lookup=forbidden) == {"status": "disabled"}
    assert calls == []


def test_denied_owner_never_reads_or_sends():
    scope, flow, _, calls = fixture(False)
    assert read_account_once(scope, enabled=True, external_read_approved=True, flow=flow) == {"status": "denied"}
    assert calls == []


def test_internal_account_only_and_buffer_wiped(capsys):
    scope, flow, buffer, calls = fixture()
    seen = []
    result = read_account_once(scope, enabled=True, external_read_approved=True,
                              flow=flow, lookup=lambda value: seen.append(value) or "synthetic-account")
    assert result == {"status": "account-verified", "account_id": "synthetic-account"}
    assert calls == ["read"] and len(seen) == 1
    assert not any(buffer)
    assert capsys.readouterr() == ("", "")


def test_exception_redacted_and_buffer_wiped(capsys):
    scope, flow, buffer, _ = fixture()
    def refused(value):
        raise RuntimeError(value)
    assert read_account_once(scope, enabled=True, external_read_approved=True,
                             flow=flow, lookup=refused) == {"status": "failed"}
    assert not any(buffer)
    assert capsys.readouterr() == ("", "")
