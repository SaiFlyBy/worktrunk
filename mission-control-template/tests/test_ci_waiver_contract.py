#!/usr/bin/env python3
"""Hostile tests for explicit CI qualification waiver authority and evidence."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from schema_subset import validate as validate_schema_instance, validate_schema_keywords
import validate_ci_waiver_evidence


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def schema() -> dict:
    value = json.loads((ROOT / "schemas" / "CI_QUALIFICATION_MATRIX_SCHEMA.json").read_text(encoding="utf-8"))
    validate_schema_keywords(value)
    return value


def matrix(*, status: str, waiver=None, skip_classification=None) -> dict:
    waiver_ref = waiver.get("evidence_ref") if isinstance(waiver, dict) else None
    evidence_refs = ["evidence/run.json"] if status == "PASS" else []
    if status == "WAIVED" and isinstance(waiver_ref, str):
        evidence_refs = [waiver_ref]
    gate = {
        "gate_id": "G1",
        "class": "E2E",
        "required": True,
        "repository": "example/repo",
        "candidate_sha": "a" * 40,
        "environment": {
            "os": "linux",
            "runtime": "python",
            "runner": "fixture",
            "external_dependencies": []
        },
        "execution_identity": "fixture-run",
        "command_or_workflow": "fixture",
        "real_path": True,
        "behavior_ids": ["B1"],
        "requirement_ids": ["R1"],
        "status": status,
        "skip_classification": skip_classification,
        "evidence_refs": evidence_refs,
        "artifact_refs": [],
        "started_at": None,
        "finished_at": None
    }
    if waiver is not None:
        gate["waiver"] = waiver
    return {
        "schema": "flyby/mission-control-ci-qualification-matrix/1",
        "mission_id": "M1",
        "candidate": [{"repository": "example/repo", "sha": "a" * 40}],
        "supported_matrix": [],
        "gates": [gate],
        "coverage": [
            {"behavior_or_requirement_id": "B1", "gate_ids": ["G1"]},
            {"behavior_or_requirement_id": "R1", "gate_ids": ["G1"]}
        ],
        "summary": {
            "required_pass": 1 if status == "PASS" else 0,
            "required_fail": 1 if status == "FAIL" else 0,
            "required_blocked": 1 if status == "BLOCKED" else 0,
            "required_not_run": 1 if status == "NOT_RUN" else 0,
            "waived": 1 if status == "WAIVED" else 0
        }
    }


def errors(value: dict) -> list[str]:
    s = schema()
    return validate_schema_instance(value, s, s, schema_path=ROOT / "schemas" / "CI_QUALIFICATION_MATRIX_SCHEMA.json")


def valid_waiver(root: Path) -> dict:
    evidence_ref = "evidence/waiver.json"
    evidence_path = root / evidence_ref
    write(evidence_path, {
        "gate_id": "G1",
        "authority": "owner",
        "reason": "documented release exception"
    })
    return {
        "reason": "documented exception",
        "authority": "owner",
        "evidence_ref": evidence_ref,
        "evidence_sha256": validate_ci_waiver_evidence.sha256(evidence_path),
    }


class CIWaiverContractSuite(unittest.TestCase):
    def test_pass_does_not_require_waiver(self) -> None:
        self.assertEqual([], errors(matrix(status="PASS")))

    def test_waived_gate_without_authority_object_is_rejected(self) -> None:
        value = matrix(status="WAIVED", skip_classification="owner-authorized release exception")
        self.assertTrue(errors(value))

    def test_waived_gate_requires_hash_bound_reason_authority_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            waiver = valid_waiver(root)
            value = matrix(
                status="WAIVED",
                skip_classification="owner-authorized release exception",
                waiver=waiver,
            )
            self.assertEqual([], errors(value))
            write(root / "control" / "CI_QUALIFICATION_MATRIX.json", value)
            self.assertEqual([], validate_ci_waiver_evidence.collect_issues(root))

    def test_waived_gate_without_evidence_hash_is_rejected(self) -> None:
        value = matrix(
            status="WAIVED",
            skip_classification="owner-authorized release exception",
            waiver={
                "reason": "documented exception",
                "authority": "owner",
                "evidence_ref": "evidence/waiver.json",
            },
        )
        self.assertTrue(errors(value))

    def test_nonwaived_gate_cannot_smuggle_waiver_authority(self) -> None:
        value = matrix(
            status="PASS",
            waiver={
                "reason": "irrelevant",
                "authority": "owner",
                "evidence_ref": "evidence/waiver.json",
                "evidence_sha256": "a" * 64,
            },
        )
        self.assertTrue(errors(value))

    def test_waiver_evidence_byte_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            waiver = valid_waiver(root)
            value = matrix(
                status="WAIVED",
                skip_classification="owner-authorized release exception",
                waiver=waiver,
            )
            write(root / "control" / "CI_QUALIFICATION_MATRIX.json", value)
            write(root / "evidence" / "waiver.json", {"tampered": True})
            issues = validate_ci_waiver_evidence.collect_issues(root)
            self.assertTrue(any("sha256 mismatch" in issue for issue in issues), issues)

    def test_waiver_evidence_reference_cannot_escape_mission_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = matrix(
                status="WAIVED",
                skip_classification="owner-authorized release exception",
                waiver={
                    "reason": "documented exception",
                    "authority": "owner",
                    "evidence_ref": "../outside.json",
                    "evidence_sha256": "a" * 64,
                },
            )
            write(root / "control" / "CI_QUALIFICATION_MATRIX.json", value)
            issues = validate_ci_waiver_evidence.collect_issues(root)
            self.assertTrue(any("escapes mission root" in issue for issue in issues), issues)

    def test_waiver_evidence_must_be_retained_by_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            waiver = valid_waiver(root)
            value = matrix(
                status="WAIVED",
                skip_classification="owner-authorized release exception",
                waiver=waiver,
            )
            value["gates"][0]["evidence_refs"] = []
            write(root / "control" / "CI_QUALIFICATION_MATRIX.json", value)
            issues = validate_ci_waiver_evidence.collect_issues(root)
            self.assertTrue(any("not retained in gate evidence_refs" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
