"""Negative, tampering, concurrency, and crash recovery tests for approvals and state (AC-H03, AC-H04)."""

import multiprocessing
import os
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orchestrator.core.approval import (
    ApprovalExpiredError,
    ApprovalManager,
    ApprovalReplayError,
    ApprovalVerificationError,
    compute_argv_digest,
)
from orchestrator.core.state import (
    CASConflictError,
    StateLedger,
    StateTransitionError,
    TaskStatus,
)


def _consume_worker(approvals_dir, token_id, token_kwargs, result_queue):
    """Subprocess function attempting to verify and consume a token."""
    manager = ApprovalManager(approvals_dir)
    try:
        manager.verify_and_consume_token(token_id=token_id, **token_kwargs)
        result_queue.put("SUCCESS")
    except ApprovalReplayError:
        result_queue.put("REPLAY_ERROR")
    except Exception as e:
        result_queue.put(f"ERROR: {type(e).__name__}")


def test_approval_tampering_and_forgery_rejected(tmp_path):
    manager = ApprovalManager(tmp_path)
    argv = ["pytest", "-q"]
    argv_digest = compute_argv_digest(argv)
    policy_hash = "a" * 64
    plan_hash = "b" * 64
    head_sha = "c" * 40

    token = manager.issue_token(
        action="task_execution",
        repository="moruku36/ai-engineering-factory",
        task_id="FND-001",
        head_sha=head_sha,
        target_ref="refs/heads/main",
        argv_digest=argv_digest,
        policy_hash=policy_hash,
        plan_hash=plan_hash,
        approved_by="kentaro",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )

    # 1. Tamper head_sha
    with pytest.raises(ApprovalVerificationError):
        manager.verify_and_consume_token(
            token_id=token["token_id"],
            action="task_execution",
            repository="moruku36/ai-engineering-factory",
            task_id="FND-001",
            head_sha="0" * 40,  # Modified SHA
            target_ref="refs/heads/main",
            argv_digest=argv_digest,
            policy_hash=policy_hash,
            plan_hash=plan_hash,
        )

    # 2. Tamper task_id
    with pytest.raises(ApprovalVerificationError):
        manager.verify_and_consume_token(
            token_id=token["token_id"],
            action="task_execution",
            repository="moruku36/ai-engineering-factory",
            task_id="SEC-002",  # Different task
            head_sha=head_sha,
            target_ref="refs/heads/main",
            argv_digest=argv_digest,
            policy_hash=policy_hash,
            plan_hash=plan_hash,
        )


def test_approval_expired_rejected(tmp_path):
    manager = ApprovalManager(tmp_path)
    argv_digest = compute_argv_digest(["pytest"])
    past_time = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    token = manager.issue_token(
        action="task_execution",
        repository="moruku36/ai-engineering-factory",
        task_id="FND-001",
        head_sha="a" * 40,
        target_ref="refs/heads/main",
        argv_digest=argv_digest,
        policy_hash="b" * 64,
        plan_hash="c" * 64,
        approved_by="kentaro",
        expires_at=past_time,
    )

    with pytest.raises(ApprovalExpiredError):
        manager.verify_and_consume_token(
            token_id=token["token_id"],
            action="task_execution",
            repository="moruku36/ai-engineering-factory",
            task_id="FND-001",
            head_sha="a" * 40,
            target_ref="refs/heads/main",
            argv_digest=argv_digest,
            policy_hash="b" * 64,
            plan_hash="c" * 64,
        )


def test_approval_concurrent_cross_process_single_consume(tmp_path):
    """Verify that multiple processes trying to consume the same token results in exactly one SUCCESS and others REPLAY_ERROR."""
    manager = ApprovalManager(tmp_path)
    argv_digest = compute_argv_digest(["pytest"])
    token = manager.issue_token(
        action="task_execution",
        repository="moruku36/ai-engineering-factory",
        task_id="FND-001",
        head_sha="a" * 40,
        target_ref="refs/heads/main",
        argv_digest=argv_digest,
        policy_hash="b" * 64,
        plan_hash="c" * 64,
        approved_by="kentaro",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )

    kwargs = {
        "action": "task_execution",
        "repository": "moruku36/ai-engineering-factory",
        "task_id": "FND-001",
        "head_sha": "a" * 40,
        "target_ref": "refs/heads/main",
        "argv_digest": argv_digest,
        "policy_hash": "b" * 64,
        "plan_hash": "c" * 64,
    }

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()

    p1 = ctx.Process(target=_consume_worker, args=(str(tmp_path), token["token_id"], kwargs, queue))
    p2 = ctx.Process(target=_consume_worker, args=(str(tmp_path), token["token_id"], kwargs, queue))

    p1.start()
    p2.start()

    p1.join(timeout=5)
    p2.join(timeout=5)

    results = [queue.get(timeout=2), queue.get(timeout=2)]
    assert "SUCCESS" in results
    assert "REPLAY_ERROR" in results


def _cas_transition_worker(state_dir, task_id, from_rev, to_status, result_queue):
    ledger = StateLedger(state_dir)
    try:
        ledger.transition(
            task_id=task_id,
            expected_revision=from_rev,
            to_status=to_status,
            reason="Concurrent worker update",
        )
        result_queue.put("SUCCESS")
    except CASConflictError:
        result_queue.put("CAS_CONFLICT")
    except Exception as e:
        result_queue.put(f"ERROR: {type(e).__name__}")


def test_state_ledger_cross_process_cas(tmp_path):
    """Verify that concurrent processes attempting state transition with the same revision result in one success and CAS conflict."""
    ledger = StateLedger(tmp_path)
    state = ledger.initialize_task(
        task_id="FND-001",
        spec_digest="a" * 64,
        policy_digest="b" * 64,
    )
    assert state["revision"] == 0

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()

    p1 = ctx.Process(target=_cas_transition_worker, args=(str(tmp_path), "FND-001", 0, TaskStatus.READY, queue))
    p2 = ctx.Process(target=_cas_transition_worker, args=(str(tmp_path), "FND-001", 0, TaskStatus.READY, queue))

    p1.start()
    p2.start()

    p1.join(timeout=5)
    p2.join(timeout=5)

    results = [queue.get(timeout=2), queue.get(timeout=2)]
    assert "SUCCESS" in results
    assert "CAS_CONFLICT" in results
