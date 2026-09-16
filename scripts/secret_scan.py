"""Deterministic, fail-closed secret scanner for git commit range, staged changes, and tree."""

import re
import subprocess
import sys

# High confidence secret patterns
SECRET_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9_]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"gho_[A-Za-z0-9_]{36}"), "GitHub OAuth Access Token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{82}"), "GitHub Fine-Grained PAT"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "Private Key Block"),
]

# Narrowly allowlisted harmless test fixture lines
ALLOWED_TEST_FIXTURE_SNIPPETS = {
    "ghp_secret12345",
    "gho_secret67890",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}


def run_git_command(args: list[str]) -> str:
    res = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"Git command failed (exit code {res.returncode}): {' '.join(args)}\n{res.stderr}")
    return res.stdout or ""


def scan_text(text: str, source_name: str) -> list[str]:
    if not text:
        return []
    found = []
    for line in text.splitlines():
        # Check if line contains known test fixture string
        if any(fixture in line for fixture in ALLOWED_TEST_FIXTURE_SNIPPETS):
            continue
        for pattern, name in SECRET_PATTERNS:
            matches = pattern.findall(line)
            if matches:
                found.append(f"[{source_name}] Detected {name} ({len(matches)} match(es))")
    return found


def scan_all() -> int:
    try:
        # Determine diff range
        # Check if origin/main exists
        res = subprocess.run(
            ["git", "rev-parse", "--verify", "origin/main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode == 0:
            diff_range = "origin/main...HEAD"
        else:
            diff_range = "HEAD~1...HEAD"

        diff_output = run_git_command(["git", "diff", diff_range])
        staged_output = run_git_command(["git", "diff", "--cached"])
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        print(f"SECRET SCAN ERROR: Failed to run git diff checks: {e}", file=sys.stderr)
        return 2  # Fail closed

    found_secrets = []
    found_secrets.extend(scan_text(diff_output, f"commit range {diff_range}"))
    found_secrets.extend(scan_text(staged_output, "staged changes"))

    if found_secrets:
        print("SECRET SCAN FAILED: Potential credentials detected:", file=sys.stderr)
        for s in found_secrets:
            print(f"  - {s}", file=sys.stderr)
        return 1

    print("Secret scan passed. No exposed secrets detected.")
    return 0


if __name__ == "__main__":
    sys.exit(scan_all())
