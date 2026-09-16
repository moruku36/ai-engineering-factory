"""Offline Linux command boundary, callable only by a trusted control process.

This is not a native Antigravity adapter or a Human approval service.
No host workspace, Docker socket, credentials or control state is worker-mounted.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class ContainerBoundaryError(RuntimeError):
    """Execution or cleanup could not be established; never fall back to Popen."""


@dataclass(frozen=True)
class ContainerCommand:
    """Trusted exact argv; task input cannot supply Docker options or extra flags."""

    argv: tuple[str, ...]
    timeout_sec: int = 60

    def __post_init__(self):
        if (not isinstance(self.argv, tuple) or not self.argv
                or not all(isinstance(a, str) and a and "\0" not in a for a in self.argv)
                or not self.argv[0].startswith("/")
                or not 1 <= self.timeout_sec <= 300):
            raise ValueError("Require absolute container executable and timeout of 1..300 seconds")


@dataclass(frozen=True)
class ContainerResult:
    run_id: str
    exit_code: int
    output: str


class OfflineContainerRunner:
    """Execute provisioned immutable images on a local Linux Docker daemon.

    control_root must be private, outside worker inputs and source repositories.
    Journals survive controller crashes; reconcile(run_id) removes only a container
    whose full ID and random ownership labels match the trusted journal.
    """

    def __init__(self, control_root: Path, image_id: str,
                 commands: dict[str, ContainerCommand]):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("Provision a local immutable sha256 image ID; tags are refused")
        if not commands or not all(isinstance(c, ContainerCommand) for c in commands.values()):
            raise ValueError("Trusted command registry required")
        self.root = Path(control_root).resolve()
        if any(char in str(self.root) for char in (",", "\n", "\r")):
            raise ValueError("Control path contains unsupported mount syntax")
        self.image_id = image_id
        self.commands = dict(commands)
        self.docker = shutil.which("docker")

    def _call(self, *args: str, timeout: int = 30) -> str:
        if sys.platform != "linux" or not self.docker:
            raise ContainerBoundaryError("UNAVAILABLE: local Linux Docker is required")
        try:
            result = subprocess.run(
                [self.docker, "--host", "unix:///var/run/docker.sock",
                 "--config", str(self.root / "docker-config"), *args],
                env={"PATH": os.defpath, "LANG": "C.UTF-8"},
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContainerBoundaryError("Docker transport failed or timed out") from exc
        if result.returncode:
            # Do not publish daemon output or worker-controlled strings as diagnostics.
            raise ContainerBoundaryError(f"Docker {args[0]} failed ({result.returncode})")
        return (result.stdout + (result.stderr if args[0] == "logs" else "")).strip()

    def _preflight(self) -> None:
        info = json.loads(self._call("info", "--format", "{{json .}}"))
        if info.get("OSType") != "linux" or not any(
            "name=seccomp" in item and "profile=builtin" in item
            for item in info.get("SecurityOptions", [])
        ):
            raise ContainerBoundaryError("Linux daemon with seccomp is required")
        image = json.loads(self._call("image", "inspect", self.image_id))[0]
        if (image.get("Id") != self.image_id or image.get("Os") != "linux"
                or image.get("Config", {}).get("Volumes")):
            raise ContainerBoundaryError("Image must be Linux with no implicit volumes")

    def _save(self, record: dict) -> None:
        directory = self.root / record["run_id"]
        temporary = directory / "record.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(directory / "record.json")
        if sys.platform == "linux":
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _find_owned(self, record: dict) -> str | None:
        found = self._call("container", "ls", "--all", "--no-trunc", "--filter",
                           f"name=^/{record['name']}$", "--format", "{{.ID}}")
        if not found:
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", found):
            raise ContainerBoundaryError("Ambiguous container identity")
        actual = json.loads(self._call("container", "inspect", found))[0]
        labels = actual.get("Config", {}).get("Labels", {})
        if (actual.get("Id") != found or actual.get("Name") != "/" + record["name"]
                or labels.get("factory.run") != record["run_id"]
                or labels.get("factory.owner") != record["owner"]
                or record.get("container_id") not in (None, found)):
            raise ContainerBoundaryError("Container ownership mismatch; refusing removal")
        return found

    def reconcile(self, run_id: str) -> None:
        """Control-plane recovery after a crash; never accepts a worker PID or name."""
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("Invalid run ID")
        record = json.loads((self.root / run_id / "record.json").read_text(encoding="utf-8"))
        if record.get("run_id") != run_id or record.get("name") != "factory-" + run_id:
            raise ContainerBoundaryError("Invalid control journal")
        identity = self._find_owned(record)
        if identity is None and not record.get("container_id"):
            raise ContainerBoundaryError("Create outcome uncertain; retain journal for reconciliation")
        if identity:
            record["container_id"] = identity
            self._save(record)
            self._call("container", "rm", "--force", "--volumes", identity)
        if self._find_owned(record) is not None:
            raise ContainerBoundaryError("Container cleanup is unconfirmed")
        record["cleanup"] = "CONFIRMED"
        self._save(record)
        # Only delete the generated input snapshot after confirmed container removal.
        inputs = self.root / run_id / "inputs"
        if inputs.exists():
            shutil.rmtree(inputs)

    def run(self, command_id: str, inputs: dict[str, bytes] | None = None) -> ContainerResult:
        """Run exact registered argv with an explicit, bounded flat input snapshot."""
        if command_id not in self.commands:
            raise ValueError("Unregistered container command")
        inputs = dict(inputs or {})
        if len(inputs) > 100 or any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", name)
            or PurePosixPath(name).name != name or not isinstance(data, bytes)
            for name, data in inputs.items()
        ) or sum(len(data) for data in inputs.values()) > 1024 * 1024:
            raise ValueError("Inputs must be at most 100 flat files and 1 MiB total")
        command = self.commands[command_id]
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if sys.platform == "linux":
            info = self.root.stat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ContainerBoundaryError("Control root must be owner-only (mode 0700)")
        (self.root / "docker-config").mkdir(exist_ok=True, mode=0o700)
        self._preflight()
        run_id = uuid.uuid4().hex
        directory = self.root / run_id
        directory.mkdir(mode=0o700)
        snapshot = directory / "inputs"
        snapshot.mkdir(mode=0o755)
        snapshot.chmod(0o755)
        for name, data in inputs.items():
            target = snapshot / name
            target.write_bytes(data)
            target.chmod(0o444)
        record = {"run_id": run_id, "name": "factory-" + run_id,
                  "owner": uuid.uuid4().hex, "image_id": self.image_id,
                  "command_id": command_id, "cleanup": "PENDING"}
        self._save(record)  # Journal intent before the first external mutation.
        try:
            identity = self._call(
                "create", "--pull=never", "--name", record["name"],
                "--label", f"factory.run={run_id}", "--label", f"factory.owner={record['owner']}",
                "--network=none", "--read-only", "--user=65534:65534",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--ipc=private",
                "--cgroupns=private", "--pids-limit=64", "--memory=256m",
                "--memory-swap=256m", "--cpus=1", "--ulimit=nofile=128:128",
                "--restart=no", "--no-healthcheck", "--log-driver=local",
                "--log-opt=max-size=1m", "--log-opt=max-file=1", "--log-opt=compress=false",
                "--tmpfs=/workspace:rw,nosuid,nodev,noexec,size=32m,mode=1777",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
                "--mount", f"type=bind,src={snapshot},dst=/inputs,readonly,bind-recursive=disabled",
                "--workdir=/workspace", "--env=HOME=/tmp",
                "--entrypoint", command.argv[0], self.image_id, *command.argv[1:],
            )
            if not re.fullmatch(r"[0-9a-f]{64}", identity):
                raise ContainerBoundaryError("Invalid container ID")
            record["container_id"] = identity
            self._save(record)
            if self._find_owned(record) != identity:
                raise ContainerBoundaryError("Created container not found")
            self._call("start", identity)
            exit_text = self._call("wait", identity, timeout=command.timeout_sec)
            if not re.fullmatch(r"[0-9]{1,3}", exit_text) or int(exit_text) > 255:
                raise ContainerBoundaryError("Invalid container exit evidence")
            output = self._call("logs", "--tail=1000", identity)
            record["exit_code"] = int(exit_text)
            self._save(record)
            return ContainerResult(run_id, int(exit_text), output)
        finally:
            # Any uncertain cleanup raises instead of returning success. The journal
            # and snapshot stay available for a trusted operator to reconcile.
            self.reconcile(run_id)
