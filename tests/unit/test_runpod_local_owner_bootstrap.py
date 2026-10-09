"""Synthetic owner-bootstrap contract; fake paths/SID/clock/enroll, no native or real config."""

import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from orchestrator import runpod_local_owner_bootstrap as boot

NOW = 1_800_000_000.0
SID = "synthetic-sid"
ACCOUNT = "moruku-runpod-personal"


def stamp(offset):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + offset))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Env:
    def __init__(self, tmp_path):
        self.root = tmp_path / "owner" / "repo"
        (self.root / "orchestrator").mkdir(parents=True)
        for rel in boot.PIN_FILES.values():
            (self.root / rel).write_text("# synthetic " + rel)
        self.python = tmp_path / "python.exe"
        self.python.write_bytes(b"synthetic python")
        self.config = self.root.parent / boot.CONFIG
        self.claims = self.root.parent / boot.CLAIMS
        self.calls = []
        self.outcome = {"status": "registered-ready"}
        self.sid = SID
        self.write()

    def data(self):
        pins = {name: sha(self.root / rel) for name, rel in boot.PIN_FILES.items()}
        pins["python.exe"] = sha(self.python)
        return {
            "owner_approved": True, "operation": boot.OPERATION,
            "approval_id": "synthetic-approval-0001", "expires_utc": stamp(600),
            "owner_sid": SID,
            "repo_root": str(self.root),
            "python_exe": str(self.python), "pins": pins,
        }

    def write(self, **changes):
        data = {**self.data(), **changes}
        self.config.write_text(json.dumps({k: v for k, v in data.items() if v is not None}))

    def loader(self, root):
        def enroll(scope, *, enabled):
            self.calls.append((scope, enabled))
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome
        return SimpleNamespace(
            sid=lambda: self.sid, enroll=enroll,
            scope=lambda *args: SimpleNamespace(args=args),
        )

    def run(self, flag, tty=True, loader=True):
        return boot.run(
            [flag], root=self.root, python=self.python, clock=lambda: NOW,
            loader=self.loader if loader else None, is_tty=lambda: tty,
        )


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_default_off_returns_before_config_identity_or_native(capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("disabled path must not touch anything")
    assert boot.run([], root=forbidden, clock=forbidden, loader=forbidden) == "disabled"
    assert boot.main([]) == 0
    assert capsys.readouterr().out == "status: disabled\n"
    assert boot.run(["--other"]) == "denied"


def test_preflight_verifies_pins_without_loading_or_claiming(env, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must not load or claim")
    env.loader = forbidden
    assert env.run("--preflight") == "pinned-config-ready-owner-unverified"
    (env.root / boot.PIN_FILES["bootstrap"]).write_text("# changed")
    assert env.run("--preflight") == "denied"
    env.write()
    env.python.write_bytes(b"changed")
    assert env.run("--preflight") == "denied"
    env.config.unlink()
    assert env.run("--preflight") == "approval-pending"
    assert not env.claims.exists()
    assert env.calls == []


def bad_configs(env):
    data = env.data()
    return [
        {"owner_approved": False}, {"owner_approved": "true"}, {"operation": "enroll"},
        {"approval_id": "short"}, {"expires_utc": stamp(-1)}, {"expires_utc": stamp(1801)},
        {"expires_utc": "never"}, {"use_until_utc": stamp(86400)},
        {"owner_sid": " "}, {"account_ref": ACCOUNT}, {"extra": "x"},
        {"pins": {**data["pins"], "bootstrap": "0" * 64}},
        {"pins": {k: v for k, v in data["pins"].items() if k != "python.exe"}},
        {"repo_root": str(env.root.parent)}, {"python_exe": str(env.root / "other.exe")},
    ]


def test_missing_incomplete_invalid_or_mismatched_approval_denied_without_input(env):
    for changes in bad_configs(env):
        env.write(**changes)
        assert env.run("--owner-enroll") in ("approval-pending", "denied"), changes
    env.config.write_text('{"owner_approved": true, "owner_approved": true}')
    assert env.run("--owner-enroll") == "approval-pending"
    env.config.write_text('{"x": NaN}')
    assert env.run("--owner-enroll") == "approval-pending"
    env.config.unlink()
    assert env.run("--owner-enroll") == "approval-pending"
    assert env.calls == [] and not env.claims.exists()


def test_no_tty_denied_before_loader_sid_or_input(env):
    def forbidden(root):
        raise AssertionError("no loader, DLL, SID call or hidden input without a TTY")
    env.loader = forbidden
    assert env.run("--owner-enroll", tty=False) == "denied"
    assert env.calls == [] and not env.claims.exists()


def test_source_python_and_wrong_sid_denied_before_claim(env):
    env.sid = "someone-else"
    assert env.run("--owner-enroll") == "denied"
    env.sid = SID
    (env.root / boot.PIN_FILES["windows_credential_store.py"]).write_text("# changed")
    assert env.run("--owner-enroll") == "denied"
    env.python.write_bytes(b"changed")
    assert env.run("--owner-enroll") == "denied"
    assert env.calls == [] and not env.claims.exists()


def test_default_loader_refuses_non_isolated_python(env):
    assert env.run("--owner-enroll", loader=False) == "failed"
    assert env.calls == [] and not env.claims.exists()


def test_approved_enrollment_runs_once_then_replay_denied(env, capsys):
    assert env.run("--owner-enroll") == "registered-ready"
    scope, enabled = env.calls[0]
    assert enabled is True and len(env.calls) == 1
    assert scope.args == (SID, ACCOUNT, {
        name: env.data()["pins"][name] for name in boot.SCOPE_PINS
    }, NOW + 600, True)  # use_until is the 30 minute approval expiry
    assert len(boot.PIN_FILES) + 1 == 5
    assert "python.exe" in scope.args[2] and "bootstrap" not in scope.args[2]
    name = hashlib.sha256(b"synthetic-approval-0001").hexdigest()
    assert [p.name for p in env.claims.iterdir()] == [name]
    assert (env.claims / name).read_bytes() == b""
    assert env.run("--owner-enroll") == "replay-denied"
    assert len(env.calls) == 1
    assert capsys.readouterr() == ("", "")


def test_cancel_also_consumes_approval_and_no_retry(env):
    env.outcome = {"status": "cancelled"}
    assert env.run("--owner-enroll") == "cancelled"
    env.outcome = {"status": "registered-ready"}
    assert env.run("--owner-enroll") == "replay-denied"
    assert len(env.calls) == 1


def test_exceptions_and_unknown_results_are_redacted(env, capsys):
    env.outcome = RuntimeError("SECRET-VALUE " + SID + str(env.root))
    assert env.run("--owner-enroll") == "failed"
    env.write(approval_id="synthetic-approval-0002")
    env.outcome = {"status": "SECRET-VALUE"}
    assert env.run("--owner-enroll") == "failed"
    out = capsys.readouterr()
    assert (out.out, out.err) == ("", "")
