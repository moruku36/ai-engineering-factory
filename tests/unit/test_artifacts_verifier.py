"""Tests for artifact collection bounds and independent candidate verification."""

import pytest

from orchestrator.core.artifacts import (
    ArtifactCollector,
    ArtifactExtractionError,
)
from orchestrator.core.verifier import (
    EvidenceState,
    IndependentVerifier,
    VerificationError,
)


def test_artifact_collection_happy_path(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hello')", encoding="utf-8")
    (src / "nested").mkdir()
    (src / "nested" / "config.json").write_text('{"key": "val"}', encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector(allowed_paths=["app.py", "nested/config.json"])
    result = collector.collect(src, dst)

    assert "app.py" in result.collected_files
    assert "nested/config.json" in result.collected_files
    assert (dst / "app.py").exists()
    assert (dst / "nested" / "config.json").exists()
    assert result.total_bytes > 0
    assert len(result.manifest_digest) == 64


def test_artifact_collection_symlink_rejected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    real_file = tmp_path / "real.txt"
    real_file.write_text("secret", encoding="utf-8")

    sym = src / "link.txt"
    try:
        sym.symlink_to(real_file)
    except OSError:
        pytest.skip("Symlink creation not permitted in this test environment")

    dst = tmp_path / "dst"
    collector = ArtifactCollector()
    with pytest.raises(ArtifactExtractionError, match="Symlink detected and rejected"):
        collector.collect(src, dst)


def test_artifact_collection_protected_path_rejected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    git_dir = src / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("evil config", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector()
    with pytest.raises(ArtifactExtractionError, match="Access to protected control path denied"):
        collector.collect(src, dst)


def test_artifact_collection_size_limit_rejected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    big_file = src / "big.bin"
    big_file.write_bytes(b"A" * 2000)

    dst = tmp_path / "dst"
    collector = ArtifactCollector(max_file_size=1000)
    with pytest.raises(ArtifactExtractionError, match="exceeds maximum"):
        collector.collect(src, dst)


def test_artifact_collection_disallowed_path_rejected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "unallowed.py").write_text("code", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector(allowed_paths=["allowed_dir/*"])
    with pytest.raises(ArtifactExtractionError, match="not in allowed_paths"):
        collector.collect(src, dst)


def test_independent_verifier_happy_path(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.py").write_text("def test_ok(): pass", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    base_sha = "1" * 40
    verifier = IndependentVerifier()
    evidence = verifier.verify_candidate(
        task_id="TASK-101",
        base_sha=base_sha,
        artifacts=artifacts,
        execution_exit_code=0,
        execution_output="collected 1 item\n\n1 passed in 0.05s\n",
    )

    assert evidence.candidate_digest is not None
    assert len(evidence.candidate_digest) == 64
    assert evidence.test_passed is True
    assert evidence.state == EvidenceState.VALID
    assert "test.py" in evidence.changed_paths
    # Without base_files this is a best-effort diff (every collected file), not a
    # verified one -- callers should not treat changed_paths as a proven diff here.
    assert evidence.metadata["diff_verified"] is False


def test_independent_verifier_junit_xml_structured_pass(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.py").write_text("def test_ok(): pass", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    verifier = IndependentVerifier()
    junit_xml = (
        '<?xml version="1.0"?>'
        '<testsuite name="pytest" tests="3" failures="0" errors="0" skipped="0"></testsuite>'
    )
    evidence = verifier.verify_candidate(
        task_id="TASK-105",
        base_sha="5" * 40,
        artifacts=artifacts,
        execution_exit_code=0,
        execution_output="",  # junit_xml is authoritative; raw output need not be parsed
        junit_xml=junit_xml,
    )
    assert evidence.test_passed is True
    assert evidence.metadata["test_report"] == "junit_xml"
    assert evidence.metadata["test_counts"]["tests"] == 3


def test_independent_verifier_junit_xml_zero_tests_fails_closed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.py").write_text("def test_ok(): pass", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    verifier = IndependentVerifier()
    junit_xml = '<testsuite name="pytest" tests="0" failures="0" errors="0" skipped="0"></testsuite>'
    with pytest.raises(VerificationError, match="zero tests"):
        verifier.verify_candidate(
            task_id="TASK-106",
            base_sha="6" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="",
            junit_xml=junit_xml,
        )


def test_independent_verifier_junit_xml_failures_rejected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.py").write_text("def test_fails(): assert False", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    verifier = IndependentVerifier()
    junit_xml = '<testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0"></testsuite>'
    with pytest.raises(VerificationError, match="1 failure"):
        verifier.verify_candidate(
            task_id="TASK-107",
            base_sha="7" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="",
            junit_xml=junit_xml,
        )


def test_independent_verifier_blank_output_fails_closed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "code.py").write_text("x = 1", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    verifier = IndependentVerifier()
    with pytest.raises(VerificationError, match="no output"):
        verifier.verify_candidate(
            task_id="TASK-108",
            base_sha="8" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="   ",
        )


def test_independent_verifier_base_files_reports_only_real_diff(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "unchanged.py").write_text("same", encoding="utf-8")
    (src / "changed.py").write_text("new content", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    unchanged_digest = artifacts.collected_files["unchanged.py"]
    base_files = {
        "unchanged.py": unchanged_digest,
        "changed.py": "0" * 64,  # different content at base_sha
    }

    verifier = IndependentVerifier()
    evidence = verifier.verify_candidate(
        task_id="TASK-109",
        base_sha="9" * 40,
        artifacts=artifacts,
        execution_exit_code=0,
        execution_output="1 passed",
        base_files=base_files,
    )
    assert evidence.changed_paths == ["changed.py"]
    assert "unchanged.py" not in evidence.changed_paths
    assert evidence.metadata["diff_verified"] is True


def test_independent_verifier_rejects_builder_claimed_mismatch(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "code.py").write_text("x = 1", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    verifier = IndependentVerifier()
    fake_claimed_digest = "f" * 40
    with pytest.raises(VerificationError, match="Builder self-reported candidate digest mismatch"):
        verifier.verify_candidate(
            task_id="TASK-102",
            base_sha="2" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="success",
            builder_claimed_digest=fake_claimed_digest,
        )


def test_independent_verifier_rejects_test_failure(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "code.py").write_text("x = 1", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    verifier = IndependentVerifier()
    with pytest.raises(VerificationError, match="Independent test verification failed"):
        verifier.verify_candidate(
            task_id="TASK-103",
            base_sha="3" * 40,
            artifacts=artifacts,
            execution_exit_code=1,
            execution_output="FAILED test_example - AssertionError",
        )


def test_independent_verifier_invalidates_on_mutation(tmp_path):
    src1 = tmp_path / "src1"
    src1.mkdir()
    (src1 / "code.py").write_text("v1", encoding="utf-8")
    dst1 = tmp_path / "dst1"

    collector = ArtifactCollector()
    art1 = collector.collect(src1, dst1)

    verifier = IndependentVerifier()
    evidence1 = verifier.verify_candidate(
        task_id="TASK-104",
        base_sha="4" * 40,
        artifacts=art1,
        execution_exit_code=0,
        execution_output="ok",
    )

    # Mutated artifact
    src2 = tmp_path / "src2"
    src2.mkdir()
    (src2 / "code.py").write_text("v2", encoding="utf-8")
    dst2 = tmp_path / "dst2"
    art2 = collector.collect(src2, dst2)

    invalidated = verifier.invalidate_on_mutation(
        prior_evidence=evidence1,
        new_base_sha="4" * 40,
        new_artifacts=art2,
    )

    assert invalidated is not None
    assert invalidated.state == EvidenceState.INVALIDATED
    assert invalidated.candidate_digest != evidence1.candidate_digest


def test_independent_verifier_enforces_phase_contract_prohibits(tmp_path):
    """Ensure verifier rejects future-phase remediations preemptively added by an earlier phase worker."""
    from orchestrator.core.verifier import PhaseContractViolationError

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    app_dir = worktree / "app"
    app_dir.mkdir()
    # Simulates Initial Builder sneaking Phase 3 HARDENED remediation into Phase 1
    (app_dir / "main.py").write_text("LAB_MODE = 'HARDENED'\nadmin_authz_remediation = True", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector(allowed_paths=["app/*"])
    artifacts = collector.collect(worktree, dst)

    phase_contract = {
        "target_phase": 1,
        "prohibits": [
            {
                "id": "PROH-01",
                "statement": "Phase 3 security remediations must not be implemented in Phase 1",
                "target_phase": 3,
                "check_type": "forbidden_pattern",
                "patterns": ["HARDENED", "admin_authz_remediation"],
                "applies_to": ["app/"],
            }
        ],
    }

    verifier = IndependentVerifier(worktree_dir=worktree)
    with pytest.raises(PhaseContractViolationError, match="prohibited pattern 'HARDENED' detected"):
        verifier.verify_candidate(
            task_id="TASK-P1",
            base_sha="5" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="ok",
            phase_contract=phase_contract,
        )


def test_independent_verifier_enforces_phase_contract_preserves(tmp_path):
    """Ensure verifier rejects changes that remove required preservation invariants."""
    from orchestrator.core.verifier import PhaseContractViolationError

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "config.py").write_text("vulnerable_flag = False", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector()
    artifacts = collector.collect(worktree, dst)

    phase_contract = {
        "target_phase": 1,
        "preserves": [
            {
                "id": "PRSV-01",
                "statement": "Intentional vulnerable flag must be preserved",
                "check_type": "required_pattern",
                "patterns": ["vulnerable_flag = True"],
            }
        ],
    }

    verifier = IndependentVerifier(worktree_dir=worktree)
    with pytest.raises(PhaseContractViolationError, match="required pattern 'vulnerable_flag = True' not found"):
        verifier.verify_candidate(
            task_id="TASK-P1",
            base_sha="6" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="ok",
            phase_contract=phase_contract,
        )


def test_independent_verifier_passes_clean_phase_contract(tmp_path):
    """Ensure clean candidate changes complying with phase contract are verified."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    app_dir = worktree / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("LAB_MODE = 'VULNERABLE'\nvulnerable_flag = True", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector(allowed_paths=["app/*"])
    artifacts = collector.collect(worktree, dst)

    phase_contract = {
        "target_phase": 1,
        "preserves": [
            {
                "id": "PRSV-01",
                "statement": "Vulnerable baseline preserved",
                "check_type": "required_pattern",
                "patterns": ["vulnerable_flag = True"],
                "applies_to": ["app/"],
            }
        ],
        "prohibits": [
            {
                "id": "PROH-01",
                "statement": "Phase 3 security remediations must not be implemented in Phase 1",
                "target_phase": 3,
                "check_type": "forbidden_pattern",
                "patterns": ["HARDENED"],
                "applies_to": ["app/"],
            }
        ],
    }

    verifier = IndependentVerifier(worktree_dir=worktree)
    evidence = verifier.verify_candidate(
        task_id="TASK-P1",
        base_sha="7" * 40,
        artifacts=artifacts,
        execution_exit_code=0,
        execution_output="ok",
        phase_contract=phase_contract,
    )
    assert evidence.state == EvidenceState.VALID
    assert evidence.metadata.get("phase_contract_verified") is True



def test_independent_verifier_rejects_unsupported_check_type(tmp_path):
    """Fail-closed: Unknown or unsupported check_types in phase contract must raise PhaseContractViolationError."""
    from orchestrator.core.verifier import PhaseContractViolationError

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test.py").write_text("print(1)", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector()
    artifacts = collector.collect(worktree, dst)

    # 1. Prohibits unsupported check_type
    bad_prohibits_contract = {
        "target_phase": 1,
        "prohibits": [
            {
                "id": "PROH-BAD",
                "statement": "Unknown check type",
                "check_type": "unknown_ai_rule",
                "patterns": ["test"],
            }
        ],
    }
    verifier = IndependentVerifier(worktree_dir=worktree)
    with pytest.raises(PhaseContractViolationError, match="Unsupported prohibits check_type 'unknown_ai_rule'"):
        verifier.verify_candidate(
            task_id="TASK-P1",
            base_sha="1" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="ok",
            phase_contract=bad_prohibits_contract,
        )

    # 2. Preserves unsupported check_type
    bad_preserves_contract = {
        "target_phase": 1,
        "preserves": [
            {
                "id": "PRSV-BAD",
                "statement": "Unknown check type",
                "check_type": "unsupported_preserves_type",
                "patterns": ["test"],
            }
        ],
    }
    with pytest.raises(PhaseContractViolationError, match="Unsupported preserves check_type 'unsupported_preserves_type'"):
        verifier.verify_candidate(
            task_id="TASK-P1",
            base_sha="1" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="ok",
            phase_contract=bad_preserves_contract,
        )

    # 3. Preserves command check_type must fail closed (not silently pass)
    cmd_preserves_contract = {
        "target_phase": 1,
        "preserves": [
            {
                "id": "PRSV-CMD",
                "statement": "Legacy command check type",
                "check_type": "command",
                "command_id": "check_invariant",
            }
        ],
    }
    with pytest.raises(PhaseContractViolationError, match="Unsupported preserves check_type 'command'"):
        verifier.verify_candidate(
            task_id="TASK-P1",
            base_sha="1" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="ok",
            phase_contract=cmd_preserves_contract,
        )


def test_independent_verifier_preexisting_prohibited_pattern_in_base_passes_if_not_in_diff(tmp_path):
    """Diff vs Candidate: Pre-existing prohibited pattern in base does not fail validation if unchanged."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "app.py").write_text("HARDENED_FLAG = True\ndef unrelated():\n    return 42\n", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector()
    artifacts = collector.collect(worktree, dst)

    base_contents = {
        "app.py": "HARDENED_FLAG = True\ndef unrelated():\n    return 0\n",
    }

    phase_contract = {
        "target_phase": 1,
        "prohibits": [
            {
                "id": "PROH-01",
                "statement": "Phase 3 security remediations must not be introduced in diff",
                "target_phase": 3,
                "check_type": "forbidden_pattern",
                "patterns": ["HARDENED_FLAG"],
            }
        ],
    }

    verifier = IndependentVerifier(worktree_dir=worktree)
    evidence = verifier.verify_candidate(
        task_id="TASK-P1",
        base_sha="2" * 40,
        artifacts=artifacts,
        execution_exit_code=0,
        execution_output="ok",
        phase_contract=phase_contract,
        base_file_contents=base_contents,
    )
    assert evidence.state == EvidenceState.VALID


def test_independent_verifier_preserves_invariant_in_unchanged_file(tmp_path):
    """Preserves checks full candidate state: Required pattern in unchanged file passes."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "config.py").write_text("vulnerable_mode = True\n", encoding="utf-8")
    (worktree / "new_feature.py").write_text("def hello(): pass\n", encoding="utf-8")

    dst = tmp_path / "dst"
    collector = ArtifactCollector()
    artifacts = collector.collect(worktree, dst)

    base_contents = {
        "config.py": "vulnerable_mode = True\n",
    }
    base_files = {
        "config.py": artifacts.collected_files["config.py"],
    }

    phase_contract = {
        "target_phase": 1,
        "preserves": [
            {
                "id": "PRSV-01",
                "statement": "Vulnerable mode must be preserved in project",
                "check_type": "required_pattern",
                "patterns": ["vulnerable_mode = True"],
            }
        ],
    }

    verifier = IndependentVerifier(worktree_dir=worktree)
    evidence = verifier.verify_candidate(
        task_id="TASK-P1",
        base_sha="3" * 40,
        artifacts=artifacts,
        execution_exit_code=0,
        execution_output="ok",
        base_files=base_files,
        phase_contract=phase_contract,
        base_file_contents=base_contents,
    )
    assert evidence.changed_paths == ["new_feature.py"]
    assert evidence.state == EvidenceState.VALID
