"""Synthetic reports: structural consistency is not execution provenance."""

import hashlib

import pytest

from orchestrator.core import junit
from orchestrator.core.artifacts import ArtifactCollectionResult
from orchestrator.core.verifier import IndependentVerifier


@pytest.mark.parametrize("xml", [
    '<testsuite tests="1" failures="0"><testcase><failure/></testcase></testsuite>',
    '<testsuite tests="1" errors="0"><testcase><error/></testcase></testsuite>',
    '<testsuite tests="1" skipped="1"><testcase><skipped/></testcase></testsuite>',
    '<testsuite tests="1" failures="no"><testcase/></testsuite>',
    '<testsuite tests="1"/>',
    '<testsuite tests="-1"><testcase/></testsuite>',
    '<testsuite tests="1.0"><testcase/></testsuite>',
    '<testsuite tests="1"><testcase><skipped/><failure/></testcase></testsuite>',
    '<testsuite><testcase><skipped/><skipped/></testcase><testcase/></testsuite>',
    '<testsuite><failure/><testcase/></testsuite>',
    '<other><testsuite><testcase/></testsuite></other>',
    '<testsuite><testcase>',
    '<!DOCTYPE testsuite [<!ENTITY x "x">]><testsuite><testcase/></testsuite>',
    '<?xml version="1.0" encoding="UTF-16"?><testsuite><testcase/></testsuite>',
    '<testsuite>\x00<testcase/></testsuite>',
    '<testsuite>\ud800</testsuite>',
    '',
])
def test_untrusted_reports_fail_closed(xml):
    with pytest.raises(junit.JUnitError):
        junit.parse_junit(xml)
    assert IndependentVerifier.parse_junit_xml(xml)[0] is False


def test_nested_counts_are_not_double_counted():
    xml = ('<testsuites tests="2" skipped="1"><testsuite tests="2" skipped="1">'
           '<testsuite tests="1"><testcase/></testsuite>'
           '<testcase><skipped/></testcase></testsuite></testsuites>')
    passed, _, counts = IndependentVerifier.parse_junit_xml(xml)
    assert passed
    assert counts == {"tests": 2, "failures": 0, "errors": 0, "skipped": 1}


def test_actual_failure_is_not_success_without_aggregate():
    passed, summary, counts = IndependentVerifier.parse_junit_xml(
        '<testsuite><testcase><failure/></testcase></testsuite>')
    assert not passed and "1 failure" in summary
    assert counts["failures"] == 1


@pytest.mark.parametrize("name,limit,xml", [
    ("MAX_JUNIT_BYTES", 20, '<testsuite><testcase/></testsuite>'),
    ("MAX_JUNIT_NODES", 2, '<testsuite><testcase/><testcase/></testsuite>'),
    ("MAX_JUNIT_DEPTH", 2, '<testsuite><testsuite><testcase/></testsuite></testsuite>'),
])
def test_resource_limits(name, limit, xml, monkeypatch):
    monkeypatch.setattr(junit, name, limit)
    with pytest.raises(junit.JUnitError, match="limit exceeded"):
        junit.parse_junit(xml)


def test_utf8_bom_and_exact_byte_boundary(monkeypatch):
    raw = b'\xef\xbb\xbf<testsuite><testcase/></testsuite>'
    monkeypatch.setattr(junit, "MAX_JUNIT_BYTES", len(raw))
    assert junit.parse_junit(raw)["tests"] == 1
    with pytest.raises(junit.JUnitError, match="byte limit"):
        junit.parse_junit(raw + b' ')


def test_missing_collected_path_is_not_deletion_evidence():
    """Characterize a limitation, not endorse complete-diff verification."""
    artifacts = ArtifactCollectionResult({"kept.py": "a" * 64}, 1, "b" * 64)
    baseline = {"kept.py": "a" * 64, "absent.py": "c" * 64}
    changed, digest, compared = IndependentVerifier.compute_diff(artifacts, baseline)
    assert changed == []
    assert digest == hashlib.sha256(b"").hexdigest()
    assert compared is True  # Collected-file comparison only; deletion is not bound.
