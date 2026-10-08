"""Small RunPod-only native wiring candidate. No model-callable secret retrieval API.

Default disabled. Only a trusted owner entry may enable after concrete approval.
No network, launcher injection, process spawning, service, ACL or account change.
"""

import ctypes
import getpass
import hashlib
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from orchestrator.windows_credential_store import WindowsCredentialStore, wipe

ITEM = "AIEngineeringFactory/RunPod/provider/v1"
OPERATION = "runpod.credential.local-use.once"
PIN_PATHS = ("runpod_local_credential.py", "windows_credential_store.py")


def current_windows_sid():
    """Read current process token SID; no credential-store call and no stdout."""
    if os.name != "nt":
        raise RuntimeError("Windows required")
    adv = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    token = wintypes.HANDLE()
    length = wintypes.DWORD()
    sid_text = wintypes.LPWSTR()
    adv.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
    ]
    adv.OpenProcessToken.restype = wintypes.BOOL
    adv.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    ]
    adv.GetTokenInformation.restype = wintypes.BOOL
    adv.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)
    ]
    adv.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise RuntimeError("owner identity unavailable")
    try:
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        if not 0 < length.value <= 65536:
            raise RuntimeError("owner identity unavailable")
        buffer = ctypes.create_string_buffer(length.value)
        if not adv.GetTokenInformation(
            token, 1, buffer, length, ctypes.byref(length)
        ):
            raise RuntimeError("owner identity unavailable")
        # TOKEN_USER begins with SID_AND_ATTRIBUTES, whose first member is PSID.
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise RuntimeError("owner identity unavailable")
        return sid_text.value
    finally:
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        kernel.CloseHandle(token)


def source_pins():
    """Public code digests only. Display together with absolute paths to the owner."""
    root = Path(__file__).resolve().parent
    pins = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in PIN_PATHS}
    pins["python.exe"] = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    return pins


@dataclass(frozen=True, repr=False)
class LocalScope:
    owner_sid: str
    account_ref: str
    pins: dict
    use_until: float
    confirmed: bool = False

    def __repr__(self):
        return "<LocalScope redacted>"


class RunPodLocalCredentialFlow:
    """One registration -> reusable store -> one read per use approval.

    confirmed is a trusted-entry approval flag, NOT cryptographic human identity.
    Account_ref is owner-specified metadata, not a verified provider account.
    Same-user arbitrary code/admins can bypass all these convenience checks.
    """

    def __init__(
        self, scope, *, enabled=False, store=None, sid_reader=current_windows_sid,
        pin_reader=source_pins, clock=time.time
    ):
        self._scope = scope
        self._enabled = enabled is True
        self._store = store
        self._sid_reader = sid_reader
        self._pin_reader = pin_reader
        self._clock = clock

    def _allowed(self, *, deleting=False):
        scope = self._scope
        return (
            self._enabled and type(scope) is LocalScope and scope.confirmed is True
            and type(scope.owner_sid) is str and bool(scope.owner_sid)
            and type(scope.account_ref) is str and bool(scope.account_ref)
            and self._sid_reader() == scope.owner_sid and self._pin_reader() == scope.pins
            and (deleting or self._clock() < scope.use_until)
        )

    def _backing_store(self):
        if self._store is None:
            self._store = WindowsCredentialStore(ITEM, enabled=True)
        return self._store

    def enroll_owner(self, read_hidden):
        value = bytearray()
        try:
            if not self._allowed():
                return {"status": "denied"}
            answer = read_hidden("Existing RunPod API key (hidden; blank cancels): ")
            if not answer:
                return {"status": "cancelled"}
            if type(answer) is not str or len(answer) > 2560:
                return {"status": "denied"}
            value = bytearray(answer, "utf-8")
            del answer
            if not self._allowed():
                return {"status": "denied"}
            self._backing_store().write(value)
            return {"status": "registered"}
        except (KeyboardInterrupt, EOFError):
            return {"status": "cancelled"}
        except Exception:  # noqa: BLE001 - never relay input/native error text
            return {"status": "failed"}
        finally:
            wipe(value)

    def local_use_once(self, *, approved=False, cancel=None):
        value = bytearray()
        try:
            if approved is not True or not self._allowed():
                return {"status": "denied"}
            if cancel is not None and cancel.is_set():
                return {"status": "cancelled"}
            started = self._clock()
            value = self._backing_store().read()
            if cancel is not None and cancel.is_set():
                return {"status": "cancelled"}
            if not self._allowed() or self._clock() - started >= 10:
                return {"status": "expired"}
            # Internal readiness check, NOT authentication or a key fingerprint.
            return {"status": "ready" if 0 < len(value) <= 2560 else "failed"}
        except Exception:  # noqa: BLE001 - no credential/native exception output
            return {"status": "failed"}
        finally:
            wipe(value)

    def delete_owner(self):
        try:
            if not self._allowed(deleting=True):
                return {"status": "denied"}
            self._backing_store().delete()
            return {"status": "deleted"}
        except Exception:  # noqa: BLE001 - never relay deletion errors
            return {"status": "failed"}


def run_owner_enrollment(scope, *, enabled=False):
    """Owner-local hidden UI wiring; not exposed by module CLI or any model tool.

    Trusted caller supplies the already-confirmed scope. Combined permission must
    cover enrollment AND one local readiness read. No prompt fallback/secret argv.
    """
    if enabled is not True:
        return {"status": "disabled"}
    if not sys.stdin.isatty():
        return {"status": "denied"}
    flow = RunPodLocalCredentialFlow(scope, enabled=True)
    result = flow.enroll_owner(getpass.getpass)
    if result != {"status": "registered"}:
        return result
    checked = flow.local_use_once(approved=True)
    return {"status": "registered-ready" if checked == {"status": "ready"}
            else "registered-check-failed"}


if __name__ == "__main__":
    print("RunPod local credential candidate disabled; no native operation performed")
