"""Dormant Win32 backing-store candidate; never a model tool or automatic enrollment."""

import ctypes
import os
from ctypes import wintypes

GENERIC = 1
LOCAL_PERSISTENCE = 2
NOT_FOUND = 1168


class StoreError(Exception):
    """Safe error with no credential, target, or native exception text."""


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


class WindowsCredentialStore:
    """Explicit opt-in is a deployment guard, not proof of human/OS authorization.

    No DLL load or native call occurs on import or default construction.
    Target comes from trusted local configuration, never worker requests.
    """

    def __init__(self, target: str, *, enabled: bool = False):
        if enabled is not True:
            raise StoreError("native backend disabled")
        if os.name != "nt":
            raise StoreError("Windows required")
        if not isinstance(target, str) or not target or "\x00" in target:
            raise StoreError("invalid configuration")
        self._target = target
        try:
            self._api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
            pointer = ctypes.POINTER(Credential)
            self._api.CredWriteW.argtypes = [pointer, wintypes.DWORD]
            self._api.CredWriteW.restype = wintypes.BOOL
            self._api.CredReadW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)
            ]
            self._api.CredReadW.restype = wintypes.BOOL
            self._api.CredDeleteW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD
            ]
            self._api.CredDeleteW.restype = wintypes.BOOL
            self._api.CredFree.argtypes = [ctypes.c_void_p]
            self._api.CredFree.restype = None
        except (OSError, AttributeError):
            raise StoreError("native backend unavailable") from None

    def write(self, value: bytearray) -> None:
        if not isinstance(value, bytearray) or not 0 < len(value) <= 2560:
            raise StoreError("invalid credential input")
        buffer = (ctypes.c_ubyte * len(value)).from_buffer(value)
        credential = Credential()
        credential.Type = GENERIC
        credential.TargetName = self._target
        credential.CredentialBlobSize = len(value)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = LOCAL_PERSISTENCE
        if not self._api.CredWriteW(ctypes.byref(credential), 0):
            raise StoreError("credential write failed")

    def read(self) -> bytearray:
        pointer = ctypes.POINTER(Credential)()
        if not self._api.CredReadW(self._target, GENERIC, 0, ctypes.byref(pointer)):
            raise StoreError("credential read failed")
        try:
            record = pointer.contents
            if not 0 < record.CredentialBlobSize <= 2560:
                raise StoreError("invalid stored credential")
            # Mutable copy; avoid creating an immutable Python string/bytes copy.
            return bytearray(record.CredentialBlob[:record.CredentialBlobSize])
        finally:
            if pointer:
                record = pointer.contents
                if record.CredentialBlob and 0 < record.CredentialBlobSize <= 2560:
                    ctypes.memset(record.CredentialBlob, 0, record.CredentialBlobSize)
                self._api.CredFree(pointer)

    def delete(self) -> None:
        if (
            not self._api.CredDeleteW(self._target, GENERIC, 0)
            and ctypes.get_last_error() != NOT_FOUND
        ):
            raise StoreError("credential deletion failed")

    def __repr__(self) -> str:
        return "<WindowsCredentialStore redacted>"
