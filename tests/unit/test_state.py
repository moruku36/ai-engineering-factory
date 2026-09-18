"""Unit tests for single-writer state ledger and lifecycle engine."""

import pytest

from orchestrator.core.state import (
    CASConflictError,
    StateLedger,
    StateTransitionError,
    TaskStatus,
)

SAMPLE_SPEC_DIGEST = "a" * 64
SAMPLE_POLICY_DIGEST = "b" * 64
SAMPLE_BASE_SHA = "c" * 40
SAMPLE_CANDIDATE_DIGEST = "d" * 40


@pytest.fixture
def ledger(tmp_path):
    return StateLedger(state_dir=tmp_path / "tasks")


def test_state_lifecycle_happy_path(ledger):
    task_id = "TASK-001"
    state = ledger.initialize_task(
        task_id=task_id,
        spec_digest=SAMPLE_SPEC_DIGEST,
        policy_digest=SAMPLE_POLICY_DIGEST,
        base_sha=SAMPLE_BASE_SHA,
    )
    assert state["status"] == TaskStatus.PROPOSED.value
    assert state["revision"] == 0

    # PROPOSED -> READY
    state = ledger.transition(task_id, 0, TaskStatus.READY, "Dependencies met")
    assert state["status"] == TaskStatus.READY.value
    assert state["revision"] == 1

    # READY -> RUNNING
    state = ledger.transition(task_id, 1, TaskStatus.RUNNING, "Worker dispatched")
    assert state["status"] == TaskStatus.RUNNING.value
    assert state["attempt"] == 1
    assert state["revision"] == 2

    # RUNNING -> VALIDATING
    state = ledger.transition(
        task_id, 2, TaskStatus.VALIDATING, "Worker candidate ready", candidate_digest=SAMPLE_CANDIDATE_DIGEST
    )
    assert state["status"] == TaskStatus.VALIDATING.value
    assert state["candidate_digest"] == SAMPLE_CANDIDATE_DIGEST
    assert state["revision"] == 3

    # VALIDATING -> REVIEW
    state = ledger.transition(task_id, 3, TaskStatus.REVIEW, "Automated tests passed")
    assert state["status"] == TaskStatus.REVIEW.value
    assert state["revision"] == 4

    # REVIEW -> READY_FOR_MERGE
    state = ledger.transition(task_id, 4, TaskStatus.READY_FOR_MERGE, "Review approved by reviewer agent")
    assert state["status"] == TaskStatus.READY_FOR_MERGE.value
    assert state["revision"] == 5

    # READY_FOR_MERGE -> DONE
    state = ledger.transition(task_id, 5, TaskStatus.DONE, "Human verified merge on remote main")
    assert state["status"] == TaskStatus.DONE.value
    assert state["revision"] == 6


def test_invalid_transition_rejected(ledger):
    task_id = "TASK-002"
    ledger.initialize_task(task_id, SAMPLE_SPEC_DIGEST, SAMPLE_POLICY_DIGEST, SAMPLE_BASE_SHA)

    # Cannot skip from PROPOSED to DONE directly
    with pytest.raises(StateTransitionError, match="Invalid transition"):
        ledger.transition(task_id, 0, TaskStatus.DONE, "Skipping ahead")


def test_cas_conflict(ledger):
    task_id = "TASK-003"
    ledger.initialize_task(task_id, SAMPLE_SPEC_DIGEST, SAMPLE_POLICY_DIGEST, SAMPLE_BASE_SHA)

    # Wrong expected revision
    with pytest.raises(CASConflictError, match="CAS conflict"):
        ledger.transition(task_id, 999, TaskStatus.READY, "Wrong revision")


def test_terminal_state_frozen(ledger):
    task_id = "TASK-004"
    ledger.initialize_task(task_id, SAMPLE_SPEC_DIGEST, SAMPLE_POLICY_DIGEST, SAMPLE_BASE_SHA)
    ledger.transition(task_id, 0, TaskStatus.CANCELLED, "Cancelled by operator")

    with pytest.raises(StateTransitionError, match="Cannot transition from terminal state"):
        ledger.transition(task_id, 1, TaskStatus.READY, "Attempting revival")


