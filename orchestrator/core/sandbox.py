"""Sandbox boundaries and command isolation engine."""

import os
import re

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
    sanitized["FACTORY_WORKER_ISOLATED"] = "true"
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
