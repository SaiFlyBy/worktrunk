#!/usr/bin/env python3
"""Behavioral tests for the single high-assurance aggregate gate."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
VALIDATOR_PATH = TOOLS / "validate_high_assurance.py"
spec = importlib.util.spec_from_file_location("high_assurance_gate", VALIDATOR_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {VALIDATOR_PATH}")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class HighAssuranceGateSuite(unittest.TestCase):
    def test_design_composes_every_pre_execution_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(validator.validate_source_collections, "collect_issues", return_value=["collection"]),
                mock.patch.object(validator.validate_source_surface_evidence, "collect_issues", return_value=["surface"]),
                mock.patch.object(validator.validate_engineering_contracts, "collect_issues", return_value=["engineering"]),
                mock.patch.object(validator.validate_engineering_rights, "collect_issues", return_value=["rights"]),
                mock.patch.object(validator.validate_ci_waiver_evidence, "collect_issues", return_value=["waiver"]),
                mock.patch.object(validator.validate_mutation_plan_traceability, "collect_issues", return_value=["mutation"]) as mutation,
            ):
                issues = validator.collect_issues(root, "design")
            self.assertEqual({
                "source_collections: collection",
                "source_surface_evidence: surface",
                "engineering_contracts: engineering",
                "engineering_rights: rights",
                "ci_waiver_evidence: waiver",
            }, set(issues))
            mutation.assert_not_called()

    def _assert_execution_phase_includes_mutation_trace(self, phase: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(validator.validate_source_collections, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_source_surface_evidence, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_engineering_contracts, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_engineering_rights, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_ci_waiver_evidence, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_mutation_plan_traceability, "collect_issues", return_value=["mutation"]),
            ):
                issues = validator.collect_issues(root, phase)
            self.assertEqual(["mutation_plan_traceability: mutation"], issues)

    def test_pre_mutation_adds_execution_plan_traceability(self) -> None:
        self._assert_execution_phase_includes_mutation_trace("pre-mutation")

    def test_qualification_adds_execution_plan_traceability(self) -> None:
        self._assert_execution_phase_includes_mutation_trace("qualification")

    def test_subvalidator_exception_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(validator.validate_source_collections, "collect_issues", side_effect=RuntimeError("boom")),
                mock.patch.object(validator.validate_source_surface_evidence, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_engineering_contracts, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_engineering_rights, "collect_issues", return_value=[]),
                mock.patch.object(validator.validate_ci_waiver_evidence, "collect_issues", return_value=[]),
            ):
                issues = validator.collect_issues(root, "design")
            self.assertTrue(any("validator failed: boom" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
