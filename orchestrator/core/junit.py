"""Bounded, structural JUnit checks shared by receipt and candidate verification.

Parsing a report does not authenticate its producer or prove tests were executed.
"""

import io
import re
import xml.etree.ElementTree as ET

MAX_JUNIT_BYTES = 10 * 1024 * 1024
MAX_JUNIT_NODES = 100_000
MAX_JUNIT_DEPTH = 64
KEYS = ("tests", "failures", "errors", "skipped")
TAGS = dict(zip(("testcase", "failure", "error", "skipped"), KEYS))


class JUnitError(ValueError):
    """Unusable, inconsistent, or resource-exceeding report."""


def parse_junit(report: str | bytes) -> dict[str, int]:
    """Count actual descendants once; validate every supplied suite aggregate."""
    if len(report) > MAX_JUNIT_BYTES:
        raise JUnitError("JUnit byte limit exceeded")
    try:
        raw = report.encode("utf-8") if isinstance(report, str) else report
        if len(raw) > MAX_JUNIT_BYTES:
            raise JUnitError("JUnit byte limit exceeded")
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise JUnitError("JUnit must be UTF-8") from exc
    if "\x00" in text:
        raise JUnitError("JUnit must be UTF-8 without NUL characters")
    declaration = re.match(r"\s*<\?xml\b[^?]*\?>", text)
    if declaration:
        encoding = re.search(r"\bencoding\s*=\s*(['\"])(.*?)\1",
                             declaration.group(), re.IGNORECASE)
        if encoding and encoding[2].lower() not in ("utf-8", "utf8"):
            raise JUnitError("JUnit encoding declaration must be UTF-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise JUnitError("DTD/entity reports refused")
    stack = []
    nodes = 0
    totals = dict.fromkeys(KEYS, 0)
    try:
        for event, element in ET.iterparse(io.StringIO(text), events=("start", "end")):
            tag = element.tag
            if event == "start":
                nodes += 1
                if nodes > MAX_JUNIT_NODES or len(stack) >= MAX_JUNIT_DEPTH:
                    raise JUnitError("JUnit structure limit exceeded")
                parent = stack[-1][0] if stack else None
                if parent is None and tag not in ("testsuite", "testsuites"):
                    raise JUnitError("Unsupported JUnit root")
                if tag in ("testsuite", "testsuites", "testcase") and parent not in (
                    None, "testsuite", "testsuites"
                ):
                    raise JUnitError("Invalid JUnit hierarchy")
                if tag in ("failure", "error", "skipped") and parent != "testcase":
                    raise JUnitError("Invalid JUnit outcome placement")
                stack.append((tag, dict.fromkeys(KEYS, 0)))
                continue
            _, counts = stack.pop()
            if tag in TAGS:
                counts[TAGS[tag]] += 1
            if tag == "testcase" and (
                counts["skipped"] > 1
                or counts["skipped"] and (counts["failures"] or counts["errors"])
            ):
                raise JUnitError("Conflicting JUnit outcomes")
            if tag in ("testsuite", "testsuites"):
                for key in KEYS:
                    if key not in element.attrib:
                        continue
                    value = element.attrib[key]
                    if not re.fullmatch(r"[0-9]{1,10}", value):
                        raise JUnitError("Invalid JUnit counts")
                    if int(value) != counts[key]:
                        raise JUnitError("JUnit count differs from test cases")
            if stack:
                for key in KEYS:
                    stack[-1][1][key] += counts[key]
            else:
                totals = counts
            element.clear()
    except ET.ParseError as exc:
        raise JUnitError("Incomplete or malformed JUnit") from exc
    if not totals["tests"]:
        raise JUnitError("JUnit XML report collected zero tests")
    if totals["tests"] == totals["skipped"]:
        raise JUnitError("All tests skipped")
    return totals
