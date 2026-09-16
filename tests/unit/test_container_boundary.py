"""Failure-path tests; actual isolation is checked separately on Linux Docker."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from orchestrator.core.container import (
    ContainerBoundaryError,
    ContainerCommand,
    OfflineContainerRunner,
)

IMAGE = "sha256:" + "a" * 64
CID = "b" * 64


def runner(tmp_path):
    return OfflineContainerRunner(tmp_path / "control", IMAGE, {
        "test": ContainerCommand(("/usr/local/bin/python", "/inputs/test.py"), 2),
    })


@pytest.mark.parametrize("image", ["python:latest", "--privileged", "sha256:bad"])
def test_mutable_or_invalid_image_refused(tmp_path, image):
    with pytest.raises(ValueError):
        OfflineContainerRunner(tmp_path, image, {"test": ContainerCommand(("/bin/true",))})


@pytest.mark.parametrize("argv", [(), ("python",), ("/bin/true", "\0"), ["/bin/true"]])
def test_command_requires_fixed_absolute_argv(argv):
    with pytest.raises(ValueError):
        ContainerCommand(argv)


@pytest.mark.parametrize("inputs", [
    {"../secret": b"x"}, {"/control": b"x"}, {"x,y": b"x"}, {"sub/x": b"x"},
    {"x": "not-bytes"}, {"x": b"x" * (1024 * 1024 + 1)},
])
def test_input_escape_rejected_before_docker(tmp_path, inputs):
    boundary = runner(tmp_path)
    boundary._call = Mock(side_effect=AssertionError("Docker must not be called"))
    with pytest.raises(ValueError):
        boundary.run("test", inputs)
    assert not boundary.root.exists()


def test_missing_docker_never_executes_host_command(tmp_path, monkeypatch):
    boundary = runner(tmp_path)
    boundary.docker = None
    execute = Mock()
    monkeypatch.setattr(subprocess, "run", execute)
    with pytest.raises(ContainerBoundaryError, match="UNAVAILABLE"):
        boundary.run("test")
    execute.assert_not_called()


def test_cli_has_no_inherited_secrets_or_remote_context(tmp_path, monkeypatch):
    boundary = runner(tmp_path)
    boundary.docker = "/usr/bin/docker"
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted:2375")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture")
    execute = Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
    monkeypatch.setattr(subprocess, "run", execute)
    boundary._call("info")
    call = execute.call_args
    assert "unix:///var/run/docker.sock" in call.args[0]
    assert "DOCKER_HOST" not in call.kwargs["env"]
    assert "GITHUB_TOKEN" not in call.kwargs["env"]


def test_foreign_container_never_removed(tmp_path):
    boundary = runner(tmp_path)
    record = {"run_id": "c" * 32, "name": "factory-" + "c" * 32, "owner": "ours"}
    directory = boundary.root / record["run_id"]
    directory.mkdir(parents=True)
    boundary._save(record)
    boundary._call = Mock(side_effect=[CID, json.dumps([{
        "Id": CID, "Name": "/" + record["name"],
        "Config": {"Labels": {"factory.run": record["run_id"], "factory.owner": "foreign"}},
    }])])
    with pytest.raises(ContainerBoundaryError, match="ownership"):
        boundary.reconcile(record["run_id"])
    assert not any("rm" in call.args for call in boundary._call.call_args_list)


def test_ambiguous_create_keeps_journal(tmp_path):
    boundary = runner(tmp_path)
    boundary._preflight = Mock()
    boundary._call = Mock(side_effect=[ContainerBoundaryError("create timeout"), ""])
    with pytest.raises(ContainerBoundaryError, match="uncertain"):
        boundary.run("test")
    record = json.loads(next(boundary.root.glob("*/record.json")).read_text())
    assert record["cleanup"] == "PENDING"


def test_cleanup_failure_never_returns_success(tmp_path):
    boundary = runner(tmp_path)
    boundary._preflight = Mock()
    boundary._find_owned = Mock(return_value=CID)
    boundary._call = Mock(side_effect=[CID, "", "0", "ok", ContainerBoundaryError("rm failed")])
    with pytest.raises(ContainerBoundaryError, match="rm failed"):
        boundary.run("test")
    record = json.loads(next(boundary.root.glob("*/record.json")).read_text())
    assert record["exit_code"] == 0
    assert record["cleanup"] == "PENDING"


def test_image_implicit_volumes_rejected(tmp_path):
    boundary = runner(tmp_path)
    boundary._call = Mock(side_effect=[
        json.dumps({"OSType": "linux", "SecurityOptions": ["name=seccomp,profile=builtin"]}),
        json.dumps([{"Id": IMAGE, "Os": "linux", "Config": {"Volumes": {"/data": {}}}}]),
    ])
    with pytest.raises(ContainerBoundaryError, match="implicit volumes"):
        boundary._preflight()


def test_recovered_create_identity_survives_repeated_cleanup(tmp_path):
    boundary = runner(tmp_path)
    record = {"run_id": "c" * 32, "name": "factory-" + "c" * 32,
              "owner": "ours", "cleanup": "PENDING"}
    (boundary.root / record["run_id"]).mkdir(parents=True)
    boundary._save(record)
    boundary._find_owned = Mock(side_effect=[CID, None, None, None])
    boundary._call = Mock(return_value="")
    boundary.reconcile(record["run_id"])
    boundary.reconcile(record["run_id"])
    saved = json.loads((boundary.root / record["run_id"] / "record.json").read_text())
    assert saved["container_id"] == CID
    assert saved["cleanup"] == "CONFIRMED"
    boundary._call.assert_called_once_with("container", "rm", "--force", "--volumes", CID)
