#!/usr/bin/env python3
"""Focused local Git-object tests for same-repository lineage preservation."""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "lineage_preservation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("lineage_preservation_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitLineageSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-lineage-git-")
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git("init")
        self.git("config", "user.name", "Lineage Test")
        self.git("config", "user.email", "lineage@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.files = {
            "LINEAGE": ("sources_provenance.yaml", b"lineage: retained\r\n"),
            "HARVEST": ("external_harvest_manifest.yaml", b"harvest: retained\n"),
            "POLICY": ("PROJECT_OPERATING_CONTRACT.md", b"preserve lineage\n"),
            "VALIDATOR": ("scripts/ci/verify_sources_provenance.py", b"print('fixture')\n"),
        }
        for _, (name, data) in self.files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git("add", ".")
        self.git("commit", "-m", "accepted base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("remote", "add", "origin", "https://github.com/example/target.git")
        self.protected = []
        for role, (name, data) in self.files.items():
            entry = self.git("ls-tree", self.base, "--", name).stdout.strip()
            header, _, _ = entry.partition("\t")
            mode, _, blob = header.split(" ")
            self.protected.append({"role": role, "path": name, "mode": mode,
                                   "git_blob": blob, "sha256": hashlib.sha256(data).hexdigest()})
        self.contract = {"repository": "example/target", "policy_base_sha": self.base,
                         "protected_files": self.protected}
        (self.repo / "implementation.py").write_text("same-repository change\n", encoding="utf-8")
        self.git("add", "implementation.py")
        self.git("commit", "-m", "candidate")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(self.repo), *args],
                              check=True, capture_output=True, text=True)

    def fixture_module(self):
        module = load_module()
        # Exercise the production validator with an inert, explicitly test-only
        # authority profile for the synthetic repository and its fixture blobs.
        module.PROFILE_REPOSITORY = "example/target"
        module.PROFILE_POLICY_BLOB = next(item["git_blob"] for item in self.protected if item["role"] == "POLICY")
        module.PROFILE_VALIDATOR_BLOB = next(item["git_blob"] for item in self.protected if item["role"] == "VALIDATOR")
        return module

    def test_production_profile_rejects_unestablished_repository(self) -> None:
        module = load_module()
        self.assertEqual("saiflyby/flybymaestro", module.PROFILE_REPOSITORY)
        self.assertTrue(module.verify_target_trees(self.repo, self.contract, self.candidate, self.base))

    def test_unchanged_committed_objects_match_at_base_and_candidate(self) -> None:
        module = self.fixture_module()
        self.assertEqual([], module.verify_target_trees(self.repo, self.contract, self.candidate, self.base))

    def test_changed_lineage_or_stale_publication_base_is_rejected(self) -> None:
        module = self.fixture_module()
        (self.repo / "sources_provenance.yaml").write_bytes(b"lineage: changed\n")
        self.git("add", "sources_provenance.yaml")
        self.git("commit", "-m", "changed lineage")
        changed = self.git("rev-parse", "HEAD").stdout.strip()
        errors = module.verify_target_trees(self.repo, self.contract, changed, self.base)
        self.assertTrue(any("sources_provenance.yaml" in error for error in errors), errors)
        errors = module.verify_target_trees(self.repo, self.contract, self.candidate, changed)
        self.assertTrue(any("base" in error.lower() for error in errors), errors)

    def test_changed_harvest_cannot_hide_behind_an_unchanged_decoy(self) -> None:
        module = self.fixture_module()
        decoy = self.repo / "unrelated-harvest.yaml"
        decoy.write_bytes(b"decoy: unchanged\n")
        self.git("add", "unrelated-harvest.yaml")
        self.git("commit", "-m", "add decoy")
        policy_base = self.git("rev-parse", "HEAD").stdout.strip()
        entry = self.git("ls-tree", policy_base, "--", "unrelated-harvest.yaml").stdout.strip()
        mode, _, blob = entry.partition("\t")[0].split(" ")
        contract = {**self.contract, "policy_base_sha": policy_base,
                    "protected_files": [dict(item) for item in self.protected]}
        harvest = next(item for item in contract["protected_files"] if item["role"] == "HARVEST")
        harvest.update({"path": "unrelated-harvest.yaml", "mode": mode, "git_blob": blob,
                        "sha256": hashlib.sha256(decoy.read_bytes()).hexdigest()})
        (self.repo / "external_harvest_manifest.yaml").write_bytes(b"harvest: changed\n")
        self.git("add", "external_harvest_manifest.yaml")
        self.git("commit", "-m", "change real harvest manifest")
        candidate = self.git("rev-parse", "HEAD").stdout.strip()
        errors = module.verify_target_trees(self.repo, contract, candidate, policy_base)
        self.assertTrue(errors, "an unchanged decoy cannot stand in for the actual harvest manifest")
    def test_unsafe_or_missing_manifest_is_rejected(self) -> None:
        module = self.fixture_module()
        contract = {**self.contract, "protected_files": [dict(item) for item in self.protected]}
        contract["protected_files"][0]["path"] = "../sources_provenance.yaml"
        errors = module.verify_target_trees(self.repo, contract, self.candidate, self.base)
        self.assertTrue(errors)
        contract["protected_files"][0]["path"] = "missing.yaml"
        errors = module.verify_target_trees(self.repo, contract, self.candidate, self.base)
        self.assertTrue(errors)


    def test_profile_rejects_swapped_duplicate_or_changed_authority(self) -> None:
        module = self.fixture_module()
        import copy
        for mutate in (
            lambda c: c["protected_files"][1].update(path="unrelated-harvest.yaml"),
            lambda c: c["protected_files"][1].update(role="POLICY"),
            lambda c: c["protected_files"][2].update(git_blob="0" * 40),
            lambda c: c.update(repository="other/repository"),
        ):
            contract = copy.deepcopy(self.contract)
            mutate(contract)
            self.assertTrue(module.validate_target_profile(contract["repository"], contract["protected_files"]))

    def test_external_or_changed_source_cannot_use_preservation_mode(self) -> None:
        import copy
        import json
        module = self.fixture_module()
        mission = Path(self.tmp.name) / "mission"
        (mission / "evidence").mkdir(parents=True)
        proof = mission / "evidence" / "review.json"
        proof.write_text('{"decision":"VERIFIED"}', encoding="utf-8")
        source = {"id": "same-repo", "kind": "REPOSITORY",
                  "locator": "https://github.com/example/target/tree/" + self.base,
                  "pin": self.base, "disposition": "SYNTHESIS_REQUIRED",
                  "copyright": {"usage_mode": "OWNER_AUTHORIZED_REUSE", "rights_status": "VERIFIED",
                                "obligations": [], "code_copy_allowed": True}}
        source_digest = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=False).encode("utf-8")).hexdigest()
        sources = {"sources": [{"id": "owner-intent", "kind": "OWNER_INTENT",
                                 "locator": "MISSION.json#owner_intent"}, source]}
        corpus = {"requirements": [{"id": "REQ", "sources": ["owner-intent", "same-repo"],
                                    "mechanisms": ["MECH"], "targets": ["example/target"]}]}
        synthesis = {"source_assessments": [{"source_id": "same-repo", "coverage_status": "COMPLETE",
                      "open_questions": [], "independent_review": {
                          "state": "VERIFIED", "review_ref": "evidence/review.json",
                          "review_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                          "source_record_sha256": source_digest,
                          "reviewer_identity": "reviewer", "extractor_identity": "extractor"}}],
                     "mechanisms": [{"id": "MECH", "disposition": "COMBINE_EXISTING",
                                     "source_ids": ["same-repo"], "target_requirements": ["REQ"]}],
                     "cross_source_synthesis": {"state": "VERIFIED"}}
        self.assertEqual([], module.verify_source_scope(mission, self.repo, "example/target",
                                                        corpus, sources, synthesis, self.candidate))
        corpus["schema"] = "flyby/mission-control-target-corpus/17"
        corpus["mission_id"] = "M1"
        corpus["provenance_materialization"] = {
            "mode": "SAME_REPOSITORY_NO_NEW_HARVEST", "coverage_requirement_id": "REQ",
            "preservation": self.contract,
        }
        (mission / "corpus").mkdir()
        for filename, value in (("TARGET_MUTATIONS.json", corpus), ("SOURCES.json", sources),
                                ("PROVENANCE_SYNTHESIS.json", synthesis)):
            (mission / "corpus" / filename).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        candidate_evidence = mission / "evidence" / "candidate-review.txt"
        candidate_evidence.write_text("independently reviewed exact candidate", encoding="utf-8")
        digest = lambda name: hashlib.sha256((mission / "corpus" / name).read_bytes()).hexdigest()
        state = {"mission_id": "M1", "mission_instance_id": "instance-1"}
        record = {"attempt": 1, "worker_identity": "worker", "verifier_identity": "verifier"}
        review = {
            "schema": "flyby/mission-control-lineage-preservation-review/1",
            "mission_id": "M1", "mission_instance_id": "instance-1", "cell_id": "M000", "attempt": 1,
            "repository": "example/target", "policy_base_sha": self.base, "candidate_sha": self.candidate,
            "corpus_sha256": digest("TARGET_MUTATIONS.json"), "sources_sha256": digest("SOURCES.json"),
            "synthesis_sha256": digest("PROVENANCE_SYNTHESIS.json"), "author_identity": "worker",
            "reviewer_identity": "verifier", "decision": "VERIFIED_SAME_REPOSITORY_NO_NEW_HARVEST",
            "no_new_external_contribution": True, "no_new_obligations": True,
            "reviewed_source_ids": ["owner-intent", "same-repo"],
            "evidence": [{"ref": "evidence/candidate-review.txt",
                          "sha256": hashlib.sha256(candidate_evidence.read_bytes()).hexdigest()}],
        }
        self.assertEqual([], module.verify_preservation_review(mission, self.repo, corpus, sources,
                          synthesis, state, "M000", record, self.candidate, self.base, review))
        # A fresh base review retains the original policy/profile pin.
        self.git("checkout", "--detach", self.base)
        (self.repo / "base-only.txt").write_text("accepted main context\n", encoding="utf-8")
        self.git("add", "base-only.txt")
        self.git("commit", "-m", "advance accepted base")
        advanced = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("merge", "--no-edit", self.candidate)
        combined = self.git("rev-parse", "HEAD").stdout.strip()
        stale_base_review = {**review, "candidate_sha": combined}
        self.assertTrue(module.verify_preservation_review(mission, self.repo, corpus, sources,
                        synthesis, state, "M000", record, combined, advanced, stale_base_review))
        renewed = {**stale_base_review, "publication_base_sha": advanced}
        self.assertEqual([], module.verify_preservation_review(mission, self.repo, corpus, sources,
                         synthesis, state, "M000", record, combined, advanced, renewed))
        self.assertEqual(self.base, renewed["policy_base_sha"])
        self.assertTrue(module.verify_target_trees(self.repo, self.contract, self.candidate,
                                                  advanced, reviewed_base=advanced))
        self.git("checkout", "--detach", advanced)
        (self.repo / "sources_provenance.yaml").write_bytes(b"changed on accepted main\n")
        self.git("add", "sources_provenance.yaml")
        self.git("commit", "-m", "change protected lineage")
        changed = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertTrue(module.verify_target_trees(self.repo, self.contract, changed,
                                                  changed, reviewed_base=changed))
        wrong_workspace = copy.deepcopy(review)
        wrong_workspace["workspace_id"] = "unregistered"
        self.assertTrue(module.verify_preservation_review(mission, self.repo, corpus, sources,
                        synthesis, state, "M000", record, self.candidate, self.base, wrong_workspace))
        extra_source = copy.deepcopy(source)
        extra_source["id"] = "another-same-repo"
        extra_sources = copy.deepcopy(sources)
        extra_sources["sources"].append(extra_source)
        extra_synthesis = copy.deepcopy(synthesis)
        extra_assessment = copy.deepcopy(synthesis["source_assessments"][0])
        extra_assessment["source_id"] = extra_source["id"]
        extra_assessment["independent_review"]["source_record_sha256"] = hashlib.sha256(
            json.dumps(extra_source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        extra_synthesis["source_assessments"].append(extra_assessment)
        for filename, value in (("SOURCES.json", extra_sources),
                                ("PROVENANCE_SYNTHESIS.json", extra_synthesis)):
            (mission / "corpus" / filename).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        extra_review = copy.deepcopy(review)
        extra_review["sources_sha256"] = digest("SOURCES.json")
        extra_review["synthesis_sha256"] = digest("PROVENANCE_SYNTHESIS.json")
        errors = module.verify_preservation_review(mission, self.repo, corpus, extra_sources,
                     extra_synthesis, state, "M000", record, self.candidate, self.base, extra_review)
        self.assertTrue(any("every exact relevant source" in error for error in errors), errors)
        extra_review["reviewed_source_ids"].append("another-same-repo")
        self.assertEqual([], module.verify_preservation_review(mission, self.repo, corpus, extra_sources,
                         extra_synthesis, state, "M000", record, self.candidate, self.base, extra_review))
        for filename, value in (("SOURCES.json", sources), ("PROVENANCE_SYNTHESIS.json", synthesis)):
            (mission / "corpus" / filename).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        stale = copy.deepcopy(review)
        stale["candidate_sha"] = self.base
        self.assertTrue(module.verify_preservation_review(mission, self.repo, corpus, sources,
                        synthesis, state, "M000", record, self.candidate, self.base, stale))
        self_review = copy.deepcopy(review)
        self_review["reviewer_identity"] = "worker"
        self.assertTrue(module.verify_preservation_review(mission, self.repo, corpus, sources,
                        synthesis, state, "M000", record, self.candidate, self.base, self_review))
        external = copy.deepcopy(sources)
        external["sources"][1]["locator"] = "https://github.com/other/donor/tree/" + self.base
        self.assertTrue(module.verify_source_scope(mission, self.repo, "example/target",
                                                   corpus, external, synthesis, self.candidate))
        wrong_host = copy.deepcopy(sources)
        wrong_host["sources"][1]["locator"] = "https://github.com.attacker.invalid/example/target"
        self.assertTrue(module.verify_source_scope(mission, self.repo, "example/target",
                                                   corpus, wrong_host, synthesis, self.candidate))
        obligations = copy.deepcopy(sources)
        obligations["sources"][1]["copyright"]["obligations"] = ["notice"]
        self.assertTrue(module.verify_source_scope(mission, self.repo, "example/target",
                                                   corpus, obligations, synthesis, self.candidate))
        proof.write_text('{"decision":"CHANGED"}', encoding="utf-8")
        self.assertTrue(module.verify_source_scope(mission, self.repo, "example/target",
                                                   corpus, sources, synthesis, self.candidate))


class AdoptionSuite(unittest.TestCase):
    def test_malformed_preservation_files_are_diagnostics_without_state_changes(self) -> None:
        import json
        import sys
        with tempfile.TemporaryDirectory(prefix="mc-lineage-malformed-contract-") as temp:
            root = Path(temp)
            (root / "MISSION.json").write_bytes((ROOT / "examples/reference-mission/MISSION.json").read_bytes())
            proc = subprocess.run([sys.executable, str(ROOT / "tools/mc.py"), "init",
                                   "--mission", str(root / "MISSION.json"), "--lineage-preservation"],
                                  capture_output=True, text=True)
            self.assertEqual(0, proc.returncode, proc.stderr)
            corpus_path = root / "corpus/TARGET_MUTATIONS.json"
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            state_path = root / "control/EXECUTION_STATE.json"
            before = state_path.read_bytes()
            for files in (None, {}, [{"role": [], "path": {}}]):
                with self.subTest(files=files):
                    corpus["provenance_materialization"].update(
                        mode="SAME_REPOSITORY_NO_NEW_HARVEST",
                        preservation={"repository": "example/target", "policy_base_sha": "a" * 40,
                                      "protected_files": files})
                    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
                    proc = subprocess.run([sys.executable, str(root / "runtime/tools/mc.py"),
                                           "doctor", "--root", str(root)], capture_output=True, text=True)
                    self.assertNotEqual(0, proc.returncode)
                    self.assertIn("MC0402", proc.stdout + proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)
                    self.assertEqual(before, state_path.read_bytes())

    def test_lineage_initialization_uses_the_authority_lock_across_temp_directories(self) -> None:
        import os
        import sys
        import time
        spec = importlib.util.spec_from_file_location("lineage_lock_runtime", ROOT / "tools/mc.py")
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory(prefix="mc-lineage-init-lock-") as temp:
            root = Path(temp) / "mission"
            root.mkdir()
            (root / "MISSION.json").write_bytes((ROOT / "examples/reference-mission/MISSION.json").read_bytes())
            alternate_temp = Path(temp) / "alternate-temp"
            alternate_temp.mkdir()
            attempted, acquired = Path(temp) / "attempted", Path(temp) / "acquired"
            script = r'''
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location("lineage_init", sys.argv[1])
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)
copy_assets = mc._copy_assets
def observe(*args, **kwargs):
    pathlib.Path(sys.argv[4]).write_text("acquired")
    return copy_assets(*args, **kwargs)
mc._copy_assets = observe
pathlib.Path(sys.argv[3]).write_text("attempted")
raise SystemExit(mc.main(["init", "--mission", sys.argv[2], "--lineage-preservation"]))
'''
            proc = None
            try:
                with runtime.mission_control_lock(root, stable=True):
                    proc = subprocess.Popen([sys.executable, "-c", script, str(ROOT / "tools/mc.py"),
                                             str(root / "MISSION.json"), str(attempted), str(acquired)],
                                            env=dict(os.environ, TEMP=str(alternate_temp), TMP=str(alternate_temp)),
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    deadline = time.monotonic() + 10
                    while not attempted.exists() and proc.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(attempted.exists(), "initializer never reached the lock boundary")
                    deadline = time.monotonic() + 0.3
                    while time.monotonic() < deadline:
                        self.assertFalse(acquired.exists(), "initializer bypassed the mission-local authority lock")
                        self.assertIsNone(proc.poll())
                        time.sleep(0.01)
                stdout, stderr = proc.communicate(timeout=20)
                self.assertEqual(0, proc.returncode, stdout + stderr)
                self.assertTrue(acquired.exists())
            finally:
                if proc is not None and proc.poll() is None:
                    proc.kill()
                    proc.communicate()

    def test_legacy_mission_rejects_preservation_mode_without_importing_missing_runtime(self) -> None:
        import json
        import sys
        with tempfile.TemporaryDirectory(prefix="mc-lineage-missing-capability-") as temp:
            root = Path(temp)
            (root / "MISSION.json").write_bytes((ROOT / "examples/reference-mission/MISSION.json").read_bytes())
            command = [sys.executable, str(ROOT / "tools/mc.py"), "init", "--mission", str(root / "MISSION.json")]
            proc = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, proc.returncode, proc.stderr)
            corpus_path = root / "corpus/TARGET_MUTATIONS.json"
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            corpus["provenance_materialization"]["mode"] = "SAME_REPOSITORY_NO_NEW_HARVEST"
            corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(root / "runtime/tools/mc.py"), "doctor", "--root", str(root)],
                                  capture_output=True, text=True)
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("MC0402", proc.stdout + proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_opt_in_seals_new_contract_without_changing_v16_default(self) -> None:
        import json
        import sys
        example = ROOT / "examples" / "reference-mission" / "MISSION.json"
        with tempfile.TemporaryDirectory(prefix="mc-lineage-adoption-") as temp:
            for enabled in (False, True):
                root = Path(temp) / ("enabled" if enabled else "legacy")
                root.mkdir()
                (root / "MISSION.json").write_bytes(example.read_bytes())
                argv = [sys.executable, str(ROOT / "tools" / "mc.py"),
                        "init", "--mission", str(root / "MISSION.json")]
                if enabled:
                    argv.append("--lineage-preservation")
                proc = subprocess.run(argv, capture_output=True, text=True)
                self.assertEqual(0, proc.returncode, proc.stderr)
                state = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
                lock = json.loads((root / "TEMPLATE_LOCK.json").read_text(encoding="utf-8"))
                corpus = json.loads((root / "corpus" / "TARGET_MUTATIONS.json").read_text(encoding="utf-8"))
                if enabled:
                    self.assertEqual("flyby/mission-control-execution-state/18", state["schema"])
                    self.assertEqual("BOOTSTRAPPED_LINEAGE_V1", state["lifecycle"])
                    self.assertEqual("flyby/mission-control-target-corpus/17", corpus["schema"])
                    self.assertIn("contracts/capabilities/lineage-preservation-v1.json", lock["assets"])
                else:
                    self.assertEqual("flyby/mission-control-execution-state/16", state["schema"])
                    self.assertEqual("flyby/mission-control-target-corpus/16", corpus["schema"])
                    self.assertNotIn("contracts/capabilities/lineage-preservation-v1.json", lock["assets"])
                    state_path = root / "control" / "EXECUTION_STATE.json"
                    before = state_path.read_bytes()
                    ignored = subprocess.run(
                        [sys.executable, str(root / "runtime" / "tools" / "mc.py"), "qualify",
                         "--root", str(root), "--result", "unused.json",
                         "--lineage-review", "unused-review.json", "--lineage-cell", "Q000"],
                        capture_output=True, text=True)
                    self.assertNotEqual(0, ignored.returncode)
                    self.assertIn("lineage qualification options require", ignored.stderr)
                    self.assertEqual(before, state_path.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
