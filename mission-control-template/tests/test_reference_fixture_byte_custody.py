#!/usr/bin/env python3
"""Prove cross-platform byte custody for the golden reference mission."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
REF = ROOT / "examples" / "reference-mission"
REF17 = ROOT / "examples" / "reference-qualification-v17"
TOOLS = ROOT / "tools" / "source_review_turn_chain.py"
sys.path.insert(0, str(ROOT / "tools"))


def load_chain_module():
    spec = importlib.util.spec_from_file_location("source_review_turn_chain_fixture_test", TOOLS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {TOOLS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


chain = load_chain_module()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ReferenceFixtureByteCustodySuite(unittest.TestCase):
    def test_01_reference_mission_is_forced_to_lf_by_git_attributes(self) -> None:
        probes = [
            REF / "PROVENANCE_SYNTHESIS.json",
            REF / "SOURCE_REVIEW_TURN.json",
            REF / "evidence" / "REFERENCE_TURN_1_PROMPT.txt",
            REF17 / "PROVENANCE_SYNTHESIS.json",
            REF17 / "evidence" / "V17_SOURCE_QUALIFICATION.txt",
        ]
        for path in probes:
            rel = path.relative_to(REPO).as_posix()
            proc = subprocess.run(
                ["git", "check-attr", "eol", "--", rel],
                cwd=REPO,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(proc.stdout.rstrip().endswith(": eol: lf"), proc.stdout)

    def test_02_reference_mission_text_files_are_lf_bytes(self) -> None:
        for path in sorted(REF.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".json", ".txt"}:
                continue
            data = path.read_bytes()
            self.assertNotIn(b"\r\n", data, path.relative_to(REF).as_posix())
            self.assertNotIn(b"\r", data, path.relative_to(REF).as_posix())

    def test_03_provenance_receipts_bind_exact_bytes(self) -> None:
        provenance = load_json(REF / "PROVENANCE_SYNTHESIS.json")
        for assessment in provenance["source_assessments"]:
            review = assessment["independent_review"]
            self.assertEqual(review["review_sha256"], file_sha(REF / review["review_ref"]))
        cross = provenance["cross_source_synthesis"]
        self.assertEqual(cross["evidence_sha256"], file_sha(REF / cross["evidence_ref"]))

    def test_03b_evidence_based_reference_binds_exact_bytes(self) -> None:
        provenance = load_json(REF17 / "PROVENANCE_SYNTHESIS.json")
        assessment = provenance["source_assessments"][0]
        review = assessment["independent_review"]
        self.assertEqual(review["review_sha256"], file_sha(REF17 / review["review_ref"]))
        for record in assessment["deep_review"]["rounds"]:
            self.assertEqual(record["evidence_sha256"], file_sha(REF17 / record["evidence_ref"]))
        for path in REF17.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"\r", path.read_bytes(), path.relative_to(REF17).as_posix())

    def test_04_direct_launch_receipt_binds_exact_prompt_and_birth_bytes(self) -> None:
        receipt_path = REF / "evidence" / "REFERENCE_DIRECT_LAUNCH_RECEIPT.json"
        receipt = load_json(receipt_path)
        self.assertEqual(receipt["turn_1_prompt_sha256"], file_sha(REF / receipt["turn_1_prompt_ref"]))
        self.assertEqual(
            receipt["session_birth_evidence_sha256"],
            file_sha(REF / receipt["session_birth_evidence_ref"]),
        )
        self.assertEqual(receipt["receipt_sha256"], chain.launch_receipt_hash(receipt))

    def test_05_turn_envelope_and_chain_index_bind_exact_bytes(self) -> None:
        index = load_json(REF / "SOURCE_REVIEW_TURN_CHAIN_INDEX.json")
        for generation in index["post_enforcement_generations"]:
            launch_path = REF / generation["launch_receipt_ref"]
            self.assertEqual(generation["launch_receipt_sha256"], file_sha(launch_path))
            for turn_record in generation["turns"]:
                turn_path = REF / turn_record["ref"]
                self.assertEqual(turn_record["sha256"], file_sha(turn_path))
                turn = load_json(turn_path)
                self.assertEqual(turn["turn_sha256"], chain.envelope_hash(turn))
                self.assertEqual(
                    turn["source_binding"]["launch_receipt_sha256"],
                    file_sha(launch_path),
                )
                instruction = turn["turn_metadata"]
                self.assertEqual(instruction["instruction_sha256"], file_sha(REF / instruction["instruction_ref"]))
                evidence = turn["evidence"]
                self.assertEqual(evidence["sha256"], file_sha(REF / evidence["ref"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
