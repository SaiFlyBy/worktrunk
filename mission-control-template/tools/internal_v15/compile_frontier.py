#!/usr/bin/env python3
"""Generic deterministic Mission Control frontier compiler.

The descriptor—not the worker—chooses objectives, exact context, consumers and output
scope. Structured results are schema-bound before dispatch. Receipt-based session reuse
is the default; FRESH_ONLY is an explicit reason-bearing exception.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from validate_json_schema_subset import validate, validate_schema_keywords

DEFAULT_SESSION_REUSE_POLICY = {
    "default_mode": "REUSE_IF_RECEIPT_MATCHES",
    "prefer_hot_before_cold_spawn": True,
    "stop_destroys_session": False,
    "fresh_override_requires_reason": True,
}


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    require(ref.startswith("#/"), f"only local refs are supported: {ref}")
    node: Any = root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        require(isinstance(node, dict) and key in node, f"unresolvable ref: {ref}")
        node = node[key]
    require(isinstance(node, dict), f"ref does not resolve to object: {ref}")
    return node


def template_value(schema: dict[str, Any], root: dict[str, Any]) -> Any:
    if "$ref" in schema:
        return template_value(resolve_ref(root, schema["$ref"]), root)
    if "const" in schema:
        return schema["const"]
    expected = schema.get("type")
    if isinstance(expected, list):
        if "null" in expected:
            return None
        expected = expected[0] if expected else None
    if expected == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {k: template_value(props[k], root) for k in schema.get("required", []) if k in props}
    if expected == "array":
        return []
    if expected == "string":
        return schema.get("enum", [""])[0]
    if expected == "integer":
        return int(schema.get("minimum", 0))
    if expected == "number":
        return schema.get("minimum", 0)
    if expected == "boolean":
        return False
    if expected == "null":
        return None
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return template_value(schema["anyOf"][0], root)
    if "oneOf" in schema:
        return template_value(schema["oneOf"][0], root)
    raise ValueError(f"cannot derive template for schema fragment: {schema}")


def policy_for(desc: dict[str, Any]) -> dict[str, Any]:
    policy = dict(DEFAULT_SESSION_REUSE_POLICY)
    supplied = desc.get("session_reuse_policy")
    if supplied is not None:
        require(isinstance(supplied, dict), "session_reuse_policy must be an object")
        policy.update(supplied)
    return policy


def prefixes(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        parts = [p for p in path.split("/") if p]
        for depth in (1, 2, 3):
            if len(parts) >= depth:
                out.add("/".join(parts[:depth]))
    return out


def nongate(consumers: list[str]) -> set[str]:
    return {c for c in consumers if re.fullmatch(r"G\d+[A-Z]*", c) is None}


def affinity(desc: dict[str, Any], cell: dict[str, Any]) -> list[dict[str, Any]]:
    c_paths = set(cell["context_paths"])
    c_prefixes = prefixes(cell["context_paths"])
    c_consumers = nongate(cell["consumers"])
    peers = []
    for other in desc["cells"]:
        if other["id"] == cell["id"]:
            continue
        exact = sorted(c_paths & set(other["context_paths"]))
        pref = sorted(c_prefixes & prefixes(other["context_paths"]))
        consumers = sorted(c_consumers & nongate(other["consumers"]))
        score = 100 * len(exact) + 10 * len(pref) + 2 * len(consumers)
        if score > 0:
            peers.append({"cell_id": other["id"], "score": score, "exact_context_overlap": exact, "shared_context_prefixes": pref, "shared_consumers": consumers})
    peers.sort(key=lambda item: (-item["score"], item["cell_id"]))
    return peers


def reuse_mode(desc: dict[str, Any], cell: dict[str, Any]) -> tuple[str, str | None]:
    policy = policy_for(desc)
    mode = cell.get("session_reuse_mode", policy["default_mode"])
    require(mode in {"REUSE_IF_RECEIPT_MATCHES", "FRESH_ONLY", "PIN_SESSION"}, f"invalid reuse mode for {cell['id']}: {mode}")
    reason = cell.get("fresh_session_reason")
    if mode == "FRESH_ONLY" and policy.get("fresh_override_requires_reason", True):
        require(bool(reason), f"{cell['id']} uses FRESH_ONLY without fresh_session_reason")
    return mode, reason


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("descriptor", type=Path)
    p.add_argument("--destination", type=Path, default=Path(".mission-control/compiled"))
    p.add_argument("--check", action="store_true")
    a = p.parse_args()

    d = json.loads(a.descriptor.read_text(encoding="utf-8"))
    for k in ("frontier_id", "control_base", "target_base", "cells", "result_schema"):
        require(k in d, f"missing {k}")
    policy = policy_for(d)
    require(policy.get("stop_destroys_session") is False, "cell STOP must not imply session destruction")
    if policy["default_mode"] == "FRESH_ONLY" and policy.get("fresh_override_requires_reason", True):
        require(bool(policy.get("default_fresh_reason")), "frontier-wide FRESH_ONLY requires explicit default_fresh_reason")

    result_schema_path = Path(d["result_schema"])
    require(result_schema_path.is_file(), f"result schema not readable: {result_schema_path}")
    result_schema = json.loads(result_schema_path.read_text(encoding="utf-8"))
    require(isinstance(result_schema, dict), "result schema must be an object")
    validate_schema_keywords(result_schema)

    ids = set()
    fresh_overrides = []
    for c in d["cells"]:
        for k in ("id", "topic", "objective", "context_paths", "consumers"):
            require(k in c, f"cell missing {k}")
        require(c["id"] not in ids, f"duplicate cell {c['id']}")
        ids.add(c["id"])
        require(c["context_paths"], f"{c['id']} has no exact context")
        require(c["consumers"], f"{c['id']} has no consumer/eval purpose")
        mode, reason = reuse_mode(d, c)
        if mode == "FRESH_ONLY":
            fresh_overrides.append({"cell_id": c["id"], "reason": reason})
        template = template_value(result_schema, result_schema)
        require(isinstance(template, dict), "result schema must produce object result")
        if "cell_id" in template:
            template["cell_id"] = c["id"]
        errors = validate(template, result_schema, result_schema)
        require(not errors, f"schema-invalid generated template for {c['id']}: {errors}")

    schema_sha = hashlib.sha256(canonical(result_schema)).hexdigest()
    if a.check:
        print(json.dumps({
            "state": "PASS",
            "frontier_id": d["frontier_id"],
            "cells": len(d["cells"]),
            "result_schema_sha256": schema_sha,
            "result_templates": "SCHEMA_VALID",
            "default_session_reuse_mode": policy["default_mode"],
            "prefer_hot_before_cold_spawn": policy.get("prefer_hot_before_cold_spawn", True),
            "stop_destroys_session": False,
            "fresh_only_overrides": fresh_overrides,
        }))
        return 0

    root = a.destination / d["frontier_id"]
    root.mkdir(parents=True, exist_ok=True)
    index = []
    reuse_cells = {}
    for c in d["cells"]:
        cr = root / c["id"]
        cr.mkdir(parents=True, exist_ok=True)
        manifest = {"cell_id": c["id"], "target_base": d["target_base"], "items": c["context_paths"], "hash_policy": "CANONICAL_JSON_SHA256"}
        result_template = template_value(result_schema, result_schema)
        if "cell_id" in result_template:
            result_template["cell_id"] = c["id"]
        schema_path = cr / "result_schema.json"
        template_path = cr / "result_template.json"
        mode, reason = reuse_mode(d, c)
        peer_list = affinity(d, c)[:8]
        workcell = {
            "cell_id": c["id"],
            "control_base": d["control_base"],
            "objective": c["objective"],
            "consumers": c["consumers"],
            "owned_scope": [f"control/archaeology/{c['id']}/**"],
            "context_manifest": "context_manifest.json",
            "worker_self_orientation": False,
            "context_expansion": "AMENDMENT_ONLY",
            "stop": "STOP_CELL_NOT_SESSION",
            "session_reuse_policy": {
                "mode": mode,
                "preferred_peer_cells": [item["cell_id"] for item in peer_list],
                "fresh_session_reason": reason,
            },
            "result_contract": {
                "schema_ref": schema_path.as_posix(),
                "schema_sha256": schema_sha,
                "template_ref": template_path.as_posix(),
                "precommit_validator": f"python control/tools/validate_json_schema_subset.py {schema_path.as_posix()} <result.json>",
                "invalid_output_policy": "SAME_ATTEMPT_CORRECTION_BEFORE_SETTLEMENT_NO_AGGREGATE_NORMALIZATION",
            },
        }
        (cr / "context_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (cr / "workcell.json").write_text(json.dumps(workcell, indent=2) + "\n", encoding="utf-8")
        schema_path.write_text(json.dumps(result_schema, indent=2) + "\n", encoding="utf-8")
        template_path.write_text(json.dumps(result_template, indent=2) + "\n", encoding="utf-8")
        index.append({
            "cell_id": c["id"],
            "manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
            "result_schema_sha256": schema_sha,
            "result_template": template_path.as_posix(),
            "session_reuse_mode": mode,
            "preferred_peer_cells": [item["cell_id"] for item in peer_list],
        })
        reuse_cells[c["id"]] = {"mode": mode, "preferred_peer_cells": peer_list}

    reuse_plan = {
        "schema": "mission-control/session-reuse-plan/1",
        "frontier_id": d["frontier_id"],
        "default_mode": policy["default_mode"],
        "stop_destroys_session": False,
        "prefer_hot_before_cold_spawn": policy.get("prefer_hot_before_cold_spawn", True),
        "cold_spawn_law": "Prefer compatible live sessions with accepted ContextReceipts when reuse plus INGEST_DELTA is cheaper. Spawn cold only when no safe match exists or recorded marginal parallel/critical-path value exceeds reuse savings.",
        "cells": reuse_cells,
    }
    reuse_path = root / "SESSION_REUSE_PLAN.json"
    reuse_path.write_text(json.dumps(reuse_plan, indent=2) + "\n", encoding="utf-8")
    (root / "INDEX.json").write_text(json.dumps({"frontier_id": d["frontier_id"], "session_reuse_plan": reuse_path.as_posix(), "cells": index}, indent=2) + "\n", encoding="utf-8")
    print(root / "INDEX.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
