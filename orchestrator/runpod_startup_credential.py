"""Owner-local v2 read for one pinned startup. Import is inert; no secret getter CLI.

The trusted launcher must supervise the entire credential-owning child. This
module never treats an account-read approval as a startup/session approval.
Same-user arbitrary code and administrator access are outside this boundary.
"""

import hashlib
import importlib.abc
import importlib.util
import json
import math
import os
import re
import sys
import time
from pathlib import Path

TARGET = "AIEngineeringFactory/RunPod/provider/v2"
SCHEMA = "runpod-startup-v2-once-v1"
FACTORY_FILES = (
    "orchestrator/__init__.py",
    "orchestrator/windows_credential_store.py",
    "orchestrator/runpod_local_credential.py",
    "orchestrator/runpod_startup_credential.py",
)
QWEN_FILES = (
    "scripts/runpod_trial.py",
    "scripts/runpod_provider.py",
    "scripts/runpod_credman_startup.py",
)
FIELDS = {
    "schema",
    "owner_approved",
    "approval_id",
    "owner_sid",
    "target",
    "operation",
    "issued_at",
    "expires_at",
    "session_seconds",
    "config_sha256",
    "pins",
    "factory_root",
    "qwen_root",
    "operations_root",
    "python_exe",
    "claims_dir",
}


