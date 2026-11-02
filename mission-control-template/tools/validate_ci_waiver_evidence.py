#!/usr/bin/env python3
"""Verify CI qualification waiver evidence is durable and mission-local."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_ref(root: Path, ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute():
        raise ValueError(f"waiver evidence reference must be mission-relative: {ref}")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"waiver evidence reference escapes mission root: {ref}")
    return resolved


def collect_issues(root: Path) -> list[str]:
    root = root.resolve()
    matrix_path = root / "control" / "CI_QUALIFICATION_MATRIX.json"
    if not matrix_path.is_file():
        return ["missing control/CI_QUALIFICATION_MATRIX.json"]
    try:
        matrix = load_json(matrix_path)
    except Exception as exc:
        return [f"control/CI_QUALIFICATION_MATRIX.json: {exc}"]

    issues: list[str] = []
    for gate in matrix.get("gates", []):
        if not isinstance(gate, dict) or gate.get("status") != "WAIVED":
            continue
        gate_id = gate.get("gate_id")
        waiver = gate.get("waiver")
        if not isinstance(waiver, dict):
            issues.append(f"gate {gate_id} is WAIVED without waiver authority object")
            continue
        evidence_ref = waiver.get("evidence_ref")
        expected_sha = waiver.get("evidence_sha256")
        if not isinstance(evidence_ref, str) or not evidence_ref:
            issues.append(f"gate {gate_id} waiver lacks evidence_ref")
            continue
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            issues.append(f"gate {gate_id} waiver lacks a 64-hex evidence_sha256")
            continue
        try:
            evidence_path = resolve_ref(root, evidence_ref)
        except ValueError as exc:
            issues.append(f"gate {gate_id}: {exc}")
            continue
        if not evidence_path.is_file():
            issues.append(f"gate {gate_id} waiver evidence is missing: {evidence_ref}")
            continue
        actual_sha = sha256(evidence_path)
        if actual_sha != expected_sha:
            issues.append(
                f"gate {gate_id} waiver evidence sha256 mismatch: expected {expected_sha}, actual {actual_sha}"
            )
        evidence_refs = gate.get("evidence_refs", [])
        if evidence_ref not in evidence_refs:
            issues.append(
                f"gate {gate_id} waiver evidence_ref is not retained in gate evidence_refs: {evidence_ref}"
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    issues = collect_issues(Path(args.root))
    if issues:
        for item in issues:
            print(f"ERROR: {item}")
        return 1
    print("CI waiver evidence custody valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
