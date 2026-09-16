"""Independent evidence verification engine for builder task artifacts and candidates.

Generates measured candidate digests from actual collected files, independently validates
test execution outputs, and invalidates review/approval evidence when candidate inputs mutate.
"""

import hashlib
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
    candidate_sha: str
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
    def compute_candidate_digest(
        base_sha: str,
        artifacts: ArtifactCollectionResult,
    ) -> str:
        """Deterministically calculate measured candidate SHA from base SHA and artifact manifest."""
        hasher = hashlib.sha256()
        hasher.update(base_sha.encode("utf-8"))
        hasher.update(b":")
        hasher.update(artifacts.manifest_digest.encode("utf-8"))
        return hasher.hexdigest()[:40]

    @staticmethod
    def parse_test_output(output: str, exit_code: int) -> tuple[bool, str]:
        """Independently parse test results from raw execution output rather than builder claim."""
        if exit_code != 0:
            return False, f"Process exited with non-zero exit code {exit_code}"

        out_lower = output.lower()
        if "error" in out_lower or "failed" in out_lower or "traceback" in out_lower:
            # Check if it was purely a summary of 0 failures
            if "0 failed" in out_lower or "0 errors" in out_lower:
                return True, "Tests passed (verified zero failures in summary)"
            return False, "Failure or traceback indicators detected in test log"

        return True, "Execution output verified without error indicators"

    def verify_candidate(
        self,
        task_id: str,
        base_sha: str,
        artifacts: ArtifactCollectionResult,
        execution_exit_code: int,
        execution_output: str,
        builder_claimed_sha: str | None = None,
    ) -> MeasuredEvidence:
        """Independently evaluate execution evidence, rejecting self-reported claims."""
        if not base_sha or len(base_sha) != 40:
            raise VerificationError("Invalid base SHA: must be 40-character commit SHA")

        # Independently calculate candidate SHA
        measured_sha = self.compute_candidate_digest(base_sha, artifacts)

        # Reject if builder claimed a different SHA
        if builder_claimed_sha and builder_claimed_sha != measured_sha:
            raise VerificationError(
                f"Builder self-reported candidate SHA mismatch: "
                f"reported '{builder_claimed_sha}' vs measured '{measured_sha}'"
            )

        # Independently verify test output
        test_passed, test_summary = self.parse_test_output(execution_output, execution_exit_code)
        if not test_passed:
            raise VerificationError(f"Independent test verification failed: {test_summary}")

        changed_paths = sorted(artifacts.collected_files.keys())
        diff_digest = artifacts.manifest_digest

        return MeasuredEvidence(
            task_id=task_id,
            base_sha=base_sha,
            candidate_sha=measured_sha,
            changed_paths=changed_paths,
            diff_digest=diff_digest,
            test_passed=test_passed,
            test_summary=test_summary,
            state=EvidenceState.VALID,
        )

    @staticmethod
    def invalidate_on_mutation(
        prior_evidence: MeasuredEvidence,
        new_base_sha: str,
        new_artifacts: ArtifactCollectionResult,
    ) -> MeasuredEvidence | None:
        """Invalidate prior approval/review evidence if candidate inputs or artifacts mutated."""
        new_sha = IndependentVerifier.compute_candidate_digest(new_base_sha, new_artifacts)
        if new_sha != prior_evidence.candidate_sha or new_base_sha != prior_evidence.base_sha:
            return MeasuredEvidence(
                task_id=prior_evidence.task_id,
                base_sha=new_base_sha,
                candidate_sha=new_sha,
                changed_paths=sorted(new_artifacts.collected_files.keys()),
                diff_digest=new_artifacts.manifest_digest,
                test_passed=False,
                test_summary="Invalidated due to candidate mutation",
                state=EvidenceState.INVALIDATED,
            )
        return None
