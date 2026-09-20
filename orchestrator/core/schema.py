"""Schema validation and parsing engine for AI Engineering Factory."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from jsonschema import Draft202012Validator
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MiB
MAX_NESTING_DEPTH = 20
SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


class UniqueKeySafeLoader(yaml.SafeLoader):
    """YAML safe loader that strictly forbids duplicate keys and tracks depth."""



def _construct_mapping(loader: UniqueKeySafeLoader, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
    if not isinstance(node, MappingNode):
        raise ConstructorError(None, None, f"expected a mapping node, but found {node.id}", node.start_mark)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError("while constructing a mapping", node.start_mark, f"found duplicate key '{key}'", key_node.start_mark)
        value = loader.construct_object(value_node, deep=deep)
        mapping[key] = value
    return mapping


UniqueKeySafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _check_depth(val: Any, current_depth: int = 1) -> None:
    if current_depth > MAX_NESTING_DEPTH:
        raise ValueError(f"Exceeded maximum nesting depth of {MAX_NESTING_DEPTH}")
    if isinstance(val, dict):
        for v in val.values():
            _check_depth(v, current_depth + 1)
    elif isinstance(val, list):
        for item in val:
            _check_depth(item, current_depth + 1)


def parse_safe_yaml(content: str) -> dict[str, Any]:
    """Parse YAML content with safety constraints:
    - Max size 1 MiB
    - No aliases / anchors / custom tags
    - No duplicate keys
    - Max depth 20
    """
    if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"Payload exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES} bytes (1 MiB)")

    # Disallow custom tags / aliases by checking compose tree
    events = list(yaml.parse(content, Loader=UniqueKeySafeLoader))
    for event in events:
        if isinstance(event, yaml.AliasEvent):
            raise TypeError("YAML aliases and anchors are prohibited")

    data = yaml.load(content, Loader=UniqueKeySafeLoader)
    if not isinstance(data, dict):
        raise TypeError("Root YAML structure must be a mapping/dict")

    _check_depth(data)
    return data


def load_schema(schema_name: str) -> dict[str, Any]:
    schema_path = SCHEMAS_DIR / schema_name
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


DEFAULT_FORMAT_CHECKER = jsonschema.FormatChecker()



@DEFAULT_FORMAT_CHECKER.checks("date-time")
def _validate_datetime_format(val: Any) -> bool:
    """Validate RFC 3339 / ISO 8601 date-time with explicit timezone."""
    if not isinstance(val, str):
        return False
    try:
        dt = datetime.fromisoformat(val)
        return dt.tzinfo is not None

    except (ValueError, TypeError):
        return False


def validate_against_schema(data: dict[str, Any], schema_name: str) -> None:
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=DEFAULT_FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        msg = "; ".join([f"{list(e.path)}: {e.message}" for e in errors])
        raise jsonschema.ValidationError(f"Schema validation failed for {schema_name}: {msg}")



def compute_spec_digest(task_data: dict[str, Any]) -> str:
    """Calculate SHA256 spec digest excluding 'status' and 'state_ref'."""
    data_for_hash = {k: v for k, v in task_data.items() if k not in ("status", "state_ref")}
    canonical_json = json.dumps(data_for_hash, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def check_circular_dependencies(tasks: dict[str, dict[str, Any]]) -> None:
    """Check task dependencies for:
    - self-dependency
    - unknown dependency
    - circular dependency
    """
    all_ids = set(tasks.keys())
    for tid, task in tasks.items():
        deps = task.get("dependencies", [])
        if tid in deps:
            raise ValueError(f"Self dependency detected in task {tid}")
        for dep in deps:
            if dep not in all_ids:
                raise ValueError(f"Task {tid} references unknown dependency '{dep}'")

    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in tasks[node].get("dependencies", []):
            if neighbor not in visited:
                dfs(neighbor, path + [neighbor])
            elif neighbor in rec_stack:
                cycle = " -> ".join(path + [neighbor])
                raise ValueError(f"Circular dependency detected: {cycle}")
        rec_stack.remove(node)

    for tid in tasks:
        if tid not in visited:
            dfs(tid, [tid])


class CapabilityStatus:
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNAVAILABLE = "UNAVAILABLE"
    MANUAL_ONLY = "MANUAL_ONLY"


class EnvironmentCapabilityProbe:
    """Probes host execution environment and tools without fabricating capabilities."""

    def probe_all(self) -> dict[str, Any]:
        import shutil
        import subprocess
        import sys

        # Python
        python_info = {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "status": CapabilityStatus.VERIFIED,
        }

        # Git
        git_path = shutil.which("git")
        if git_path:
            git_res = subprocess.run(
                [git_path, "--version"], capture_output=True, text=True, check=False, timeout=15
            )
            git_ver = git_res.stdout.strip() if git_res.returncode == 0 else None
            git_info = {
                "status": CapabilityStatus.VERIFIED if git_ver else CapabilityStatus.UNAVAILABLE,
                "version": git_ver,
                "path": git_path,
            }
        else:
            git_info = {"status": CapabilityStatus.UNAVAILABLE, "version": None}

        # GitHub CLI (gh)
        gh_path = shutil.which("gh")
        if gh_path:
            try:
                gh_res = subprocess.run(
                    [gh_path, "auth", "status"], capture_output=True, text=True, check=False, timeout=30
                )
                is_auth = gh_res.returncode == 0
            except subprocess.TimeoutExpired:
                is_auth = False
            gh_info = {
                "status": CapabilityStatus.VERIFIED if is_auth else CapabilityStatus.MANUAL_ONLY,
                "authenticated": is_auth,
                "path": gh_path,
            }
        else:
            gh_info = {"status": CapabilityStatus.UNAVAILABLE, "authenticated": False}

        # Antigravity CLI
        agy_path = shutil.which("agy")
        agy_info = {
            "status": CapabilityStatus.UNVERIFIED if agy_path else CapabilityStatus.UNAVAILABLE,
            "path": agy_path,
            "note": "Binary detected; execution contract unverified" if agy_path else "agy CLI not detected in PATH",
        }

        # Isolation
        isolation_info = {
            "worktree_support": None,
            "runtime_root_isolation": None,
            "status": CapabilityStatus.MANUAL_ONLY,
            "note": "OS isolation has not been probed; environment filtering is not a sandbox",
        }

        return {
            "python": python_info,
            "git": git_info,
            "gh": gh_info,
            "antigravity_cli": agy_info,
            "isolation": isolation_info,
        }


class PlanIngestionEngine:
    """Validates and ingests execution plans according to plan.schema.json."""

    @staticmethod
    def ingest_plan(plan_dict: dict[str, Any], available_tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
        validate_against_schema(plan_dict, "plan.schema.json")
        task_refs = plan_dict["task_refs"]

        # Ensure all task refs exist in available_tasks
        missing = [t for t in task_refs if t not in available_tasks]
        if missing:
            raise KeyError(f"Plan references unknown tasks not present in repository: {missing}")

        # Check for circular dependencies among referenced tasks
        referenced_tasks = {t: available_tasks[t] for t in task_refs}
        check_circular_dependencies(referenced_tasks)

        return plan_dict

