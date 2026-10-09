"""Owner UI and bounded launcher contract tests; synthetic only, no live adapter."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

import orchestrator.bounded_credential_mock as module
from orchestrator.bounded_credential_mock import BoundedMockBroker, TrialApproval
from orchestrator.credential_enrollment_mock import main, run_mock_enrollment
from orchestrator.local_credential_broker import MockCredentialStore
from orchestrator.windows_credential_store import StoreError


def setup():
    stores = {name: MockCredentialStore() for name in module.OPERATIONS}
    for store in stores.values():
        store.write(bytearray(b"synthetic-fixture"))
    now = [100.0]
    broker = BoundedMockBroker(stores, lambda: now[0])
    return broker, stores, now


def approval(operation="runpod.trial.once"):
    return TrialApproval(
        "synthetic-approval", "synthetic-task", operation,
        "synthetic-target", 0.0, 200.0, "synthetic-plan"
    )


def request(broker, approved=None):
    approved = approved or approval()
    return {
        "handle": broker.grant_trusted(approved),
        "operation": approved.operation
    }


def test_ui_registration_and_deletion_without_echo():
    messages = []
    prompts = []
    store = MockCredentialStore()
    def hidden(prompt):
        prompts.append(prompt)
        return "synthetic-fixture"
    assert run_mock_enrollment(hidden, messages.append, store) == {"status": "ok"}
    assert len(prompts) == 1 and "hidden" in prompts[0]
    assert all(message != "synthetic-fixture" for message in messages)
    assert store.read() == bytearray(b"synthetic-fixture")
    store.delete()
    with pytest.raises(StoreError):
        store.read()


@pytest.mark.parametrize("answer,status", [
    ("", "cancelled"), ("unapproved-input", "denied")
])
def test_ui_cancel_or_non_synthetic_value_not_registered(answer, status):
    store = MockCredentialStore()
    messages = []
    assert run_mock_enrollment(lambda prompt: answer, messages.append, store) == {
        "status": status
    }
    assert answer != "unapproved-input" or answer not in repr(messages)
    with pytest.raises(StoreError):
        store.read()


def test_ui_native_store_rejected_before_prompt():
    assert run_mock_enrollment(
        lambda prompt: pytest.fail("must not prompt"), lambda text: None, object()
    ) == {"status": "denied"}


def test_ui_noninteractive_does_not_prompt(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        "getpass.getpass", lambda prompt: pytest.fail("must not prompt")
    )
    assert main() == 2
    assert "no registration" in capsys.readouterr().out


@pytest.mark.parametrize("operation", sorted(module.OPERATIONS))
def test_fixed_operations_budget_deadline_and_no_screen(monkeypatch, capsys, operation):
    def forbidden(*args, **kwargs):
        pytest.fail("no screen, subprocess, native API or hidden input")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("os.system", forbidden)
    monkeypatch.setattr("os.startfile", forbidden, raising=False)
    monkeypatch.setattr("ctypes.WinDLL", forbidden, raising=False)
    monkeypatch.setattr("getpass.getpass", forbidden)
    broker, _, _ = setup()
    approved = approval(operation)
    req = request(broker, approved)
    seen = []
    def adapter(value, context):
        seen.append(context)
        return value == bytearray(b"synthetic-fixture")
    monkeypatch.setattr(module, "fixed_mock_adapter", adapter)
    assert broker.execute(req, trusted_task=approved.task) == {"status": "ok"}
    assert seen[0].approval is approved
    assert seen[0].approval.budget_cap == 0.0
    assert seen[0].deadline == approved.deadline
    assert broker.execute(req, trusted_task=approved.task) == {"status": "denied"}
    with pytest.raises(ValueError, match="already issued"):
        broker.grant_trusted(approved)
    assert capsys.readouterr() == ("", "")
    assert req["handle"] not in repr(broker.audit_snapshot_trusted())


def test_mm_five_minute_ceiling_and_earlier_owner_deadline(monkeypatch):
    broker, _, _ = setup()
    approved = replace(approval("mattermost.monitor.once"), deadline=1000.0)
    req = request(broker, approved)
    seen = []
    monkeypatch.setattr(
        module, "fixed_mock_adapter", lambda value, ctx: seen.append(ctx) or True
    )
    assert broker.execute(req, trusted_task=approved.task) == {"status": "ok"}
    assert seen[0].deadline == 400.0
    approved2 = replace(approved, approval_id="second", deadline=150.0)
    assert broker.execute(request(broker, approved2), trusted_task=approved.task) == {
        "status": "ok"
    }
    assert seen[1].deadline == 150.0


@pytest.mark.parametrize("mutation", [
    {"operation": "runpod.start.unbounded"}, {"operation": []},
    {"budget_cap": 999}, {"deadline": 999}, {"target_ref": "other"},
    {"argv": []}, {"handle": []},
])
def test_worker_cannot_change_plan_or_limits(mutation):
    broker, _, _ = setup()
    req = request(broker)
    req.update(mutation)
    assert broker.execute(req, trusted_task="synthetic-task") == {"status": "denied"}


def test_reference_expiry_cancel_and_delete():
    broker, stores, now = setup()
    req = request(broker)
    now[0] = 130.0
    assert broker.execute(req, trusted_task="synthetic-task") == {"status": "denied"}
    req2 = request(broker, replace(approval(), approval_id="second"))
    broker.cancel_trusted(req2["handle"])
    assert broker.execute(req2, trusted_task="synthetic-task") == {"status": "denied"}
    req3 = request(broker, replace(approval(), approval_id="third"))
    assert broker.delete_trusted("runpod.trial.once") == {"status": "ok"}
    assert broker.execute(req3, trusted_task="synthetic-task") == {"status": "denied"}
    with pytest.raises(StoreError):
        stores["runpod.trial.once"].read()


@pytest.mark.parametrize("action", ["cancel", "delete", "expire"])
def test_running_adapter_cancellation_deletion_deadline_and_wipe(monkeypatch, action):
    broker, _, now = setup()
    req = request(broker)
    entered, release = Event(), Event()
    seen = []
    def adapter(value, ctx):
        seen.append((value, ctx))
        entered.set()
        assert release.wait(3)
        return not ctx.stopped()
    monkeypatch.setattr(module, "fixed_mock_adapter", adapter)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(broker.execute, req, trusted_task="synthetic-task")
        assert entered.wait(3)
        if action == "cancel":
            broker.cancel_trusted(req["handle"])
        elif action == "delete":
            broker.delete_trusted("runpod.trial.once")
        else:
            now[0] = 200.0
        release.set()
        assert future.result(timeout=3) == {
            "status": "expired" if action == "expire" else "cancelled"
        }
    assert seen[0][0] == bytearray(len(seen[0][0]))
    assert "synthetic-fixture" not in repr(broker.audit_snapshot_trusted())


@pytest.mark.parametrize("budget,deadline", [
    (-1.0, 200.0), (float("inf"), 200.0), (0.0, 100.0),
    (0.0, float("inf")), (True, 200.0),
])
def test_invalid_owner_limit_denied(budget, deadline):
    broker, _, _ = setup()
    with pytest.raises(ValueError, match="invalid bounded approval"):
        broker.grant_trusted(replace(approval(), budget_cap=budget, deadline=deadline))


def test_task_and_operation_binding():
    broker, _, _ = setup()
    req = request(broker)
    assert broker.execute(req, trusted_task="wrong") == {"status": "denied"}
    wrong = {**req, "operation": "mattermost.monitor.once"}
    assert broker.execute(wrong, trusted_task="synthetic-task") == {"status": "denied"}
    assert broker.execute(req, trusted_task="synthetic-task") == {"status": "ok"}


@pytest.mark.parametrize("error", [KeyboardInterrupt, EOFError])
def test_owner_interrupt_is_cancelled(error):
    store = MockCredentialStore()
    def hidden(prompt):
        raise error()
    assert run_mock_enrollment(hidden, lambda text: None, store) == {
        "status": "cancelled"
    }
    with pytest.raises(StoreError):
        store.read()
