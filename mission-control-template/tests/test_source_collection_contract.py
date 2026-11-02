#!/usr/bin/env python3
"""Behavioral tests for frozen dynamic source-collection intake."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_source_collections.py"
spec = importlib.util.spec_from_file_location("source_collection_validator", VALIDATOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {VALIDATOR_PATH}")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path, *, disposition: str = "SYNTHESIS_REQUIRED") -> None:
    source_id = "SRC-ONE"
    revision = "a" * 40
    locator = "example/repo"
    write(root / "corpus" / "SOURCES.json", {
        "schema": "flyby/mission-control-source-registry/16",
        "mission_id": "M1",
        "sources": [{
            "id": source_id,
            "kind": "REPOSITORY",
            "locator": locator,
            "role": "fixture source",
            "pin": revision,
            "admission": "full collection review",
            "license": "MIT",
            "disposition": disposition,
            "inspection_scope": ["full repository"],
            "copyright": {
                "usage_mode": "LICENSE_PERMITTED_REUSE",
                "rights_status": "VERIFIED",
                "rights_basis": "fixture",
                "code_copy_allowed": True,
                "text_copy_allowed": True,
                "structure_reuse_allowed": True,
                "obligations": ["preserve license notice"],
                "evidence_ref": "evidence/license.txt",
                "notes": "fixture only"
            }
        }]
    })
    write(root / "corpus" / "source-surfaces" / f"{source_id}.json", {
        "schema": "flyby/mission-control-source-surface-map/1",
        "mission_id": "M1",
        "source_id": source_id,
        "source_identity": locator,
        "source_version": revision,
        "root_inventory_sha256": "b" * 64,
        "rights_status": "RESOLVED",
        "coverage_status": "EXHAUSTED",
        "partitions": [{
            "partition_id": "ROOT",
            "locator": ".",
            "kind": "SOURCE",
            "criticality": "CRITICAL",
            "status": "INSPECTED",
            "coverage_evidence": ["evidence/root-inventory.json"],
            "mechanism_ids": ["MECH-ONE"],
            "exclusion_reason": None
        }],
        "auxiliary_surfaces": {
            name: {"present": False, "status": "NOT_PRESENT", "locators": [], "notes": "fixture"}
            for name in (
                "tests", "ci_cd", "benchmarks", "examples", "security",
                "packaging_release", "license_notice", "change_history"
            )
        },
        "open_questions": [],
        "terminal_receipt_ref": "evidence/source-one.json",
        "terminal_receipt_sha256": "c" * 64
    })
    membership_ref = "evidence/star-list-page-1.json"
    membership_path = root / membership_ref
    write(membership_path, {"repositories": [locator], "terminal_cursor": True})
    evidence_id = "PAGE-1"
    items = [{
        "source_id": source_id,
        "source_locator": locator,
        "snapshot_revision": revision,
        "membership_evidence_id": evidence_id
    }]
    write(root / "corpus" / "source-collections" / "stars.json", {
        "schema": "flyby/mission-control-source-collection-snapshot/1",
        "mission_id": "M1",
        "collection_id": "STAR-LIST-1",
        "kind": "GITHUB_STAR_LIST",
        "locator": "https://github.com/stars/example/lists/example",
        "observed_at": "2026-09-16T20:00:00-04:00",
        "retrieval": {
            "method": "provider collection enumeration",
            "pagination_or_cursors": ["page-1:end"],
            "reported_total": 1,
            "raw_evidence": [{
                "evidence_id": evidence_id,
                "ref": membership_ref,
                "sha256": validator.sha256(membership_path)
            }],
            "completeness_assertion": "provider reported one item and terminal cursor was observed"
        },
        "items": items,
        "item_count": 1,
        "items_sha256": validator.canonical_items_sha256(items),
        "frozen": True
    })


class SourceCollectionContractSuite(unittest.TestCase):
    def test_valid_frozen_collection_closes_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            self.assertEqual([], validator.collect_issues(root, "pre-mutation"))

    def test_normal_synthesis_required_path_is_not_misread_as_lifecycle_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, disposition="SYNTHESIS_REQUIRED")
            self.assertEqual([], validator.collect_issues(root, "pre-mutation"))

    def test_adjudicated_synthesis_path_is_also_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, disposition="ADJUDICATED_SYNTHESIS")
            self.assertEqual([], validator.collect_issues(root, "pre-mutation"))

    def test_collection_count_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-collections" / "stars.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["item_count"] = 2
            write(path, value)
            issues = validator.collect_issues(root, "design")
            self.assertTrue(any("item_count" in issue for issue in issues), issues)

    def test_collection_digest_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-collections" / "stars.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["items_sha256"] = "0" * 64
            write(path, value)
            issues = validator.collect_issues(root, "design")
            self.assertTrue(any("items_sha256 mismatch" in issue for issue in issues), issues)

    def test_raw_membership_evidence_byte_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            write(root / "evidence" / "star-list-page-1.json", {"repositories": [], "terminal_cursor": True})
            issues = validator.collect_issues(root, "design")
            self.assertTrue(any("raw evidence PAGE-1 sha256 mismatch" in issue for issue in issues), issues)

    def test_unknown_membership_evidence_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / "corpus" / "source-collections" / "stars.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["items"][0]["membership_evidence_id"] = "MISSING"
            value["items_sha256"] = validator.canonical_items_sha256(value["items"])
            write(path, value)
            issues = validator.collect_issues(root, "design")
            self.assertTrue(any("unknown membership evidence" in issue for issue in issues), issues)

    def test_collection_member_must_have_registry_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            sources = root / "corpus" / "SOURCES.json"
            value = json.loads(sources.read_text(encoding="utf-8"))
            value["sources"] = []
            write(sources, value)
            issues = validator.collect_issues(root, "design")
            self.assertTrue(any("has no SOURCES.json record" in issue for issue in issues), issues)

    def test_missing_exhausted_surface_map_blocks_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            (root / "corpus" / "source-surfaces" / "SRC-ONE.json").unlink()
            issues = validator.collect_issues(root, "pre-mutation")
            self.assertTrue(any("lacks an exhausted source-surface map" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
