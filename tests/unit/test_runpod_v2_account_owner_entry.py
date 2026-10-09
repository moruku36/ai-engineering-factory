"""Owner entry checks with synthetic files/SID/account and no native/API use."""
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from orchestrator import runpod_v2_account_owner_entry as entry


def environment(tmp_path):
    root = tmp_path / "repo"
    (root / "orchestrator").mkdir(parents=True)
    for name in entry.PINS.values():
        (root / name).write_text("synthetic fixture", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"synthetic python")
    now = 1_800_000_000
    pins = {key: hashlib.sha256((root / path).read_bytes()).hexdigest() for key, path in entry.PINS.items()}
    pins["python.exe"] = hashlib.sha256(python.read_bytes()).hexdigest()
    config = {"owner_approved": True, "operation": entry.OPERATION,
              "approval_id": "synthetic-account-approval-01", "owner_sid": "synthetic-sid",
              "expires_utc": datetime.fromtimestamp(now + 120, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "repo_root": str(root), "python_exe": str(python), "pins": pins}
    path = root.parent / entry.CONFIG
    path.write_text(json.dumps(config), encoding="utf-8")
    calls = []
    def execute(scope, **kwargs):
        calls.append((scope, kwargs))
        return {"status": "account-verified", "account_id": "synthetic-account"}
    runtime = SimpleNamespace(sid=lambda: "synthetic-sid", scope=lambda *a: a, execute=execute)
    return root, python, now, path, config, calls, runtime


def test_disabled_and_pending_never_load(tmp_path):
    root, python, now, path, _, calls, _ = environment(tmp_path)
    def forbidden(_):
        raise AssertionError("no identity/credential/API call")
    kwargs = {"root": root, "python": python, "clock": lambda: now, "loader": forbidden}
    assert entry.run([], **kwargs) == {"status": "disabled"}
    path.unlink()
    assert entry.run(["--run"], **kwargs) == {"status": "approval-pending"}
    assert calls == []


def test_approved_entry_calls_once_then_refuses_replay(tmp_path, capsys):
    root, python, now, _, _, calls, runtime = environment(tmp_path)
    kwargs = {"root": root, "python": python, "clock": lambda: now, "loader": lambda _: runtime}
    assert entry.run(["--run"], **kwargs) == {"status": "account-verified", "account_id": "synthetic-account"}
    assert entry.run(["--run"], **kwargs) == {"status": "replay-denied"}
    assert len(calls) == 1
    assert calls[0][1] == {"enabled": True, "external_read_approved": True}
    assert capsys.readouterr() == ("", "")


def test_hash_or_operation_mismatch_never_loads(tmp_path):
    root, python, now, path, config, calls, _ = environment(tmp_path)
    def forbidden(_):
        raise AssertionError("must not load with mismatched approval")
    kwargs = {"root": root, "python": python, "clock": lambda: now, "loader": forbidden}
    config["operation"] = "enroll+initial-local-read"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert entry.run(["--run"], **kwargs) == {"status": "approval-pending"}
    config["operation"] = entry.OPERATION
    path.write_text(json.dumps(config), encoding="utf-8")
    (root / entry.PINS["adapter"]).write_text("changed", encoding="utf-8")
    assert entry.run(["--run"], **kwargs) == {"status": "approval-pending"}
    assert calls == []


def test_wrong_owner_refuses_before_read(tmp_path):
    root, python, now, _, _, calls, runtime = environment(tmp_path)
    runtime.sid = lambda: "wrong-sid"
    assert entry.run(["--run"], root=root, python=python, clock=lambda: now,
                     loader=lambda _: runtime) == {"status": "denied"}
    assert calls == []
