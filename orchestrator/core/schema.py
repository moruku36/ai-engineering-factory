"""Schema validation and parsing engine for AI Engineering Factory."""

import hashlib
import json
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


def validate_against_schema(data: dict[str, Any], schema_name: str) -> None:
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema)
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
