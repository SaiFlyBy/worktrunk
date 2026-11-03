#!/usr/bin/env python3
"""Behavioral tests for high-assurance engineering contracts."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_engineering_contracts.py"
spec = importlib.util.spec_from_file_location("engineering_contract_validator", VALIDATOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {VALIDATOR_PATH}")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def valid_fixture(root: Path) -> None:
    source_id = "SRC-EXAMPLE"
    write(root / "corpus" / "SOURCES.json", {
        "schema": "flyby/mission-control-source-registry/16",
        "mission_id": "M1",
        "sources": [{
            "id": source_id,
            "kind": "REPOSITORY",
            "locator": "example/repo",
            "role": "fixture repository used to prove exhaustive source accounting",
            "pin": "a" * 40,
            "admission": "fixture admission",
            "license": "MIT",
            "disposition": "ADJUDICATED_SYNTHESIS",
            "inspection_scope": ["full repository"],
            "copyright": {
                "usage_mode": "CLEAN_ROOM_BEHAVIORAL_SYNTHESIS",
                "rights_status": "VERIFIED",
                "rights_basis": "fixture rights evidence",
                "code_copy_allowed": False,
                "text_copy_allowed": False,
                "structure_reuse_allowed": False,
                "obligations": [],
                "evidence_ref": "evidence/rights.json",
                "notes": "fixture exercises conservative synthesis"
            }
        }]
    })
    write(root / "corpus" / "TARGET_MUTATIONS.json", {
        "schema": "flyby/mission-control-target-corpus/16",
        "mission_id": "M1",
        "provenance_materialization": {
            "mode": "TARGET_HAS_NO_LINEAGE_MANIFEST",
            "target_refs": [],
            "coverage_requirement_id": None,
            "validation_schema_ref": None,
            "authority": "LINEAGE_ONLY",
            "acceptance": ["fixture lineage state is explicit"]
        },
        "requirements": [{
            "id": "R-1",
            "name": "Example requirement",
            "sources": [source_id],
            "targets": ["example/repo"],
            "acceptance": ["V-1"]
        }]
    })
    write(root / "control" / "SPECIFICATION.json", {
        "schema": "flyby/mission-control-specification-contract/1",
        "mission_id": "M1",
        "spec_id": "SPEC-1",
        "state": "FROZEN",
        "owner_intent_refs": ["MISSION.json#owner_intent/0"],
        "behaviors": [{
            "behavior_id": "B-1",
            "requirement_ids": ["R-1"],
            "statement": "A requested operation produces the declared result.",
            "positive_scenarios": ["valid request succeeds"],
            "negative_scenarios": ["invalid request fails closed"],
            "boundary_cases": ["empty optional input remains valid"],
            "effects": ["writes only the owned target"],
            "authority": "target owner",
            "acceptance_ids": ["V-1"]
        }],
        "invariants": [{
            "invariant_id": "I-1",
            "statement": "unowned state is unchanged",
            "scope": ["target"],
            "violation_behavior": "reject",
            "verification_ids": ["V-1"]
        }],
        "interfaces": [{
            "interface_id": "API-1",
            "inputs": ["request"],
            "outputs": ["result"],
            "effects": ["owned write"],
            "errors": ["invalid request"],
            "compatibility_surface": ["API-1"]
        }],
        "state_transitions": [{
            "transition_id": "T-1",
            "from": "READY",
            "trigger": "request",
            "guards": ["authorized"],
            "to": "DONE",
            "effects": ["owned write"],
            "idempotency": "same request identity yields one effect"
        }],
        "failure_semantics": {
            "failure_modes": ["invalid input"],
            "retry": "safe before effect",
            "cancellation": "no effect after cancellation",
            "recovery": "retry",
            "rollback": "restore prior owned state",
            "partial_success": "not accepted"
        },
        "compatibility": {
            "preserve": ["API-1"],
            "migration": ["none"],
            "breaking_change_policy": "explicit migration required"
        },
        "performance_resources": {
            "dimensions": ["latency"],
            "targets": ["calibrated baseline"],
            "calibration_method": "measure target baseline before mutation"
        },
        "observability": {
            "signals": ["result"],
            "diagnostics": ["structured error"],
            "auditability": ["verification receipt"]
        },
        "non_goals": [],
        "rejected_alternatives": [],
        "open_questions": [],
        "traceability": [{
            "behavior_id": "B-1",
            "mechanism_ids": ["MECH-1"],
            "requirement_ids": ["R-1"],
            "verification_ids": ["V-1"]
        }]
    })
    write(root / "corpus" / "source-surfaces" / f"{source_id}.json", {
        "schema": "flyby/mission-control-source-surface-map/1",
        "mission_id": "M1",
        "source_id": source_id,
        "source_identity": "example/repo",
        "source_version": "a" * 40,
        "root_inventory_sha256": "b" * 64,
        "rights_status": "RESOLVED",
        "coverage_status": "EXHAUSTED",
        "partitions": [{
            "partition_id": "P1",
            "locator": "src/",
            "kind": "SOURCE",
            "criticality": "CRITICAL",
            "status": "INSPECTED",
            "coverage_evidence": ["src/"],
            "mechanism_ids": ["MECH-1"],
            "exclusion_reason": None
        }],
        "auxiliary_surfaces": {
            key: {
                "present": False,
                "status": "NOT_PRESENT",
                "locators": [],
                "notes": "not present in fixture"
            }
            for key in (
                "tests", "ci_cd", "benchmarks", "examples", "security",
                "packaging_release", "license_notice", "change_history"
            )
        },
        "open_questions": [],
        "terminal_receipt_ref": "evidence/source-review.json",
        "terminal_receipt_sha256": "c" * 64
    })
    write(root / "corpus" / "ENGINEERING_LEDGER.json", {
        "schema": "flyby/mission-control-engineering-ledger/1",
        "mission_id": "M1",
        "entries": [{
            "mechanism_id": "MECH-1",
            "name": "example mechanism",
            "source_ids": [source_id],
            "finding_class": "ADMITTED_TARGET_AUTHORITY",
            "evidence_locators": ["src/example.py"],
            "problem": "duplicate work",
            "observable_value": "known behavior is reusable",
            "mechanism": {
                "summary": "bounded deterministic transform",
                "state": "none",
                "data_flow": "request to result",
                "control_flow": "validate then apply",
                "algorithm_or_process": "validate and materialize",
                "lifecycle": "request scoped"
            },
            "role": {
                "authority_owner": "target owner",
                "responsibilities": ["materialize"],
                "non_responsibilities": ["orchestration"]
            },
            "relationships": {
                "depends_on": [],
                "consumed_by": ["B-1"],
                "conflicts_with": [],
                "composes_with": [],
                "affected_by": [],
                "affects": ["B-1"]
            },
            "target_analysis": {
                "owner": "target owner",
                "inspected_locations": ["src/"],
                "existing_capabilities": [],
                "gaps": ["MECH-1"],
                "preserve": ["API-1"]
            },
            "disposition": "IMPLEMENT",
            "implementation": {
                "reuse_mode": "PARAPHRASED_SYNTHESIS",
                "target_requirements": ["R-1"],
                "planned_locations": ["src/example.py"],
                "landed_locations": ["src/example.py"],
                "migration": "none",
                "rollback": "revert owned commit"
            },
            "verification": {
                "positive": ["V-1"],
                "negative": ["invalid request"],
                "hostile": ["unowned path"],
                "compatibility": ["API-1"],
                "performance": ["baseline"],
                "verification_ids": ["V-1"]
            },
            "failure_recovery": {
                "failure_modes": ["invalid input"],
                "recovery": ["reject"],
                "rollback": ["revert"]
            },
            "observability": {
                "signals": ["result"],
                "diagnostics": ["error code"]
            },
            "security_privacy": {
                "trust_boundaries": ["request boundary"],
                "security_impact": "fail closed",
                "privacy_impact": "none"
            },
            "performance_resources": {
                "expected_effect": "bounded",
                "calibration_needed": False,
                "resource_dimensions": ["latency"]
            },
            "portability": {
                "supported": ["fixture"],
                "constraints": [],
                "nonportable_source_specifics": []
            },
            "rights": {
                "use_mode": "CLEAN_ROOM_BEHAVIORAL_SYNTHESIS",
                "reuse_source_ids": [],
                "obligations": [],
                "notice_or_attribution_refs": []
            },
            "rejected_alternatives": [],
            "open_questions": [],
            "confidence": "HIGH",
            "authority_status": "ADMITTED"
        }],
        "traceability": [{
            "requirement_id": "R-1",
            "mechanism_ids": ["MECH-1"],
            "spec_behavior_ids": ["B-1"],
            "cell_ids": ["M001"],
            "verification_ids": ["V-1"],
            "qualification_gate_ids": ["GATE-1"]
        }]
    })
    write(root / "control" / "structural-mutation-plans" / "M001.json", {
        "schema": "flyby/mission-control-structural-mutation-plan/1",
        "mission_id": "M1",
        "cell_id": "M001",
        "repository": "example/repo",
        "base_sha": "a" * 40,
        "surfaces": [{
            "surface_id": "S1",
            "language_or_format": "python",
            "owned_paths": ["src/example.py"],
            "mutation_kind": "SYMBOL_REFACTOR",
            "engine": "TREE_SITTER",
            "engine_identity": {
                "name": "fixture structural parser",
                "version_or_digest": "fixture",
                "source_ref": source_id
            },
            "selectors": ["function:example"],
            "expected_affected": ["src/example.py"],
            "expected_unaffected": ["src/other.py"],
            "excluded_boundaries": ["vendor/"],
            "preservation": ["comments", "public API"],
            "parse_failure_policy": "block and diagnose",
            "text_fallback_rationale": None,
            "idempotency": "REQUIRED"
        }],
        "global_preservation": ["unowned paths"],
        "post_mutation_checks": ["parse", "tests"]
    })
    write(root / "control" / "CI_QUALIFICATION_MATRIX.json", {
        "schema": "flyby/mission-control-ci-qualification-matrix/1",
        "mission_id": "M1",
        "candidate": [{"repository": "example/repo", "sha": "d" * 40}],
        "supported_matrix": [{
            "matrix_id": "linux-py",
            "dimensions": {"os": "linux", "runtime": "python"},
            "release_critical": True,
            "equivalence_rationale": None
        }],
        "gates": [{
            "gate_id": "GATE-1",
            "class": "E2E",
            "required": True,
            "repository": "example/repo",
            "candidate_sha": "d" * 40,
            "environment": {
                "os": "linux",
                "runtime": "python",
                "runner": "fixture",
                "external_dependencies": []
            },
            "execution_identity": "fixture-run",
            "command_or_workflow": "python tests/e2e.py",
            "real_path": True,
            "behavior_ids": ["B-1"],
            "requirement_ids": ["R-1"],
            "status": "PASS",
            "skip_classification": None,
            "evidence_refs": ["evidence/e2e.txt"],
            "artifact_refs": [],
            "started_at": None,
            "finished_at": None
        }],
        "coverage": [
            {"behavior_or_requirement_id": "B-1", "gate_ids": ["GATE-1"]},
            {"behavior_or_requirement_id": "R-1", "gate_ids": ["GATE-1"]}
        ],
        "summary": {
            "required_pass": 1,
            "required_fail": 0,
            "required_blocked": 0,
            "required_not_run": 0,
            "waived": 0
        }
    })


class EngineeringContractSuite(unittest.TestCase):
    def test_valid_qualification_fixture_closes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            self.assertEqual([], validator.collect_issues(root, "qualification"))

    def test_required_ci_not_run_blocks_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            path = root / "control" / "CI_QUALIFICATION_MATRIX.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["gates"][0]["status"] = "NOT_RUN"
            value["gates"][0]["skip_classification"] = "required environment unavailable"
            value["gates"][0]["evidence_refs"] = []
            value["summary"] = {
                "required_pass": 0,
                "required_fail": 0,
                "required_blocked": 0,
                "required_not_run": 1,
                "waived": 0
            }
            write(path, value)
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("not PASS/WAIVED" in issue for issue in issues), issues)

    def test_required_repository_source_cannot_disappear_from_surface_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            (root / "corpus" / "source-surfaces" / "SRC-EXAMPLE.json").unlink()
            issues = validator.collect_issues(root, "pre-mutation")
            self.assertTrue(any("lacks corpus/source-surfaces" in issue for issue in issues), issues)

    def test_exhausted_source_with_pending_partition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-EXAMPLE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["partitions"][0]["status"] = "PENDING"
            write(path, value)
            issues = validator.collect_issues(root, "pre-mutation")
            self.assertTrue(any("nonterminal partition" in issue for issue in issues), issues)

    def test_critical_partition_cannot_be_excluded_as_irrelevant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-EXAMPLE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["partitions"][0]["status"] = "EXCLUDED_IRRELEVANT_WITH_RATIONALE"
            value["partitions"][0]["exclusion_reason"] = "attempted shortcut"
            write(path, value)
            issues = validator.collect_issues(root, "pre-mutation")
            self.assertTrue(any("CRITICAL partition" in issue for issue in issues), issues)

    def test_surface_mechanism_must_exist_in_engineering_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-EXAMPLE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["partitions"][0]["mechanism_ids"].append("MECH-MISSING")
            write(path, value)
            issues = validator.collect_issues(root, "pre-mutation")
            self.assertTrue(any("missing from engineering ledger" in issue for issue in issues), issues)

    def test_spec_amendment_must_be_refrozen_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            path = root / "control" / "SPECIFICATION.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["state"] = "AMENDED"
            write(path, value)
            issues = validator.collect_issues(root, "pre-mutation")
            self.assertTrue(any("must be FROZEN" in issue for issue in issues), issues)

    def test_text_only_mutation_requires_explicit_rationale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            path = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["surfaces"][0]["engine"] = "TEXT_ONLY_WITH_JUSTIFICATION"
            value["surfaces"][0]["text_fallback_rationale"] = None
            write(path, value)
            issues = validator.collect_issues(root, "pre-mutation")
            self.assertTrue(any("text-only surface" in issue for issue in issues), issues)

    def test_qualification_requires_gate_coverage_for_each_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_fixture(root)
            path = root / "control" / "CI_QUALIFICATION_MATRIX.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["coverage"] = [row for row in value["coverage"] if row["behavior_or_requirement_id"] != "R-1"]
            write(path, value)
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("qualification coverage missing for R-1" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
