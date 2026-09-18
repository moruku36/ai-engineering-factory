"""Independent evidence verification engine for builder task artifacts and candidates.

Generates measured candidate digests from actual collected files, independently validates
test execution outputs, and invalidates review/approval evidence when candidate inputs mutate.
"""

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from orchestrator.core.artifacts import ArtifactCollectionResult


class VerificationError(Exception):
    """Raised when evidence verification fails or evidence was tampered with."""


class EvidenceState(str, Enum):
    VALID = "VALID"
    INVALIDATED = "INVALIDATED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class MeasuredEvidence:
    task_id: str
    base_sha: str
    candidate_digest: str
    changed_paths: list[str]
    diff_digest: str
    test_passed: bool
    test_summary: str
    state: EvidenceState = EvidenceState.VALID
    metadata: dict[str, Any] = field(default_factory=dict)


class IndependentVerifier:
    """Performs independent calculation and validation of task candidate outputs."""

    def __init__(self, worktree_dir: Path | str | None = None):
        self.worktree_dir = Path(worktree_dir).resolve() if worktree_dir else None

    @staticmethod
    def compute_candidate_digest(base_sha: str, diff_digest: str) -> str:
        """Deterministically calculate the measured candidate digest from base SHA and diff digest.

        Returns the full 64-character SHA-256 hex digest (never truncated: a shortened
        hex digest is easy to mistake for a SHA-1 and needlessly weakens collision
        resistance for a value used as an approval-binding identifier).
        """
        hasher = hashlib.sha256()
        hasher.update(base_sha.encode("utf-8"))
        hasher.update(b":")
        hasher.update(diff_digest.encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def compute_diff(
        artifacts: ArtifactCollectionResult,
        base_files: dict[str, str] | None,
    ) -> tuple[list[str], str, bool]:
        """Determine which collected files actually differ from the base tree.

        When base_files (a rel_path -> sha256 map of the base_sha tree, restricted to
        the task's allowed_paths) is supplied, changed_paths is the genuine diff: only
        files whose measured content digest differs from the base. Without it, every
        collected file is reported as "changed" and the diff cannot be independently
        confirmed against the base -- this is a best-effort fallback, not a real diff,
        and is flagged as such via the returned diff_verified flag.
        """
        if base_files is not None:
            changed = sorted(
                path
                for path, digest in artifacts.collected_files.items()
                if base_files.get(path) != digest
            )
            canonical = sorted((path, artifacts.collected_files[path]) for path in changed)
            raw = "\n".join(f"{path}:{digest}" for path, digest in canonical)
            diff_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            return changed, diff_digest, True

        return sorted(artifacts.collected_files.keys()), artifacts.manifest_digest, False

    @staticmethod
    def parse_test_output(output: str, exit_code: int) -> tuple[bool, str]:
        """Legacy string-heuristic fallback for when no structured JUnit XML report exists.

        Prefer passing junit_xml to verify_candidate. This substring match can be
        fooled by log content (e.g. a file merely named 'test_error_handling.py', or
        a builder padding its log with a fabricated summary line) and should not be
        treated as a trustworthy sole gate.
        """
        if exit_code != 0:
            return False, f"Process exited with non-zero exit code {exit_code}"

        if not output or not output.strip():
            return False, "Execution produced no output; cannot independently confirm tests ran"

        out_lower = output.lower()
        if "error" in out_lower or "failed" in out_lower or "traceback" in out_lower:
            # Check if it was purely a summary of 0 failures
            if "0 failed" in out_lower or "0 errors" in out_lower:
                return True, "Tests passed (verified zero failures in summary)"
            return False, "Failure or traceback indicators detected in test log"

        return True, (
            "Execution output verified without error indicators "
            "(heuristic; no JUnit XML report provided)"
        )

    @staticmethod
    def parse_junit_xml(xml_text: str) -> tuple[bool, str, dict[str, int]]:
        """Independently parse a JUnit XML report rather than trusting a builder's claim.

        Fails closed: a missing/unparsable report, or a report with zero collected
        tests, is treated as verification failure rather than silently passing.
        """
        empty_counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        if not xml_text or not xml_text.strip():
            return False, "No JUnit XML report was produced", empty_counts

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            return False, f"JUnit XML report could not be parsed: {exc}", empty_counts

        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if not suites:
            return False, "No <testsuite> elements found in JUnit XML report", empty_counts

        def _count(elem, attr: str) -> int:
            try:
                return int(elem.get(attr, 0) or 0)
            except ValueError:
                return 0

        totals = dict(empty_counts)
        for suite in suites:
            for key in totals:
                totals[key] += _count(suite, key)

        if totals["tests"] == 0:
            return False, "JUnit XML report collected zero tests", totals
        if totals["failures"] or totals["errors"]:
            return False, (
                f"{totals['failures']} failure(s) and {totals['errors']} error(s) "
                f"among {totals['tests']} test(s)"
            ), totals
        return True, f"{totals['tests']} test(s) passed ({totals['skipped']} skipped)", totals

    def verify_candidate(
        self,
        task_id: str,
        base_sha: str,
        artifacts: ArtifactCollectionResult,
        execution_exit_code: int,
        execution_output: str,
        builder_claimed_digest: str | None = None,
        base_files: dict[str, str] | None = None,
        junit_xml: str | None = None,
    ) -> MeasuredEvidence:
        """Independently evaluate execution evidence, rejecting self-reported claims.

        base_files: optional rel_path -> sha256 map of the base_sha tree (restricted
            to the task's allowed_paths). When supplied, changed_paths and the resulting
            candidate_digest are bound to a genuinely measured diff against that base
            rather than to the full set of collected files.
        junit_xml: optional JUnit XML report text. When supplied, test pass/fail is
            determined from independently parsed structured counts instead of a string
            heuristic over raw output.
        """
        if not base_sha or len(base_sha) != 40:
            raise VerificationError("Invalid base SHA: must be 40-character commit SHA")

        changed_paths, diff_digest, diff_verified = self.compute_diff(artifacts, base_files)

        # Independently calculate the candidate digest from the measured diff
        measured_digest = self.compute_candidate_digest(base_sha, diff_digest)

        # Reject if builder claimed a different digest
        if builder_claimed_digest and builder_claimed_digest != measured_digest:
            raise VerificationError(
                f"Builder self-reported candidate digest mismatch: "
                f"reported '{builder_claimed_digest}' vs measured '{measured_digest}'"
            )

        # A non-zero exit always fails, regardless of what any report claims.
        if execution_exit_code != 0:
            raise VerificationError(
                f"Independent test verification failed: "
                f"Process exited with non-zero exit code {execution_exit_code}"
            )

        metadata: dict[str, Any] = {"diff_verified": diff_verified}
        if junit_xml is not None:
            test_passed, test_summary, counts = self.parse_junit_xml(junit_xml)
            metadata["test_counts"] = counts
            metadata["test_report"] = "junit_xml"
        else:
            test_passed, test_summary = self.parse_test_output(execution_output, execution_exit_code)
            metadata["test_report"] = "heuristic"

        if not test_passed:
            raise VerificationError(f"Independent test verification failed: {test_summary}")

        return MeasuredEvidence(
            task_id=task_id,
            base_sha=base_sha,
            candidate_digest=measured_digest,
            changed_paths=changed_paths,
            diff_digest=diff_digest,
            test_passed=test_passed,
            test_summary=test_summary,
            state=EvidenceState.VALID,
            metadata=metadata,
        )

    @staticmethod
    def invalidate_on_mutation(
        prior_evidence: MeasuredEvidence,
        new_base_sha: str,
        new_artifacts: ArtifactCollectionResult,
        base_files: dict[str, str] | None = None,
    ) -> MeasuredEvidence | None:
        """Invalidate prior approval/review evidence if candidate inputs or artifacts mutated."""
        _, new_diff_digest, _ = IndependentVerifier.compute_diff(new_artifacts, base_files)
        new_digest = IndependentVerifier.compute_candidate_digest(new_base_sha, new_diff_digest)
        if new_digest != prior_evidence.candidate_digest or new_base_sha != prior_evidence.base_sha:
            return MeasuredEvidence(
                task_id=prior_evidence.task_id,
                base_sha=new_base_sha,
                candidate_digest=new_digest,
                changed_paths=sorted(new_artifacts.collected_files.keys()),
                diff_digest=new_diff_digest,
                test_passed=False,
                test_summary="Invalidated due to candidate mutation",
                state=EvidenceState.INVALIDATED,
            )
        return None
