"""Dormant owner bootstrap for RunPod local enrollment. Default OFF; no secret getter.

Run only from an owner terminal as: python -I <this file> --preflight | --owner-enroll
Approval is a non-secret JSON file next to the repo clone. The boolean in it is a
convenience guard, NOT cryptographic human proof; same-user code/admins can bypass it.
One 30 minute approval window (expires_utc) covers the enrollment and the initial local
read; LocalScope.use_until is that same expiry. Retention after enrollment is indefinite
until the owner deletes it; any later use needs a separate fresh approval and a launcher
that does not exist yet. Self-pin set is exactly 5: this file, package init, the two
credential modules and python.exe. --preflight only hashes those; it loads nothing.
Stdlib only at import: no config read, pinned import, identity or native call by default.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

CONFIG = "runpod-local-enrollment-approval.local.json"
CLAIMS = "runpod-local-enrollment-claims"
OPERATION = "enroll+initial-local-read"
MAX_BYTES = 8192
MAX_APPROVAL_SECONDS = 1800
ACCOUNT_REF = "moruku-runpod-personal"  # non-secret owner label, not a provider id
PIN_FILES = {
    "bootstrap": "orchestrator/runpod_local_owner_bootstrap.py",
    "package_init": "orchestrator/__init__.py",
    "runpod_local_credential.py": "orchestrator/runpod_local_credential.py",
    "windows_credential_store.py": "orchestrator/windows_credential_store.py",
}
SCOPE_PINS = ("runpod_local_credential.py", "windows_credential_store.py", "python.exe")
KEYS = {
    "owner_approved", "operation", "approval_id", "expires_utc",
    "owner_sid", "repo_root", "python_exe", "pins",
}
STATUSES = {
    "registered-ready", "registered-check-failed", "cancelled", "denied", "failed",
    "disabled", "already-exists",
}
SHA = re.compile(r"[0-9a-f]{64}")
APPROVAL_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
UTC_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def _strict(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _reject(_):
    raise ValueError("non-finite or float")


def _utc(text):
    if type(text) is not str or not UTC_TIME.fullmatch(text):
        raise ValueError("time")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC).timestamp()


def _text(value):
    return type(value) is str and bool(value.strip()) and len(value) <= 256 and value.isprintable()


def _approval(root, clock):
    """Validated non-secret approval dict, or None for any problem."""
    try:
        with open(root.parent / CONFIG, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        data = json.loads(raw[:MAX_BYTES].decode("utf-8"), object_pairs_hook=_strict,
                          parse_constant=_reject, parse_float=_reject)
        pins = data["pins"]
        now = clock()
        expires = _utc(data["expires_utc"])
        if (
            len(raw) > MAX_BYTES or set(data) != KEYS
            or data["owner_approved"] is not True or data["operation"] != OPERATION
            or type(data["approval_id"]) is not str
            or not APPROVAL_ID.fullmatch(data["approval_id"])
            or not _text(data["owner_sid"])
            or not _text(data["repo_root"]) or not _text(data["python_exe"])
            or type(pins) is not dict or set(pins) != {*PIN_FILES, "python.exe"}
            or not all(type(v) is str and SHA.fullmatch(v) for v in pins.values())
            or not now < expires <= now + MAX_APPROVAL_SECONDS
        ):
            return None
        return data
    except Exception:  # noqa: BLE001 - status only, never relay parse/path text
        return None


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _same(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(
        str(Path(right).resolve()))


def _verify(root, python, data):
    try:
        if not (_same(data["repo_root"], root) and _same(data["python_exe"], python)):
            return False
        actual = {name: _sha(root / rel) for name, rel in PIN_FILES.items()}
        actual["python.exe"] = _sha(python)
        return actual == data["pins"]
    except Exception:  # noqa: BLE001
        return False


def _load_pinned(root):
    """Import only the already hash-verified package from the derived repo root."""
    if not sys.flags.isolated:
        raise RuntimeError("isolated python required")
    sys.path.insert(0, str(root))
    import importlib
    module = importlib.import_module("orchestrator.runpod_local_credential")
    if not _same(module.__file__, root / PIN_FILES["runpod_local_credential.py"]):
        raise RuntimeError("unexpected module")
    return SimpleNamespace(
        sid=module.current_windows_sid, scope=module.LocalScope,
        enroll=module.run_owner_enrollment,
    )


def _tty():
    return sys.stdin.isatty() and sys.stdout.isatty()


def _claim(root, approval_id):
    """Atomically consume the approval once; the claim file holds no data."""
    directory = root.parent / CLAIMS
    directory.mkdir(exist_ok=True)
    name = hashlib.sha256(approval_id.encode("utf-8")).hexdigest()
    try:
        os.close(os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return False
    return True


def run(argv, *, root=None, python=None, clock=time.time, loader=None, is_tty=None):
    """Return a status word only; never a secret, SID, path or exception text."""
    if not argv:
        return "disabled"
    if list(argv) not in (["--preflight"], ["--owner-enroll"]):
        return "denied"
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    python = python or sys.executable
    data = _approval(root, clock)
    if data is None:
        return "approval-pending"
    if not _verify(root, python, data):
        return "denied"
    if argv[0] == "--preflight":
        return "pinned-config-ready-owner-unverified"
    try:
        if not (is_tty or _tty)():
            return "denied"
        owner = (loader or _load_pinned)(root)
        if not _verify(root, python, data) or owner.sid() != data["owner_sid"]:
            return "denied"
        if not _claim(root, data["approval_id"]):
            return "replay-denied"
        scope = owner.scope(
            data["owner_sid"], ACCOUNT_REF,
            {name: data["pins"][name] for name in SCOPE_PINS},
            _utc(data["expires_utc"]), True,
        )
        result = owner.enroll(scope, enabled=True)
        status = result.get("status") if type(result) is dict else None
        return status if status in STATUSES else "failed"
    except Exception:  # noqa: BLE001 - claim stays consumed; never retry
        return "failed"


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    status = run(arguments)
    print("status: " + status)
    if list(arguments) == ["--owner-enroll"]:
        destination = Path(__file__).resolve().parents[2] / "runpod-local-enrollment-result.local.json"
        destination.write_text(json.dumps({"status": status}), encoding="utf-8")
    return 0 if status in (
        "disabled", "pinned-config-ready-owner-unverified", "registered-ready") else 1


if __name__ == "__main__":
    sys.exit(main())