def test_retry_budget_enforcement(ledger):
    task_id = "TASK-005"
    ledger.initialize_task(task_id, SAMPLE_SPEC_DIGEST, SAMPLE_POLICY_DIGEST, SAMPLE_BASE_SHA)
    ledger.transition(task_id, 0, TaskStatus.READY, "Ready")
    ledger.transition(task_id, 1, TaskStatus.RUNNING, "Run 1")
    ledger.transition(task_id, 2, TaskStatus.FAILED, "Fail 1")

    # Retry 1: FAILED -> READY
    ledger.transition(task_id, 3, TaskStatus.READY, "Retry 1")
    ledger.transition(task_id, 4, TaskStatus.RUNNING, "Run 2")
    ledger.transition(task_id, 5, TaskStatus.FAILED, "Fail 2")

    # Retry 2: FAILED -> READY
    ledger.transition(task_id, 6, TaskStatus.READY, "Retry 2")
    ledger.transition(task_id, 7, TaskStatus.RUNNING, "Run 3")
    ledger.transition(task_id, 8, TaskStatus.FAILED, "Fail 3")

    # Retry 3: FAILED -> READY (Exceeds budget after 3 retries)
    with pytest.raises(StateTransitionError, match="exceeded max attempts"):
        ledger.transition(task_id, 9, TaskStatus.READY, "Retry 4 over budget")


def test_base_change_invalidates_candidate(ledger):
    task_id = "TASK-006"
    ledger.initialize_task(task_id, SAMPLE_SPEC_DIGEST, SAMPLE_POLICY_DIGEST, SAMPLE_BASE_SHA)
    ledger.transition(task_id, 0, TaskStatus.READY, "Ready")
    ledger.transition(task_id, 1, TaskStatus.RUNNING, "Run")
    ledger.transition(task_id, 2, TaskStatus.VALIDATING, "Validating", candidate_digest=SAMPLE_CANDIDATE_DIGEST)
    state = ledger.transition(task_id, 3, TaskStatus.REVIEW, "Review")
    assert state["candidate_digest"] == SAMPLE_CANDIDATE_DIGEST

    # Base changes during REVIEW -> transition back to READY with new base_sha
    new_base_sha = "e" * 40
    state = ledger.transition(task_id, 4, TaskStatus.READY, "Rebased onto new main", base_sha=new_base_sha)
    assert state["base_sha"] == new_base_sha
    assert state["candidate_digest"] is None  # Candidate invalidated!


