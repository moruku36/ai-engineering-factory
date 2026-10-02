"""Offline, bounded receipt checks for manifest v0.1; never grants VERIFIED/COMPLETE."""

import hashlib
import json
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_OUTPUTS = 100
SHA256 = re.compile(r"[0-9a-f]{64}")
SHA1 = re.compile(r"[0-9a-f]{40}")
STATES = {
    "PLANNED", "ACCEPTED", "RUNNING", "EXECUTED", "COLLECTED", "VERIFIED", "COMPLETE",
    "BLOCKED_CAPABILITY", "WAITING_APPROVAL", "FAILED", "CANCELLED", "CANCEL_REQUESTED",
    "UNKNOWN", "RECONCILING",
}
PROTECTED = {".git", ".env", "id_rsa", "id_ed25519", "operator.key"}
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
}


class HandoffError(ValueError):
    """Missing, mismatched or unsupported receipt evidence; fail closed."""


def _require(condition, message):
    if not condition:
        raise HandoffError(message)


def _text(value, label):
    _require(isinstance(value, str) and bool(value.strip()), f"Missing {label}")


def _hash(value, label):
    _require(isinstance(value, str) and SHA256.fullmatch(value), f"Invalid {label}")


def _object(value, label):
    _require(isinstance(value, dict), f"Invalid {label}")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(raw):
    """Reject duplicate keys, nonfinite numbers, invalid encoding and oversized JSON."""
    _require(len(raw) <= MAX_MANIFEST_BYTES, "JSON exceeds size limit")
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=lambda value: _require(False, f"Invalid JSON constant: {value}"),
        )
    except HandoffError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HandoffError("Invalid JSON") from exc


def _safe_path(value):
    _text(value, "output path")
    parts = value.split("/")
    _require(all(part not in ("", ".", "..") for part in parts), "Invalid relative path")
    for part in parts:
        _require(
            not any(ord(char) < 32 or char in '\\:*?"<>|' for char in part)
            and not part.endswith((".", " "))
            and part.upper().split(".")[0] not in RESERVED
            and part.lower() not in PROTECTED
            and not part.lower().startswith(".git"),
            "Unsafe or protected output path",
        )
    _require(value.lower() != "manifest.json", "Manifest cannot be its own output")
    return parts


