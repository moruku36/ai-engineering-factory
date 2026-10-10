"""Synthetic contract: local_use_once rejects bytes/str via the shared wipe TypeError."""

from types import SimpleNamespace

import pytest

from orchestrator.runpod_local_credential import LocalScope, RunPodLocalCredentialFlow

KEY = "synthetic-provider-credential"


def local_flow(value):
    pins = {"dummy": "pin"}
    calls = []

    def read():
        calls.append("read")
        return value

    def forbidden(*args, **kwargs):
        raise AssertionError("real effect forbidden")

    scope = LocalScope("synthetic-sid", "synthetic-account", pins, 2000.0, True)
    flow = RunPodLocalCredentialFlow(
        scope,
        enabled=True,
        store=SimpleNamespace(read=read, write=forbidden, delete=forbidden),
        sid_reader=lambda: "synthetic-sid",
        pin_reader=lambda: pins,
        clock=lambda: 1000.0,
        exists_reader=forbidden,
    )
    return flow, calls


@pytest.mark.parametrize("value", [KEY.encode(), KEY], ids=["bytes", "str"])
def test_local_use_once_rejects_bytes_and_str_via_shared_wipe_typeerror(value):
    flow, calls = local_flow(value)
    with pytest.raises(TypeError) as error:
        flow.local_use_once(approved=True)
    assert type(error.value) is TypeError
    assert KEY not in str(error.value)
    assert calls == ["read"]


def test_local_use_once_bytearray_control_is_ready_and_wiped():
    buffer = bytearray(KEY.encode())
    flow, calls = local_flow(buffer)
    assert flow.local_use_once(approved=True) == {"status": "ready"}
    assert calls == ["read"] and buffer == bytearray(len(buffer))
