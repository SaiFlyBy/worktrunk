#!/usr/bin/env python3
"""Dependency-free validator for the JSON Schema subset used by Mission Control packets.

Fails on unsupported assertion keywords rather than silently accepting them. Supports
local #/... refs and the common object/array/scalar constraints used by control packets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ANNOTATIONS = {"$schema", "$id", "title", "description", "default", "examples", "$defs"}
SUPPORTED = {"$ref","const","enum","type","required","properties","additionalProperties","items","minItems","maxItems","minimum","maximum","minLength","maxLength","pattern","anyOf","oneOf"}


def json_type_ok(value: Any, expected: str) -> bool:
    if expected == "object": return isinstance(value, dict)
    if expected == "array": return isinstance(value, list)
    if expected == "string": return isinstance(value, str)
    if expected == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean": return isinstance(value, bool)
    if expected == "null": return value is None
    raise ValueError(f"unsupported JSON type {expected!r}")


def resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"only local refs are supported: {ref}")
    node: Any = root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"unresolvable ref: {ref}")
        node = node[key]
    if not isinstance(node, dict):
        raise ValueError(f"ref does not resolve to schema object: {ref}")
    return node


def validate_schema_keywords(schema: dict[str, Any], path: str = "$") -> None:
    for key, value in schema.items():
        if key in ANNOTATIONS:
            if key == "$defs" and isinstance(value, dict):
                for name, child in value.items():
                    if isinstance(child, dict): validate_schema_keywords(child, f"{path}.$defs.{name}")
            continue
        if key not in SUPPORTED:
            raise ValueError(f"unsupported schema assertion keyword {key!r} at {path}")
        if key == "properties" and isinstance(value, dict):
            for name, child in value.items():
                if isinstance(child, dict): validate_schema_keywords(child, f"{path}.properties.{name}")
        elif key in {"items", "additionalProperties"} and isinstance(value, dict):
            validate_schema_keywords(value, f"{path}.{key}")
        elif key in {"anyOf", "oneOf"} and isinstance(value, list):
            for i, child in enumerate(value):
                if isinstance(child, dict): validate_schema_keywords(child, f"{path}.{key}[{i}]")


def validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    if "$ref" in schema: return validate(value, resolve_ref(root, schema["$ref"]), root, path)
    if "const" in schema and value != schema["const"]: errors.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]: errors.append(f"{path}: value {value!r} not in enum {schema['enum']!r}")
    if "anyOf" in schema and not any(not validate(value, b, root, path) for b in schema["anyOf"]): errors.append(f"{path}: no anyOf branch matched")
    if "oneOf" in schema:
        matches = sum(1 for b in schema["oneOf"] if not validate(value, b, root, path))
        if matches != 1: errors.append(f"{path}: expected exactly one oneOf match, got {matches}")
    expected = schema.get("type")
    if expected is not None:
        expected_types = [expected] if isinstance(expected, str) else list(expected)
        if not any(json_type_ok(value, t) for t in expected_types):
            errors.append(f"{path}: expected type {expected_types!r}, got {type(value).__name__}")
            return errors
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value: errors.append(f"{path}: missing required property {key!r}")
        props = schema.get("properties", {})
        for key, child in props.items():
            if key in value: errors.extend(validate(value[key], child, root, f"{path}.{key}"))
        extras = set(value) - set(props)
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in sorted(extras): errors.append(f"{path}: additional property not allowed: {key!r}")
        elif isinstance(additional, dict):
            for key in extras: errors.extend(validate(value[key], additional, root, f"{path}.{key}"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]: errors.append(f"{path}: minItems {schema['minItems']} violated")
        if "maxItems" in schema and len(value) > schema["maxItems"]: errors.append(f"{path}: maxItems {schema['maxItems']} violated")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value): errors.extend(validate(item, schema["items"], root, f"{path}[{i}]"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]: errors.append(f"{path}: minLength {schema['minLength']} violated")
        if "maxLength" in schema and len(value) > schema["maxLength"]: errors.append(f"{path}: maxLength {schema['maxLength']} violated")
        if "pattern" in schema and re.search(schema["pattern"], value) is None: errors.append(f"{path}: pattern {schema['pattern']!r} not matched")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]: errors.append(f"{path}: minimum {schema['minimum']} violated")
        if "maximum" in schema and value > schema["maximum"]: errors.append(f"{path}: maximum {schema['maximum']} violated")
    return errors


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("schema", type=Path)
    p.add_argument("instance", type=Path)
    a = p.parse_args()
    root = json.loads(a.schema.read_text(encoding="utf-8"))
    instance = json.loads(a.instance.read_text(encoding="utf-8"))
    if not isinstance(root, dict): raise ValueError("schema root must be an object")
    validate_schema_keywords(root)
    errors = validate(instance, root, root)
    if errors:
        print(json.dumps({"state":"FAIL","errors":errors}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state":"PASS","schema":str(a.schema),"instance":str(a.instance)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
