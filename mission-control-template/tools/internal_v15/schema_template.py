#!/usr/bin/env python3
"""Deterministic, fail-closed template generation for the Mission Control JSON-Schema subset."""
from __future__ import annotations

import re
from typing import Any


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _resolve(root: dict[str, Any], ref: str) -> dict[str, Any]:
    _require(ref.startswith("#/"), f"only local schema refs are supported: {ref}")
    node: Any = root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        _require(isinstance(node, dict) and key in node, f"unresolvable schema ref: {ref}")
        node = node[key]
    _require(isinstance(node, dict), f"schema ref does not resolve to object: {ref}")
    return node


def template_value(schema: dict[str, Any], root: dict[str, Any]) -> Any:
    if "$ref" in schema:
        return template_value(_resolve(root, schema["$ref"]), root)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        return examples[0]
    expected = schema.get("type")
    if isinstance(expected, list):
        if "null" in expected:
            return None
        expected = expected[0] if expected else None
    if expected == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {key: template_value(props[key], root) for key in schema.get("required", []) if key in props}
    if expected == "array":
        count = int(schema.get("minItems", 0))
        if count == 0:
            return []
        item_schema = schema.get("items")
        _require(isinstance(item_schema, dict), "minItems>0 requires an object items schema")
        return [template_value(item_schema, root) for _ in range(count)]
    if expected == "string":
        min_length = int(schema.get("minLength", 0))
        candidate = "x" * max(min_length, 1 if min_length else 0)
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, candidate) is None:
            raise ValueError(f"cannot deterministically synthesize pattern {pattern!r}; bind the field before validation")
        return candidate
    if expected == "integer":
        return int(schema.get("minimum", 0))
    if expected == "number":
        return schema.get("minimum", 0)
    if expected == "boolean":
        return False
    if expected == "null":
        return None
    if "anyOf" in schema:
        return template_value(schema["anyOf"][0], root)
    if "oneOf" in schema:
        return template_value(schema["oneOf"][0], root)
    raise ValueError(f"cannot derive deterministic template for schema fragment: {schema}")
