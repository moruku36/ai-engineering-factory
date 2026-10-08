"""Dummy end-to-end native wiring contract; no actual SID/DLL/credential calls."""

from dataclasses import replace
from threading import Event

from orchestrator.local_credential_broker import MockCredentialStore
from orchestrator.runpod_local_credential import LocalScope, RunPodLocalCredentialFlow


def fixture(*, enabled=True, store=None):
    now = [100.0]
    scope = LocalScope("synthetic-sid", "synthetic-account", {"dummy": "pin"}, 200.0, True)
    store = store or MockCredentialStore()
    flow = RunPodLocalCredentialFlow(
        scope, enabled=enabled, store=store, sid_reader=lambda: "synthetic-sid",
        pin_reader=lambda: {"dummy": "pin"}, clock=lambda: now[0]
    )
    return flow, store, now, scope


def test_registration_once_reuses_store_without_prompt_and_deletes(capsys):
    flow, store, _, _ = fixture()
    prompts = []
    def hidden(prompt):
        prompts.append(prompt)
        return "synthetic-fixture"
    assert flow.enroll_owner(hidden) == {"status": "registered"}
    for _ in range(2):
        assert flow.local_use_once(approved=True) == {"status": "ready"}
    assert len(prompts) == 1
    assert flow.local_use_once() == {"status": "denied"}
    assert flow.delete_owner() == {"status": "deleted"}
    assert flow.local_use_once(approved=True) == {"status": "failed"}
    assert capsys.readouterr() == ("", "")
    assert "synthetic-fixture" not in repr(store)


def test_default_disabled_never_resolves_identity_or_native_store(monkeypatch):
    scope = LocalScope("synthetic-sid", "synthetic-account", {}, 200.0, True)
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled path must not call")
    monkeypatch.setattr("ctypes.WinDLL", forbidden, raising=False)
    flow = RunPodLocalCredentialFlow(scope, sid_reader=forbidden, pin_reader=forbidden)
    assert flow.enroll_owner(forbidden) == {"status": "denied"}
    assert flow.local_use_once(approved=True) == {"status": "denied"}
    assert flow.delete_owner() == {"status": "denied"}


def test_wrong_owner_pins_or_unconfirmed_scope_denies_before_input():
    _, store, _, scope = fixture()
    for denied in [replace(scope, owner_sid="other"), replace(scope, pins={}),
                   replace(scope, confirmed=False), replace(scope, account_ref="")]:
        flow = RunPodLocalCredentialFlow(
            denied, enabled=True, store=store, sid_reader=lambda: "synthetic-sid",
            pin_reader=lambda: {"dummy": "pin"}, clock=lambda: 100.0
        )
        assert flow.enroll_owner(lambda prompt: "synthetic-fixture") == {"status": "denied"}
        assert flow.local_use_once(approved=True) == {"status": "denied"}


def test_cancel_expiry_does_not_remove_retained_key():
    flow, store, now, _ = fixture()
    flow.enroll_owner(lambda prompt: "synthetic-fixture")
    cancel = Event()
    cancel.set()
    assert flow.local_use_once(approved=True, cancel=cancel) == {"status": "cancelled"}
    now[0] = 200.0
    assert flow.local_use_once(approved=True) == {"status": "denied"}
    assert store.read() == bytearray(b"synthetic-fixture")
    assert flow.delete_owner() == {"status": "deleted"}


def test_input_cancel_and_error_text_not_echoed(capsys):
    flow, _, _, _ = fixture()
    assert flow.enroll_owner(lambda prompt: "") == {"status": "cancelled"}
    def fail(prompt):
        raise RuntimeError("synthetic-fixture")
    assert flow.enroll_owner(fail) == {"status": "failed"}
    assert capsys.readouterr() == ("", "")


def test_read_buffer_cleared_and_slow_native_result_expired():
    class ObservedStore(MockCredentialStore):
        def read(self):
            self.copy = super().read()
            now[0] = 111.0
            return self.copy
    store = ObservedStore()
    flow, _, now, _ = fixture(store=store)
    flow.enroll_owner(lambda prompt: "synthetic-fixture")
    assert flow.local_use_once(approved=True) == {"status": "expired"}
    assert store.copy == bytearray(len(store.copy))


def test_owner_ui_wiring_uses_hidden_input_and_returns_status_only(monkeypatch):
    from orchestrator import runpod_local_credential as module

    flow, _, _, scope = fixture()
    monkeypatch.setattr(module, "RunPodLocalCredentialFlow", lambda *args, **kwargs: flow)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    prompts = []
    def hidden(prompt):
        prompts.append(prompt)
        return "synthetic-fixture"
    monkeypatch.setattr("getpass.getpass", hidden)
    assert module.run_owner_enrollment(scope) == {"status": "disabled"}
    assert not prompts
    assert module.run_owner_enrollment(scope, enabled=True) == {"status": "registered-ready"}
    assert len(prompts) == 1
