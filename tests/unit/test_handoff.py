"""Anonymous CPU fixtures runnable with unittest as well as the repository pytest suite."""

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.core.handoff import HandoffError, collect_receipt, load_json, validate_manifest
from orchestrator.handoff import main, publish_receipt


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture_manifest():
    content = b"Synthetic request: clarify deadline; no commitment made.\n"
    report = b'<testsuite tests="1"><testcase name="anonymous_fixture"/></testsuite>'
    outputs = []
    for path, raw in (("clarification.txt", content), ("report.xml", report)):
        outputs.append({
            "path": path, "purpose": "anonymous fixture", "required": True,
            "size_bytes": len(raw), "sha256": digest(raw), "producer": "fixture-builder",
            "retrieved_at": "2026-10-02T00:00:00Z",
            "storage": {"id": "private-fixture-record", "version": "1"},
        })
    snapshot = digest(content)
    return {
        "schema_version": "0.1", "run_id": "synthetic-mail-001", "attempt_id": "attempt-1",
        "parent_run_id": None, "purpose": "Offline synthetic clarification packet",
        "producer": "fixture-builder", "request_sha256": digest(b"fixture request"),
        "acceptance_criteria": ["Unanswered deadline stays unknown"],
        "declared_status": "EXECUTED", "next_step": "Owner reviews unanswered deadline",
        "source": {"repository": "anonymous-fixture", "commit_sha": "unknown",
                   "snapshot_sha256": snapshot, "base_sha": "unknown", "dirty": True,
                   "complete_diff_required": False},
        "inputs": [{"id": "synthetic-mail", "size_bytes": len(content), "sha256": snapshot}],
        "environment": {"kind": "local-cpu-fixture", "os": "unknown", "tool_versions": {},
                        "requested": {"model": "session-default", "effort": "session-default"},
                        "observed": {"model": "unknown", "effort": "unknown"}},
        "execution": {"accepted_at": None, "started_at": None, "ended_at": None,
                      "exit_code": None},
        "limits_and_authority": {"cost_cap": 0, "operations": ["local fixture receipt"]},
        "outputs": outputs,
        "tests": {"required": True, "command": "anonymous fixture, not live execution",
                  "tool_version": "fixture-v1", "target_sha256": snapshot,
                  "report_path": "report.xml"},
        "reviews": [{"reviewer": "fixture-reviewer", "target_sha256": snapshot,
                     "verdict": "unknown", "findings": []}],
    }, {"clarification.txt": content, "report.xml": report}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.packet = self.root / "receiver"
        self.packet.mkdir()
        self.manifest, self.contents = fixture_manifest()
        self.trust = self.write_packet()

    def write_packet(self, repin=True):
        raw = json.dumps(self.manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        (self.packet / "manifest.json").write_bytes(raw)
        for path, content in self.contents.items():
            (self.packet / path).write_bytes(content)
        trust = {"manifest_sha256": digest(raw), "run_id": self.manifest["run_id"],
                 "attempt_id": self.manifest["attempt_id"],
                 "output_versions": {item["path"]: item["storage"]["version"]
                                     for item in self.manifest["outputs"]}}
        if repin:
            self.trust = trust
        return trust

    def collect(self):
        return collect_receipt(self.packet, self.trust)

    def test_receiver_copy_and_resume_receipt(self):
        # A separate receiver directory and only pinned record/bytes suffice.
        receipt = self.collect()
        self.assertEqual(receipt["status"], "COLLECTED")
        self.assertEqual(len(receipt["outputs"]), 2)
        self.assertEqual(receipt["run_id"], self.trust["run_id"])
        self.assertIn("unknown", receipt["verification"])
        self.assertEqual(receipt["next_step"], self.manifest["next_step"])

    def test_missing_truncated_and_same_size_tampered_output(self):
        path = self.packet / "clarification.txt"
        original = path.read_bytes()
        for mutation in (None, original[:-1], b"X" + original[1:]):
            with self.subTest(mutation=mutation):
                if mutation is None:
                    path.unlink()
                else:
                    path.write_bytes(mutation)
                with self.assertRaises(HandoffError):
                    self.collect()
                path.write_bytes(original)

    def test_entire_packet_replacement_does_not_replace_external_pin(self):
        self.manifest["run_id"] = "other-run"
        self.contents["clarification.txt"] = b"replacement"
        self.manifest["outputs"][0].update(size_bytes=11, sha256=digest(b"replacement"))
        self.write_packet(repin=False)
        with self.assertRaisesRegex(HandoffError, "trusted hash"):
            self.collect()

    def test_run_attempt_and_version_mismatch(self):
        for field in ("run_id", "attempt_id"):
            with self.subTest(field=field):
                trust = copy.deepcopy(self.trust)
                trust[field] = "different"
                with self.assertRaisesRegex(HandoffError, "Wrong"):
                    collect_receipt(self.packet, trust)
        self.trust["output_versions"]["clarification.txt"] = "2"
        with self.assertRaisesRegex(HandoffError, "version"):
            self.collect()

    def test_declared_success_acceptance_cancellation_and_crash_never_verify(self):
        for state in ("ACCEPTED", "EXECUTED", "VERIFIED", "COMPLETE", "CANCEL_REQUESTED",
                      "UNKNOWN", "RECONCILING", "CANCELLED"):
            with self.subTest(state=state):
                self.manifest["declared_status"] = state
                self.manifest["execution"]["exit_code"] = 0
                self.write_packet()
                receipt = self.collect()
                self.assertEqual(receipt["status"], "COLLECTED")
                self.assertEqual(receipt["declared_status"], state)
        # Receipt measures bytes only; cancellation/process reconciliation is external.

    def test_required_junit_missing_zero_malformed_failures_and_skips(self):
        reports = (
            b'<testsuite tests="0"/>', b'<testsuite tests="1">',
            b'<testsuite tests="1"><testcase><failure/></testcase></testsuite>',
            b'<testsuite tests="1"><testcase><error/></testcase></testsuite>',
            b'<testsuite tests="1"><testcase><skipped/></testcase></testsuite>',
            b'<testsuite tests="2"><testcase/></testsuite>',
            b'<testsuite errors="1"><testcase/></testsuite>',
            b'<testsuite skipped="1"><testcase/></testsuite>',
            b'<!DOCTYPE testsuite [<!ENTITY x "x">]><testsuite><testcase/></testsuite>',
        )
        (self.packet / "report.xml").unlink()
        with self.assertRaises(HandoffError):
            self.collect()
        for report in reports:
            with self.subTest(report=report):
                self.contents["report.xml"] = report
                self.manifest["outputs"][1].update(size_bytes=len(report), sha256=digest(report))
                self.write_packet()
                with self.assertRaises(HandoffError):
                    self.collect()

    def test_invalid_paths_and_duplicate_inventory(self):
        for path in ("../escape", "/absolute", "a\\b", "C:/file", "a//b", ".env",
                     ".git/config", "NUL.txt", "x:stream", "x.", "manifest.json"):
            with self.subTest(path=path):
                manifest = copy.deepcopy(self.manifest)
                manifest["outputs"][0]["path"] = path
                with self.assertRaises(HandoffError):
                    validate_manifest(manifest)
        self.manifest["outputs"][1]["path"] = "CLARIFICATION.TXT"
        with self.assertRaisesRegex(HandoffError, "Duplicate"):
            validate_manifest(self.manifest)

    def test_symlink_and_linked_parent_rejected(self):
        path = self.packet / "clarification.txt"
        path.unlink()
        outside = self.root / "outside.txt"
        outside.write_bytes(self.contents["clarification.txt"])
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("Host does not permit symlink creation")
        with self.assertRaisesRegex(HandoffError, "Symlink"):
            self.collect()
        path.unlink()
        directory = self.packet / "linked"
        directory.symlink_to(self.root, target_is_directory=True)
        self.manifest["outputs"][0]["path"] = "linked/outside.txt"
        self.contents.pop("clarification.txt")
        self.write_packet()
        with self.assertRaisesRegex(HandoffError, "Symlink"):
            self.collect()

    def test_unknown_base_and_full_diff_never_pass_as_complete(self):
        self.manifest["source"]["complete_diff_required"] = True
        with self.assertRaisesRegex(HandoffError, "known base"):
            validate_manifest(self.manifest)
        self.manifest["source"]["base_sha"] = "a" * 40
        with self.assertRaisesRegex(HandoffError, "unsupported"):
            validate_manifest(self.manifest)

    def test_tests_and_review_must_bind_to_fixed_snapshot(self):
        for field in ("tests", "reviews"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                entry = manifest[field] if field == "tests" else manifest[field][0]
                entry["target_sha256"] = "b" * 64
                with self.assertRaisesRegex(HandoffError, "different snapshot"):
                    validate_manifest(manifest)

    def test_optional_missing_and_unlisted_files_are_not_received(self):
        self.manifest["outputs"][0]["required"] = False
        self.write_packet()
        (self.packet / "clarification.txt").unlink()
        (self.packet / "unlisted-raw-log.txt").write_text("not allowlisted")
        receipt = self.collect()
        self.assertEqual(receipt["missing_optional"], ["clarification.txt"])
        self.assertEqual([item["path"] for item in receipt["outputs"]], ["report.xml"])

    def test_malformed_json_duplicate_keys_and_size_limits(self):
        for raw in (b'{"run_id":1,"run_id":2}', b'{"x":NaN}', b'\xff', b'{'):
            with self.subTest(raw=raw):
                (self.packet / "manifest.json").write_bytes(raw)
                self.trust["manifest_sha256"] = digest(raw)
                with self.assertRaises(HandoffError):
                    self.collect()
        self.manifest["outputs"][0]["size_bytes"] = True
        with self.assertRaises(HandoffError):
            validate_manifest(self.manifest)

    def test_untrusted_status_type_and_oversize_manifest_fail_closed(self):
        for state in ([], {}, None, True):
            with self.subTest(state=state):
                manifest = copy.deepcopy(self.manifest)
                manifest["declared_status"] = state
                with self.assertRaises(HandoffError):
                    validate_manifest(manifest)
        raw = b" " * (1024 * 1024 + 1)
        (self.packet / "manifest.json").write_bytes(raw)
        self.trust["manifest_sha256"] = digest(raw)
        with self.assertRaisesRegex(HandoffError, "size limit"):
            self.collect()

    def test_cli_exclusive_receipt_and_external_trust(self):
        trust_path = self.root / "trusted.json"
        trust_path.write_text(json.dumps(self.trust), encoding="utf-8")
        receipt_path = self.root / "receipt.json"
        args = ["--packet", str(self.packet), "--trust", str(trust_path),
                "--receipt", str(receipt_path)]
        with patch("sys.stdout"), patch("sys.stderr"):
            self.assertEqual(main(args), 0)
            original = receipt_path.read_bytes()
            self.assertEqual(main(args), 2)
            self.assertEqual(receipt_path.read_bytes(), original)
            nested_trust = self.packet / "trust.json"
            nested_trust.write_bytes(trust_path.read_bytes())
            args[3] = str(nested_trust)
            self.assertEqual(main(args), 2)

    def test_missing_bytes_cannot_create_success_receipt(self):
        trust_path = self.root / "trusted.json"
        trust_path.write_text(json.dumps(self.trust), encoding="utf-8")
        receipt_path = self.root / "receipt.json"
        (self.packet / "report.xml").unlink()
        with patch("sys.stderr"):
            self.assertEqual(main(["--packet", str(self.packet), "--trust", str(trust_path),
                                   "--receipt", str(receipt_path)]), 2)
        self.assertFalse(receipt_path.exists())

    def test_utf16_junit_declarations_rejected_before_xml_parser(self):
        xml = ('<?xml version="1.0" encoding="UTF-16"?>'
               '<!DOCTYPE testsuite [<!ENTITY unsafe "payload">]>'
               '<testsuite tests="1"><testcase name="&unsafe;"/></testsuite>')
        for encoding in ("utf-16", "utf-16-le", "utf-16-be", "utf-32-le"):
            with self.subTest(encoding=encoding):
                report = xml.encode(encoding)
                self.contents["report.xml"] = report
                self.manifest["outputs"][1].update(size_bytes=len(report), sha256=digest(report))
                self.write_packet()
                with patch("orchestrator.core.handoff.ET.fromstring") as parser:
                    with self.assertRaisesRegex(HandoffError, "UTF-8"):
                        self.collect()
                    parser.assert_not_called()

    def test_junit_utf8_bom_allowed_and_other_declared_encoding_rejected(self):
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<testsuite tests="1"><testcase name="匿名"/></testsuite>')
        report = xml.encode("utf-8-sig")
        self.contents["report.xml"] = report
        self.manifest["outputs"][1].update(size_bytes=len(report), sha256=digest(report))
        self.write_packet()
        self.assertEqual(self.collect()["status"], "COLLECTED")
        report = xml.replace("UTF-8", "ISO-8859-1").encode("utf-8")
        self.contents["report.xml"] = report
        self.manifest["outputs"][1].update(size_bytes=len(report), sha256=digest(report))
        self.write_packet()
        with self.assertRaisesRegex(HandoffError, "encoding declaration"):
            self.collect()

    def test_lone_surrogate_cannot_leave_receipt_stub(self):
        self.manifest["next_step"] = "invalid \ud800"
        raw = json.dumps(self.manifest, ensure_ascii=True).encode("utf-8")
        (self.packet / "manifest.json").write_bytes(raw)
        self.trust["manifest_sha256"] = digest(raw)
        trust_path = self.root / "trusted.json"
        trust_path.write_text(json.dumps(self.trust), encoding="utf-8")
        receipt_path = self.root / "invalid-receipt.json"
        with patch("sys.stderr"):
            self.assertEqual(main(["--packet", str(self.packet), "--trust", str(trust_path),
                                   "--receipt", str(receipt_path)]), 2)
        self.assertFalse(receipt_path.exists())
        self.assertEqual(list(self.root.glob(".receipt-*.tmp")), [])

    def test_interrupted_temporary_write_cannot_leave_final_stub(self):
        real_fdopen = os.fdopen
        receipt_path = self.root / "interrupted-receipt.json"
        for interruption in (InterruptedError, KeyboardInterrupt):
            with self.subTest(interruption=interruption):
                class InterruptedStream:
                    def __init__(self, descriptor, mode):
                        self.stream = real_fdopen(descriptor, mode)

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        self.stream.close()

                    def write(self, content):
                        self.stream.write(content[:5])
                        self.stream.flush()
                        raise interruption()

                with patch("orchestrator.handoff.os.fdopen", InterruptedStream):
                    with self.assertRaises(interruption):
                        publish_receipt(receipt_path, {"run_id": "fixture"})
                self.assertFalse(receipt_path.exists())
                self.assertEqual(list(self.root.glob(".receipt-*.tmp")), [])

    def test_concurrent_existing_receipt_is_preserved_at_publication(self):
        receipt_path = self.root / "concurrent-receipt.json"
        real_link = os.link

        def race(source, destination):
            receipt_path.write_bytes(b"previous receiver evidence")
            real_link(source, destination)

        with patch("orchestrator.handoff.os.link", side_effect=race):
            with self.assertRaises(FileExistsError):
                publish_receipt(receipt_path, {"run_id": "new fixture"})
        self.assertEqual(receipt_path.read_bytes(), b"previous receiver evidence")
        self.assertEqual(list(self.root.glob(".receipt-*.tmp")), [])

    def test_large_json_integer_has_controlled_error(self):
        previous = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(4300)
            raw = b'{"number":' + b"1" * 5000 + b"}"
            with self.assertRaises(HandoffError):
                load_json(raw)
            (self.packet / "manifest.json").write_bytes(raw)
            self.trust["manifest_sha256"] = digest(raw)
            with self.assertRaises(HandoffError):
                self.collect()
        finally:
            sys.set_int_max_str_digits(previous)

    def test_large_junit_count_has_controlled_error(self):
        previous = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(4300)
            report = b'<testsuite tests="' + b"1" * 5000 + b'"><testcase/></testsuite>'
            self.contents["report.xml"] = report
            self.manifest["outputs"][1].update(size_bytes=len(report), sha256=digest(report))
            self.write_packet()
            with self.assertRaisesRegex(HandoffError, "Invalid JUnit counts"):
                self.collect()
        finally:
            sys.set_int_max_str_digits(previous)

    def test_cleanup_failure_does_not_misreport_published_receipt(self):
        trust_path = self.root / "trusted.json"
        trust_path.write_text(json.dumps(self.trust), encoding="utf-8")
        receipt_path = self.root / "cleanup-receipt.json"
        with patch.object(Path, "unlink", side_effect=PermissionError("cleanup refused")):
            with patch("sys.stdout"):
                self.assertEqual(main(["--packet", str(self.packet), "--trust", str(trust_path),
                                       "--receipt", str(receipt_path)]), 0)
        self.assertEqual(json.loads(receipt_path.read_bytes())["status"], "COLLECTED")
        self.assertEqual(len(list(self.root.glob(".receipt-*.tmp"))), 1)

    def test_cleanup_failure_does_not_mask_original_publication_failure(self):
        receipt_path = self.root / "previous-receipt.json"
        receipt_path.write_bytes(b"previous evidence")
        with patch.object(Path, "unlink", side_effect=PermissionError("cleanup refused")):
            with self.assertRaises(FileExistsError):
                publish_receipt(receipt_path, {"run_id": "new fixture"})
        self.assertEqual(receipt_path.read_bytes(), b"previous evidence")
        self.assertEqual(len(list(self.root.glob(".receipt-*.tmp"))), 1)

    def test_optional_missing_under_marked_reparse_parent_rejected(self):
        self.manifest["outputs"][0].update(path="marked/absent.txt", required=False)
        self.write_packet()
        real_lstat = Path.lstat

        def marked_lstat(path):
            if path == self.packet / "marked":
                return SimpleNamespace(st_mode=stat.S_IFDIR,
                                       st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return real_lstat(path)

        with patch.object(Path, "lstat", marked_lstat):
            with self.assertRaisesRegex(HandoffError, "reparse point"):
                self.collect()

    @unittest.skipUnless(os.name == "nt", "Windows dangling junction fixture")
    def test_optional_missing_under_real_dangling_junction_rejected(self):
        target = self.root / "absent-junction-target"
        target.mkdir()
        link = self.packet / "dangling-junction"
        result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(link.rmdir)
        target.rmdir()  # Only this empty fixture directory, leaving a dangling junction.
        self.manifest["outputs"][0].update(path="dangling-junction/absent.txt", required=False)
        self.write_packet()
        with self.assertRaisesRegex(HandoffError, "reparse point"):
            self.collect()

    def test_windows_reparse_attribute_without_path_is_junction(self):
        real_lstat = Path.lstat
        for flagged_path in (self.packet, self.packet / "clarification.txt"):
            with self.subTest(path=flagged_path):
                def marked_lstat(path):
                    if path == flagged_path:
                        return SimpleNamespace(st_mode=stat.S_IFDIR,
                                               st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    return real_lstat(path)

                with patch.object(Path, "is_junction", None, create=True):
                    with patch.object(Path, "lstat", marked_lstat):
                        with self.assertRaisesRegex(HandoffError, "reparse point"):
                            self.collect()

    @unittest.skipUnless(os.name == "nt", "Windows junction fixture")
    def test_real_windows_junction_rejected(self):
        target = self.root / "junction-target"
        target.mkdir()
        (target / "outside.txt").write_bytes(self.contents["clarification.txt"])
        link = self.packet / "junction"
        result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Remove only the junction entry before TemporaryDirectory's recursive cleanup.
        self.addCleanup(link.rmdir)
        self.manifest["outputs"][0]["path"] = "junction/outside.txt"
        self.write_packet()
        with self.assertRaisesRegex(HandoffError, "reparse point"):
            self.collect()


if __name__ == "__main__":
    unittest.main()
