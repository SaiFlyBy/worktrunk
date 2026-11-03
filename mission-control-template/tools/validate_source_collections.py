#!/usr/bin/env python3
"""Validate frozen dynamic source collections against the canonical source registry.

Collection coverage and provenance-review terminality are intentionally separate
contracts. This validator proves that a dynamic collection was frozen exactly,
that its raw membership evidence remains byte-identical, that every member
exists in SOURCES.json at the same identity/revision, and that repository
members have exhausted source-surface maps before mutation. The canonical
provenance-synthesis validator remains the authority for whether a
SYNTHESIS_REQUIRED or ADJUDICATED_SYNTHESIS review path has terminalized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from schema_subset import validate as validate_schema_instance, validate_schema_keywords


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def schemas_root(root: Path) -> Path:
    copied = root / "contracts" / "schemas"
    if copied.is_dir():
        return copied
    source = Path(__file__).resolve().parents[1] / "schemas"
    if source.is_dir():
        return source
    raise ValueError("cannot resolve Mission Control schemas")


def validate_doc(path: Path, schema_path: Path) -> tuple[dict[str, Any], list[str]]:
    value = load_json(path)
    schema = load_json(schema_path)
    validate_schema_keywords(schema)
    return value, validate_schema_instance(value, schema, schema, schema_path=schema_path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_evidence_ref(root: Path, ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute():
        raise ValueError(f"evidence reference must be mission-relative: {ref}")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"evidence reference escapes mission root: {ref}")
    return resolved


def canonical_items_sha256(items: list[dict[str, Any]]) -> str:
    normalized = sorted(
        (
            {
                "membership_evidence_id": item.get("membership_evidence_id"),
                "snapshot_revision": item.get("snapshot_revision"),
                "source_id": item.get("source_id"),
                "source_locator": item.get("source_locator"),
            }
            for item in items
        ),
        key=lambda item: (
            str(item.get("source_id")),
            str(item.get("source_locator")),
            str(item.get("snapshot_revision")),
            str(item.get("membership_evidence_id")),
        ),
    )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _surface_map_by_source(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    directory = root / "corpus" / "source-surfaces"
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            value = load_json(path)
        except Exception:
            continue
        source_id = value.get("source_id")
        if isinstance(source_id, str) and source_id:
            out[source_id] = value
    return out


def collect_issues(root: Path, phase: str) -> list[str]:
    root = root.resolve()
    directory = root / "corpus" / "source-collections"
    collection_paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not collection_paths:
        return []

    schemas = schemas_root(root)
    schema_path = schemas / "SOURCE_COLLECTION_SNAPSHOT_SCHEMA.json"
    registry_path = root / "corpus" / "SOURCES.json"
    if not registry_path.is_file():
        return ["dynamic source collections exist but corpus/SOURCES.json is missing"]
    try:
        registry, registry_errors = validate_doc(registry_path, schemas / "SOURCE_REGISTRY_SCHEMA.json")
    except Exception as exc:
        return [f"corpus/SOURCES.json: {exc}"]
    issues = [f"corpus/SOURCES.json: {error}" for error in registry_errors]
    sources = {
        item.get("id"): item
        for item in registry.get("sources", [])
        if isinstance(item, dict) and item.get("id")
    }
    surface_maps = _surface_map_by_source(root)
    collection_ids: set[str] = set()

    for path in collection_paths:
        rel = path.relative_to(root).as_posix()
        try:
            value, errors = validate_doc(path, schema_path)
        except Exception as exc:
            issues.append(f"{rel}: {exc}")
            continue
        issues.extend(f"{rel}: {error}" for error in errors)
        collection_id = value.get("collection_id")
        if collection_id in collection_ids:
            issues.append(f"{rel}: duplicate collection_id {collection_id}")
        collection_ids.add(collection_id)

        retrieval = value.get("retrieval", {})
        raw_evidence = retrieval.get("raw_evidence", []) if isinstance(retrieval, dict) else []
        evidence_ids = [item.get("evidence_id") for item in raw_evidence if isinstance(item, dict)]
        evidence_refs = [item.get("ref") for item in raw_evidence if isinstance(item, dict)]
        if len(evidence_ids) != len(set(evidence_ids)):
            issues.append(f"{rel}: duplicate raw evidence_id values")
        if len(evidence_refs) != len(set(evidence_refs)):
            issues.append(f"{rel}: duplicate raw evidence refs")
        known_evidence_ids = set(evidence_ids)
        for evidence in raw_evidence:
            if not isinstance(evidence, dict):
                continue
            evidence_id = evidence.get("evidence_id")
            evidence_ref = evidence.get("ref")
            expected = evidence.get("sha256")
            try:
                evidence_path = resolve_evidence_ref(root, str(evidence_ref))
            except ValueError as exc:
                issues.append(f"{rel}: raw evidence {evidence_id}: {exc}")
                continue
            if not evidence_path.is_file():
                issues.append(f"{rel}: raw evidence {evidence_id} is missing: {evidence_ref}")
                continue
            actual = sha256(evidence_path)
            if actual != expected:
                issues.append(
                    f"{rel}: raw evidence {evidence_id} sha256 mismatch: expected {expected}, actual {actual}"
                )

        items = value.get("items", [])
        if value.get("item_count") != len(items):
            issues.append(
                f"{rel}: item_count={value.get('item_count')} does not equal actual item count {len(items)}"
            )
        reported_total = retrieval.get("reported_total") if isinstance(retrieval, dict) else None
        if reported_total is not None and reported_total != len(items):
            issues.append(
                f"{rel}: provider reported_total={reported_total} does not equal frozen item count {len(items)}"
            )
        actual_digest = canonical_items_sha256(items)
        if value.get("items_sha256") != actual_digest:
            issues.append(f"{rel}: items_sha256 mismatch; expected {actual_digest}")
        if phase in {"pre-mutation", "qualification"} and value.get("frozen") is not True:
            issues.append(f"{rel}: collection must be frozen before {phase}")

        source_ids = [item.get("source_id") for item in items]
        locators = [item.get("source_locator") for item in items]
        if len(source_ids) != len(set(source_ids)):
            issues.append(f"{rel}: duplicate source_id values inside collection")
        if len(locators) != len(set(locators)):
            issues.append(f"{rel}: duplicate source_locator values inside collection")

        for item in items:
            source_id = item.get("source_id")
            locator = item.get("source_locator")
            revision = item.get("snapshot_revision")
            membership_evidence_id = item.get("membership_evidence_id")
            if membership_evidence_id not in known_evidence_ids:
                issues.append(
                    f"{rel}: collection member {source_id} references unknown membership evidence "
                    f"{membership_evidence_id!r}"
                )
            record = sources.get(source_id)
            if record is None:
                issues.append(f"{rel}: collection member {source_id} has no SOURCES.json record")
                continue
            if record.get("kind") != "REPOSITORY":
                issues.append(f"{rel}: collection member {source_id} is not a REPOSITORY source")
            if record.get("locator") != locator:
                issues.append(
                    f"{rel}: member {source_id} locator {locator!r} does not match "
                    f"SOURCES.json locator {record.get('locator')!r}"
                )
            pin = record.get("pin")
            if pin and pin != revision:
                issues.append(
                    f"{rel}: member {source_id} snapshot revision {revision!r} does not match registry pin {pin!r}"
                )
            if phase in {"pre-mutation", "qualification"}:
                # Do not reinterpret SOURCE_REGISTRY.disposition as lifecycle state.
                # SYNTHESIS_REQUIRED is the normal review path and may remain the
                # registry disposition after a complete/verified source assessment.
                # Provenance terminality is validated by the canonical provenance
                # synthesis gate; this collection gate proves item-for-item coverage.
                surface = surface_maps.get(source_id)
                if surface is None:
                    issues.append(f"{rel}: collection member {source_id} lacks an exhausted source-surface map")
                elif surface.get("coverage_status") != "EXHAUSTED":
                    issues.append(
                        f"{rel}: collection member {source_id} source-surface map is not EXHAUSTED"
                    )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--phase", choices=("design", "pre-mutation", "qualification"), default="design")
    args = parser.parse_args()
    issues = collect_issues(Path(args.root), args.phase)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print(f"source collection contracts valid for phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
