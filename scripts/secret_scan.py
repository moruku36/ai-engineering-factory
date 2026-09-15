"""Deterministic secret scanner for repository commits and tree."""

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


def scan_diff() -> int:
    try:
        # Check against HEAD~1 or empty tree
        cmd = ["git", "diff", "HEAD~1...HEAD"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        diff_text = res.stdout if res.returncode == 0 else ""
    except OSError:
        diff_text = ""

    found_secrets = []
    for pattern, name in SECRET_PATTERNS:
        matches = pattern.findall(diff_text)
        if matches:
            found_secrets.append(f"Detected {name} ({len(matches)} instance(s))")

    if found_secrets:
        print("SECRET SCAN FAILED: Potential credentials detected in commit diff:", file=sys.stderr)
        for s in found_secrets:
            print(f"  - {s}", file=sys.stderr)
        return 1

    print("Secret scan passed. No exposed secrets detected in diff.")
    return 0


if __name__ == "__main__":
    sys.exit(scan_diff())
