"""Sandbox boundaries, command registry, and execution isolation engine."""

import ctypes
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DANGEROUS_ENV_PREFIXES = (
    "GITHUB_",
    "GH_",
    "AWS_",
    "AZURE_",
    "GOOGLE_",
    "GCP_",
    "SSH_",
    "DOCKER_",
    "KUBE",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
)

SAFE_PASSTHROUGH_ENV_VARS = {
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "PYTHONPATH",
    "PYTHONHOME",
    "LANG",
    "LC_ALL",
}

# Metacharacters indicating dangerous shell chaining or injection
SHELL_INJECTION_PATTERN = re.compile(r"[;&|`$><]")


class ShellInjectionError(Exception):
    """Raised when command argv contains dangerous shell metacharacters."""


class PathContainmentError(Exception):
    """Raised when a path escapes its designated sandbox root."""


class CommandRegistryError(Exception):
    """Raised when command is unregistered or fails argument schema validation."""


class PortReservationError(Exception):
    """Raised when port allocation fails."""


class ProcessOwnershipError(Exception):
    """Raised when process ownership or PID creation time verification fails."""


def sanitize_worker_environment(source_env: dict[str, str] | None = None) -> dict[str, str]:
    """Strip all unapproved, credential, token, cloud, and Docker variables from worker environment.
    Strictly enforce that only keys in SAFE_PASSTHROUGH_ENV_VARS (or safe system essentials) are kept.
    """
    if source_env is None:
        source_env = dict(os.environ)

    sanitized: dict[str, str] = {}
    for k, v in source_env.items():
        k_upper = k.upper()
        # Drop if matches any dangerous prefix
        if any(k_upper.startswith(prefix) for prefix in DANGEROUS_ENV_PREFIXES):
            continue
        # Drop if contains suspicious substrings
        if any(bad in k_upper for bad in ("KEY", "SECRET", "TOKEN", "CREDENTIAL", "PASS")):
            continue
        # Strictly enforce allowlist
        if k_upper not in SAFE_PASSTHROUGH_ENV_VARS:
            continue
        sanitized[k] = v

    # Explicitly enforce safe defaults
    sanitized["CI"] = "false"
    sanitized["FACTORY_WORKER_ISOLATED"] = "false"
    return sanitized


def validate_command_argv(argv: list[str]) -> None:
    """Validate typed argv to ensure no shell injection metacharacters are embedded."""
    if not argv:
        raise ValueError("Argv cannot be empty")

    for arg in argv:
        if SHELL_INJECTION_PATTERN.search(arg):
            raise ShellInjectionError(
                f"Dangerous shell metacharacter detected in command argument: '{arg}'"
            )


def validate_path_containment(target_path: Path | str, root_dir: Path | str) -> Path:
    """Validate that target_path strictly resolves inside root_dir without escaping via .. or symlinks."""
    resolved_root = Path(root_dir).resolve()
    resolved_target = Path(target_path).resolve()

    try:
        common = os.path.commonpath([str(resolved_target), str(resolved_root)])
    except ValueError as err:
        raise PathContainmentError(f"Path on different drive/device: {target_path}") from err

    if common.lower() != str(resolved_root).lower():
        raise PathContainmentError(
            f"Path escape detected: '{target_path}' resolves to '{resolved_target}' outside '{resolved_root}'"
        )
    return resolved_target


class PortReservation:
    """Own a bound socket until close; hand this socket to a compatible worker.

    Closing and rebinding the number is not an atomic handoff.
    """

    def __init__(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(("127.0.0.1", 0))
            self.port = self.socket.getsockname()[1]
        except OSError:
            self.socket.close()
            raise

    def close(self) -> None:
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def reserve_ephemeral_port() -> PortReservation:
    """Return a live reservation, not a port number whose socket was closed."""
    return PortReservation()


@dataclass
class CommandDefinition:
    command_id: str
    executable: str
    allowed_flags: list[str] = field(default_factory=list)
    max_positional_args: int = 0
    network_profile: str = "NONE"
    timeout_sec: int = 60


class CommandRegistry:
    """Registry mapping command IDs to strict execution specs."""

    def __init__(self) -> None:
        self._registry: dict[str, CommandDefinition] = {}

    def register(
        self,
        command_id: str,
        executable: str,
        allowed_flags: list[str] | None = None,
        max_positional_args: int = 0,
        network_profile: str = "NONE",
        timeout_sec: int = 60,
    ) -> None:
        self._registry[command_id] = CommandDefinition(
            command_id=command_id,
            executable=executable,
            allowed_flags=allowed_flags or [],
            max_positional_args=max_positional_args,
            network_profile=network_profile,
            timeout_sec=timeout_sec,
        )

    def resolve_and_validate(
        self,
        command_id: str,
        argv: list[str],
        requested_network: str = "NONE",
    ) -> list[str]:
        if command_id not in self._registry:
            raise CommandRegistryError(f"Unregistered command ID: {command_id}")

        defn = self._registry[command_id]
        if requested_network != defn.network_profile:
            raise CommandRegistryError(
                f"Network profile mismatch: requested '{requested_network}', but command requires '{defn.network_profile}'"
            )

        validate_command_argv(argv)

        positional_count = 0
        for arg in argv:
            if arg.startswith("-"):
                if arg not in defn.allowed_flags:
                    raise CommandRegistryError(f"Disallowed argument flag: '{arg}' for {command_id}")
            else:
                positional_count += 1

        if positional_count > defn.max_positional_args:
            raise CommandRegistryError(
                f"Too many positional arguments: {positional_count} > {defn.max_positional_args}"
            )

        return [defn.executable] + argv


def _windows_process_api():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(ctypes.c_int64)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _get_process_creation_time(pid: int) -> float:
    """Get process creation time as epoch timestamp with high precision to guard against PID reuse."""
    if sys.platform == "win32":
        kernel32 = _windows_process_api()
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return 0.0

        creation_time = ctypes.c_int64()
        exit_time = ctypes.c_int64()
        kernel_time = ctypes.c_int64()
        user_time = ctypes.c_int64()

        try:
            success = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation_time),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            )
            if success:
                return (creation_time.value - 116444736000000000) / 10000000.0
            return 0.0
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            stat_path = Path(f"/proc/{pid}/stat")
            if stat_path.exists():
                # comm (field 2) can contain spaces or parentheses.
                parts = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
                if len(parts) > 19:
                    return float(parts[19])
        except (OSError, ValueError, IndexError):
            pass
        return 0.0


