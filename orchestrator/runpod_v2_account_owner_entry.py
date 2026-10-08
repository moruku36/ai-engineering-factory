"""Dormant fixed v2 account-read owner entry. Separate approval, no key output."""
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

CONFIG = "runpod-v2-account-read-approval.local.json"
OPERATION = "runpod.account.read.once"
PINS = {
    "entry": "orchestrator/runpod_v2_account_owner_entry.py",
    "package_init": "orchestrator/__init__.py",
    "adapter": "orchestrator/runpod_v2_account_adapter.py",
    "credential": "orchestrator/runpod_local_credential.py",
    "store": "orchestrator/windows_credential_store.py",
}
KEYS = {"owner_approved", "operation", "approval_id", "expires_utc", "owner_sid",
        "repo_root", "python_exe", "pins"}


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def load_approved(root, python, clock):
    try:
        with (root.parent / CONFIG).open("rb") as handle:
            raw = handle.read(8193)
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
        if len(raw) > 8192 or set(data) != KEYS or data["owner_approved"] is not True:
            return None
        if (data["operation"] != OPERATION or type(data["approval_id"]) is not str
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", data["approval_id"])
                or type(data["owner_sid"]) is not str or not data["owner_sid"]):
            return None
        text = data["expires_utc"]
        if type(text) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", text):
            return None
        expiry = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
        if not clock() < expiry <= clock() + 300:
            return None
        if Path(data["repo_root"]).resolve() != root.resolve() or Path(data["python_exe"]).resolve() != Path(python).resolve():
            return None
        actual = {key: hashlib.sha256((root / path).read_bytes()).hexdigest() for key, path in PINS.items()}
        actual["python.exe"] = hashlib.sha256(Path(python).read_bytes()).hexdigest()
        if data["pins"] != actual:
            return None
        return data, expiry
    except Exception:  # noqa: BLE001 - never emit private configuration details
        return None


def load_runtime(root):
    if not sys.flags.isolated:
        raise RuntimeError("isolated required")
    sys.path.insert(0, str(root))
    from orchestrator import runpod_local_credential as credential
    from orchestrator import runpod_v2_account_adapter as adapter
    return SimpleNamespace(sid=credential.current_windows_sid, scope=credential.LocalScope,
                           execute=adapter.read_account_once)


def run(argv, *, root=None, python=None, clock=time.time, loader=load_runtime):
    if not argv:
        return {"status": "disabled"}
    if list(argv) != ["--run"]:
        return {"status": "denied"}
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    python = python or sys.executable
    approved = load_approved(root, python, clock)
    if approved is None:
        return {"status": "approval-pending"}
    data, expiry = approved
    try:
        runtime = loader(root)
        if runtime.sid() != data["owner_sid"] or not load_approved(root, python, clock):
            return {"status": "denied"}
        claims = root.parent / "runpod-account-read-claims"
        claims.mkdir(exist_ok=True)
        name = hashlib.sha256(data["approval_id"].encode()).hexdigest()
        try:
            os.close(os.open(claims / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            return {"status": "replay-denied"}
        scope = runtime.scope(data["owner_sid"], "moruku-runpod-personal", {
            "runpod_local_credential.py": data["pins"]["credential"],
            "windows_credential_store.py": data["pins"]["store"],
            "python.exe": data["pins"]["python.exe"],
        }, expiry, True)
        result = runtime.execute(scope, enabled=True, external_read_approved=True)
        if type(result) is not dict or result.get("status") not in {"account-verified", "denied", "expired", "failed"}:
            return {"status": "failed"}
        if result["status"] == "account-verified":
            account = result.get("account_id")
            if type(account) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", account):
                return {"status": "failed"}
            return {"status": "account-verified", "account_id": account}
        return {"status": result["status"]}
    except Exception:  # noqa: BLE001 - errors must not include URLs or key values
        return {"status": "failed"}


def main():
    result = run(sys.argv[1:])
    if sys.argv[1:] == ["--run"]:
        # Fixed private result: non-secret account ID for later account binding.
        path = Path(__file__).resolve().parents[2] / "runpod-account-read-result.local.json"
        path.write_text(json.dumps(result), encoding="utf-8")
    print("status: " + result["status"])
    return 0 if result["status"] in {"disabled", "account-verified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
