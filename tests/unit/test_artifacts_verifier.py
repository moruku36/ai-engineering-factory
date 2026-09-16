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

    assert evidence.candidate_sha is not None
    assert len(evidence.candidate_sha) == 40
    assert evidence.test_passed is True
    assert evidence.state == EvidenceState.VALID
    assert "test.py" in evidence.changed_paths


def test_independent_verifier_rejects_builder_claimed_mismatch(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "code.py").write_text("x = 1", encoding="utf-8")
    dst = tmp_path / "dst"

    collector = ArtifactCollector()
    artifacts = collector.collect(src, dst)

    verifier = IndependentVerifier()
    fake_claimed_sha = "f" * 40
    with pytest.raises(VerificationError, match="Builder self-reported candidate SHA mismatch"):
        verifier.verify_candidate(
            task_id="TASK-102",
            base_sha="2" * 40,
            artifacts=artifacts,
            execution_exit_code=0,
            execution_output="success",
            builder_claimed_sha=fake_claimed_sha,
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
    assert invalidated.candidate_sha != evidence1.candidate_sha
