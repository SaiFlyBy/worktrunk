#!/usr/bin/env python3
"""Qualification behavior and legacy mission contract compatibility."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import test_runtime_state_machine as runtime_fixture

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SCHEMA = ROOT / "tests" / "fixtures" / "PROVENANCE_SYNTHESIS_V16_SCHEMA.json"


class EvidenceBasedSourceQualificationTests(unittest.TestCase):
    # Reuse the existing end-to-end mission fixture, without inheriting its tests.
    setUp = runtime_fixture.RuntimeStateMachineSuite.setUp
    tearDown = runtime_fixture.RuntimeStateMachineSuite.tearDown
    _run = runtime_fixture.RuntimeStateMachineSuite._run
    source = runtime_fixture.RuntimeStateMachineSuite.source
    mc = runtime_fixture.RuntimeStateMachineSuite.mc

    def qualified_candidate(self) -> dict:
        candidate = json.loads((runtime_fixture.QUALIFICATION_EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        assessment = candidate["source_assessments"][0]
        evidence = self.root / "evidence" / "source-qualification.txt"
        evidence.write_text("Inspected the source promotion path and its target obligations.\n", encoding="utf-8")
        review = assessment["deep_review"]
        review["strategy"] = "EVIDENCE_BASED_QUALIFICATION"
        review["critical_partitions"] = ["promotion path and target obligations"]
        review["rounds"] = [{
            "round": 1,
            "reviewer": "reference-golden-reviewer",
            "focus": "promotion path and target obligations",
            "evidence_ref": "evidence/source-qualification.txt",
            "evidence_sha256": runtime_fixture.sha256(evidence),
            "findings": 2,
            "disposition": "COMPLETE",
        }]
        review["convergence"]["rationale"] = "The declared source scope is covered by the attached evidence."
        self.bind_independent_receipt(assessment)
        return candidate

    def bind_independent_receipt(self, assessment: dict) -> None:
        fields = ("source_id", "inspected_locators", "coverage_items", "open_questions", "deep_review", "mechanism_contributions")
        payload = {key: assessment[key] for key in fields}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        independent = assessment["independent_review"]
        independent["coverage_sha256"] = digest
        receipt = json.loads((runtime_fixture.EXAMPLE / "evidence" / "REFERENCE_SOURCE_INDEPENDENT_REVIEW.json").read_text(encoding="utf-8"))
        receipt["coverage_sha256"] = digest
        receipt["inspection_evidence"] = ["independently checked the source evidence and source-local contributions"]
        path = self.root / "evidence" / "evidence-based-independent-review.json"
        runtime_fixture.write_json(path, receipt)
        independent["review_ref"] = "evidence/evidence-based-independent-review.json"
        independent["review_sha256"] = runtime_fixture.sha256(path)

    def load_candidate(self, candidate: dict, *, ok: bool = True, source: bool = False):
        path = self.root / "candidate-provenance.json"
        runtime_fixture.write_json(path, candidate)
        runner = self.source if source else self.mc
        return runner("provenance", "load", "--root", self.root, "--file", path, ok=ok)

    def test_single_evidence_bound_assessment_can_qualify(self) -> None:
        candidate = self.qualified_candidate()
        self.load_candidate(candidate)
        self.mc("doctor", "--root", self.root)
        self.source("doctor", "--root", self.root)
        self.mc("baseline", "compile", "--root", self.root)

    def test_evidence_must_exist_stay_bound_and_remain_in_mission(self) -> None:
        candidate = self.qualified_candidate()
        row = candidate["source_assessments"][0]["deep_review"]["rounds"][0]
        row["evidence_ref"] = "evidence/missing.txt"
        self.bind_independent_receipt(candidate["source_assessments"][0])
        self.assertIn("MC0392", self.load_candidate(candidate, ok=False).stderr)
        row["evidence_ref"] = "../outside-mission.txt"
        self.bind_independent_receipt(candidate["source_assessments"][0])
        self.assertIn("MC0391", self.load_candidate(candidate, ok=False).stderr)
        row["evidence_ref"] = "evidence/source-qualification.txt"
        self.bind_independent_receipt(candidate["source_assessments"][0])
        (self.root / row["evidence_ref"]).write_text("changed after review\n", encoding="utf-8")
        self.assertIn("MC0393", self.load_candidate(candidate, ok=False).stderr)

    def test_completed_qualification_requires_an_assessment_and_digest(self) -> None:
        candidate = self.qualified_candidate()
        assessment = candidate["source_assessments"][0]
        assessment["deep_review"]["rounds"] = []
        self.bind_independent_receipt(assessment)
        self.assertIn("MC0312", self.load_candidate(candidate, ok=False).stderr)
        candidate = self.qualified_candidate()
        del candidate["source_assessments"][0]["deep_review"]["rounds"][0]["evidence_sha256"]
        result = self.load_candidate(candidate, ok=False)
        self.assertIn("REJECTED", result.stderr)

    def test_independence_open_gaps_and_contract_mixing_are_rejected(self) -> None:
        candidate = self.qualified_candidate()
        assessment = candidate["source_assessments"][0]
        assessment["independent_review"]["reviewer"] = "reference-golden-reviewer"
        assessment["independent_review"]["reviewer_identity"] = "reference-golden-reviewer"
        self.assertIn("MC0355", self.load_candidate(candidate, ok=False).stderr)
        candidate = self.qualified_candidate()
        assessment = candidate["source_assessments"][0]
        assessment["deep_review"]["uninspected_critical_partitions"] = ["promotion path and target obligations"]
        assessment["deep_review"]["convergence"]["material_omissions_remaining"] = True
        self.bind_independent_receipt(assessment)
        result = self.load_candidate(candidate, ok=False)
        self.assertIn("MC0329", result.stderr)
        self.assertIn("MC0313", result.stderr)
        candidate = self.qualified_candidate()
        candidate["schema"] = "flyby/mission-control-provenance-synthesis/16"
        self.assertIn("REJECTED", self.load_candidate(candidate, ok=False).stderr)
        legacy = json.loads((runtime_fixture.EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        self.assertIn("REJECTED", self.load_candidate(legacy, ok=False).stderr)
        legacy["schema"] = "flyby/mission-control-provenance-synthesis/17"
        self.assertIn("REJECTED", self.load_candidate(legacy, ok=False).stderr)

    def use_legacy_contract(self) -> None:
        contract = self.root / "contracts" / "schemas" / "PROVENANCE_SYNTHESIS_SCHEMA.json"
        contract.write_bytes(LEGACY_SCHEMA.read_bytes())
        lock_path = self.root / "TEMPLATE_LOCK.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["assets"]["contracts/schemas/PROVENANCE_SYNTHESIS_SCHEMA.json"] = runtime_fixture.sha256(contract)
        runtime_fixture.write_json(lock_path, lock)
        legacy = json.loads((runtime_fixture.EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        self.load_candidate(legacy, source=True)

    def test_legacy_evidence_keeps_legacy_floor(self) -> None:
        self.use_legacy_contract()
        self.mc("doctor", "--root", self.root)
        legacy = json.loads((runtime_fixture.EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        review = legacy["source_assessments"][0]["deep_review"]
        review["rounds"] = review["rounds"][-1:]
        review["rounds"][0]["round"] = 1
        self.assertIn("MC0312", self.load_candidate(legacy, ok=False).stderr)

    def test_new_source_tool_respects_frozen_v16_contract_without_rewriting_it(self) -> None:
        self.use_legacy_contract()
        contract = self.root / "contracts" / "schemas" / "PROVENANCE_SYNTHESIS_SCHEMA.json"
        lock_path = self.root / "TEMPLATE_LOCK.json"
        self.source("doctor", "--root", self.root)
        protected = [lock_path, contract, self.runtime, self.root / "corpus" / "PROVENANCE_SYNTHESIS.json"]
        before = {p: runtime_fixture.sha256(p) for p in protected}
        candidate = self.qualified_candidate()
        result = self.load_candidate(candidate, ok=False, source=True)
        self.assertIn("REJECTED", result.stderr)
        self.assertEqual(before, {p: runtime_fixture.sha256(p) for p in protected})
        self.mc("doctor", "--root", self.root)


if __name__ == "__main__":
    unittest.main()
