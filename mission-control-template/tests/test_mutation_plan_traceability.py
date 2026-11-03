#!/usr/bin/env python3
"""Hostile tests for structural-plan-to-execution traceability."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_mutation_plan_traceability.py"
spec = importlib.util.spec_from_file_location("mutation_plan_traceability", VALIDATOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {VALIDATOR_PATH}")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path) -> None:
    write(root / "control" / "EXECUTION_DAG.json", {
        "schema": "flyby/mission-control-execution-dag/16",
        "mission_id": "M1",
        "revision": 1,
        "cells": [{
            "cell_id": "M001",
            "kind": "MUTATION",
            "dependencies": ["G000"],
            "objective": "change the owned parser surface",
            "acceptance": ["R-1 behavior is verified"],
            "status": "PENDING",
            "conflict_class": "write:example",
            "resource_claims": ["example/repo:src"],
            "requirement_ids": ["R-1"],
            "target": {
                "repository": "example/repo",
                "base_sha": "a" * 40,
                "owned_paths": ["src"]
            },
            "positive_verification": ["positive"],
            "negative_verification": ["negative"],
            "rollback": "revert candidate",
            "result_schema": "contracts/schemas/RESULT_SCHEMA.json"
        }]
    })
    write(root / "corpus" / "ENGINEERING_LEDGER.json", {
        "schema": "flyby/mission-control-engineering-ledger/1",
        "mission_id": "M1",
        "entries": [],
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
        "requirement_ids": ["R-1"],
        "repository": "example/repo",
        "base_sha": "a" * 40,
        "surfaces": [{
            "surface_id": "PY-AST",
            "language_or_format": "python",
            "owned_paths": ["src/parser.py"],
            "mutation_kind": "SYMBOL_REFACTOR",
            "engine": "COMPILER_AST",
            "engine_identity": {
                "name": "python ast",
                "version_or_digest": "stdlib",
                "source_ref": "python"
            },
            "selectors": ["function:parse"],
            "expected_affected": ["src/parser.py"],
            "expected_unaffected": ["src/runtime.py"],
            "excluded_boundaries": ["src/vendor"],
            "preservation": ["public API"],
            "parse_failure_policy": "block",
            "text_fallback_rationale": None,
            "idempotency": "REQUIRED"
        }],
        "global_preservation": ["unowned paths"],
        "post_mutation_checks": ["parse", "tests"]
    })


class MutationPlanTraceabilitySuite(unittest.TestCase):
    def test_valid_plan_is_bound_to_canonical_mutation_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            self.assertEqual([], validator.collect_issues(root))

    def test_requirement_binding_must_equal_canonical_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["requirement_ids"] = ["R-OTHER"]
            write(path, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("requirement_ids" in issue for issue in issues), issues)

    def test_ledger_requirement_must_be_carried_by_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "ENGINEERING_LEDGER.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["traceability"][0]["requirement_id"] = "R-OTHER"
            write(path, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("absent from the canonical cell" in issue for issue in issues), issues)

    def test_surface_cannot_escape_cell_write_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["surfaces"][0]["owned_paths"] = ["docs/readme.md"]
            value["surfaces"][0]["expected_affected"] = ["docs/readme.md"]
            write(path, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("escapes canonical cell owned_paths" in issue for issue in issues), issues)

    def test_expected_affected_must_stay_inside_surface_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["surfaces"][0]["expected_affected"] = ["src/other.py"]
            write(path, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("escapes the surface owned_paths" in issue for issue in issues), issues)

    def test_affected_surface_cannot_overlap_excluded_or_unaffected_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["surfaces"][0]["excluded_boundaries"] = ["src/parser.py"]
            value["surfaces"][0]["expected_unaffected"] = ["src/parser.py"]
            write(path, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("overlaps an excluded boundary" in issue for issue in issues), issues)
            self.assertTrue(any("overlaps expected_unaffected" in issue for issue in issues), issues)

    def test_dotdot_traversal_cannot_fake_owned_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["surfaces"][0]["owned_paths"] = ["src/../outside.py"]
            value["surfaces"][0]["expected_affected"] = ["src/../outside.py"]
            write(path, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("unsafe relative path 'src/../outside.py'" in issue for issue in issues), issues)
            self.assertTrue(any("escapes canonical cell owned_paths" in issue for issue in issues), issues)

    def test_absolute_and_drive_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["surfaces"][0]["expected_unaffected"] = ["/etc/passwd", "C:\\temp\\outside.txt"]
            write(path, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("unsafe relative path '/etc/passwd'" in issue for issue in issues), issues)
            self.assertTrue(any("unsafe relative path 'C:\\\\temp\\\\outside.txt'" in issue for issue in issues), issues)

    def test_traced_mutation_cannot_lack_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            (root / "control" / "structural-mutation-plans" / "M001.json").unlink()
            issues = validator.collect_issues(root)
            self.assertTrue(any("lacks structural mutation plan" in issue for issue in issues), issues)

    def test_plan_filename_and_mission_identity_are_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            original = root / "control" / "structural-mutation-plans" / "M001.json"
            value = json.loads(original.read_text(encoding="utf-8"))
            value["mission_id"] = "OTHER"
            original.unlink()
            write(root / "control" / "structural-mutation-plans" / "wrong-name.json", value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("filename must equal cell_id" in issue for issue in issues), issues)
            self.assertTrue(any("mission_id" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
