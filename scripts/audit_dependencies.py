"""Deterministic dependency auditing script for CI/CLI quality gates."""

import subprocess
import sys


def audit() -> int:
    # 1. Run pip check to verify broken requirements or incompatible versions
    res = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, check=False)
    if res.returncode != 0:
        print("DEPENDENCY AUDIT FAILED: Broken dependencies found:", file=sys.stderr)
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return 1

    print("Dependency audit passed: No broken requirements detected.")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
