#!/usr/bin/env python3
"""Behavioral tests for engineering-ledger/source-rights closure."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_engineering_rights.py"
spec = importlib.util.spec_from_file_location("engineering_rights_validator", VALIDATOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {VALIDATOR_PATH}")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path, *, source_mode="LICENSE_PERMITTED_REUSE", verified=True, code_copy=True, structure_reuse=True) -> None:
    source = {
        "id": "SRC1",
        "kind": "REPOSITORY",
        "locator": "example/repo",
        "role": "fixture",
        "copyright": {
            "usage_mode": source_mode,
            "rights_status": "VERIFIED" if verified else "PENDING",
            "rights_basis": "fixture",
            "code_copy_allowed": code_copy,
            "text_copy_allowed": True,
            "structure_reuse_allowed": structure_reuse,
            "obligations": ["retain license notice"],
            "evidence_ref": "evidence/license.txt",
            "notes": "fixture"
        }
    }
    write(root / "corpus" / "SOURCES.json", {
        "schema": "flyby/mission-control-source-registry/16",
        "mission_id": "M1",
        "sources": [source]
    })
    write(root / "corpus" / "ENGINEERING_LEDGER.json", {
        "schema": "flyby/mission-control-engineering-ledger/1",
        "mission_id": "M1",
        "entries": [{
            "mechanism_id": "MECH1",
            "source_ids": ["SRC1"],
            "implementation": {"reuse_mode": "DIRECT_REUSE"},
            "rights": {
                "use_mode": "LICENSE_PERMITTED_REUSE",
                "reuse_source_ids": ["SRC1"],
                "obligations": ["retain license notice"],
                "notice_or_attribution_refs": ["NOTICE.md"]
            }
        }],
        "traceability": []
    })


class EngineeringRightsContractSuite(unittest.TestCase):
    def test_permitted_reuse_with_obligation_closure_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            self.assertEqual([], validator.collect_issues(root))

    def test_clean_room_source_cannot_be_reclassified_as_direct_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, source_mode="CLEAN_ROOM_BEHAVIORAL_SYNTHESIS", code_copy=False, structure_reuse=False)
            issues = validator.collect_issues(root)
            self.assertTrue(any("does not authorize implementation reuse" in item for item in issues), issues)

    def test_pending_rights_block_direct_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, verified=False)
            issues = validator.collect_issues(root)
            self.assertTrue(any("rights are not VERIFIED" in item for item in issues), issues)

    def test_source_obligations_cannot_disappear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            ledger = root / "corpus" / "ENGINEERING_LEDGER.json"
            value = json.loads(ledger.read_text(encoding="utf-8"))
            value["entries"][0]["rights"]["obligations"] = []
            write(ledger, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("drops source obligations" in item for item in issues), issues)

    def test_noncopy_synthesis_cannot_smuggle_reuse_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            ledger = root / "corpus" / "ENGINEERING_LEDGER.json"
            value = json.loads(ledger.read_text(encoding="utf-8"))
            value["entries"][0]["implementation"]["reuse_mode"] = "PARAPHRASED_SYNTHESIS"
            write(ledger, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("must not name implementation reuse_source_ids" in item for item in issues), issues)

    def test_adapted_reuse_requires_structure_permission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, structure_reuse=False)
            ledger = root / "corpus" / "ENGINEERING_LEDGER.json"
            value = json.loads(ledger.read_text(encoding="utf-8"))
            value["entries"][0]["implementation"]["reuse_mode"] = "ADAPTED_IMPLEMENTATION"
            write(ledger, value)
            issues = validator.collect_issues(root)
            self.assertTrue(any("does not authorize structural adaptation" in item for item in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
