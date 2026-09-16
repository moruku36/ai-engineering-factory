"""Tests for dependency vulnerability audit gate and exception lifecycle."""

import json
from unittest.mock import patch

import pytest

from scripts.audit_dependencies import (
    VulnerabilityAuditError,
    audit,
    load_and_validate_exceptions,
    parse_requirements,
    query_package_vulnerabilities,
)


def test_parse_requirements(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pyyaml==6.0.3\n# comment\npytest==9.1.1\n\n", encoding="utf-8")
    parsed = parse_requirements(req_file)
    assert parsed == [("pyyaml", "6.0.3"), ("pytest", "9.1.1")]


def test_load_exceptions_rejects_expired(tmp_path):
    exc_file = tmp_path / "exceptions.json"
    exc_file.write_text(json.dumps([
        {
            "cve_id": "CVE-2023-0001",
            "package": "insecure-pkg",
            "reason": "Temporary exception",
            "owner": "sec-team",
            "expires_at": "2020-01-01T00:00:00Z",  # Expired!
        }
    ]), encoding="utf-8")

    with pytest.raises(VulnerabilityAuditError, match="expired on"):
        load_and_validate_exceptions(exc_file)


def test_load_exceptions_rejects_missing_mandatory_fields(tmp_path):
    exc_file = tmp_path / "exceptions.json"
    exc_file.write_text(json.dumps([
        {
            "cve_id": "CVE-2023-0001",
            "package": "pkg",
            # Missing reason, owner, expires_at
        }
    ]), encoding="utf-8")

    with pytest.raises(VulnerabilityAuditError, match="missing mandatory field"):
        load_and_validate_exceptions(exc_file)


def test_query_vulnerabilities_fail_closed_on_connection_error():
    # Simulate network failure to audit service
    with (
        patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")),
        pytest.raises(VulnerabilityAuditError, match="Fail-closed policy: audit connection failure"),
    ):
        query_package_vulnerabilities("requests", "2.0.0", offline_db=None)


def test_audit_detects_known_vulnerability(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("vulnerable-pkg==1.0.0\n", encoding="utf-8")

    exc_file = tmp_path / "exceptions.json"
    exc_file.write_text("[]", encoding="utf-8")

    fake_db = {
        "vulnerable-pkg": {
            "1.0.0": [{"id": "CVE-2024-9999", "summary": "Critical RCE vulnerability"}]
        }
    }

    exit_code = audit(
        requirements_file=req_file,
        exceptions_file=exc_file,
        offline_db=fake_db,
    )
    assert exit_code == 1


def test_audit_allows_active_valid_exception(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("vulnerable-pkg==1.0.0\n", encoding="utf-8")

    exc_file = tmp_path / "exceptions.json"
    exc_file.write_text(json.dumps([
        {
            "cve_id": "CVE-2024-9999",
            "package": "vulnerable-pkg",
            "reason": "Documented sandbox mitigation in place",
            "owner": "lead-architect@example.com",
            "expires_at": "2028-12-31T23:59:59Z",
        }
    ]), encoding="utf-8")

    fake_db = {
        "vulnerable-pkg": {
            "1.0.0": [{"id": "CVE-2024-9999", "summary": "Known issue"}]
        }
    }

    exit_code = audit(
        requirements_file=req_file,
        exceptions_file=exc_file,
        offline_db=fake_db,
    )
    assert exit_code == 0
