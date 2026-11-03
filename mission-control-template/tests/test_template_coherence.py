#!/usr/bin/env python3
"""Static coherence tests for Mission Control template v16."""
from __future__ import annotations

import argparse
import importlib.util
import json
import py_compile
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_mc():
    path = ROOT / "tools" / "mc.py"
    spec = importlib.util.spec_from_file_location("template_mc", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load_mc()


class TemplateCoherenceSuite(unittest.TestCase):
    def test_01_template_manifest_is_small_and_operational(self) -> None:
        template = mc.load_json(ROOT / "TEMPLATE.json")
        self.assertEqual(mc.TEMPLATE_SCHEMA, template["schema"])
        self.assertLessEqual(len(template), 45, "TEMPLATE.json should remain a compact contract index, not a policy encyclopedia")
        for key in (
            "initializer", "doctor", "operator_cli", "mission_schema", "template_lock_schema",
            "current_authority_schema", "execution_dag_schema", "execution_state_schema", "compiler_control_schema",
            "cell_schema", "workcell_schema", "frontier_schema", "result_schema", "adjudication_schema", "target_corpus_schema", "source_registry_schema",
            "provenance_synthesis_schema", "source_independent_review_schema", "provenance_methodology", "engineering_audit_methodology", "native_task_pipeline_policy", "task_pipeline_schema", "source_review_turn_contract_schema", "source_review_turn_chain_index_schema", "source_review_checkpoint_schema", "source_review_cleanup_schema", "workspace_reconciliation_schema", "supersession_record_schema", "workspace_reconciliation_policy", "workspace_ledger_schema",
            "context_manifest_schema", "context_receipt_schema",
            "session_residency_schema", "qualification_schema", "closure_schema", "schema_validator",
            "mission_test", "golden_test",
        ):
            self.assertIn(key, template)
        path_values = [
            template["operator_cli"], template["mission_schema"], template["template_lock_schema"],
            template["current_authority_schema"], template["execution_dag_schema"], template["execution_state_schema"],
            template["compiler_control_schema"], template["cell_schema"], template["workcell_schema"], template["frontier_schema"], template["result_schema"], template["adjudication_schema"],
            template["target_corpus_schema"], template["source_registry_schema"], template["provenance_synthesis_schema"], template["source_independent_review_schema"], template["provenance_methodology"], template["engineering_audit_methodology"], template["native_task_pipeline_policy"], template["task_pipeline_schema"], template["source_review_turn_contract_schema"], template["source_review_turn_chain_index_schema"], template["source_review_checkpoint_schema"], template["source_review_cleanup_schema"],
            template["workspace_reconciliation_schema"], template["supersession_record_schema"], template["workspace_reconciliation_policy"], template["workspace_ledger_schema"], template["context_manifest_schema"],
            template["context_receipt_schema"], template["session_residency_schema"],
            template["qualification_schema"], template["closure_schema"], template["schema_validator"],
            template["mission_test"], template["golden_test"],
        ]
        for rel in path_values:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertEqual(["UNINITIALIZED", *mc.LIFECYCLE], template["lifecycle"])
        self.assertEqual({"AUDIT", "MUTATION", "INTEGRATION", "QUALIFICATION", "BARRIER"}, set(template["cell_kinds"]))

    def test_02_all_template_json_parses_and_schema_ids_are_unique(self) -> None:
        ids: dict[str, Path] = {}
        for path in sorted(ROOT.rglob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("$id"), str):
                schema_id = value["$id"]
                self.assertNotIn(schema_id, ids, f"duplicate $id {schema_id}: {ids.get(schema_id)} and {path}")
                ids[schema_id] = path
        self.assertIn(mc.MISSION_SCHEMA, ids)
        self.assertIn(mc.RESULT_SCHEMA, ids)
        self.assertIn(mc.STATE_SCHEMA, ids)

    def test_03_local_schema_references_resolve(self) -> None:
        failures: list[str] = []

        def walk(value, source: Path) -> None:
            if isinstance(value, dict):
                ref = value.get("$ref")
                if isinstance(ref, str) and "://" not in ref and not ref.startswith("#"):
                    target = (source.parent / ref.split("#", 1)[0]).resolve()
                    if not target.is_file():
                        failures.append(f"{source.relative_to(ROOT)} -> {ref}")
                for child in value.values():
                    walk(child, source)
            elif isinstance(value, list):
                for child in value:
                    walk(child, source)

        for path in sorted((ROOT / "schemas").rglob("*.json")):
            walk(json.loads(path.read_text(encoding="utf-8")), path)
        self.assertEqual([], failures, "unresolved schema refs:\n" + "\n".join(failures))

    def test_04_operator_cli_surface_matches_documented_lifecycle(self) -> None:
        parser = mc.build_parser()
        action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        expected = {"init", "doctor", "status", "sources", "provenance", "corpus", "workspace", "baseline", "barrier", "retry", "compile", "dispatch", "settle", "integrate", "qualify", "close", "test", "repair"}
        self.assertEqual(expected, set(action.choices))
        for command in ("sources", "provenance", "corpus"):
            command_parser = action.choices[command]
            command_action = next(a for a in command_parser._actions if isinstance(a, argparse._SubParsersAction))
            self.assertEqual({"load"}, set(command_action.choices))
        workspace_parser = action.choices["workspace"]
        workspace_action = next(a for a in workspace_parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual({"register", "load"}, set(workspace_action.choices))
        baseline_parser = action.choices["baseline"]
        baseline_action = next(a for a in baseline_parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual({"compile", "accept"}, set(baseline_action.choices))
        barrier_parser = action.choices["barrier"]
        barrier_action = next(a for a in barrier_parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual({"accept"}, set(barrier_action.choices))
        repair_parser = action.choices["repair"]
        repair_action = next(a for a in repair_parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual({"bootstrap"}, set(repair_action.choices))
        dispatch_parser = action.choices["dispatch"]
        dispatch_required = {option for item in dispatch_parser._actions if item.required for option in item.option_strings}
        self.assertTrue({"--root", "--cell", "--worker-identity", "--verifier-identity"} <= dispatch_required)
        settle_parser = action.choices["settle"]
        required = {option for item in settle_parser._actions if item.required for option in item.option_strings}
        self.assertTrue({"--root", "--cell", "--attempt", "--result", "--context-receipt", "--adjudication"} <= required)

    def test_05_reference_mission_is_valid_author_input(self) -> None:
        mission = mc.load_json(ROOT / "examples" / "reference-mission" / "MISSION.json")
        self.assertEqual([], mc.validate_mission_spec(mission))
        frontier = mc.load_json(ROOT / "examples" / "reference-mission" / "MUTATION_FRONTIER.json")
        self.assertEqual([], mc._validate_frontier(frontier))
        sources = mc.load_json(ROOT / "examples" / "reference-mission" / "SOURCES.json")
        provenance = mc.load_json(ROOT / "examples" / "reference-mission" / "PROVENANCE_SYNTHESIS.json")
        corpus = mc.load_json(ROOT / "examples" / "reference-mission" / "TARGET_CORPUS.json")
        workspace = mc.load_json(ROOT / "examples" / "reference-mission" / "WORKSPACE_RECONCILIATION.json")
        workspace_ledger = mc.load_json(ROOT / "examples" / "reference-mission" / "WORKSPACE_LEDGER.json")
        source_review = mc.load_json(ROOT / "examples" / "reference-mission" / "evidence" / "REFERENCE_SOURCE_INDEPENDENT_REVIEW.json")
        source_review_schema = mc.load_json(ROOT / "schemas" / "SOURCE_INDEPENDENT_REVIEW_SCHEMA.json")
        self.assertEqual([], mc.validate_schema_instance(source_review, source_review_schema, source_review_schema, schema_path=ROOT / "schemas" / "SOURCE_INDEPENDENT_REVIEW_SCHEMA.json"))
        self.assertEqual([], mc.validate_schema_instance(sources, mc.load_json(ROOT / "schemas" / "SOURCE_REGISTRY_SCHEMA.json"), mc.load_json(ROOT / "schemas" / "SOURCE_REGISTRY_SCHEMA.json"), schema_path=ROOT / "schemas" / "SOURCE_REGISTRY_SCHEMA.json"))
        self.assertEqual([], mc.validate_schema_instance(corpus, mc.load_json(ROOT / "schemas" / "TARGET_CORPUS_SCHEMA.json"), mc.load_json(ROOT / "schemas" / "TARGET_CORPUS_SCHEMA.json"), schema_path=ROOT / "schemas" / "TARGET_CORPUS_SCHEMA.json"))
        self.assertEqual([], mc.validate_schema_instance(provenance, mc.load_json(ROOT / "schemas" / "PROVENANCE_SYNTHESIS_SCHEMA.json"), mc.load_json(ROOT / "schemas" / "PROVENANCE_SYNTHESIS_SCHEMA.json"), schema_path=ROOT / "schemas" / "PROVENANCE_SYNTHESIS_SCHEMA.json"))
        self.assertEqual([], mc.validate_schema_instance(workspace, mc.load_json(ROOT / "schemas" / "WORKSPACE_RECONCILIATION_SCHEMA.json"), mc.load_json(ROOT / "schemas" / "WORKSPACE_RECONCILIATION_SCHEMA.json"), schema_path=ROOT / "schemas" / "WORKSPACE_RECONCILIATION_SCHEMA.json"))
        self.assertEqual([], mc.validate_schema_instance(workspace_ledger, mc.load_json(ROOT / "schemas" / "WORKSPACE_LEDGER_SCHEMA.json"), mc.load_json(ROOT / "schemas" / "WORKSPACE_LEDGER_SCHEMA.json"), schema_path=ROOT / "schemas" / "WORKSPACE_LEDGER_SCHEMA.json"))
        mission_targets = {target["repository"] for target in mission["target_repositories"]}
        for requirement in corpus["requirements"]:
            self.assertTrue(set(requirement["targets"]) <= mission_targets)
        multi_target_corpus = {
            "requirements": [{
                "id": "R-MULTI",
                "targets": ["repo/A", "repo/B"],
                "acceptance": ["criterion-one", "criterion-two"],
            }]
        }
        one_repo_cells = [{
            "kind": "MUTATION",
            "requirement_ids": ["R-MULTI"],
            "target": {"repository": "repo/A"},
            "acceptance": ["criterion-one", "criterion-two"],
        }]
        self.assertEqual({"R-MULTI": ["repo/B"]}, mc.requirement_target_gaps(multi_target_corpus, one_repo_cells))
        partial_repo_b = [
            *one_repo_cells,
            {
                "kind": "MUTATION",
                "requirement_ids": ["R-MULTI"],
                "target": {"repository": "repo/B"},
                "acceptance": ["criterion-one"],
            },
        ]
        self.assertEqual({}, mc.requirement_target_gaps(multi_target_corpus, partial_repo_b))
        self.assertEqual(
            {"R-MULTI@repo/B": ["criterion-two"]},
            mc.requirement_target_acceptance_gaps(multi_target_corpus, partial_repo_b),
        )
        complete_repo_b = json.loads(json.dumps(partial_repo_b))
        complete_repo_b[1]["acceptance"].append("criterion-two")
        self.assertEqual({}, mc.requirement_target_acceptance_gaps(multi_target_corpus, complete_repo_b))
        frontier_schema_path = ROOT / "schemas" / "FRONTIER_SCHEMA.json"
        frontier_schema = mc.load_json(frontier_schema_path)
        self.assertEqual([], mc.validate_schema_instance(frontier, frontier_schema, frontier_schema, schema_path=frontier_schema_path))
        bad = json.loads(json.dumps(frontier))
        bad["cells"][0]["target"]["owned_paths"] = []
        self.assertTrue(any("owned_paths" in error for error in mc._validate_frontier(bad)))
        bad_status = json.loads(json.dumps(frontier))
        bad_status["cells"][0]["status"] = "ACCEPTED"
        self.assertTrue(mc.validate_schema_instance(bad_status, frontier_schema, frontier_schema, schema_path=frontier_schema_path))
        bad_result_schema = json.loads(json.dumps(frontier))
        bad_result_schema["cells"][0]["result_schema"] = "contracts/schemas/CUSTOM.json"
        self.assertTrue(mc.validate_schema_instance(bad_result_schema, frontier_schema, frontier_schema, schema_path=frontier_schema_path))
        bad_qualification = json.loads(json.dumps(frontier))
        q000 = next(cell for cell in bad_qualification["cells"] if cell["cell_id"] == "Q000")
        q000["requirement_ids"] = ["REF-001"]
        self.assertTrue(mc.validate_schema_instance(bad_qualification, frontier_schema, frontier_schema, schema_path=frontier_schema_path))

    def test_06_policy_carries_forward_nonnegotiable_control_laws(self) -> None:
        executor = (ROOT / "policies" / "EXECUTOR_PROTOCOL.md").read_text(encoding="utf-8")
        laws = (ROOT / "policies" / "CONTROL_LAWS.md").read_text(encoding="utf-8")
        testing = (ROOT / "policies" / "LIFECYCLE_AND_TESTING.md").read_text(encoding="utf-8")
        self.assertIn("TARGET_BASE = CompiledWorkCell.base.repository + branch + head", executor)
        self.assertIn("not a target mutation base", executor)
        self.assertIn("gap != cause", laws.lower())
        self.assertIn("model self-report/confidence is never primary truth", laws.lower())
        self.assertIn("contextreceipt", laws.lower())
        self.assertIn("conflict graph", laws.lower())
        self.assertIn("v15-derived MCV6", testing)
        runtime = (ROOT / "tools" / "mc.py").read_text(encoding="utf-8")
        for token in ("PURE_PACKET_RECONSTRUCTION", "independent_adjudication_required", "preassigned_custody_required", "context_receipt_required", "session_residency_required", "aggregate_normalization"):
            self.assertIn(token, runtime)

    def test_06b_mcv_engineering_audit_methodology_carries_forward_mcv6_laws(self) -> None:
        template = mc.load_json(ROOT / "TEMPLATE.json")
        self.assertEqual(
            "policies/MCV_ENGINEERING_AUDIT_AND_ADJUDICATION.md",
            template["engineering_audit_methodology"],
        )
        policy = (ROOT / template["engineering_audit_methodology"]).read_text(encoding="utf-8")
        for token in (
            "**One material finding at a time**",
            "The Stage-A author/session must not self-certify Stage B",
            "Stage-C readiness is packaging, not adjudication",
            "Only the lowest nonterminal eligible fresh source may enter Stage C",
            "provider availability is not proof that the canonical adjudicator session is runnable",
            "full-source terminal receipt",
            "claims + recent durable receipts",
            "A/B closure is not Stage C completion",
        ):
            self.assertIn(token, policy)

    def test_06c_native_task_pipeline_preserves_mcv_queue_and_independence_laws(self) -> None:
        template = mc.load_json(ROOT / "TEMPLATE.json")
        self.assertEqual("policies/NATIVE_TASK_PIPELINE.md", template["native_task_pipeline_policy"])
        self.assertEqual("schemas/TASK_PIPELINE_SCHEMA.json", template["task_pipeline_schema"])
        policy = (ROOT / template["native_task_pipeline_policy"]).read_text(encoding="utf-8")
        for token in (
            "initially materialize **only Phase A** for every item",
            "append it at the **tail**",
            "AUTO_ASSIGN_NEXT_TO_COMPLETING_SEAT",
            "different_from_previous=true",
            "distinct_lineage_seat=true",
            "mission-defined project workflow",
            "actual Stage C remains the canonical serial adjudicator flow",
            "final Astra full-system pass in MCV6 is **not** a generic per-cell Phase C",
        ):
            self.assertIn(token, policy)

        schema_path = ROOT / template["task_pipeline_schema"]
        schema = mc.load_json(schema_path)
        example = mc.load_json(ROOT / "examples" / "reference-mission" / "TASK_PIPELINE.json")
        self.assertEqual([], mc.validate_schema_instance(example, schema, schema, schema_path=schema_path))
        self.assertEqual(["A", "B", "C"], [phase["id"] for phase in example["phases"]])
        self.assertTrue(example["phases"][1]["different_from_previous"])
        self.assertTrue(example["phases"][2]["distinct_lineage_seat"])

    def test_07_template_has_one_canonical_source_layout(self) -> None:
        forbidden_root_files = [
            "MANIFEST.json", "CONTEXT_AMENDMENT_SCHEMA.json", "CONTEXT_MANIFEST_SCHEMA.json",
            "CONTEXT_RECEIPT_SCHEMA.json", "CORE_MUTATION_CONTRACT_SCHEMA.json", "EXECUTION_STATE_SCHEMA.json",
            "WORKCELL_SCHEMA.json", "CONTROL_COHERENCE_GATE.md", "EXECUTION_STATE_AUTHORITY.md",
            "EXECUTOR_PROTOCOL.md", "OUTPUT_CONTRACT_ENFORCEMENT.md", "SESSION_REUSE_AND_REBINDING.md",
            "SESSION_REUSE_ADJUDICATION_SCHEMA.json", "SESSION_RESIDENCY_REGISTRY_SCHEMA.json",
        ]
        present = [name for name in forbidden_root_files if (ROOT / name).exists()]
        self.assertEqual([], present, f"legacy duplicate root artifacts remain: {present}")
        self.assertFalse((ROOT / "template").exists(), "template must not snapshot itself")

    def test_08_python_sources_compile(self) -> None:
        failures: list[str] = []
        for directory in (ROOT / "tools", ROOT / "tests"):
            for path in sorted(directory.rglob("*.py")):
                try:
                    py_compile.compile(str(path), doraise=True)
                except Exception as exc:  # pragma: no cover
                    failures.append(f"{path.relative_to(ROOT)}: {exc}")
        self.assertEqual([], failures, "python compile failures:\n" + "\n".join(failures))

    def test_09_testing_assets_are_present(self) -> None:
        self.assertTrue((ROOT / "tests" / "test_mission_control.py").is_file())
        self.assertTrue((ROOT / "tests" / "test_runtime_state_machine.py").is_file())
        self.assertTrue((ROOT / "tools" / "test_template_v16.py").is_file())
        self.assertTrue((ROOT / "policies" / "LIFECYCLE_AND_TESTING.md").is_file())

    def test_09b_adjudicated_synthesis_is_hash_bound_authorizing_input(self) -> None:
        source_schema = mc.load_json(ROOT / "schemas" / "SOURCE_REGISTRY_SCHEMA.json")
        dispositions = source_schema["properties"]["sources"]["items"]["properties"]["disposition"]["enum"]
        self.assertIn("ADJUDICATED_SYNTHESIS", dispositions)
        provenance_schema = mc.load_json(ROOT / "schemas" / "PROVENANCE_SYNTHESIS_SCHEMA.json")
        assessment = provenance_schema["$defs"]["source_assessment"]
        self.assertNotIn("deep_review", assessment["required"])
        self.assertNotIn("independent_review", assessment["required"])
        adjudication = assessment["properties"]["adjudication_evidence"]
        self.assertEqual(
            {"state", "admission", "receipt_ref", "receipt_sha256", "candidate_ref", "candidate_sha256"},
            set(adjudication["required"]),
        )
        runtime = (ROOT / "tools" / "mc.py").read_text(encoding="utf-8")
        policy = (ROOT / "policies" / "PROVENANCE_SYNTHESIS.md").read_text(encoding="utf-8")
        self.assertIn('{"SYNTHESIS_REQUIRED", "ADJUDICATED_SYNTHESIS"}', runtime)
        self.assertIn('source_disposition == "ADJUDICATED_SYNTHESIS"', runtime)
        self.assertIn("citation, summary, model verdict, or unbound transcript is never enough", policy.lower())


    def test_11_source_review_turn_contract_example_is_valid(self) -> None:
        schema = mc.load_json(ROOT / "schemas" / "SOURCE_REVIEW_TURN_CONTRACT_SCHEMA.json")
        instance = mc.load_json(ROOT / "examples" / "reference-mission" / "SOURCE_REVIEW_TURN.json")
        self.assertEqual([], mc.validate_schema_instance(instance, schema, schema, schema_path=ROOT / "schemas" / "SOURCE_REVIEW_TURN_CONTRACT_SCHEMA.json"))
        self.assertEqual("flyby/source-review-turn-contract/2.1", instance["contract_version"])
        self.assertEqual(1, instance["turn_metadata"]["turn_number"])
        self.assertIsNone(instance["turn_metadata"]["prior_turn_sha256"])
        self.assertEqual("IN_PROGRESS", instance["turn_payload"]["disposition_status"])
        self.assertTrue(instance["turn_payload"]["material_omissions_remaining"])
        self.assertTrue(instance["turn_payload"]["uninspected_critical_partitions"])
        self.assertFalse(instance["source_binding"]["child_thread_created"])
        self.assertFalse(instance["source_binding"]["delegation_used"])
        chain_schema=mc.load_json(ROOT / "schemas" / "SOURCE_REVIEW_TURN_CHAIN_INDEX_SCHEMA.json")
        chain=mc.load_json(ROOT / "examples" / "reference-mission" / "SOURCE_REVIEW_TURN_CHAIN_INDEX.json")
        self.assertEqual([], mc.validate_schema_instance(chain, chain_schema, chain_schema, schema_path=ROOT / "schemas" / "SOURCE_REVIEW_TURN_CHAIN_INDEX_SCHEMA.json"))

    def test_10_runtime_schema_subset_supports_every_runtime_schema(self) -> None:
        runtime_schemas = (
            "MISSION_SCHEMA.json", "TEMPLATE_LOCK_SCHEMA.json", "CURRENT_AUTHORITY_SCHEMA.json",
            "EXECUTION_DAG_SCHEMA.json", "EXECUTION_STATE_SCHEMA.json", "COMPILER_CONTROL_SCHEMA.json",
            "WORKCELL_SCHEMA.json", "RESULT_SCHEMA.json", "ADJUDICATION_SCHEMA.json", "TARGET_CORPUS_SCHEMA.json", "SOURCE_REGISTRY_SCHEMA.json",
            "PROVENANCE_SYNTHESIS_SCHEMA.json", "SOURCE_INDEPENDENT_REVIEW_SCHEMA.json", "TASK_PIPELINE_SCHEMA.json", "SOURCE_REVIEW_TURN_CONTRACT_SCHEMA.json", "SOURCE_REVIEW_TURN_CHAIN_INDEX_SCHEMA.json", "SOURCE_REVIEW_CHECKPOINT_SCHEMA.json", "SOURCE_REVIEW_CLEANUP_SCHEMA.json", "WORKSPACE_RECONCILIATION_SCHEMA.json", "SUPERSESSION_RECORD_SCHEMA.json", "WORKSPACE_LEDGER_SCHEMA.json",
            "CONTEXT_RECEIPT_SCHEMA.json", "SESSION_RESIDENCY_REGISTRY_SCHEMA.json",
            "QUALIFICATION_SCHEMA.json", "CLOSURE_SCHEMA.json",
        )
        for name in runtime_schemas:
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            mc.validate_schema_keywords(schema)

        frontier_path = ROOT / "schemas" / "FRONTIER_SCHEMA.json"
        frontier_schema = json.loads(frontier_path.read_text(encoding="utf-8"))
        frontier = json.loads((ROOT / "examples" / "reference-mission" / "MUTATION_FRONTIER.json").read_text(encoding="utf-8"))
        self.assertEqual([], mc.validate_schema_instance(frontier, frontier_schema, frontier_schema, schema_path=frontier_path))
        invalid = json.loads(json.dumps(frontier))
        del invalid["cells"][0]["objective"]
        self.assertTrue(mc.validate_schema_instance(invalid, frontier_schema, frontier_schema, schema_path=frontier_path))

    def test_11_provenance_schema_supports_evidence_without_mechanism_inflation(self) -> None:
        schema=mc.load_json(ROOT / "schemas" / "PROVENANCE_SYNTHESIS_SCHEMA.json")
        enum=schema["$defs"]["source_assessment"]["properties"]["coverage_items"]["items"]["properties"]["disposition"]["enum"]
        self.assertIn("EVIDENCE_ONLY", enum)
        policy=(ROOT / "policies" / "PROVENANCE_SYNTHESIS.md").read_text(encoding="utf-8")
        self.assertIn("Mechanism versus evidence classification", policy)
        self.assertIn("must never delete its evidence", policy)

    def test_11_source_review_policy_is_compaction_safe_and_cleanup_protects_authority(self) -> None:
        policy=(ROOT / "policies" / "PROVENANCE_SYNTHESIS.md").read_text(encoding="utf-8")
        self.assertIn("read the whole source, then write the report", policy)
        self.assertIn("previous_checkpoint_sha256", policy)
        self.assertIn("SOURCE_FACT", policy)
        self.assertIn("ENGINEERING_INFERENCE", policy)
        self.assertIn("SOURCE_REVIEW_CLEANUP_SCHEMA.json", policy)
        self.assertIn("AGENT_AUTHORED_REVIEW", policy)

    def test_11_provenance_policy_requires_behavior_specific_source_attribution(self) -> None:
        policy=(ROOT / "policies" / "PROVENANCE_SYNTHESIS.md").read_text(encoding="utf-8")
        self.assertIn("Behavior-specific source attribution", policy)
        self.assertIn("does not automatically support every acceptance clause", policy)
        self.assertIn("must not be credited to a source merely because its mechanism is composed into the same subsystem", policy)

    def test_11_provenance_policy_preserves_rejected_and_negative_review_rows(self) -> None:
        policy=(ROOT / "policies" / "PROVENANCE_SYNTHESIS.md").read_text(encoding="utf-8")
        self.assertIn("Reviewed source rows may outnumber executable mechanisms", policy)
        self.assertIn("Rejected or negative rows remain full-fidelity evidence", policy)

    def test_11_template_provenance_distinguishes_clean_and_dirty_sources(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcv16-provenance-") as tmp:
            repo = Path(tmp) / "repo"
            template = repo / "mission-control-template"
            template.mkdir(parents=True)
            marker = template / "marker.txt"
            marker.write_text("clean\n", encoding="utf-8")
            (repo / ".gitignore").write_text("ignored-template/\nmission-control-template/schemas/ignored-*.json\n", encoding="utf-8")
            for relative in ("TEMPLATE.json", "schemas/schema.json", "policies/policy.md",
                             "tools/mc.py", "tools/wt_mission.py", "tools/schema_subset.py",
                             "tests/test_mission_control.py"):
                asset = template / relative
                asset.parent.mkdir(parents=True, exist_ok=True)
                asset.write_text("fixture\n", encoding="utf-8")
            commands = (
                ["git", "init"],
                ["git", "config", "user.name", "Mission Control Test"],
                ["git", "config", "user.email", "mission-control@example.invalid"],
                ["git", "add", "."],
                ["git", "commit", "-m", "fixture"],
            )
            for command in commands:
                subprocess.run(command, cwd=repo, check=True, capture_output=True, text=True)
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            clean = mc._template_provenance(template)
            self.assertEqual("CLEAN_COMMIT", clean["template_source_state"])
            self.assertEqual(head, clean["template_commit"])
            self.assertEqual(head, clean["template_base_commit"])

            packaged = repo / "ignored-template" / "mission-control-template"
            shutil.copytree(template, packaged)
            unversioned = mc._template_provenance(packaged)
            self.assertEqual("UNVERSIONED", unversioned["template_source_state"])
            self.assertIsNone(unversioned["template_commit"])
            self.assertIsNone(unversioned["template_base_commit"])

            hidden_asset = template / "schemas" / "ignored-extra.json"
            hidden_asset.write_text("{}\n", encoding="utf-8")
            ignored_dirty = mc._template_provenance(template)
            self.assertEqual("DIRTY_WORKTREE", ignored_dirty["template_source_state"])
            self.assertEqual(head, ignored_dirty["template_base_commit"])
            hidden_asset.unlink()

            indexed_asset = template / "schemas" / "schema.json"
            indexed_path = "mission-control-template/schemas/schema.json"
            for flag, clear in (("--assume-unchanged", "--no-assume-unchanged"),
                                ("--skip-worktree", "--no-skip-worktree")):
                subprocess.run(["git", "update-index", flag, indexed_path], cwd=repo, check=True, capture_output=True)
                indexed_asset.write_text("changed despite index flag\n", encoding="utf-8")
                flagged = mc._template_provenance(template)
                self.assertEqual("DIRTY_WORKTREE", flagged["template_source_state"], flag)
                self.assertIsNone(flagged["template_commit"], flag)
                indexed_asset.write_text("fixture\n", encoding="utf-8")
                subprocess.run(["git", "update-index", clear, indexed_path], cwd=repo, check=True, capture_output=True)

            marker.write_text("dirty\n", encoding="utf-8")
            dirty = mc._template_provenance(template)
            self.assertEqual("DIRTY_WORKTREE", dirty["template_source_state"])
            self.assertIsNone(dirty["template_commit"])
            self.assertEqual(head, dirty["template_base_commit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
