"""Synthetic startup authority, source capture and durable replay tests."""

import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from orchestrator import runpod_startup_credential as startup
from orchestrator.windows_credential_store import wipe


@pytest.fixture
def prepared(tmp_path):
    factory, qwen, operations = (tmp_path / name for name in ("factory", "qwen", "operations"))
    for root, files in (
        (factory, startup.FACTORY_FILES),
        (qwen, startup.QWEN_FILES),
        (operations, ("qmc_runpod/__init__.py", "qmc_runpod/fake.py")),
    ):
        for rel in files:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('"""Synthetic public source."""\n', encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text('{"synthetic":true}', encoding="utf-8")
    claims = tmp_path / "runpod-startup-claims"
    claims.mkdir()
    data = {
        "schema": startup.SCHEMA,
        "owner_approved": True,
        "approval_id": "synthetic-startup-approval-001",
        "owner_sid": "synthetic-sid",
        "target": startup.TARGET,
        "operation": "runpod.start.once",
        "issued_at": 1000,
        "expires_at": 1300,
        "session_seconds": 6000,
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "pins": startup.public_pins(factory, qwen, operations),
        "factory_root": str(factory),
        "qwen_root": str(qwen),
        "operations_root": str(operations),
        "python_exe": sys.executable,
        "claims_dir": str(claims),
    }
    approval = tmp_path / "synthetic-approval.json"

    def load(command="start", **changes):
        approval.write_text(json.dumps(dict(data, **changes)), encoding="utf-8")
        return startup.load_approval(
            approval,
            factory=factory,
            qwen=qwen,
            operations=operations,
            config_path=config,
            command=command,
            clock=lambda: 1001,
        )

    return SimpleNamespace(
        factory=factory,
        qwen=qwen,
        operations=operations,
        config=config,
        claims=claims,
        data=data,
        approval=approval,
        load=load,
    )


def test_exact_scope_pins_paths_config_and_finite_window(prepared):
    f = prepared
    assert f.load() == f.data
    for alteration in (
        {"owner_approved": False},
        {"operation": "runpod.account.read.once.bearer"},
        {"expires_at": 1001},
        {"issued_at": 1002},
        {"expires_at": 1301},
        {"expires_at": float("nan")},
        {"session_seconds": 6001},
        {"claims_dir": str(f.factory)},
        {"pins": {}},
        {"config_sha256": "0" * 64},
    ):
        with pytest.raises(startup.StartupRefused, match="APPROVAL_REFUSED"):
            f.load(**alteration)
    f.config.write_text('{"changed":true}')
    with pytest.raises(startup.StartupRefused):
        f.load()


def test_source_capture_rejects_new_or_changed_consumers(prepared):
    f = prepared
    sources = startup.load_sources(f.data, factory=f.factory, qwen=f.qwen, operations=f.operations)
    assert "runpod_trial" in sources and "qmc_runpod.fake" in sources
    (f.operations / "qmc_runpod/fake.py").write_text("raise RuntimeError('changed')")
    with pytest.raises(startup.StartupRefused, match="SOURCE_REFUSED"):
        startup.load_sources(f.data, factory=f.factory, qwen=f.qwen, operations=f.operations)
    (f.operations / "qmc_runpod/new.py").write_text("# new consumer")
    with pytest.raises(startup.StartupRefused):
        f.load()


def test_start_approval_cannot_enable_serve(prepared):
    with pytest.raises(startup.StartupRefused):
        prepared.load(command="serve")
    assert (
        prepared.load(command="serve", operation="runpod.serve.once")["operation"]
        == "runpod.serve.once"
    )


def fixture_reader(f, *, enabled=True, sid="synthetic-sid", valid=True, elapsed=0, fail=False):
    buffer = bytearray(b"synthetic-provider-credential")
    calls = []

    def read():
        calls.append("read")
        if fail:
            raise RuntimeError("SYNTHETIC_SECRET_CANARY")
        return buffer

    times = iter((0, elapsed))
    credential = SimpleNamespace(
        current_windows_sid=lambda: sid,
        wipe=wipe,
        WindowsCredentialStore=lambda *a, **k: pytest.fail("native store forbidden"),
    )
    reader = startup.ProviderOnce(
        f.data,
        revalidate=lambda: f.data if valid else None,
        claims=f.claims,
        credential=credential,
        enabled=enabled,
        clock=lambda: 1001,
        monotonic=lambda: next(times),
        store=SimpleNamespace(read=read),
    )
    return reader, buffer, calls


def test_one_read_wipe_and_replay_across_new_instances(prepared, capsys):
    reader, value, calls = fixture_reader(prepared)
    assert reader.read() == "synthetic-provider-credential"
    assert value == bytearray(len(value)) and calls == ["read"]
    assert "synthetic" not in repr(reader)
    for replay in (reader, fixture_reader(prepared)[0]):
        with pytest.raises(startup.StartupRefused, match="CREDENTIAL_REFUSED"):
            replay.read()
    assert len(list(prepared.claims.iterdir())) == 1
    assert next(prepared.claims.iterdir()).read_bytes() == b""
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("changes", [{"enabled": False}, {"sid": "other"}, {"valid": False}])
def test_gate_refuses_before_claim_or_read(prepared, changes):
    reader, _, calls = fixture_reader(prepared, **changes)
    with pytest.raises(startup.StartupRefused):
        reader.read()
    assert calls == [] and list(prepared.claims.iterdir()) == []


@pytest.mark.parametrize("changes", [{"elapsed": 10}, {"fail": True}])
def test_read_failure_or_deadline_consumes_claim_without_retry(prepared, changes):
    reader, value, calls = fixture_reader(prepared, **changes)
    with pytest.raises(startup.StartupRefused) as error:
        reader.read()
    assert str(error.value) == "CREDENTIAL_REFUSED"
    if not changes.get("fail"):
        assert value == bytearray(len(value))
    assert calls == ["read"] and len(list(prepared.claims.iterdir())) == 1


def test_post_read_sid_change_wipes_before_consumer(prepared):
    reader, value, calls = fixture_reader(prepared)
    identities = iter(("synthetic-sid", "synthetic-sid", "other"))
    reader.credential.current_windows_sid = lambda: next(identities)
    with pytest.raises(startup.StartupRefused):
        reader.read()
    assert calls == ["read"] and value == bytearray(len(value))


def test_post_read_pin_or_config_change_wipes_before_consumer(prepared):
    reader, value, calls = fixture_reader(prepared)
    validations = iter((prepared.data, prepared.data, None))
    reader.revalidate = lambda: next(validations)
    with pytest.raises(startup.StartupRefused):
        reader.read()
    assert calls == ["read"] and value == bytearray(len(value))
