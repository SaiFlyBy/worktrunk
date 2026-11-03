#!/usr/bin/env python3
"""Verify durable evidence bindings for repository source-surface maps."""
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
        raise ValueError(f"evidence reference must be mission-relative: {ref}")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"evidence reference escapes mission root: {ref}")
    return resolved


def _verify_bound_file(
    root: Path,
    rel: str,
    label: str,
    ref: Any,
    expected_sha: Any,
    issues: list[str],
) -> None:
    if not isinstance(ref, str) or not ref:
        issues.append(f"{rel}: {label} reference is missing")
        return
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        issues.append(f"{rel}: {label} sha256 is missing or malformed")
        return
    try:
        path = resolve_ref(root, ref)
    except ValueError as exc:
        issues.append(f"{rel}: {label}: {exc}")
        return
    if not path.is_file():
        issues.append(f"{rel}: {label} evidence is missing: {ref}")
        return
    actual = sha256(path)
    if actual != expected_sha:
        issues.append(
            f"{rel}: {label} sha256 mismatch: expected {expected_sha}, actual {actual}"
        )


def collect_issues(root: Path, phase: str) -> list[str]:
    root = root.resolve()
    surface_dir = root / "corpus" / "source-surfaces"
    paths = sorted(surface_dir.glob("*.json")) if surface_dir.is_dir() else []
    if not paths:
        return []

    registry_path = root / "corpus" / "SOURCES.json"
    registry_mission: str | None = None
    if registry_path.is_file():
        try:
            registry_mission = load_json(registry_path).get("mission_id")
        except Exception:
            registry_mission = None

    issues: list[str] = []
    seen_sources: set[str] = set()
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            value = load_json(path)
        except Exception as exc:
            issues.append(f"{rel}: {exc}")
            continue

        source_id = value.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            issues.append(f"{rel}: source_id is missing")
        elif source_id in seen_sources:
            issues.append(f"{rel}: duplicate source_id {source_id}")
        else:
            seen_sources.add(source_id)
        if isinstance(source_id, str) and path.stem != source_id:
            issues.append(f"{rel}: filename must equal source_id ({source_id}.json)")

        if registry_mission is not None and value.get("mission_id") != registry_mission:
            issues.append(
                f"{rel}: mission_id {value.get('mission_id')!r} differs from SOURCES.json {registry_mission!r}"
            )

        exhausted = value.get("coverage_status") == "EXHAUSTED"
        if phase in {"pre-mutation", "qualification"} and not exhausted:
            # The semantic validator also reports this; retain the evidence-layer
            # assertion so this command is independently fail-closed.
            issues.append(f"{rel}: source surface is not EXHAUSTED before {phase}")

        if exhausted:
            _verify_bound_file(
                root,
                rel,
                "root inventory",
                value.get("root_inventory_ref"),
                value.get("root_inventory_sha256"),
                issues,
            )
            _verify_bound_file(
                root,
                rel,
                "terminal receipt",
                value.get("terminal_receipt_ref"),
                value.get("terminal_receipt_sha256"),
                issues,
            )

        for partition in value.get("partitions", []):
            if not isinstance(partition, dict):
                continue
            status = partition.get("status")
            evidence = partition.get("coverage_evidence", [])
            if status in {
                "INSPECTED",
                "EXCLUDED_GENERATED",
                "EXCLUDED_VENDOR",
                "EXCLUDED_BINARY",
                "EXCLUDED_IRRELEVANT_WITH_RATIONALE",
            } and not evidence:
                issues.append(
                    f"{rel}: terminal partition {partition.get('partition_id')} lacks coverage_evidence"
                )

        auxiliary = value.get("auxiliary_surfaces", {})
        if isinstance(auxiliary, dict):
            for name, surface in auxiliary.items():
                if not isinstance(surface, dict):
                    continue
                present = surface.get("present")
                status = surface.get("status")
                locators = surface.get("locators", [])
                if present is True and status == "INSPECTED" and not locators:
                    issues.append(f"{rel}: present auxiliary surface {name} lacks locators")
                if present is False and status == "NOT_PRESENT" and locators:
                    issues.append(
                        f"{rel}: absent auxiliary surface {name} must not carry locators"
                    )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--phase",
        choices=("design", "pre-mutation", "qualification"),
        default="design",
    )
    args = parser.parse_args()
    issues = collect_issues(Path(args.root), args.phase)
    if issues:
        for item in issues:
            print(f"ERROR: {item}")
        return 1
    print(f"source surface evidence valid for phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
