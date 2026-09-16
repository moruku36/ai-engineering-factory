"""Unit tests for schema validation and security parser."""

import jsonschema
import pytest
from yaml.constructor import ConstructorError

from orchestrator.core.schema import (
    CapabilityStatus,
    EnvironmentCapabilityProbe,
    PlanIngestionEngine,
    check_circular_dependencies,
    compute_spec_digest,
    parse_safe_yaml,
    validate_against_schema,
)

VALID_TASK_YAML = """
schema_version: "2020-12"
id: "TASK-001"
title: "Sample Task"
description: "A sample valid task for testing"
phase: 1
dependencies: []
parallelizable: true
role: "builder"
repository: "https://github.com/moruku36/ai-engineering-factory"
base_ref: "main"
branch: "task/sample-001"
worktree: "runtime-root/worktrees/sample-001"
allowed_paths:
  - "orchestrator/"
prohibited_paths:
  - ".github/"
validation:
  - command_id: "pytest_unit"
    timeout_seconds: 300
completion_criteria:
  - id: "CC-1"
    statement: "Unit tests pass"
    evidence_type: "test_run"
risk: "low"
approval:
  before_execution: false
  before_merge: true
output_artifacts:
  - kind: "test_report"
    path: "reports/test.json"
    classification: "internal"
resources:
  ports: [8000]
  test_db: true
  exclusive_keys: ["db_lock"]
permissions:
  - "default"
retry:
  max_attempts: 3
  timeout_minutes: 30
status: "PROPOSED"
state_ref: "state/tasks/TASK-001.json"
"""


def test_valid_task_manifest():
    data = parse_safe_yaml(VALID_TASK_YAML)
    validate_against_schema(data, "task.schema.json")
    assert data["id"] == "TASK-001"


def test_reject_unknown_field():
    yaml_with_extra = VALID_TASK_YAML + "\nextra_unauthorized_field: 'malicious'\n"
    data = parse_safe_yaml(yaml_with_extra)
    with pytest.raises(jsonschema.ValidationError):
        validate_against_schema(data, "task.schema.json")


def test_reject_invalid_task_id():
    yaml_bad_id = VALID_TASK_YAML.replace('id: "TASK-001"', 'id: "bad-task-id"')
    data = parse_safe_yaml(yaml_bad_id)
    with pytest.raises(jsonschema.ValidationError):
        validate_against_schema(data, "task.schema.json")


def test_reject_duplicate_yaml_keys():
    duplicate_key_yaml = """
schema_version: "2020-12"
id: "TASK-001"
id: "TASK-002"
"""
    with pytest.raises(ConstructorError):
        parse_safe_yaml(duplicate_key_yaml)


def test_reject_yaml_alias():
    alias_yaml = """
base: &base_anchor
  schema_version: "2020-12"
target:
  <<: *base_anchor
"""
    with pytest.raises(TypeError, match="YAML aliases and anchors are prohibited"):
        parse_safe_yaml(alias_yaml)


def test_spec_digest_invariance():
    data1 = parse_safe_yaml(VALID_TASK_YAML)
    digest1 = compute_spec_digest(data1)

    # Modify status and state_ref
    data2 = dict(data1)
    data2["status"] = "RUNNING"
    data2["state_ref"] = "different/ref.json"
    digest2 = compute_spec_digest(data2)

    assert digest1 == digest2

    # Modifying title should change digest
    data3 = dict(data1)
    data3["title"] = "Modified Title"
    digest3 = compute_spec_digest(data3)
    assert digest1 != digest3


def test_circular_and_invalid_dependencies():
    tasks = {
        "TASK-001": {"dependencies": ["TASK-002"]},
        "TASK-002": {"dependencies": ["TASK-001"]},
    }
    with pytest.raises(ValueError, match="Circular dependency detected"):
        check_circular_dependencies(tasks)

    # Self dependency
    self_dep = {"TASK-001": {"dependencies": ["TASK-001"]}}
    with pytest.raises(ValueError, match="Self dependency detected"):
        check_circular_dependencies(self_dep)

    # Unknown dependency
    unknown_dep = {"TASK-001": {"dependencies": ["TASK-999"]}}
    with pytest.raises(ValueError, match="unknown dependency"):
        check_circular_dependencies(unknown_dep)


def test_environment_capability_probe():
    probe = EnvironmentCapabilityProbe()
    report = probe.probe_all()

    assert "python" in report
    assert report["python"]["status"] == CapabilityStatus.VERIFIED
    assert "git" in report
    assert "isolation" in report
    assert report["isolation"]["status"] == CapabilityStatus.MANUAL_ONLY


def test_plan_ingestion_engine():
    valid_plan = {
        "schema_version": "2020-12",
        "plan_id": "PLAN-0001",
        "target_repo": "https://github.com/moruku36/ai-engineering-factory",
        "requested_phase": 4,
        "task_refs": ["AUT-001", "AUT-002"],
        "max_workers": 2,
        "max_wall_seconds": 3600,
        "approved_scope_ref": "scope-v1",
    }
    available = {
        "AUT-001": {"id": "AUT-001", "dependencies": []},
        "AUT-002": {"id": "AUT-002", "dependencies": ["AUT-001"]},
    }
    ingested = PlanIngestionEngine.ingest_plan(valid_plan, available)
    assert ingested["plan_id"] == "PLAN-0001"

    # Missing task ref fails
    with pytest.raises(KeyError, match="Plan references unknown tasks"):
        PlanIngestionEngine.ingest_plan(valid_plan, {"AUT-001": available["AUT-001"]})


def test_schema_format_checker_rejects_naive_datetime():
    """Ensure date-time format validation rejects datetimes without timezone offset."""
    invalid_token = {
        "schema_version": "2020-12",
        "token_id": "tok-12345678",
        "action": "task_execution",
        "repository": "moruku36/ai-engineering-factory",
        "task_id": "TASK-001",
        "head_sha": "a" * 40,
        "target_ref": "refs/heads/main",
        "argv_digest": "0" * 64,
        "policy_hash": "1" * 64,
        "plan_hash": "2" * 64,
        "approved_by": "alice",
        "created_at": "2026-09-17T00:00:00",  # naive: no timezone
        "expires_at": "2026-09-17T01:00:00Z",
        "consumed": False,
        "key_id": "3" * 64,
        "operator_signature": "4" * 64,
    }
    with pytest.raises(jsonschema.ValidationError, match="is not a 'date-time'"):
        validate_against_schema(invalid_token, "approval.schema.json")


def test_schema_format_checker_rejects_invalid_datetime():
    """Ensure date-time format validation rejects malformed date strings."""
    invalid_token = {
        "schema_version": "2020-12",
        "token_id": "tok-12345678",
        "action": "task_execution",
        "repository": "moruku36/ai-engineering-factory",
        "task_id": "TASK-001",
        "head_sha": "a" * 40,
        "target_ref": "refs/heads/main",
        "argv_digest": "0" * 64,
        "policy_hash": "1" * 64,
        "plan_hash": "2" * 64,
        "approved_by": "alice",
        "created_at": "2026-09-17T00:00:00Z",
        "expires_at": "not-a-valid-datetime",
        "consumed": False,
        "key_id": "3" * 64,
        "operator_signature": "4" * 64,
    }
    with pytest.raises(jsonschema.ValidationError, match="is not a 'date-time'"):
        validate_against_schema(invalid_token, "approval.schema.json")


