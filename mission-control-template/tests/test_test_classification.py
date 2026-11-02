#!/usr/bin/env python3
"""Contract tests for Mission Control test taxonomy and retained proof inventory."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYERS = ROOT / "tests" / "TEST_LAYERS.json"
RETAINED = ROOT / "tests" / "RETAINED_TESTS.json"
PROOF_MAP = ROOT / "tests" / "PROOF_MAP.json"
EXPECTED_ORDER = ["unit_regression", "e2e", "performance_load", "environment_integration"]


class TestClassificationSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.layers = json.loads(LAYERS.read_text(encoding="utf-8"))
        self.retained = json.loads(RETAINED.read_text(encoding="utf-8"))
        self.proof_map = json.loads(PROOF_MAP.read_text(encoding="utf-8"))

    def test_01_required_order_is_exact(self) -> None:
        self.assertEqual("flyby/mission-control-test-layers/1", self.layers["schema"])
        self.assertEqual(EXPECTED_ORDER, self.layers["order"])
        self.assertEqual(set(EXPECTED_ORDER), set(self.layers["layers"]))
        self.assertTrue(self.layers["layers"]["unit_regression"]["required"])
        self.assertTrue(self.layers["layers"]["e2e"]["required"])
        self.assertTrue(self.layers["layers"]["performance_load"]["required"])
        self.assertTrue(self.layers["layers"]["environment_integration"]["required"])
        policy = (ROOT / "policies" / "LIFECYCLE_AND_TESTING.md").read_text(encoding="utf-8")
        self.assertIn("All four layers are required for FlyByRefactor's reusable-template qualification", policy)
        self.assertNotIn("The first three layers are required.", policy)

    def test_02_each_primary_proof_belongs_to_exactly_one_layer(self) -> None:
        ownership: dict[str, list[str]] = {}
        for layer, config in self.layers["layers"].items():
            self.assertIsInstance(config["required"], bool)
            for proof in config["proofs"]:
                ownership.setdefault(proof, []).append(layer)
        duplicates = {proof: layers for proof, layers in ownership.items() if len(layers) != 1}
        self.assertEqual({}, duplicates)
        for proof in ownership:
            self.assertTrue((ROOT / proof).is_file(), proof)

    def test_03_commands_use_existing_proofs_and_python_entrypoints(self) -> None:
        for layer, config in self.layers["layers"].items():
            proof_set = set(config["proofs"])
            for command in config["commands"]:
                self.assertGreaterEqual(len(command), 2, layer)
                self.assertEqual("python", command[0], command)
                self.assertIn(command[1], proof_set, command)
                self.assertTrue((ROOT / command[1]).is_file(), command[1])
        environment = self.layers["layers"]["environment_integration"]
        self.assertTrue(environment["required"], "tracked legacy integration fixture must remain a release-blocking proof")

    def test_04_retained_inventory_matches_primary_proofs(self) -> None:
        active = self.retained["active_proofs"]
        self.assertEqual(len(active), len(set(active)))
        expected = {
            proof
            for config in self.layers["layers"].values()
            for proof in config["proofs"]
        }
        self.assertEqual(expected, set(active))
        for proof in active:
            self.assertTrue((ROOT / proof).is_file(), proof)
        for retirement in self.retained["retirements"]:
            self.assertEqual({"path", "reason", "replacement", "authority"}, set(retirement))
            self.assertTrue(retirement["path"])
            self.assertTrue(retirement["reason"])
            self.assertTrue(retirement["authority"])

    def test_05_feature_proof_map_references_classified_active_proofs(self) -> None:
        active = set(self.retained["active_proofs"])
        layers = self.layers["layers"]
        for feature, layer_map in self.proof_map["features"].items():
            self.assertTrue(layer_map, feature)
            for layer, proofs in layer_map.items():
                self.assertIn(layer, layers, (feature, layer))
                classified = set(layers[layer]["proofs"])
                for proof in proofs:
                    self.assertIn(proof, active, (feature, proof))
                    self.assertIn(proof, classified, (feature, layer, proof))
                    self.assertTrue((ROOT / proof).is_file(), proof)

    def test_06_performance_scenario_catalog_is_unique_and_covers_core_shapes(self) -> None:
        catalog = json.loads((ROOT / "tests" / "PERFORMANCE_SCENARIOS.json").read_text(encoding="utf-8"))
        self.assertEqual("flyby/mission-control-performance-scenarios/1", catalog["schema"])
        ids = [scenario["id"] for scenario in catalog["scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({"S0_IDLE", "S1_SMALL_STATE", "S4_PARALLEL", "S8_LARGE_STATE", "S9_SOAK"} <= set(ids))
        for scenario in catalog["scenarios"]:
            self.assertTrue(isinstance(scenario.get("purpose"), str) and scenario["purpose"].strip())
            self.assertIsInstance(scenario.get("work_units"), int)
            self.assertGreaterEqual(scenario["work_units"], 0)

    def test_07_every_test_module_is_catalogued(self) -> None:
        physical = {f"tests/{path.name}" for path in (ROOT / "tests").glob("test_*.py")}
        classified = {
            proof
            for config in self.layers["layers"].values()
            for proof in config["proofs"]
            if proof.startswith("tests/test_") and proof.endswith(".py")
        }
        self.assertEqual(physical, classified)


if __name__ == "__main__":
    unittest.main(verbosity=2)
