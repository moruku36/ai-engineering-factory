"""Deterministic dependency auditing script for CI/CLI quality gates.

Enforces:
1. pip check (package dependencies consistency)
2. Known vulnerability (CVE) checking against vulnerability database
3. Strict fail-closed policy: network/audit failures must NEVER be treated as clean
4. Time-bounded, owned exceptions with mandatory justification (audit_exceptions.json)
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


class VulnerabilityAuditError(Exception):
    """Raised when the vulnerability audit cannot be completed or fails policy."""


def load_and_validate_exceptions(exceptions_file: Path) -> dict[str, dict]:
    """Load exception records. Require cve_id, package, reason, owner, and unexpired expires_at."""
    if not exceptions_file.exists():
        return {}

    try:
        data = json.loads(exceptions_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise VulnerabilityAuditError(f"Failed to parse exceptions file {exceptions_file}: {exc}") from exc

    if not isinstance(data, list):
        raise VulnerabilityAuditError("Exceptions file must contain a JSON list of objects")

    now = datetime.now(UTC)
    active_exceptions = {}
    for entry in data:
        for required in ("cve_id", "package", "reason", "owner", "expires_at"):
            if not entry.get(required) or not str(entry[required]).strip():
                raise VulnerabilityAuditError(f"Exception entry missing mandatory field '{required}': {entry}")

        cve = entry["cve_id"].strip().upper()
        expires_at_str = entry["expires_at"].strip()
        try:
            exp_date = datetime.fromisoformat(expires_at_str)
        except ValueError as exc:
            raise VulnerabilityAuditError(f"Invalid expires_at format for {cve}: {expires_at_str}") from exc

        if now > exp_date:
            raise VulnerabilityAuditError(
                f"Vulnerability exception for {cve} ({entry['package']}) expired on {expires_at_str}. "
                f"Permanent unconditional exclusions are forbidden; renew or remediate."
            )

        active_exceptions[cve] = entry

    return active_exceptions


def query_package_vulnerabilities(
    package: str,
    version: str,
    offline_db: dict | None = None,
    timeout: int = 10,
) -> list[dict]:
    """Query vulnerability database (OSV API or local verified snapshot). Fail-closed on error."""
    if offline_db is not None:
        return offline_db.get(package, {}).get(version, [])

    # Query OSV (Open Source Vulnerabilities) API
    payload = json.dumps({
        "package": {"name": package, "ecosystem": "PyPI"},
        "version": version,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.osv.dev/v1/query",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "AIFactory-AuditGate/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise VulnerabilityAuditError(f"OSV API returned unexpected HTTP status {resp.status}")
            data = json.loads(resp.read().decode("utf-8"))
            vulns = data.get("vulns", [])
            return vulns
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VulnerabilityAuditError(
            f"Failed to connect to vulnerability audit service: {exc}. "
            f"Fail-closed policy: audit connection failure must NEVER be treated as 'no vulnerabilities'."
        ) from exc


def parse_requirements(req_file: Path) -> list[tuple[str, str]]:
    """Parse exact package==version entries from requirements file."""
    packages = []
    if not req_file.exists():
        return packages

    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            pkg, ver = line.split("==", 1)
            packages.append((pkg.strip().lower(), ver.strip()))
    return packages


def audit(
    requirements_file: Path | str | None = None,
    exceptions_file: Path | str | None = None,
    offline_db: dict | None = None,
) -> int:
    root = Path(__file__).resolve().parent.parent
    req_path = Path(requirements_file) if requirements_file else root / "requirements.txt"
    exc_path = Path(exceptions_file) if exceptions_file else root / "scripts" / "audit_exceptions.json"

    print("=== Dependency and Vulnerability Audit Gate ===")

    # 1. Run pip check to verify broken requirements or incompatible versions
    res = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, check=False)
    if res.returncode != 0:
        print("DEPENDENCY AUDIT FAILED: Broken dependencies found by pip check:", file=sys.stderr)
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return 1
    print("[*] pip check: OK (No conflicting dependencies)")

    # 2. Validate exception registry (reject expired exceptions)
    try:
        active_exceptions = load_and_validate_exceptions(exc_path)
    except VulnerabilityAuditError as exc:
        print(f"DEPENDENCY AUDIT FAILED: {exc}", file=sys.stderr)
        return 1

    # 3. Parse pinned requirements
    pinned_packages = parse_requirements(req_path)
    print(f"[*] Pinned packages scanned: {len(pinned_packages)}")

    # 4. Check known vulnerabilities (Fail-closed on connection or policy errors)
    unmitigated_vulns = []
    for pkg, ver in pinned_packages:
        try:
            vulns = query_package_vulnerabilities(pkg, ver, offline_db=offline_db)
            for v in vulns:
                vid = v.get("id", "UNKNOWN-VULN").upper()
                aliases = [a.upper() for a in v.get("aliases", [])]
                if vid not in active_exceptions and not any(a in active_exceptions for a in aliases):
                    unmitigated_vulns.append((pkg, ver, vid, v.get("summary", "No details")))
                else:
                    exc_info = active_exceptions.get(vid) or next(active_exceptions[a] for a in aliases if a in active_exceptions)
                    print(f"[!] Vulnerability {vid} on {pkg}=={ver} excluded by active approved exception (Owner: {exc_info['owner']})")
        except VulnerabilityAuditError as exc:
            print(f"DEPENDENCY AUDIT FAILED: {exc}", file=sys.stderr)
            return 1

    if unmitigated_vulns:
        print("DEPENDENCY AUDIT FAILED: Known security vulnerabilities detected:", file=sys.stderr)
        for pkg, ver, vid, summary in unmitigated_vulns:
            print(f"  - [{vid}] {pkg}=={ver}: {summary}", file=sys.stderr)
        return 1

    print("[*] Vulnerability Scan: OK (0 unmitigated CVEs)")
    print("Dependency audit passed: No vulnerabilities or broken requirements detected.")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
