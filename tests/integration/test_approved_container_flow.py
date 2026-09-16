"""Real approval -> container -> run-loop evidence, with fixture-only token issuance."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orchestrator.adapters.container import ApprovedContainerAdapter
from orchestrator.core.approval import ApprovalManager, ApprovalVerificationError
from orchestrator.core.container import ContainerCommand, OfflineContainerRunner
from orchestrator.core.lease import RuntimeLeaseManager
from orchestrator.core.loop import RunLoopController
from orchestrator.core.state import StateLedger, TaskStatus

pytestmark = pytest.mark.skipif(
    not os.environ.get("FACTORY_TEST_IMAGE"), reason="Dedicated Linux Docker job required",
)


def build_fixture(root, code):
    root = Path(root)
    task = {"id": "TASK-001", "worktree": "unmounted-reference", "dependencies": [],
            "allowed_paths": ["src/"]}
    runner = OfflineContainerRunner(root / "workers", os.environ["FACTORY_TEST_IMAGE"], {
        "probe": ContainerCommand(("/usr/local/bin/python", "/inputs/probe.py"), 120),
    })
    plans = {task["id"]: {
        "repository": "example/factory", "head_sha": "c" * 40, "target_ref": "task/one",
        "policy_hash": "b" * 64, "plan_hash": "a" * 64, "command_id": "probe",
        "inputs": {"probe.py": code},
    }}
    adapter = ApprovedContainerAdapter(runner, ApprovalManager(root / "approvals"), plans,
                                       {}, root / "adapter")
    loop = RunLoopController([task], StateLedger(root / "state"),
                             RuntimeLeaseManager(root / "leases.sqlite"), adapter,
                             "a" * 64, "b" * 64, base_sha="c" * 40, max_workers=1)
    return adapter, task, loop


def admit_fixture(adapter, task, loop):
    token = adapter.approvals.issue_token(
        **adapter.approval_context(task, task["worktree"]), approved_by="fixture-only",
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    adapter.tokens[task["id"]] = token["token_id"]
    loop.initialize_tasks()
    loop.state_ledger.transition(task["id"], 0, TaskStatus.READY, "Trusted CI fixture preflight")
    loop.initialize_tasks()


def test_real_approved_execution_resumes_as_validation_only(tmp_path):
    code = b"import os; assert 'AI_FACTORY_APPROVAL_SECRET' not in os.environ; print('FLOW_OK')"
    adapter, task, loop = build_fixture(tmp_path, code)
    admit_fixture(adapter, task, loop)
    loop.step()
    assert loop.state_ledger.get_state(task["id"])["status"] == "RUNNING"
    fresh, _, restarted = build_fixture(tmp_path, code)
    restarted.initialize_tasks()
    restarted.step()
    state = restarted.state_ledger.get_state(task["id"])
    assert state["status"] == "VALIDATING"
    assert state["candidate_sha"] is None
    session = fresh.recover_task(task, task["worktree"])
    assert "FLOW_OK" in fresh.collect_results(session)["output"]
    assert len(list(adapter.runner.root.glob("*/record.json"))) == 1
    assert restarted.lease_manager.get_active_lease(task["id"]) is None


def test_real_binding_failure_starts_no_container(tmp_path):
    adapter, task, loop = build_fixture(tmp_path, b"print('approved')")
    admit_fixture(adapter, task, loop)
    adapter.plans[task["id"]]["inputs"]["probe.py"] = b"print('changed')"
    with pytest.raises(ApprovalVerificationError):
        loop.step()
    assert not adapter.runner.root.exists()
    assert loop.state_ledger.get_state(task["id"])["status"] == "BLOCKED"


def test_real_crash_reconciles_without_redispatch(tmp_path):
    code = b"import time; time.sleep(120)"
    # Import these credential-free fixture builders in the child controller.
    program = f'''
import sys
sys.path.insert(0, {str(Path(__file__).parent)!r})
from test_approved_container_flow import build_fixture, admit_fixture
adapter, task, loop = build_fixture({str(tmp_path)!r}, {code!r})
admit_fixture(adapter, task, loop)
loop.step()
'''
    adapter, task, loop = build_fixture(tmp_path, code)
    process = subprocess.Popen([sys.executable, "-c", program])
    record = None
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            files = list(adapter.runner.root.glob("*/record.json"))
            if files:
                record = json.loads(files[0].read_text())
                if record.get("container_id"):
                    actual = json.loads(adapter.runner._call("inspect", record["container_id"]))[0]
                    if actual["State"]["Running"]:
                        break
            time.sleep(0.1)
        else:
            pytest.fail("Approved worker did not start")
        process.kill()
        process.wait(timeout=10)
        loop.initialize_tasks()
        loop.step()
        assert loop.state_ledger.get_state(task["id"])["status"] == "BLOCKED"
        assert adapter.runner._find_owned(record) is None
        assert len(list(adapter.runner.root.glob("*/record.json"))) == 1
        assert loop.lease_manager.get_active_lease(task["id"]) is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if record:
            adapter.runner.reconcile(record["run_id"])