class StartupRefused(Exception):
    """Fixed public reason only; do not retain native errors or approval data."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StartupRefused("APPROVAL_REFUSED")
        result[key] = value
    return result


def source_files(factory, qwen, operations):
    """Explicit public roots only, no credential/config/environment discovery."""
    paths = {"factory:" + rel: Path(factory) / rel for rel in FACTORY_FILES}
    paths.update({"qwen:" + rel: Path(qwen) / rel for rel in QWEN_FILES})
    package = Path(operations) / "qmc_runpod"
    paths.update(
        {
            "operations:" + p.relative_to(Path(operations)).as_posix(): p
            for p in package.rglob("*.py")
        }
    )
    if "operations:qmc_runpod/__init__.py" not in paths:
        raise StartupRefused("SOURCE_REFUSED")
    paths["python.exe"] = Path(sys.executable)
    return paths


def public_pins(factory, qwen, operations):
    return {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in source_files(factory, qwen, operations).items()
    }


def load_approval(path, *, factory, qwen, operations, config_path, command, clock=time.time):
    """Exact startup scope, source set, config digest and <=300s entry window."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(65537)
        data = json.loads(raw, object_pairs_hook=_unique)
        now = clock()
        if (
            len(raw) > 65536
            or type(data) is not dict
            or set(data) != FIELDS
            or data["schema"] != SCHEMA
            or data["owner_approved"] is not True
            or data["target"] != TARGET
            or command not in {"start", "serve"}
            or data["operation"] != "runpod." + command + ".once"
            or type(data["approval_id"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{16,64}", data["approval_id"]) is None
            or type(data["owner_sid"]) is not str
            or not 1 <= len(data["owner_sid"]) <= 256
            or any(
                type(data[k]) not in (int, float) or not math.isfinite(data[k])
                for k in ("issued_at", "expires_at")
            )
            or not data["issued_at"] <= now < data["expires_at"] <= data["issued_at"] + 300
            or type(data["session_seconds"]) is not int
            or data["session_seconds"] != 6000
            or data["config_sha256"] != hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
            or data["pins"] != public_pins(factory, qwen, operations)
        ):
            raise StartupRefused("APPROVAL_REFUSED")
        for key, bound_path in {
            "factory_root": factory,
            "qwen_root": qwen,
            "operations_root": operations,
            "python_exe": sys.executable,
            "claims_dir": Path(factory).resolve().parent / "runpod-startup-claims",
        }.items():
            if (
                type(data[key]) is not str
                or not Path(data[key]).is_absolute()
                or os.path.normcase(str(Path(data[key]).resolve()))
                != os.path.normcase(str(Path(bound_path).resolve()))
            ):
                raise StartupRefused("APPROVAL_REFUSED")
        return data
    except Exception:  # noqa: BLE001 - never expose approval/path/parser details
        raise StartupRefused("APPROVAL_REFUSED") from None


def load_sources(data, *, factory, qwen, operations):
    """Capture and verify before executing; no .pyc or ambient package imports."""
    sources = {}
    for key, path in source_files(factory, qwen, operations).items():
        if key == "python.exe":
            continue
        with path.open("rb") as stream:
            source = stream.read(1048577)
        if len(source) > 1048576 or hashlib.sha256(source).hexdigest() != data["pins"][key]:
            raise StartupRefused("SOURCE_REFUSED")
        if key.startswith("operations:"):
            rel = key.split(":", 1)[1][:-3]
            package = rel.endswith("/__init__")
            name = (rel[:-9] if package else rel).replace("/", ".")
        else:
            rel = key.split(":", 1)[1][:-3]
            package = rel.endswith("/__init__")
            name = (rel[:-9] if package else rel).replace("/", ".")
            if key.startswith("qwen:"):
                name = Path(rel).name
        sources[name] = (path, source, package)
    return sources


class PinnedSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Trusted worker only: execute the captured source set instead of imports."""

    def __init__(self, sources):
        self.sources = sources

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.sources:
            return importlib.util.spec_from_loader(
                fullname, self, is_package=self.sources[fullname][2]
            )
        if fullname.startswith(("qmc_runpod.", "orchestrator.")):
            raise StartupRefused("SOURCE_REFUSED")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, source, package = self.sources[module.__name__]
        module.__file__ = str(path)
        if package:
            module.__path__ = [str(path.parent)]
        exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102 - captured pinned source only


class ProviderOnce:
    """Child-local provider injection; caller owns subsequent session deadline.

    Validate SID, full pins, config and entry expiry before claim/read and after
    read. A claimed ID stays consumed on every failure. No key is persisted or
    returned over IPC; the returned str is for the same pinned worker only.
    """

    def __init__(
        self,
        data,
        *,
        revalidate,
        claims,
        credential,
        enabled=False,
        clock=time.time,
        monotonic=time.monotonic,
        store=None,
    ):
        self.data = data
        self.revalidate = revalidate
        self.claims = Path(claims)
        self.credential = credential
        self.enabled = enabled is True
        self.clock = clock
        self.monotonic = monotonic
        self.store = store
        self.used = False

    def __repr__(self):
        return "<ProviderOnce redacted>"

    def _allowed(self):
        return (
            self.enabled
            and self.clock() < self.data["expires_at"]
            and self.credential.current_windows_sid() == self.data["owner_sid"]
            and self.revalidate() == self.data
        )

    def read(self):
        value = bytearray()
        try:
            if self.used or not self._allowed():
                raise StartupRefused("CREDENTIAL_REFUSED")
            self.used = True
            if not self.claims.is_dir():
                raise StartupRefused("CLAIM_REFUSED")
            name = hashlib.sha256(self.data["approval_id"].encode("ascii")).hexdigest()
            descriptor = os.open(self.claims / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            if not self._allowed():
                raise StartupRefused("CREDENTIAL_REFUSED")
            started = self.monotonic()
            backing = (
                self.store
                if self.store is not None
                else self.credential.WindowsCredentialStore(TARGET, enabled=True)
            )
            value = backing.read()
            if (
                type(value) is not bytearray
                or not self._allowed()
                or self.monotonic() - started >= 10
            ):
                raise StartupRefused("CREDENTIAL_REFUSED")
            key = value.decode("utf-8")
            if re.fullmatch(r"[A-Za-z0-9_.-]{16,512}", key) is None:
                raise StartupRefused("CREDENTIAL_REFUSED")
            return key
        except Exception:  # noqa: BLE001 - never expose native/key exceptions
            raise StartupRefused("CREDENTIAL_REFUSED") from None
        finally:
            self.credential.wipe(value)
