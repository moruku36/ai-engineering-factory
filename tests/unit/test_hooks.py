"""Unit tests for Factory lifecycle hooks and Rule/Skill validation."""

from pathlib import Path

import pytest

from orchestrator.core.hooks import (
    HookEngine,
    HookEvent,
    HookExecutionError,
    HookMissingError,
    HookTimeoutError,
)
from orchestrator.core.schema import parse_safe_yaml, validate_against_schema


def test_hook_happy_path():
    engine = HookEngine()
    executed = []

    def sample_hook(ctx):
        executed.append(ctx["task_id"])
        return {"status": "PASS", "info": "ok"}

    engine.register_hook(HookEvent.BEFORE_COMMIT, sample_hook)
    results = engine.execute_hook(HookEvent.BEFORE_COMMIT, {"task_id": "TASK-001"})
    assert len(results) == 1
    assert results[0]["status"] == "PASS"
    assert executed == ["TASK-001"]


def test_hook_failure_causes_deny():
    engine = HookEngine()

    def failing_hook(ctx):
        return {"status": "FAIL", "reason": "Secret detected in diff"}

    engine.register_hook(HookEvent.BEFORE_PUSH, failing_hook)
    with pytest.raises(HookExecutionError, match="returned non-PASS status"):
        engine.execute_hook(HookEvent.BEFORE_PUSH, {"task_id": "TASK-002"})


def test_missing_mandatory_hook_causes_deny():
    engine = HookEngine()
    # No hook registered for BEFORE_MERGE_READY
    with pytest.raises(HookMissingError, match="Mandatory hook 'before_merge_ready' has no registered handler"):
        engine.execute_hook(HookEvent.BEFORE_MERGE_READY, {"task_id": "TASK-003"}, required=True)


def test_hook_timeout_causes_deny():
    engine = HookEngine()

    def slow_hook(ctx):
        import time

        time.sleep(0.05)
        return {"status": "PASS"}

    engine.register_hook(HookEvent.BEFORE_ACTION, slow_hook)
    with pytest.raises(HookTimeoutError, match="exceeded timeout"):
        engine.execute_hook(HookEvent.BEFORE_ACTION, {"action": "step"}, timeout_seconds=0.01)


def test_rule_and_skill_schemas_valid():
    repo_root = Path(__file__).resolve().parent.parent.parent

    # Validate sample rules
    rule1_path = repo_root / ".agents" / "rules" / "RULE-001.yaml"
    with open(rule1_path, "r", encoding="utf-8") as f:
        data1 = parse_safe_yaml(f.read())
    validate_against_schema(data1, "rule.schema.json")
    assert data1["id"] == "RULE-001"

    # Validate sample skills
    skill1_path = repo_root / ".agents" / "skills" / "SKILL-001.yaml"
    with open(skill1_path, "r", encoding="utf-8") as f:
        data2 = parse_safe_yaml(f.read())
    validate_against_schema(data2, "skill.schema.json")
    assert data2["id"] == "SKILL-001"