def test_transition_to_done_requires_human_approval(ledger, monkeypatch, tmp_path):
    from orchestrator.core.approval import ApprovalManager
    from orchestrator.core.policy import ApprovalRequiredError

    monkeypatch.setenv("AI_FACTORY_APPROVAL_SECRET", "01234567890123456789012345678901")
    mgr = ApprovalManager(approvals_dir=tmp_path / "approvals")

    task_id = "TASK-007"
    SAMPLE_PR_HEAD_SHA = "1" * 40
    ledger.initialize_task(task_id, SAMPLE_SPEC_DIGEST, SAMPLE_POLICY_DIGEST, SAMPLE_BASE_SHA)
    ledger.transition(task_id, 0, TaskStatus.READY, "Ready")
    ledger.transition(task_id, 1, TaskStatus.RUNNING, "Run")
    ledger.transition(task_id, 2, TaskStatus.VALIDATING, "Validating", candidate_digest=SAMPLE_CANDIDATE_DIGEST)
    ledger.transition(task_id, 3, TaskStatus.REVIEW, "Review")
    ledger.transition(task_id, 4, TaskStatus.READY_FOR_MERGE, "Ready for merge", pr_head_sha=SAMPLE_PR_HEAD_SHA)

    # 1. Fail closed when human approval is required but token is missing
    with pytest.raises(ApprovalRequiredError, match="human approval token is required before merge"):
        ledger.transition(task_id, 5, TaskStatus.DONE, "Attempted merge", requires_human_approval=True)

    # 2. Fail closed when approval_manager is omitted
    with pytest.raises(ApprovalRequiredError, match="approval_manager is required to verify token"):
        ledger.transition(
            task_id, 5, TaskStatus.DONE, "Attempted merge",
            requires_human_approval=True, approval_token_id="tok-fabricated-123",
        )

    # 3. Fabricated token ID -> rejected
    with pytest.raises(ApprovalRequiredError, match="approval token verification failed"):
        ledger.transition(
            task_id, 5, TaskStatus.DONE, "Attempted merge",
            requires_human_approval=True, approval_token_id="tok-fabricated-123",
            approval_manager=mgr, repository="moruku36/ai-engineering-factory",
        )

    # Issue token bound to base_sha (incorrect binding, should be PR HEAD SHA)
    tok_base = mgr.issue_token(
        action="merge_pull_request",
        repository="moruku36/ai-engineering-factory",
        task_id=task_id,
        head_sha=SAMPLE_BASE_SHA,
        target_ref="refs/heads/main",
        argv_digest="0" * 64,
        policy_hash=SAMPLE_POLICY_DIGEST,
        plan_hash=SAMPLE_SPEC_DIGEST,
        approved_by="human-operator",
        expires_at="2099-01-01T00:00:00Z",
    )
    tok_base_id = tok_base["token_id"]
    mgr.verify_and_consume_token(
        token_id=tok_base_id,
        action="merge_pull_request",
        repository="moruku36/ai-engineering-factory",
        task_id=task_id,
        head_sha=SAMPLE_BASE_SHA,
        target_ref="refs/heads/main",
        argv_digest="0" * 64,
        policy_hash=SAMPLE_POLICY_DIGEST,
        plan_hash=SAMPLE_SPEC_DIGEST,
    )

    # 4. Approval token bound to base_sha is REJECTED when PR HEAD SHA differs
    with pytest.raises(ApprovalRequiredError, match="Token binding mismatch on 'head_sha'"):
        ledger.transition(
            task_id, 5, TaskStatus.DONE, "Attempted merge",
            requires_human_approval=True, approval_token_id=tok_base_id,
            approval_manager=mgr, repository="moruku36/ai-engineering-factory",
        )

    # Issue token bound correctly to PR HEAD SHA
    tok_pr = mgr.issue_token(
        action="merge_pull_request",
        repository="moruku36/ai-engineering-factory",
        task_id=task_id,
        head_sha=SAMPLE_PR_HEAD_SHA,
        target_ref="refs/heads/main",
        argv_digest="0" * 64,
        policy_hash=SAMPLE_POLICY_DIGEST,
        plan_hash=SAMPLE_SPEC_DIGEST,
        approved_by="human-operator",
        expires_at="2099-01-01T00:00:00Z",
    )
    tok_pr_id = tok_pr["token_id"]

    # 5. Existing but unconsumed token -> rejected
    with pytest.raises(ApprovalRequiredError, match="has not been consumed yet"):
        ledger.transition(
            task_id, 5, TaskStatus.DONE, "Attempted merge",
            requires_human_approval=True, approval_token_id=tok_pr_id,
            approval_manager=mgr, repository="moruku36/ai-engineering-factory",
        )

    # 6. Revoked token -> rejected
    mgr.revoke_token(tok_pr_id, reason="Revoked before consume")
    with pytest.raises(ApprovalRequiredError, match="has been revoked"):
        ledger.transition(
            task_id, 5, TaskStatus.DONE, "Attempted merge",
            requires_human_approval=True, approval_token_id=tok_pr_id,
            approval_manager=mgr, repository="moruku36/ai-engineering-factory",
        )

    # Issue another token correctly bound to PR HEAD SHA and consume it
    tok_valid = mgr.issue_token(
        action="merge_pull_request",
        repository="moruku36/ai-engineering-factory",
        task_id=task_id,
        head_sha=SAMPLE_PR_HEAD_SHA,
        target_ref="refs/heads/main",
        argv_digest="0" * 64,
        policy_hash=SAMPLE_POLICY_DIGEST,
        plan_hash=SAMPLE_SPEC_DIGEST,
        approved_by="human-operator",
        expires_at="2099-01-01T00:00:00Z",
    )
    tok_valid_id = tok_valid["token_id"]
    mgr.verify_and_consume_token(
        token_id=tok_valid_id,
        action="merge_pull_request",
        repository="moruku36/ai-engineering-factory",
        task_id=task_id,
        head_sha=SAMPLE_PR_HEAD_SHA,
        target_ref="refs/heads/main",
        argv_digest="0" * 64,
        policy_hash=SAMPLE_POLICY_DIGEST,
        plan_hash=SAMPLE_SPEC_DIGEST,
    )

    # 7. New commit pushed to PR (PR HEAD mutated) -> approval token for old HEAD is rejected
    with pytest.raises(ApprovalRequiredError, match="Token binding mismatch on 'head_sha'"):
        ledger.transition(
            task_id, 5, TaskStatus.DONE, "Attempted merge after new push",
            requires_human_approval=True, approval_token_id=tok_valid_id,
            approval_manager=mgr, repository="moruku36/ai-engineering-factory",
            pr_head_sha="2" * 40,
        )

    # 8. Valid consumed token with matching PR HEAD SHA succeeds
    done_state = ledger.transition(
        task_id, 5, TaskStatus.DONE, "Human verified merge",
        requires_human_approval=True, approval_token_id=tok_valid_id,
        approval_manager=mgr, repository="moruku36/ai-engineering-factory",
    )
    assert done_state["status"] == TaskStatus.DONE.value
    assert done_state["pr_head_sha"] == SAMPLE_PR_HEAD_SHA

