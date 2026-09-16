"""Real Linux Docker acceptance, required by the dedicated container CI job."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from orchestrator.core.container import (
    ContainerBoundaryError,
    ContainerCommand,
    OfflineContainerRunner,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("FACTORY_TEST_IMAGE"), reason="Dedicated Linux Docker job required",
)


@pytest.fixture(autouse=True)
def fixture_daemon_diagnostics(monkeypatch):
    """Expose daemon failures only for these generated, credential-free CI fixtures."""
    execute = subprocess.run

    def checked(*args, **kwargs):
        result = execute(*args, **kwargs)
        if result.returncode:
            print("Fixture daemon diagnostic:", result.stderr[:2000])
        return result

    monkeypatch.setattr(subprocess, "run", checked)


def make_runner(tmp_path, timeout=15):
    return OfflineContainerRunner(tmp_path / "control", os.environ["FACTORY_TEST_IMAGE"], {
        "probe": ContainerCommand(("/usr/local/bin/python", "/inputs/probe.py"), timeout),
    })


def test_real_file_network_identity_and_control_boundary(tmp_path, monkeypatch):
    outside = tmp_path / "outside-fixture.txt"
    outside.write_text("review-owned harmless fixture")
    boundary = make_runner(tmp_path)
    monkeypatch.setenv("FACTORY_HOST_SECRET", "fixture-not-a-real-secret")
    probe = f'''
import errno, os, pathlib, socket
assert os.getuid() == 65534
status = dict(line.split(":", 1) for line in pathlib.Path("/proc/self/status").read_text().splitlines())
assert int(status["CapEff"].strip(), 16) == 0
assert status["NoNewPrivs"].strip() == "1"
assert status["Seccomp"].strip() == "2"
assert "FACTORY_HOST_SECRET" not in os.environ
assert "AI_FACTORY_APPROVAL_SECRET" not in os.environ
assert not pathlib.Path("/var/run/docker.sock").exists()
assert not pathlib.Path({str(outside)!r}).exists()
assert not pathlib.Path({str(boundary.root)!r}).exists()
for target in ["/inputs/probe.py", "/etc/factory-write-test"]:
    try:
        pathlib.Path(target).write_text("escape")
    except OSError as exc:
        assert exc.errno in (errno.EROFS, errno.EACCES)
    else:
        raise AssertionError("read-only boundary failed")
pathlib.Path("/workspace/artifact").write_text("scratch works")
assert pathlib.Path("/workspace/artifact").read_text() == "scratch works"
assert set(os.listdir("/sys/class/net")) == {{"lo"}}
with socket.socket() as sock:
    sock.settimeout(1)
    try:
        sock.connect(("192.0.2.1", 443))
    except OSError:
        pass
    else:
        raise AssertionError("outbound network was available")
print("BOUNDARY_OK")
'''
    result = boundary.run("probe", {"probe.py": probe.encode()})
    assert result.exit_code == 0, result.output
    assert "BOUNDARY_OK" in result.output
    record = json.loads((boundary.root / result.run_id / "record.json").read_text())
    assert record["cleanup"] == "CONFIRMED"
    assert boundary._find_owned(record) is None
    assert outside.read_text() == "review-owned harmless fixture"


def test_real_nonzero_exit_is_not_success(tmp_path):
    boundary = make_runner(tmp_path)
    result = boundary.run("probe", {"probe.py": b"import sys; print('failed', file=sys.stderr); sys.exit(7)"})
    assert result.exit_code == 7
    assert "failed" in result.output


def test_real_timeout_removes_container_and_descendants(tmp_path):
    boundary = make_runner(tmp_path, timeout=1)
    code = b"import subprocess, time; subprocess.Popen(['/bin/sleep', '120']); time.sleep(120)"
    with pytest.raises(ContainerBoundaryError, match="timed out"):
        boundary.run("probe", {"probe.py": code})
    record = json.loads(next(boundary.root.glob("*/record.json")).read_text())
    assert record["cleanup"] == "CONFIRMED"
    assert boundary._find_owned(record) is None


def test_real_concurrent_runs_have_separate_scratch(tmp_path):
    def execute(index):
        boundary = make_runner(tmp_path / str(index))
        code = (
            "import pathlib,time; p=pathlib.Path('/workspace/same'); "
            f"p.write_text('{index}'); time.sleep(1); assert p.read_text() == '{index}'"
        )
        return boundary.run("probe", {"probe.py": code.encode()})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, [0, 1]))
    assert all(result.exit_code == 0 for result in results)
    assert results[0].run_id != results[1].run_id


def test_real_crashed_controller_can_be_reconciled(tmp_path):
    # Start a real worker and abruptly terminate only the review-owned controller.
    image = os.environ["FACTORY_TEST_IMAGE"]
    root = tmp_path / "control"
    program = f'''
from pathlib import Path
from orchestrator.core.container import ContainerCommand, OfflineContainerRunner
runner = OfflineContainerRunner(Path({str(root)!r}), {image!r}, {{
    "probe": ContainerCommand(("/usr/local/bin/python", "/inputs/probe.py"), 120)}})
runner.run("probe", {{"probe.py": b"import time; time.sleep(120)"}})
'''
    import sys
    import time

    process = subprocess.Popen([sys.executable, "-c", program])
    boundary = make_runner(tmp_path)
    record = None
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            records = list(root.glob("*/record.json"))
            if records:
                record = json.loads(records[0].read_text())
                if record.get("container_id"):
                    actual = json.loads(boundary._call("inspect", record["container_id"]))[0]
                    if actual["State"]["Running"]:
                        break
            time.sleep(0.1)
        else:
            pytest.fail("Worker did not start")
        process.kill()
        process.wait(timeout=10)
        # A fresh control instance recovers from durable evidence, not memory.
        make_runner(tmp_path).reconcile(record["run_id"])
        assert boundary._find_owned(record) is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if record:
            boundary.reconcile(record["run_id"])
