#!/usr/bin/env python3
"""Prove byte custody for the archived MCV6 compatibility fixture."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
MCV6 = REPO / "archive" / "mission-control-v6"
DESCRIPTOR = MCV6 / "frontier-102" / "MUTATION_DESCRIPTOR.json"
A000_RECEIPT = MCV6 / "frontier-000" / "evidence" / "A000" / "context_receipt.json"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_attr(attribute: str, path: Path) -> str:
    rel = path.relative_to(REPO).as_posix()
    proc = subprocess.run(
        ["git", "check-attr", attribute, "--", rel],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


class LegacyFixtureByteCustodySuite(unittest.TestCase):
    def test_01_legacy_text_is_explicitly_crlf_and_binary_xml_is_not_text(self) -> None:
        probes = [
            DESCRIPTOR,
            A000_RECEIPT,
            MCV6 / "tools" / "check_control_coherence.py",
            MCV6 / "frontier-000" / "evidence" / "A000" / "REPORT.md",
        ]
        for path in probes:
            self.assertTrue(git_attr("eol", path).endswith(": eol: crlf"), path.as_posix())
        xml = MCV6 / "frontier-000" / "evidence" / "A000" / "raw" / "python" / "pytest-e2e.xml"
        self.assertTrue(git_attr("text", xml).endswith(": text: unset"), git_attr("text", xml))

    def test_02_sealed_legacy_authority_bytes_are_crlf(self) -> None:
        for path in (DESCRIPTOR, A000_RECEIPT):
            data = path.read_bytes()
            self.assertIn(b"\r\n", data, path.as_posix())
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), path.as_posix())

    def test_03_frontier_descriptor_hash_remains_exact(self) -> None:
        state = json.loads((MCV6 / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
        compiled = state["compiled_frontier"]
        self.assertEqual("frontier-102/MUTATION_DESCRIPTOR.json", compiled["descriptor_ref"])
        self.assertEqual(
            "a250dd270b016e5e2372f2e5f2ef91095dcf9b8053a66f6241e93358b88a2dfe",
            compiled["descriptor_sha256"],
        )
        self.assertEqual(compiled["descriptor_sha256"], file_sha(MCV6 / compiled["descriptor_ref"]))

    def test_04_a000_context_receipt_hash_remains_exact(self) -> None:
        state = json.loads((MCV6 / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
        a000 = state["cells"]["A000"]
        self.assertEqual("frontier-000/evidence/A000/context_receipt.json", a000["context_receipt_ref"])
        self.assertEqual(
            "99df1e82a1cb0738c8cac02320270921b0e292b449d18c68584e2853042412c8",
            a000["context_receipt_sha256"],
        )
        self.assertEqual(a000["context_receipt_sha256"], file_sha(MCV6 / a000["context_receipt_ref"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
