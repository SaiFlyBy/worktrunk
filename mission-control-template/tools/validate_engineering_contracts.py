#!/usr/bin/env python3
"""Validate Mission Control engineering contracts and cross-document closure.

This validator is intentionally standard-library only and uses the template's
JSON-schema subset validator. It supplements the core operator CLI with the
high-assurance specification/source/mutation/CI contracts used by large
engineering missions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from schema_subset import validate as validate_schema_instance, validate_schema_keywords


CONTRACTS = {
    "specification": ("control/SPECIFICATION.json", "SPECIFICATION_CONTRACT_SCHEMA.json"),
    "ledger": ("corpus/ENGINEERING_LEDGER.json", "ENGINEERING_LEDGER_SCHEMA.json"),
    "ci": ("control/CI_QUALIFICATION_MATRIX.json", "CI_QUALIFICATION_MATRIX_SCHEMA.json"),
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def schema_root(root: Path) -> Path:
    copied = root / "contracts" / "schemas"
    if copied.is_dir():
        return copied
    source = Path(__file__).resolve().parents[1] / "schemas"
    if source.is_dir():
        return source
    raise ValueError("cannot resolve engineering-contract schemas")


def validate_doc(path: Path, schema_path: Path) -> tuple[dict[str, Any], list[str]]:
    value = load_json(path)
    schema = load_json(schema_path)
    validate_schema_keywords(schema)
    return value, validate_schema_instance(value, schema, schema, schema_path=schema_path)


def _source_map_issues(value: dict[str, Any], name: str, phase: str) -> list[str]:
    issues: list[str] = []
    partitions = value.get("partitions", [])
    partition_ids = [item.get("partition_id") for item in partitions if isinstance(item, dict)]
    if len(partition_ids) != len(set(partition_ids)):
        issues.append(f"{name}: duplicate partition_id values")

    if phase in {"pre-mutation", "qualification"} and value.get("coverage_status") != "EXHAUSTED":
        issues.append(f"{name}: repository source must be EXHAUSTED before {phase}")

    if value.get("coverage_status") == "EXHAUSTED":
        if value.get("rights_status") != "RESOLVED":
            issues.append(f"{name}: EXHAUSTED source must have RESOLVED rights")
        if value.get("open_questions"):
            issues.append(f"{name}: EXHAUSTED source must have no open_questions")
        terminal = {
            "INSPECTED", "EXCLUDED_GENERATED", "EXCLUDED_VENDOR", "EXCLUDED_BINARY",
            "EXCLUDED_IRRELEVANT_WITH_RATIONALE",
        }
        for item in partitions:
            if item.get("status") not in terminal:
                issues.append(
                    f"{name}: EXHAUSTED source has nonterminal partition "
                    f"{item.get('partition_id')}: {item.get('status')}"
                )
            if item.get("criticality") == "CRITICAL" and item.get("status") != "INSPECTED":
                issues.append(
                    f"{name}: CRITICAL partition {item.get('partition_id')} must be INSPECTED, "
                    f"not {item.get('status')}"
                )
            if str(item.get("status", "")).startswith("EXCLUDED_") and not item.get("exclusion_reason"):
                issues.append(f"{name}: excluded partition {item.get('partition_id')} lacks exclusion_reason")
        for surface_name, surface in value.get("auxiliary_surfaces", {}).items():
            status = surface.get("status") if isinstance(surface, dict) else None
            present = surface.get("present") if isinstance(surface, dict) else None
            if status not in {"INSPECTED", "NOT_PRESENT"}:
                issues.append(f"{name}: auxiliary surface {surface_name} is not terminal: {status}")
            if present is True and status != "INSPECTED":
                issues.append(f"{name}: present auxiliary surface {surface_name} must be INSPECTED")
            if present is False and status != "NOT_PRESENT":
                issues.append(f"{name}: absent auxiliary surface {surface_name} must be NOT_PRESENT")
        if not value.get("terminal_receipt_ref") or not value.get("terminal_receipt_sha256"):
            issues.append(f"{name}: EXHAUSTED source lacks terminal receipt binding")
    return issues


def _spec_issues(value: dict[str, Any], phase: str) -> list[str]:
    issues: list[str] = []
    if phase in {"pre-mutation", "qualification"}:
        if value.get("state") != "FROZEN":
            issues.append(f"specification must be FROZEN before {phase}; amendments must be re-frozen")
        if value.get("open_questions"):
            issues.append(f"specification has unresolved open_questions before {phase}")
    behavior_ids = [item.get("behavior_id") for item in value.get("behaviors", [])]
    if len(behavior_ids) != len(set(behavior_ids)):
        issues.append("specification contains duplicate behavior_id values")
    invariant_ids = [item.get("invariant_id") for item in value.get("invariants", [])]
    if len(invariant_ids) != len(set(invariant_ids)):
        issues.append("specification contains duplicate invariant_id values")
    known_behaviors = set(behavior_ids)
    traced = set()
    for trace in value.get("traceability", []):
        behavior_id = trace.get("behavior_id")
        traced.add(behavior_id)
        if behavior_id not in known_behaviors:
            issues.append(f"spec traceability references unknown behavior {behavior_id}")
        if phase in {"pre-mutation", "qualification"}:
            if not trace.get("requirement_ids"):
                issues.append(f"spec behavior {behavior_id} has no requirement_ids")
            if not trace.get("verification_ids"):
                issues.append(f"spec behavior {behavior_id} has no verification_ids")
    if phase in {"pre-mutation", "qualification"}:
        missing = sorted(known_behaviors - traced)
        if missing:
            issues.append(f"spec behaviors lack traceability rows: {missing}")
    return issues


def _ledger_issues(
    value: dict[str, Any],
    phase: str,
    *,
    known_source_ids: set[str],
    known_requirement_ids: set[str],
    known_behavior_ids: set[str],
    surface_mechanism_ids: set[str],
) -> list[str]:
    issues: list[str] = []
    entries = value.get("entries", [])
    ids = [item.get("mechanism_id") for item in entries if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        issues.append("engineering ledger contains duplicate mechanism_id values")
    known_mechanisms = set(ids)

    for item in entries:
        mechanism_id = item.get("mechanism_id")
        unknown_sources = set(item.get("source_ids", [])) - known_source_ids
        if unknown_sources:
            issues.append(f"mechanism {mechanism_id} references unknown sources: {sorted(unknown_sources)}")
        impl = item.get("implementation", {})
        unknown_requirements = set(impl.get("target_requirements", [])) - known_requirement_ids
        if unknown_requirements:
            issues.append(
                f"mechanism {mechanism_id} references unknown target requirements: "
                f"{sorted(unknown_requirements)}"
            )
        if phase == "qualification":
            if item.get("authority_status") == "BLOCKED" or item.get("disposition") == "BLOCKED":
                issues.append(f"mechanism {mechanism_id} remains BLOCKED at qualification")
            disposition = item.get("disposition")
            if disposition in {"IMPLEMENT", "EXTEND", "COMBINE"}:
                if item.get("authority_status") != "ADMITTED":
                    issues.append(f"mechanism {mechanism_id} is landed but authority_status is not ADMITTED")
                if not impl.get("target_requirements"):
                    issues.append(f"mechanism {mechanism_id} has no target_requirements")
                if not impl.get("landed_locations"):
                    issues.append(f"mechanism {mechanism_id} has no landed_locations")
                if not item.get("verification", {}).get("verification_ids"):
                    issues.append(f"mechanism {mechanism_id} has no verification_ids")

    missing_from_ledger = sorted(surface_mechanism_ids - known_mechanisms)
    if missing_from_ledger:
        issues.append(f"source surface maps reference mechanisms missing from engineering ledger: {missing_from_ledger}")

    trace_requirement_ids: set[str] = set()
    trace_behavior_ids: set[str] = set()
    for trace in value.get("traceability", []):
        requirement_id = trace.get("requirement_id")
        trace_requirement_ids.add(requirement_id)
        for mechanism_id in trace.get("mechanism_ids", []):
            if mechanism_id not in known_mechanisms:
                issues.append(f"traceability references unknown mechanism {mechanism_id}")
        unknown_behaviors = set(trace.get("spec_behavior_ids", [])) - known_behavior_ids
        if unknown_behaviors:
            issues.append(
                f"traceability for requirement {requirement_id} references unknown spec behaviors: "
                f"{sorted(unknown_behaviors)}"
            )
        trace_behavior_ids.update(trace.get("spec_behavior_ids", []))
        if requirement_id not in known_requirement_ids:
            issues.append(f"traceability references unknown requirement {requirement_id}")
        if phase in {"pre-mutation", "qualification"}:
            if not trace.get("mechanism_ids"):
                issues.append(f"requirement {requirement_id} traceability has no mechanism_ids")
            if not trace.get("spec_behavior_ids"):
                issues.append(f"requirement {requirement_id} traceability has no spec_behavior_ids")
            if not trace.get("cell_ids"):
                issues.append(f"requirement {requirement_id} traceability has no cell_ids")
            if not trace.get("verification_ids"):
                issues.append(f"requirement {requirement_id} traceability has no verification_ids")
            if phase == "qualification" and not trace.get("qualification_gate_ids"):
                issues.append(f"requirement {requirement_id} traceability has no qualification_gate_ids")

    if phase in {"pre-mutation", "qualification"}:
        missing_requirements = sorted(known_requirement_ids - trace_requirement_ids)
        if missing_requirements:
            issues.append(f"active target requirements lack engineering-ledger traceability: {missing_requirements}")
        missing_behaviors = sorted(known_behavior_ids - trace_behavior_ids)
        if missing_behaviors:
            issues.append(f"spec behaviors lack engineering-ledger traceability: {missing_behaviors}")
    return issues


def _structural_plan_issues(value: dict[str, Any], name: str) -> list[str]:
    issues: list[str] = []
    surface_ids = [surface.get("surface_id") for surface in value.get("surfaces", [])]
    if len(surface_ids) != len(set(surface_ids)):
        issues.append(f"{name}: duplicate surface_id values")
    for surface in value.get("surfaces", []):
        if surface.get("engine") == "TEXT_ONLY_WITH_JUSTIFICATION" and not surface.get("text_fallback_rationale"):
            issues.append(f"{name}: text-only surface {surface.get('surface_id')} lacks fallback rationale")
        if surface.get("engine") != "TEXT_ONLY_WITH_JUSTIFICATION" and surface.get("text_fallback_rationale"):
            issues.append(f"{name}: structural surface {surface.get('surface_id')} carries an unnecessary text fallback rationale")
        if not surface.get("expected_affected"):
            issues.append(f"{name}: surface {surface.get('surface_id')} lacks expected_affected")
        if not surface.get("expected_unaffected"):
            issues.append(f"{name}: surface {surface.get('surface_id')} lacks expected_unaffected")
        if not surface.get("post_mutation_checks") and False:
            # Kept unreachable intentionally: post-mutation checks are mission-plan-wide below,
            # not duplicated per surface.
            issues.append("unreachable")
    if not value.get("post_mutation_checks"):
        issues.append(f"{name}: structural mutation plan lacks post_mutation_checks")
    return issues


def _ci_issues(
    value: dict[str, Any],
    phase: str,
    *,
    known_requirement_ids: set[str],
    known_behavior_ids: set[str],
) -> list[str]:
    issues: list[str] = []
    candidates = {item["repository"]: item["sha"].lower() for item in value.get("candidate", [])}
    gates = {item.get("gate_id"): item for item in value.get("gates", [])}
    if len(gates) != len(value.get("gates", [])):
        issues.append("CI qualification matrix contains duplicate gate_id values")
    for gate in value.get("gates", []):
        gate_id = gate.get("gate_id")
        repo = gate.get("repository")
        expected = candidates.get(repo)
        actual = str(gate.get("candidate_sha", "")).lower()
        if expected is None:
            issues.append(f"gate {gate_id} references repository outside candidate set: {repo}")
        elif expected != actual:
            issues.append(f"gate {gate_id} candidate SHA differs from matrix candidate")
        if gate.get("required") and phase == "qualification" and gate.get("status") not in {"PASS", "WAIVED"}:
            issues.append(f"required gate {gate_id} is not PASS/WAIVED: {gate.get('status')}")
        if gate.get("status") in {"NOT_RUN", "WAIVED"} and not gate.get("skip_classification"):
            issues.append(f"gate {gate_id} {gate.get('status')} lacks skip_classification")
        if gate.get("status") == "PASS" and not gate.get("evidence_refs"):
            issues.append(f"passing gate {gate_id} lacks evidence_refs")
        if gate.get("class") in {"REAL_ENVIRONMENT", "DEPLOYMENT_RECONCILIATION"} and not gate.get("real_path"):
            issues.append(f"gate {gate_id} is {gate.get('class')} but real_path is false")
        unknown_requirements = set(gate.get("requirement_ids", [])) - known_requirement_ids
        if unknown_requirements:
            issues.append(f"gate {gate_id} references unknown requirements: {sorted(unknown_requirements)}")
        unknown_behaviors = set(gate.get("behavior_ids", [])) - known_behavior_ids
        if unknown_behaviors:
            issues.append(f"gate {gate_id} references unknown behaviors: {sorted(unknown_behaviors)}")
        if gate.get("required") and not (gate.get("requirement_ids") or gate.get("behavior_ids")):
            issues.append(f"required gate {gate_id} proves no requirement or spec behavior")

    covered: dict[str, set[str]] = {}
    for row in value.get("coverage", []):
        subject = row.get("behavior_or_requirement_id")
        covered.setdefault(subject, set()).update(row.get("gate_ids", []))
        for gate_id in row.get("gate_ids", []):
            if gate_id not in gates:
                issues.append(f"coverage references unknown gate {gate_id}")

    if phase == "qualification":
        for subject in sorted(known_requirement_ids | known_behavior_ids):
            gate_ids = covered.get(subject, set())
            if not gate_ids:
                issues.append(f"qualification coverage missing for {subject}")
                continue
            if not any(gates.get(gate_id, {}).get("status") in {"PASS", "WAIVED"} for gate_id in gate_ids):
                issues.append(f"qualification coverage for {subject} has no PASS/WAIVED gate")

    required = [gate for gate in value.get("gates", []) if gate.get("required")]
    expected_summary = {
        "required_pass": sum(g.get("status") == "PASS" for g in required),
        "required_fail": sum(g.get("status") == "FAIL" for g in required),
        "required_blocked": sum(g.get("status") == "BLOCKED" for g in required),
        "required_not_run": sum(g.get("status") == "NOT_RUN" for g in required),
        "waived": sum(g.get("status") == "WAIVED" for g in value.get("gates", [])),
    }
    if value.get("summary") != expected_summary:
        issues.append(f"CI summary does not match gate states: expected {expected_summary}")
    return issues


def _active_requirement_ids(target_corpus: dict[str, Any]) -> set[str]:
    return {
        item.get("id")
        for item in target_corpus.get("requirements", [])
        if isinstance(item, dict) and item.get("id") and not item.get("waiver")
    }


def collect_issues(root: Path, phase: str) -> list[str]:
    root = root.resolve()
    schemas = schema_root(root)
    issues: list[str] = []
    loaded: dict[str, dict[str, Any]] = {}

    for name, (rel, schema_name) in CONTRACTS.items():
        path = root / rel
        if not path.is_file():
            issues.append(f"missing required {name} contract: {rel}")
            continue
        try:
            value, errors = validate_doc(path, schemas / schema_name)
        except Exception as exc:
            issues.append(f"{rel}: {exc}")
            continue
        loaded[name] = value
        issues.extend(f"{rel}: {error}" for error in errors)

    source_registry: dict[str, Any] = {"sources": []}
    target_corpus: dict[str, Any] = {"requirements": []}
    source_registry_path = root / "corpus" / "SOURCES.json"
    target_corpus_path = root / "corpus" / "TARGET_MUTATIONS.json"
    for label, path, schema_name in (
        ("source registry", source_registry_path, "SOURCE_REGISTRY_SCHEMA.json"),
        ("target corpus", target_corpus_path, "TARGET_CORPUS_SCHEMA.json"),
    ):
        if not path.is_file():
            issues.append(f"missing canonical {label}: {path.relative_to(root)}")
            continue
        try:
            value, errors = validate_doc(path, schemas / schema_name)
        except Exception as exc:
            issues.append(f"{path.relative_to(root)}: {exc}")
            continue
        issues.extend(f"{path.relative_to(root)}: {error}" for error in errors)
        if label == "source registry":
            source_registry = value
        else:
            target_corpus = value

    source_records = {
        item.get("id"): item
        for item in source_registry.get("sources", [])
        if isinstance(item, dict) and item.get("id")
    }
    known_source_ids = set(source_records)
    known_requirement_ids = _active_requirement_ids(target_corpus)
    known_behavior_ids = {
        item.get("behavior_id")
        for item in loaded.get("specification", {}).get("behaviors", [])
        if isinstance(item, dict) and item.get("behavior_id")
    }

    source_schema = schemas / "SOURCE_SURFACE_MAP_SCHEMA.json"
    source_dir = root / "corpus" / "source-surfaces"
    map_paths = sorted(source_dir.glob("*.json")) if source_dir.is_dir() else []
    source_maps: dict[str, tuple[Path, dict[str, Any]]] = {}
    surface_mechanism_ids: set[str] = set()
    for path in map_paths:
        try:
            value, errors = validate_doc(path, source_schema)
        except Exception as exc:
            issues.append(f"{path.relative_to(root)}: {exc}")
            continue
        rel = str(path.relative_to(root))
        issues.extend(f"{rel}: {error}" for error in errors)
        source_id = value.get("source_id")
        if source_id in source_maps:
            issues.append(f"duplicate source surface maps for source_id {source_id}")
        else:
            source_maps[source_id] = (path, value)
        issues.extend(_source_map_issues(value, rel, phase))
        for partition in value.get("partitions", []):
            surface_mechanism_ids.update(partition.get("mechanism_ids", []))

    required_repo_sources = {
        source_id: record
        for source_id, record in source_records.items()
        if record.get("kind") == "REPOSITORY"
        and record.get("disposition") in {"SYNTHESIS_REQUIRED", "ADJUDICATED_SYNTHESIS"}
    }
    for source_id, record in required_repo_sources.items():
        pair = source_maps.get(source_id)
        if pair is None:
            issues.append(f"repository source {source_id} lacks corpus/source-surfaces/{source_id}.json")
            continue
        _, source_map = pair
        pin = record.get("pin")
        if pin and source_map.get("source_version") != pin:
            issues.append(
                f"source map {source_id} version {source_map.get('source_version')} does not match registry pin {pin}"
            )
        if source_map.get("source_identity") != record.get("locator"):
            issues.append(
                f"source map {source_id} identity {source_map.get('source_identity')!r} "
                f"does not match registry locator {record.get('locator')!r}"
            )
        copyright_record = record.get("copyright") or {}
        if copyright_record.get("rights_status") == "VERIFIED" and source_map.get("rights_status") != "RESOLVED":
            issues.append(f"source map {source_id} does not reflect verified/resolved rights")

    for source_id in source_maps:
        if source_id not in known_source_ids:
            issues.append(f"source surface map references unknown source_id {source_id}")

    structural_schema = schemas / "STRUCTURAL_MUTATION_PLAN_SCHEMA.json"
    plans_dir = root / "control" / "structural-mutation-plans"
    plans = sorted(plans_dir.glob("*.json")) if plans_dir.is_dir() else []
    if phase in {"pre-mutation", "qualification"} and known_requirement_ids and not plans:
        issues.append("no structural mutation plans found under control/structural-mutation-plans")
    for path in plans:
        try:
            value, errors = validate_doc(path, structural_schema)
        except Exception as exc:
            issues.append(f"{path.relative_to(root)}: {exc}")
            continue
        rel = str(path.relative_to(root))
        issues.extend(f"{rel}: {error}" for error in errors)
        issues.extend(_structural_plan_issues(value, rel))

    if "specification" in loaded:
        issues.extend(_spec_issues(loaded["specification"], phase))
    if "ledger" in loaded:
        issues.extend(
            _ledger_issues(
                loaded["ledger"],
                phase,
                known_source_ids=known_source_ids,
                known_requirement_ids=known_requirement_ids,
                known_behavior_ids=known_behavior_ids,
                surface_mechanism_ids=surface_mechanism_ids,
            )
        )
    if "ci" in loaded:
        issues.extend(
            _ci_issues(
                loaded["ci"],
                phase,
                known_requirement_ids=known_requirement_ids,
                known_behavior_ids=known_behavior_ids,
            )
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--phase", choices=("design", "pre-mutation", "qualification"), default="design")
    args = parser.parse_args()
    issues = collect_issues(Path(args.root), args.phase)
    if issues:
        for item in issues:
            print(f"ERROR: {item}")
        return 1
    print(f"engineering contracts valid for phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
