#!/usr/bin/env python3
"""Static checks for high-assurance engineering contract assets."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from source_fixture import source_proof_repo

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SOURCE_REPO = source_proof_repo(REPO)


class EngineeringContractIndexSuite(unittest.TestCase):
    def test_engineering_index_names_every_contract_without_growing_template_manifest(self) -> None:
        template = json.loads((ROOT / "TEMPLATE.json").read_text(encoding="utf-8"))
        self.assertLessEqual(len(template), 45)
        index = json.loads((ROOT / "policies" / "ENGINEERING_CONTRACTS.json").read_text(encoding="utf-8"))
        self.assertEqual("flyby/mission-control-engineering-contract-index/1", index["schema"])
        contracts = {key: value for key, value in index.items() if key != "schema"}
        expected = {
            "scope_policy",
            "specification_policy",
            "structural_mutation_policy",
            "ci_cd_policy",
            "source_exhaustion_policy",
            "provenance_ingestion_workflow",
            "high_assurance_policy",
            "provenance",
            "source_collection_snapshot_schema",
            "source_surface_map_schema",
            "engineering_ledger_schema",
            "specification_schema",
            "structural_mutation_plan_schema",
            "ci_qualification_matrix_schema",
            "validator",
            "source_collection_validator",
            "source_surface_evidence_validator",
            "rights_validator",
            "ci_waiver_evidence_validator",
            "mutation_trace_validator",
            "high_assurance_validator",
            "test",
            "source_collection_test",
            "source_surface_evidence_test",
            "rights_test",
            "mutation_trace_test",
            "high_assurance_test",
            "index_test",
        }
        self.assertEqual(expected, set(contracts))
        for name, rel in contracts.items():
            self.assertTrue((ROOT / rel).is_file(), f"{name}: missing {rel}")

    def test_policy_laws_are_not_accidentally_removed(self) -> None:
        expected_tokens = {
            "policies/SCOPE_COMPLETENESS_AND_NO_MINIMALIZATION.md": [
                "Decomposition is permitted. Silent scope reduction is not.",
                "A green subset is not a green mission.",
            ],
            "policies/SPECIFICATION_DRIVEN_ENGINEERING.md": [
                "owner intent -> specification -> architecture/plan -> task/cell graph -> implementation -> convergence -> qualification",
                "No later stage may silently rewrite an earlier stage.",
            ],
            "policies/STRUCTURAL_MUTATION_AND_CODE_INTELLIGENCE.md": [
                "prefer a structural mutation path over regex/string replacement",
                "Parse failure is evidence.",
            ],
            "policies/CI_CD_QUALIFICATION.md": [
                "CI/CD is release evidence, not ceremony.",
                "A required behavior that is skipped",
                "mutation testing or equivalent test-effectiveness evidence",
                "a workflow cannot be the sole validator of its own parseability",
                "A backup that was never restored is not proven recovery.",
            ],
            "policies/SOURCE_EXHAUSTION_AND_ENGINEERING_LEDGER.md": [
                "Mission Control freezes the collection before source-review scheduling.",
                "A repository is not exhausted because its README",
                "The engineering ledger is not a bibliography.",
            ],
            "policies/PROVENANCE_INGESTION_WORKFLOW.md": [
                "The material mechanism is the unit of ingestion.",
                "Representative sampling is not source completion.",
                "Execution may be decomposed. Accepted capability scope may not be silently minimized.",
                "Code or configuration presence alone is not proof of ingestion.",
                "No source island and no mechanism orphan may remain at mutation admission.",
            ],
            "policies/HIGH_ASSURANCE_ENGINEERING_GATE.md": [
                "Individual validators are diagnostics; they are not independent release authority.",
                "Adoption is sticky for the mission.",
                "pre-mutation",
                "validate_high_assurance.py",
            ],
        }
        for rel, tokens in expected_tokens.items():
            content = (ROOT / rel).read_text(encoding="utf-8")
            for token in tokens:
                self.assertIn(token, content, f"{rel}: {token}")

    def test_provenance_ingestion_workflow_is_reusable_and_fail_closed(self) -> None:
        index = json.loads((ROOT / "policies" / "ENGINEERING_CONTRACTS.json").read_text(encoding="utf-8"))
        self.assertEqual("policies/PROVENANCE_INGESTION_WORKFLOW.md", index["provenance_ingestion_workflow"])
        policy = (ROOT / index["provenance_ingestion_workflow"]).read_text(encoding="utf-8")
        for token in (
            "The material mechanism is the unit of ingestion.",
            "Representative sampling is not source completion.",
            "smallest correct intervention",
            "Accepted capability scope may not be silently minimized.",
            "implementation-grade target after-state",
            "No source island and no mechanism orphan may remain at mutation admission.",
            "may not silently reduce the admitted mechanism set",
        ):
            self.assertIn(token, policy)
        for mission_specific in ("FlyByMaestro", "mcv7", "SaiFlyBy", "OpenTofu", "Terraform"):
            self.assertNotIn(mission_specific, policy)

        audit = (ROOT / "policies" / "MCV_ENGINEERING_AUDIT_AND_ADJUDICATION.md").read_text(encoding="utf-8")
        synthesis = (ROOT / "policies" / "PROVENANCE_SYNTHESIS.md").read_text(encoding="utf-8")
        exhaustion = (ROOT / "policies" / "SOURCE_EXHAUSTION_AND_ENGINEERING_LEDGER.md").read_text(encoding="utf-8")
        scope = (ROOT / "policies" / "SCOPE_COMPLETENESS_AND_NO_MINIMALIZATION.md").read_text(encoding="utf-8")
        for linked in (audit, synthesis, exhaustion, scope):
            self.assertIn("PROVENANCE_INGESTION_WORKFLOW.md", linked)

    def test_ci_schema_keeps_high_risk_proof_classes_explicit(self) -> None:
        schema = json.loads((ROOT / "schemas" / "CI_QUALIFICATION_MATRIX_SCHEMA.json").read_text(encoding="utf-8"))
        classes = set(schema["properties"]["gates"]["items"]["properties"]["class"]["enum"])
        self.assertTrue({
            "WORKFLOW_DEFINITION_VALIDATION",
            "MUTATION_TEST_EFFECTIVENESS",
            "DETERMINISM_REPLAY_IDEMPOTENCY",
            "FAULT_INJECTION_CHAOS_RECOVERY",
            "BACKUP_RESTORE_DATA_INTEGRITY",
            "EXECUTABLE_DOCS_EXAMPLES_CONFORMANCE",
            "REAL_ENVIRONMENT",
            "DEPLOYMENT_RECONCILIATION",
            "PROVENANCE_LICENSE_SBOM_ATTESTATION",
        } <= classes)
        waiver = schema["properties"]["gates"]["items"]["properties"]["waiver"]
        self.assertEqual({"reason", "authority", "evidence_ref", "evidence_sha256"}, set(waiver["required"]))

    def test_structural_plan_schema_exposes_requirement_binding(self) -> None:
        schema = json.loads((ROOT / "schemas" / "STRUCTURAL_MUTATION_PLAN_SCHEMA.json").read_text(encoding="utf-8"))
        self.assertIn("requirement_ids", schema["properties"])
        surface = schema["properties"]["surfaces"]["items"]["properties"]
        self.assertEqual("#/$defs/nonempty_string_set", surface["owned_paths"]["$ref"])
        self.assertEqual("#/$defs/nonempty_string_set", surface["expected_affected"]["$ref"])

    def test_source_surface_schema_exposes_root_inventory_reference(self) -> None:
        schema = json.loads((ROOT / "schemas" / "SOURCE_SURFACE_MAP_SCHEMA.json").read_text(encoding="utf-8"))
        self.assertIn("root_inventory_ref", schema["properties"])
        self.assertIn("root_inventory_sha256", schema["properties"])

    def test_high_assurance_tests_are_registered_in_all_machine_catalogs(self) -> None:
        layers = json.loads((ROOT / "tests" / "TEST_LAYERS.json").read_text(encoding="utf-8"))
        retained = json.loads((ROOT / "tests" / "RETAINED_TESTS.json").read_text(encoding="utf-8"))
        proof_map = json.loads((ROOT / "tests" / "PROOF_MAP.json").read_text(encoding="utf-8"))
        expected = {
            "tests/test_source_collection_contract.py",
            "tests/test_source_surface_evidence.py",
            "tests/test_engineering_contracts.py",
            "tests/test_engineering_rights_contract.py",
            "tests/test_mutation_plan_traceability.py",
            "tests/test_ci_waiver_contract.py",
            "tests/test_high_assurance_gate.py",
            "tests/test_proof_runner_contract.py",
            "tests/test_reference_fixture_byte_custody.py",
            "tests/test_legacy_fixture_byte_custody.py",
            "tests/test_source_review_turn_chain.py",
            "tests/test_engineering_contract_index.py",
        }
        unit_proofs = set(layers["layers"]["unit_regression"]["proofs"])
        unit_commands = {tuple(command) for command in layers["layers"]["unit_regression"]["commands"]}
        self.assertTrue(expected <= unit_proofs)
        self.assertTrue(expected <= set(retained["active_proofs"]))
        for path in expected:
            self.assertIn(("python", path), unit_commands)
        mapped = set()
        for feature in proof_map["features"].values():
            mapped.update(feature.get("unit_regression", []))
        self.assertTrue(expected <= mapped)

    def test_external_methodology_provenance_is_exact_and_noncopying(self) -> None:
        value = json.loads((ROOT / "policies" / "ENGINEERING_CONTRACT_PROVENANCE.json").read_text(encoding="utf-8"))
        self.assertEqual("flyby/mission-control-engineering-contract-provenance/1", value["schema"])
        sources = {item["id"]: item for item in value["sources"]}
        self.assertEqual({"PROV-SPEC-KIT", "PROV-TREE-SITTER", "PROV-ACTIONLINT"}, set(sources))
        for source in sources.values():
            self.assertRegex(source["revision"], r"^[0-9a-f]{40}$")
            self.assertEqual("MIT", source["license"])
            self.assertRegex(source["license_blob_sha"], r"^[0-9a-f]{40}$")
            self.assertFalse(source["direct_code_reuse"])
            self.assertFalse(source["direct_text_reuse"])
            self.assertTrue(source["contribution"])
            self.assertTrue(source["mission_control_derivation"])

    def test_template_ci_uses_immutable_action_revisions_and_least_privilege(self) -> None:
        workflow = SOURCE_REPO / ".github" / "workflows" / "mission-control-template.yml"
        content = workflow.read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", content)
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)", content, flags=re.MULTILINE)
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, r"@([0-9a-f]{40})$", action)
        self.assertIn("ubuntu-latest", content)
        self.assertIn("windows-latest", content)
        self.assertIn("macos-latest", content)
        self.assertIn("EXPECTED_SHA", content)
        self.assertIn("PYTHONPYCACHEPREFIX", content)
        self.assertIn("git','rev-parse','HEAD", content)
        self.assertIn("run_template_suite.py", content)
        self.assertIn("--expected-sha", content)
        self.assertIn("--require-clean", content)
        self.assertIn("--evidence-dir .ci-evidence", content)
        self.assertIn("uses: actions/upload-artifact@", content)
        self.assertIn("if-no-files-found: error", content)
        self.assertIn("include-hidden-files: true", content)
        self.assertIn("retention-days: 30", content)
        long_path_index = content.index("git config --global core.longpaths true")
        checkout_index = content.index("uses: actions/checkout@")
        self.assertLess(long_path_index, checkout_index, "Windows long-path preflight must run before checkout")
        self.assertIn("if: runner.os == 'Windows'", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
