#!/usr/bin/env python3
"""Hostile tests for durable source-surface evidence bindings."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_source_surface_evidence.py"
spec = importlib.util.spec_from_file_location("source_surface_evidence", VALIDATOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {VALIDATOR_PATH}")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path) -> None:
    write(root / "corpus" / "SOURCES.json", {
        "schema": "flyby/mission-control-source-registry/16",
        "mission_id": "M1",
        "sources": []
    })
    inventory_ref = "evidence/source-one-root.json"
    terminal_ref = "evidence/source-one-terminal.json"
    write(root / inventory_ref, {"root": ["src", "tests"], "complete": True})
    write(root / terminal_ref, {"source_id": "SRC-ONE", "terminal": True})
    write(root / "corpus" / "source-surfaces" / "SRC-ONE.json", {
        "schema": "flyby/mission-control-source-surface-map/1",
        "mission_id": "M1",
        "source_id": "SRC-ONE",
        "source_identity": "example/repo",
        "source_version": "a" * 40,
        "root_inventory_ref": inventory_ref,
        "root_inventory_sha256": validator.sha256(root / inventory_ref),
        "rights_status": "RESOLVED",
        "coverage_status": "EXHAUSTED",
        "partitions": [{
            "partition_id": "SRC",
            "locator": "src/",
            "kind": "SOURCE",
            "criticality": "CRITICAL",
            "status": "INSPECTED",
            "coverage_evidence": ["source:src/"],
            "mechanism_ids": ["MECH-1"],
            "exclusion_reason": None
        }],
        "auxiliary_surfaces": {
            "tests": {
                "present": True,
                "status": "INSPECTED",
                "locators": ["tests/"],
                "notes": "reviewed"
            },
            **{
                name: {
                    "present": False,
                    "status": "NOT_PRESENT",
                    "locators": [],
                    "notes": "not present"
                }
                for name in (
                    "ci_cd", "benchmarks", "examples", "security",
                    "packaging_release", "license_notice", "change_history"
                )
            }
        },
        "open_questions": [],
        "terminal_receipt_ref": terminal_ref,
        "terminal_receipt_sha256": validator.sha256(root / terminal_ref)
    })


class SourceSurfaceEvidenceSuite(unittest.TestCase):
    def test_valid_exhausted_surface_binds_inventory_and_terminal_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            self.assertEqual([], validator.collect_issues(root, "qualification"))

    def test_root_inventory_byte_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            write(root / "evidence" / "source-one-root.json", {"root": [], "complete": False})
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("root inventory sha256 mismatch" in issue for issue in issues), issues)

    def test_terminal_receipt_byte_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            write(root / "evidence" / "source-one-terminal.json", {"terminal": False})
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("terminal receipt sha256 mismatch" in issue for issue in issues), issues)

    def test_terminal_partition_requires_coverage_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-ONE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["partitions"][0]["coverage_evidence"] = []
            write(path, value)
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("lacks coverage_evidence" in issue for issue in issues), issues)

    def test_present_auxiliary_surface_requires_locator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-ONE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["auxiliary_surfaces"]["tests"]["locators"] = []
            write(path, value)
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("present auxiliary surface tests lacks locators" in issue for issue in issues), issues)

    def test_absent_auxiliary_surface_cannot_claim_locator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-ONE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["auxiliary_surfaces"]["ci_cd"]["locators"] = [".github/workflows/"]
            write(path, value)
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("absent auxiliary surface ci_cd" in issue for issue in issues), issues)

    def test_exhausted_surface_cannot_omit_root_inventory_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-ONE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value.pop("root_inventory_ref")
            write(path, value)
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("root inventory reference is missing" in issue for issue in issues), issues)

    def test_evidence_reference_cannot_escape_mission_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-surfaces" / "SRC-ONE.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["root_inventory_ref"] = "../outside.json"
            write(path, value)
            issues = validator.collect_issues(root, "qualification")
            self.assertTrue(any("escapes mission root" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