def _reject_link(path):
    """lstat reparse attributes are available on Windows Python 3.11 too."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return  # Required byte retrieval below still rejects missing paths.
    except OSError as exc:
        raise HandoffError("Cannot inspect packet path") from exc
    _require(not stat.S_ISLNK(info.st_mode), "Symlink refused")
    _require(not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
             "Windows reparse point refused")


def _read_file(root, relative, limit, *, optional=False):
    """Check every component; this offline tool requires a quiescent receiver directory."""
    parts = relative.split("/")
    current = root
    for part in parts:
        current = current / part
        _reject_link(current)
    try:
        _require(current.resolve().is_relative_to(root), "Path escapes packet")
        if optional and not current.exists():
            return None  # Every component was inspected before accepting optional absence.
        _require(stat.S_ISREG(current.stat().st_mode), "Output must be a regular file")
        with current.open("rb") as stream:
            raw = stream.read(limit + 1)
        _require(len(raw) <= limit, "File exceeds size limit")
        return raw
    except OSError as exc:
        raise HandoffError(f"Cannot retrieve required bytes: {relative}") from exc


def validate_manifest(manifest):
    """Validate the fixed inventory and source/evidence bindings, not semantic quality."""
    _object(manifest, "manifest")
    _require(manifest.get("schema_version") == "0.1", "Unsupported schema_version")
    for field in ("run_id", "attempt_id", "purpose", "producer", "next_step"):
        _text(manifest.get(field), field)
    _require(manifest.get("parent_run_id") is None or isinstance(
        manifest["parent_run_id"], str), "Invalid parent_run_id")
    _hash(manifest.get("request_sha256"), "request_sha256")
    _require(isinstance(manifest.get("declared_status"), str)
             and manifest["declared_status"] in STATES, "Invalid declared_status")
    _require(isinstance(manifest.get("acceptance_criteria"), list)
             and bool(manifest["acceptance_criteria"]), "Missing acceptance criteria")
    for criterion in manifest["acceptance_criteria"]:
        _text(criterion, "acceptance criterion")

    source = _object(manifest.get("source"), "source")
    _text(source.get("repository"), "repository")
    commit = source.get("commit_sha")
    _require(commit == "unknown" or isinstance(commit, str) and SHA1.fullmatch(commit),
             "Source commit must be full SHA or unknown")
    _hash(source.get("snapshot_sha256"), "source snapshot")
    _require(type(source.get("dirty")) is bool, "Invalid dirty flag")
    _require(type(source.get("complete_diff_required")) is bool, "Missing diff requirement")
    base = source.get("base_sha")
    _require(base == "unknown" or isinstance(base, str) and SHA1.fullmatch(base),
             "Base must be full SHA or unknown")
    if source["complete_diff_required"]:
        _require(base != "unknown", "BLOCKED_CAPABILITY: complete diff requires known base")
        # v0.1 is a byte handoff, not a full Git tree/mode verifier.
        raise HandoffError("BLOCKED_CAPABILITY: complete diff verification is unsupported")

    _object(manifest.get("environment"), "environment")
    for field in ("kind", "os", "tool_versions", "requested", "observed"):
        _require(field in manifest["environment"], f"Missing environment {field}")
    for identity in ("requested", "observed"):
        value = _object(manifest["environment"][identity], identity)
        for field in ("model", "effort"):
            _text(value.get(field), f"{identity} {field}; use unknown if unobserved")
    execution = _object(manifest.get("execution"), "execution")
    for field in ("accepted_at", "started_at", "ended_at", "exit_code"):
        _require(field in execution, f"Missing execution {field}")
    _require(execution["exit_code"] is None or type(execution["exit_code"]) is int,
             "Invalid exit_code")
    _require(isinstance(manifest.get("inputs"), list), "Missing inputs")
    for item in manifest["inputs"]:
        _object(item, "input")
        _text(item.get("id"), "input id")
        _hash(item.get("sha256"), "input sha256")
        _require(type(item.get("size_bytes")) is int and item["size_bytes"] >= 0,
                 "Invalid input size")
    _object(manifest.get("limits_and_authority"), "limits_and_authority")

    outputs = manifest.get("outputs")
    _require(isinstance(outputs, list) and 0 < len(outputs) <= MAX_OUTPUTS,
             "Output inventory must contain 1..100 files")
    paths = set()
    total = 0
    for item in outputs:
        _object(item, "output")
        parts = _safe_path(item.get("path"))
        key = "/".join(parts).casefold()
        _require(key not in paths, "Duplicate output path")
        _require(not any(key.startswith(p + "/") or p.startswith(key + "/") for p in paths),
                 "Conflicting output paths")
        paths.add(key)
        _require(type(item.get("required")) is bool, "Missing required flag")
        for field in ("purpose", "producer", "retrieved_at"):
            _text(item.get(field), field)
        _hash(item.get("sha256"), "output sha256")
        _require(type(item.get("size_bytes")) is int
                 and 0 <= item["size_bytes"] <= MAX_FILE_BYTES, "Invalid output size")
        total += item["size_bytes"]
        storage = _object(item.get("storage"), "storage")
        for field in ("id", "version"):
            _text(storage.get(field), f"storage {field}")
    _require(any(item["required"] for item in outputs), "At least one required output is needed")
    _require(total <= MAX_TOTAL_BYTES, "Inventory exceeds total size limit")

    tests = _object(manifest.get("tests"), "tests")
    _require(type(tests.get("required")) is bool, "Missing test requirement")
    if tests["required"]:
        _text(tests.get("command"), "test command")
        _text(tests.get("tool_version"), "test tool_version")
        _require(tests.get("target_sha256") == source["snapshot_sha256"],
                 "Tests target a different snapshot")
        report = next((item for item in outputs if item["path"] == tests.get("report_path")), None)
        _require(report is not None and report["required"], "Required report not in inventory")
    reviews = manifest.get("reviews")
    _require(isinstance(reviews, list), "Missing reviews")
    for review in reviews:
        _object(review, "review")
        _text(review.get("reviewer"), "reviewer")
        _require(review.get("target_sha256") == source["snapshot_sha256"],
                 "Review targets a different snapshot")
        _text(review.get("verdict"), "review verdict")
        _require(isinstance(review.get("findings"), list), "Missing review findings")
    return manifest


def collect_receipt(packet_dir, trust):
    """Measure receiver bytes against out-of-band pins; highest state is COLLECTED.

    trust must originate from the coordinator's separate approved record. Caller
    authentication, test execution and independent review are outside this function.
    """
    _object(trust, "trusted record")
    _hash(trust.get("manifest_sha256"), "trusted manifest hash")
    for field in ("run_id", "attempt_id"):
        _text(trust.get(field), f"trusted {field}")
    versions = _object(trust.get("output_versions"), "trusted output versions")
    root = Path(packet_dir)
    _reject_link(root)
    root = root.resolve()
    raw = _read_file(root, "manifest.json", MAX_MANIFEST_BYTES)
    _require(hashlib.sha256(raw).hexdigest() == trust["manifest_sha256"],
             "Manifest differs from separately trusted hash")
    manifest = validate_manifest(load_json(raw))
    for field in ("run_id", "attempt_id"):
        _require(manifest[field] == trust[field], f"Wrong {field}")
    _require(set(versions) == {item["path"] for item in manifest["outputs"]},
             "Trusted inventory differs")
    received = []
    measured_bytes = {}
    for item in manifest["outputs"]:
        _require(versions[item["path"]] == item["storage"]["version"], "Wrong output version")
        content = _read_file(root, item["path"], MAX_FILE_BYTES, optional=not item["required"])
        if content is None:
            continue
        _require(len(content) == item["size_bytes"], "Output size differs")
        digest = hashlib.sha256(content).hexdigest()
        _require(digest == item["sha256"], "Output hash differs")
        measured_bytes[item["path"]] = content
        received.append({"path": item["path"], "size_bytes": len(content), "sha256": digest,
                         "version": item["storage"]["version"]})
    tests = manifest["tests"]
    if tests["required"]:
        report = measured_bytes[tests["report_path"]]
        try:
            text = report.decode("utf-8-sig")
        except UnicodeError as exc:
            raise HandoffError("JUnit must be UTF-8") from exc
        _require("\x00" not in text, "JUnit must be UTF-8 without NUL characters")
        declaration = re.match(r"\s*<\?xml\b[^?]*\?>", text)
        if declaration:
            encoding = re.search(r"\bencoding\s*=\s*(['\"])(.*?)\1",
                                 declaration.group(), re.IGNORECASE)
            _require(encoding is None or encoding[2].lower() in ("utf-8", "utf8"),
                     "JUnit encoding declaration must be UTF-8")
        _require("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(),
                 "DTD/entity reports refused")
        try:
            tree = ET.fromstring(text)
        except ET.ParseError as exc:
            raise HandoffError("Incomplete or malformed JUnit") from exc
        _require(tree.tag in ("testsuite", "testsuites"), "Unsupported JUnit root")
        cases = list(tree.iter("testcase"))
        _require(bool(cases), "JUnit contains zero test cases")
        _require(any(case.find("skipped") is None for case in cases), "All tests skipped")
        _require(not list(tree.iter("failure")) and not list(tree.iter("error")),
                 "JUnit reports failure/error")
        for suite in tree.iter():
            if suite.tag in ("testsuite", "testsuites"):
                for attr in ("tests", "failures", "errors", "skipped"):
                    if attr in suite.attrib:
                        value = suite.attrib[attr]
                        _require(value.isdecimal(), "Invalid JUnit counts")
                        tag = {"tests": "testcase", "failures": "failure",
                               "errors": "error", "skipped": "skipped"}[attr]
                        expected = len(list(suite.iter(tag)))
                        try:
                            count = int(value)
                        except (ValueError, OverflowError) as exc:
                            raise HandoffError("Invalid JUnit counts") from exc
                        _require(count == expected, "JUnit count differs from test cases")
                        if attr in ("failures", "errors"):
                            _require(count == 0, "JUnit reports failure/error")
    return {
        "schema_version": "0.1", "run_id": manifest["run_id"],
        "attempt_id": manifest["attempt_id"], "status": "COLLECTED",
        "declared_status": manifest["declared_status"],
        "manifest_sha256": trust["manifest_sha256"], "outputs": received,
        "missing_optional": [item["path"] for item in manifest["outputs"]
                             if item["path"] not in measured_bytes],
        "next_step": manifest["next_step"],
        "verification": "unknown: independent acceptance tests/review not executed by receipt tool",
    }
