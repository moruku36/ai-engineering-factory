"""Integration test verifying Phase 1 Foundation E2E lifecycle."""

from pathlib import Path

from orchestrator.adapters.manual import ManualAdapter
from orchestrator.core.schema import (
    compute_spec_digest,
    parse_safe_yaml,
    validate_against_schema,
)
from orchestrator.core.state import StateLedger, TaskStatus
from orchestrator.core.worktree import HandoffManager, validate_paths_against_policy


def test_phase1_e2e_single_agent_flow(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent.parent
    task_file = repo_root / "tasks" / "examples" / "sample-task.yaml"
    with open(task_file, "r", encoding="utf-8") as f:
        task_content = f.read()

    # Step 1: Parse and validate task schema
    manifest = parse_safe_yaml(task_content)
    validate_against_schema(manifest, "task.schema.json")
    task_id = manifest["id"]
    assert task_id == "SMP-001"

    # Step 2: Compute spec digest
    spec_digest = compute_spec_digest(manifest)
    policy_digest = "e" * 64
    base_sha = "f" * 40

    # Step 3: Initialize state ledger
    state_dir = tmp_path / "state" / "tasks"
    ledger = StateLedger(state_dir=state_dir)
    state = ledger.initialize_task(task_id, spec_digest, policy_digest, base_sha)
    assert state["status"] == TaskStatus.PROPOSED.value
    assert state["revision"] == 0

    # Step 4: Advance to READY
    state = ledger.transition(task_id, 0, TaskStatus.READY, "Preflight checks passed")
    assert state["status"] == TaskStatus.READY.value

    # Step 5: Advance to RUNNING and dispatch via ManualAdapter
    adapter = ManualAdapter()
    run_id = adapter.start_task(manifest, str(repo_root))
    state = ledger.transition(task_id, 1, TaskStatus.RUNNING, f"Dispatched run {run_id}")
    assert state["status"] == TaskStatus.RUNNING.value

    # Step 6: Execute validation command in adapter (pytest)
    val_result = adapter.execute_validation_step(
        run_id,
        "pytest",
        [str(repo_root / ".venv" / "Scripts" / "pytest"), "-q", "tests/unit/test_schema.py"],
    )
    assert val_result["status"] == "PASS"

    # Step 7: Verify path governance on changed paths
    candidate_changes = ["orchestrator/adapters/manual.py"]
    validate_paths_against_policy(
        candidate_changes,
        manifest["allowed_paths"],
        manifest["prohibited_paths"],
    )

    # Step 8: Transition to VALIDATING with candidate SHA
    candidate_sha = "1" * 40
    state = ledger.transition(
        task_id, 2, TaskStatus.VALIDATING, "Validating candidate diff", candidate_sha=candidate_sha
    )
    assert state["status"] == TaskStatus.VALIDATING.value
    assert state["candidate_sha"] == candidate_sha

    # Step 9: Transition to REVIEW
    state = ledger.transition(task_id, 3, TaskStatus.REVIEW, "Automated validation passed")
    assert state["status"] == TaskStatus.REVIEW.value

    # Step 10: Transition to READY_FOR_MERGE
    state = ledger.transition(task_id, 4, TaskStatus.READY_FOR_MERGE, "Reviewer verdict APPROVED")
    assert state["status"] == TaskStatus.READY_FOR_MERGE.value

    # Step 11: Collect and validate final execution result schema
    exec_result = adapter.collect_results(run_id)
    exec_result["spec_sha"] = spec_digest
    exec_result["policy_sha"] = policy_digest
    exec_result["base_sha"] = base_sha
    exec_result["candidate_sha"] = candidate_sha
    validate_against_schema(exec_result, "result.schema.json")
    assert exec_result["status"] == "SUCCESS"

    # Step 12: Test Handoff save and resume
    handoff_dir = tmp_path / "state" / "handoffs"
    handoff_mgr = HandoffManager(handoffs_dir=handoff_dir)
    handoff_mgr.save_handoff(
        task_id=task_id,
        run_id=run_id,
        attempt=1,
        spec_digest=spec_digest,
        policy_digest=policy_digest,
        base_sha=base_sha,
        head_sha=candidate_sha,
        completed_steps=["validation", "review"],
        pending_steps=["human_merge"],
        changed_paths=candidate_changes,
        validations=exec_result["validations"],
        artifacts=exec_result["artifact_hashes"],
        is_dirty=False,
        lease_id=None,
        blocked_reason=None,
        next_action="Awaiting human merge on GitHub remote",
        required_approvals=["merge_pull_request"],
    )
    resumed = handoff_mgr.verify_resume_preflight(task_id, spec_digest, base_sha)
    assert resumed["head_sha"] == candidate_sha
    assert resumed["next_action"] == "Awaiting human merge on GitHub remote"