def get_process_creation_time(pid: int) -> float:
    """Public wrapper around the process creation-time probe, for cross-process PID verification."""
    return _get_process_creation_time(pid)


def _is_process_alive(pid: int, proc_handle: Any = None) -> bool:
    """Non-destructive process liveness probe."""
    if proc_handle is not None and hasattr(proc_handle, "poll") and proc_handle.poll() is not None:
        return False

    if sys.platform == "win32":
        kernel32 = _windows_process_api()
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Unknown is not proof of exit.
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            status_file = Path(f"/proc/{pid}/status")
            if status_file.exists():
                for line in status_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("State:"):
                        if "Z" in line:  # Zombie process
                            return False
                        break
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return True


@dataclass
class ProcessRecord:
    pid: int
    start_time: float
    run_id: str
    worker_id: str
    proc: Any = None

    def is_alive(self) -> bool:
        return _is_process_alive(self.pid, self.proc)


class ProcessTreeController:
    """Controls lifecycle of worker processes and all descendant processes."""

    def __init__(self) -> None:
        self._owned_processes: dict[int, ProcessRecord] = {}

    def spawn(
        self,
        argv: list[str],
        cwd: Path | str,
        run_id: str,
        worker_id: str,
        env: dict[str, str] | None = None,
    ) -> ProcessRecord:
        sanitized_env = sanitize_worker_environment(env)
        kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "env": sanitized_env,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(argv, **kwargs)

        start_time = _get_process_creation_time(proc.pid)
        if start_time == 0.0:
            start_time = time.time()

        record = ProcessRecord(
            pid=proc.pid,
            start_time=start_time,
            run_id=run_id,
            worker_id=worker_id,
            proc=proc,
        )
        self._owned_processes[proc.pid] = record
        return record

    def verify_ownership(self, record: ProcessRecord) -> None:
        """Verify process record matches actual process creation time and ownership."""
        if not _is_process_alive(record.pid, record.proc):
            raise ProcessOwnershipError("Process ownership verification failed: Process is not alive")

        current_time = _get_process_creation_time(record.pid)
        if current_time == 0.0 or current_time != record.start_time:
            raise ProcessOwnershipError(
                f"Process ownership verification failed: PID {record.pid} creation time mismatch (suspected PID reuse)"
            )

        if record.pid in self._owned_processes:
            owned = self._owned_processes[record.pid]
            if owned.run_id != record.run_id or owned.worker_id != record.worker_id:
                raise ProcessOwnershipError("Process ownership verification failed: Run/worker mismatch")
        else:
            raise ProcessOwnershipError("Process ownership verification failed: PID not in owned registry")

    def terminate_tree(self, record: ProcessRecord) -> None:
        """Forcefully terminate process and all its child/descendant processes."""
        # Validate ownership at the destructive entrypoint, not only in a helper test.
        if self._owned_processes.get(record.pid) is not record:
            raise ProcessOwnershipError("Process ownership verification failed: unknown process record")
        if not _is_process_alive(record.pid, record.proc):
            return
        self.verify_ownership(record)

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(record.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                # Terminate the whole process group
                os.killpg(record.pid, 9)
            except OSError:
                try:
                    os.kill(record.pid, 9)
                except OSError:
                    pass

        if record.proc is not None and hasattr(record.proc, "poll"):
            try:
                record.proc.wait(timeout=5.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            time.sleep(0.1)

    def terminate_external(self, pid: int, start_time: float, timeout: float = 5.0) -> bool:
        """Terminate a process (and its process group) not spawned by this controller instance.

        Used to cancel a worker owned by a separate process invocation (e.g. a CLI process
        cancelling a previously-dispatched worker), identity-verified against the process
        creation time recorded when its lease was acquired to guard against PID reuse.
        Returns True once the process is confirmed terminated (or was already dead).
        """
        if not _is_process_alive(pid):
            return True

        current_time = _get_process_creation_time(pid)
        if start_time and current_time and current_time != start_time:
            raise ProcessOwnershipError(
                f"Process ownership verification failed: PID {pid} creation time mismatch "
                "(suspected PID reuse)"
            )

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
        else:
            try:
                os.killpg(pid, 9)
            except OSError:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _is_process_alive(pid):
                return True
            time.sleep(0.1)
        return not _is_process_alive(pid)
