#!/usr/bin/env python3
"""Outside-in preservation mission fixture using local Git only."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
import test_runtime_state_machine as lifecycle
from reservation_fixture import ReservationProtocol

write_json = lifecycle.write_json


class MissionLifecycleSuite(unittest.TestCase):
    def test_preservation_requires_review_before_acceptance_and_publication(self) -> None:
        self.preservation_lifecycle(coordination=False)

    def test_coordinated_preservation_retains_reviews_and_requires_release(self) -> None:
        self.preservation_lifecycle(coordination=True)

    def test_reserved_preservation_retains_transport_binding_through_handoff_and_closure(self) -> None:
        self.preservation_lifecycle(coordination=True, reservations=True)

    def preservation_lifecycle(self, *, coordination: bool, reservations: bool = False) -> None:
        fixture = lifecycle.RuntimeStateMachineSuite()
        original_source = fixture.source
        original_mc = fixture.mc
        original_frontier = fixture.reference_frontier_payload
        synthetic = {}

        def frontier_payload():
            value = original_frontier()
            if coordination:
                for cell in value["cells"]:
                    if isinstance(cell.get("target"), dict):
                        cell["target"]["owned_paths"] = ["reference-only/"]
            return value

        fixture.reference_frontier_payload = frontier_payload

        def digest_json(value, *, ensure_ascii=True):
            return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=ensure_ascii).encode("utf-8")).hexdigest()

        def source_wrapper(*args, **kwargs):
            if args and args[0] == "init":
                fixture.git = lambda *gitargs: subprocess.run(
                    ["git", "-C", str(fixture.target_repo), *map(str, gitargs)],
                    check=True, capture_output=True, text=True)
                fixture.git("config", "core.autocrlf", "false")
                fixture.git("remote", "set-url", "origin", "https://github.com/example/target.git")
                files = {
                    "LINEAGE": ("sources_provenance.yaml", b"lineage: preserved\n"),
                    "HARVEST": ("external_harvest_manifest.yaml", b"harvest: preserved\n"),
                    "POLICY": ("PROJECT_OPERATING_CONTRACT.md", b"preserve lineage\n"),
                    "VALIDATOR": ("scripts/ci/verify_sources_provenance.py", b"print('fixture')\n"),
                }
                for name, data in files.values():
                    path = fixture.target_repo / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                fixture.git("add", ".")
                fixture.git("commit", "-m", "add lineage fixture")
                fixture.target_base_sha = fixture.git("rev-parse", "HEAD").stdout.strip()
                manifest = json.loads((fixture.root / "MISSION.json").read_text(encoding="utf-8"))
                manifest["target_repositories"][0]["baseline_sha"] = fixture.target_base_sha
                write_json(fixture.root / "MISSION.json", manifest)
                protected = []
                for role, (name, data) in files.items():
                    line = fixture.git("ls-tree", fixture.target_base_sha, "--", name).stdout.strip()
                    mode, _, oid = line.partition("\t")[0].split(" ")
                    protected.append({"role": role, "path": name, "mode": mode, "git_blob": oid,
                                      "sha256": hashlib.sha256(data).hexdigest()})
                synthetic["contract"] = {"repository": "example/target",
                                         "policy_base_sha": fixture.target_base_sha,
                                         "protected_files": protected}
                # Copy the template to disposable storage and substitute only
                # the sealed profile's repository and policy object identities.
                # This tests the same guard with inert local fixture objects.
                template = Path(fixture.tmp.name) / "synthetic-template"
                shutil.copytree(Path(__file__).resolve().parents[1], template,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                profile_path = template / "tools" / "lineage_preservation.py"
                profile = profile_path.read_text(encoding="utf-8")
                replacements = {
                    'PROFILE_REPOSITORY = "saiflyby/flybymaestro"': 'PROFILE_REPOSITORY = "example/target"',
                    "02c210f2dfb91f49790429dd205d955aef7d8e83":
                        next(item["git_blob"] for item in protected if item["role"] == "POLICY"),
                    "79ab372d4217bf21598cbeb743ae6fc460df4d42":
                        next(item["git_blob"] for item in protected if item["role"] == "VALIDATOR"),
                }
                for old, new in replacements.items():
                    if profile.count(old) != 1:
                        raise AssertionError("fixture profile substitution is not unique")
                    profile = profile.replace(old, new)
                profile_path.write_text(profile, encoding="utf-8")
                args = (*args, "--lineage-preservation")
                if coordination:
                    args = (*args, "--cell-coordination")
                if reservations:
                    args = (*args, "--execution-reservations")
                return fixture._run(template / "tools" / "mc.py", *args, **kwargs)
            return original_source(*args, **kwargs)

        def mc_wrapper(*args, **kwargs):
            args = list(args)
            if reservations and args and args[0] == "dispatch":
                cell = str(args[args.index("--cell") + 1])
                packet = fixture.packet(cell)
                if packet.get("target"):
                    target = packet["target"]
                    binding = {
                        "mission_id": fixture.state()["mission_id"],
                        "mission_instance_id": fixture.state()["mission_instance_id"],
                        "cell_id": cell, "attempt": fixture.state()["cells"][cell]["attempt"],
                        "workspace_id": "ws-" + cell, "workspace_path": str(fixture.target_worktree(cell).resolve()),
                        "workspace_origin": "https://github.com/example/target.git",
                        "repository": target["repository"], "base_sha": target["base_sha"],
                        "worker_identity": "runtime-state-worker", "verifier_identity": "runtime-state-verifier",
                        "task_id": "task:" + cell, "seat_id": "seat-1", "worker_id": "worker-1",
                        "claim_id": "claim:" + cell, "claim_generation": 1, "worker_generation": 1,
                        "project_id": "project-1", "provider": "codex", "account_id": None, "node_id": "node-1"}
                    binding_path = fixture.root / (cell + "-execution-binding.json")
                    write_json(binding_path, binding)
                    response = original_mc("execution", "reserve", "--root", fixture.root, "--binding", binding_path,
                                           "--launch-intent-id", "lineage-intent:" + cell, **kwargs)
                    request = fixture.state()["cells"][cell]["coordination"]
                    if request["phase"] == "ADMITTED":
                        original_mc("execution", "launching", "--root", fixture.root, "--cell", cell,
                                    *protocol.selectors(protocol.current(cell)),
                                    "--executor-identity", "lineage-fixture:" + cell)
                        protocol.running(cell)
                    return response
            if coordination and args and args[0] == "settle" and "--cell" in args:
                cell = args[args.index("--cell") + 1]
                request = fixture.state()["cells"][cell].get("coordination")
                if request:
                    args.extend(["--generation", request["generation"], "--token", request["token"]])
                    if reservations:
                        selected = protocol.current(cell)
                        if not selected.get("terminal_observation_ref"):
                            protocol.terminal(cell)
                        args.extend(["--binding-digest", selected["binding_digest"]])
            if args[:2] == ["sources", "load"]:
                source = json.loads(Path(args[args.index("--file") + 1]).read_text(encoding="utf-8"))
                row = next(item for item in source["sources"] if item["id"] == "reference-method")
                row.update({"kind": "REPOSITORY",
                            "locator": "https://github.com/example/target/tree/" + fixture.target_base_sha,
                            "pin": fixture.target_base_sha})
                row["copyright"].update({"usage_mode": "OWNER_AUTHORIZED_REUSE", "code_copy_allowed": True})
                synthetic["sources"] = source
                path = fixture.root / "synthetic-sources.json"
                write_json(path, source)
                args[args.index("--file") + 1] = path
            elif args[:2] == ["provenance", "load"]:
                value = json.loads(Path(args[args.index("--file") + 1]).read_text(encoding="utf-8"))
                assessment = value["source_assessments"][0]
                assessment["mechanism_contributions"][0]["rights_mode"] = "OWNER_AUTHORIZED_REUSE"
                review = assessment["independent_review"]
                source_row = next(item for item in synthetic["sources"]["sources"] if item["id"] == "reference-method")
                review["source_record_sha256"] = digest_json(source_row, ensure_ascii=False)
                review["contributions_sha256"] = digest_json(assessment["mechanism_contributions"])
                payload = {key: assessment.get(key, []) for key in (
                    "source_id", "inspected_locators", "coverage_items", "open_questions",
                    "deep_review", "mechanism_contributions")}
                review["coverage_sha256"] = digest_json(payload)
                review_file = fixture.root / review["review_ref"]
                receipt = json.loads(review_file.read_text(encoding="utf-8"))
                for key in ("source_record_sha256", "contributions_sha256", "coverage_sha256"):
                    receipt[key] = review[key]
                write_json(review_file, receipt)
                review["review_sha256"] = hashlib.sha256(review_file.read_bytes()).hexdigest()
                path = fixture.root / "synthetic-provenance.json"
                write_json(path, value)
                args[args.index("--file") + 1] = path
            elif args[:2] == ["corpus", "load"]:
                value = json.loads(Path(args[args.index("--file") + 1]).read_text(encoding="utf-8"))
                value["schema"] = "flyby/mission-control-target-corpus/17"
                value["provenance_materialization"] = {
                    "mode": "SAME_REPOSITORY_NO_NEW_HARVEST",
                    "target_refs": ["sources_provenance.yaml"], "coverage_requirement_id": "REF-001",
                    "validation_schema_ref": None, "authority": "LINEAGE_ONLY",
                    "acceptance": ["Preserve exact lineage and target policy."],
                    "preservation": synthetic["contract"],
                }
                path = fixture.root / "synthetic-corpus.json"
                write_json(path, value)
                args[args.index("--file") + 1] = path
            response = original_mc(*args, **kwargs)
            if coordination and args and args[0] == "dispatch" and response.returncode == 0:
                cell = str(args[args.index("--cell") + 1])
                request = fixture.state()["cells"][cell].get("coordination")
                if request and request["phase"] == "ADMITTED":
                    original_mc("coordination", "launching", "--root", fixture.root, "--cell", cell,
                                "--generation", request["generation"], "--token", request["token"],
                                "--executor-identity", "lineage-fixture:" + cell)
            return response

        def release(cell):
            if reservations:
                protocol.action("release", cell)
                return
            request = fixture.state()["cells"][cell]["coordination"]
            evidence = fixture.root / "evidence" / (cell + "-stopped.json")
            write_json(evidence, {"fixture": "test owns this writer; no external provider or descendants remain"})
            observation = {
                "schema": "flyby/mission-control-fence-observation/1", "kind": "INDEPENDENT_OPERATOR_CONFIRMATION",
                "cell": cell, "attempt": fixture.state()["cells"][cell]["attempt"],
                "generation": request["generation"], "token": request["token"],
                "executor_identity": request["executor_identity"], "observer_identity": "runtime-state-verifier",
                "termination_confirmed": True, "descendants_fenced": True,
                "rationale": "Controlled local fixture writer has finished and its execution domain is owned by the test.",
                "evidence": [{"ref": evidence.relative_to(fixture.root).as_posix(),
                              "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            }
            path = fixture.root / (cell + "-fence.json")
            write_json(path, observation)
            fence = ["--generation", request["generation"], "--token", request["token"]]
            fixture.mc("coordination", "confirm-stop", "--root", fixture.root, "--cell", cell, *fence,
                       "--observation", path)
            fixture.mc("coordination", "release", "--root", fixture.root, "--cell", cell, *fence)

        fixture.source = source_wrapper
        fixture.mc = mc_wrapper
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        protocol = ReservationProtocol(fixture)
        original_receipt = fixture.receipt
        def receipt_wrapper(cell, **kwargs):
            path = original_receipt(cell, **kwargs)
            if reservations and fixture.state()["cells"][cell].get("execution_reservation"):
                protocol.receipt_session(path, cell)
            return path
        fixture.receipt = receipt_wrapper
        fixture.accept_baseline()
        fixture.compile_reference()
        fixture.mc("dispatch", "--root", fixture.root, "--cell", "M000")
        worktree = fixture.target_worktree("M000")
        source_publication_base = fixture.target_base_sha
        if coordination:
            inherited = fixture.target_repo / "reference-only/main-owned.py"
            inherited.parent.mkdir(parents=True)
            inherited.write_text("accepted main owned change\n", encoding="utf-8")
            fixture.git("add", "reference-only/main-owned.py")
            fixture.git("commit", "-m", "main advances before independent settlement")
            source_publication_base = fixture.git("rev-parse", "HEAD").stdout.strip()
            subprocess.run(["git", "-C", str(worktree), "merge", "--no-edit", source_publication_base],
                           check=True, capture_output=True, text=True)
        changed = worktree / "reference-only" / "implementation.py"
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text("owned change\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(worktree), "add", "reference-only/implementation.py"], check=True)
        subprocess.run(["git", "-C", str(worktree), "commit", "-m", "fixture candidate"],
                       check=True, capture_output=True, text=True)
        candidate = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"],
                                   check=True, capture_output=True, text=True).stdout.strip()
        result = fixture.result("M000")
        value = json.loads(result.read_text(encoding="utf-8"))
        value["target_outcomes"][0]["head_sha"] = candidate
        write_json(result, value)
        receipt = fixture.receipt("M000")
        adjudication = fixture.adjudication("M000", result, receipt, attempt=1)
        evidence = fixture.root / "evidence" / "lineage-candidate-review.txt"
        evidence.write_text("independent candidate and source review", encoding="utf-8")
        state = fixture.state()
        review = {
            "schema": "flyby/mission-control-lineage-preservation-review/1",
            "mission_id": state["mission_id"], "mission_instance_id": state["mission_instance_id"],
            "cell_id": "M000", "attempt": 1, "repository": "example/target",
            "policy_base_sha": fixture.target_base_sha, "candidate_sha": candidate,
            "corpus_sha256": hashlib.sha256((fixture.root / "corpus" / "TARGET_MUTATIONS.json").read_bytes()).hexdigest(),
            "sources_sha256": hashlib.sha256((fixture.root / "corpus" / "SOURCES.json").read_bytes()).hexdigest(),
            "synthesis_sha256": hashlib.sha256((fixture.root / "corpus" / "PROVENANCE_SYNTHESIS.json").read_bytes()).hexdigest(),
            "author_identity": "runtime-state-worker", "reviewer_identity": "runtime-state-verifier",
            "decision": "VERIFIED_SAME_REPOSITORY_NO_NEW_HARVEST",
            "no_new_external_contribution": True, "no_new_obligations": True,
            "reviewed_source_ids": ["owner-intent", "reference-method"],
            "evidence": [{"ref": "evidence/lineage-candidate-review.txt",
                          "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
        }
        review_path = fixture.root / "candidate-lineage-review.json"
        if coordination:
            review["publication_base_sha"] = source_publication_base
        write_json(review_path, review)
        settle = ("settle", "--root", fixture.root, "--cell", "M000", "--attempt", "1",
                  "--result", result, "--context-receipt", receipt, "--adjudication", adjudication)
        fixture.mc(*settle, ok=False)
        self.assertEqual("DISPATCHED", fixture.state()["cells"]["M000"]["state"])
        stale = copy.deepcopy(review)
        stale["candidate_sha"] = fixture.target_base_sha
        write_json(review_path, stale)
        fixture.mc(*settle, "--lineage-review", review_path, ok=False)
        write_json(review_path, review)
        bridge_path = Path(__file__).resolve().parents[1] / "tools" / "wt_mission.py"
        fence = []
        if coordination:
            request = fixture.state()["cells"]["M000"]["coordination"]
            fence = ["--generation", str(request["generation"]), "--token", request["token"]]
            if reservations:
                fence.extend(["--binding-digest", protocol.current("M000")["binding_digest"]])
        bridge_settle = subprocess.run(
            [sys.executable, str(bridge_path), *map(str, settle), "--lineage-review", str(review_path), *fence],
            capture_output=True, text=True)
        self.assertEqual(0, bridge_settle.returncode, bridge_settle.stderr)
        self.assertEqual("ACCEPTED", fixture.state()["cells"]["M000"]["state"])
        if reservations:
            selected = fixture.state()["cells"]["M000"]["execution_reservation"]
            lookup = json.loads(fixture.mc("execution", "inspect", "--root", fixture.root, "--cell", "M000",
                                "--reservation-id", selected["token"], "--fence", selected["generation"],
                                "--binding-digest", selected["binding_digest"]).stdout)
            self.assertEqual(fixture.state()["cells"]["M000"]["lineage_review_sha256"],
                             lookup["lineage_review_sha256"])
            self.assertEqual({"result_sha256", "context_receipt_sha256", "adjudication_sha256"}, set(lookup["evidence_hashes"]))
            self.assertEqual(digest_json(lookup["evidence_hashes"], ensure_ascii=False), lookup["evidence_digest"])
        replay = subprocess.run(
            [sys.executable, str(bridge_path), *map(str, settle), "--lineage-review", str(review_path),
             *fence, "--reconcile"], capture_output=True, text=True)
        self.assertEqual(0, replay.returncode, replay.stderr)
        self.assertTrue(json.loads(replay.stdout)["reconciled"])
        altered = {**review, "candidate_sha": fixture.target_base_sha}
        write_json(review_path, altered)
        replay = subprocess.run(
            [sys.executable, str(bridge_path), *map(str, settle), "--lineage-review", str(review_path),
             *fence, "--reconcile"], capture_output=True, text=True)
        self.assertNotEqual(0, replay.returncode)
        write_json(review_path, review)
        if coordination:
            if not reservations:
                denied = fixture.mc("coordination", "verify", "--root", fixture.root, "--cell", "M000",
                                    "--candidate", candidate, "--publication-base", fixture.target_base_sha, ok=False)
                self.assertIn("termination", denied.stderr.lower())
            release("M000")
        fixture.mc("doctor", "--root", fixture.root)
        fixture.mc("lineage", "verify", "--root", fixture.root, "--cell", "M000",
                   "--candidate", candidate, "--publication-base", source_publication_base)

        import argparse
        import importlib.util
        from unittest import mock
        bridge_spec = importlib.util.spec_from_file_location("lineage_bridge_fixture", bridge_path)
        bridge = importlib.util.module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge)
        args = argparse.Namespace(root=str(fixture.root), cell="M000", base="main",
                                  gh="fake-gh", title="fixture", body="fixture")
        real_run = bridge.run
        forge_calls = []
        def routed_run(argv, **kwargs):
            if argv[0] == "fake-gh":
                forge_calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "[]", "")
            return real_run(argv, **kwargs)
        def remote_for(base):
            return lambda repo, ref: base if ref == "refs/heads/main" else None

        args.base = "other-branch"
        with mock.patch.object(bridge, "run", side_effect=routed_run), \
             mock.patch.object(bridge, "remote_head", return_value=fixture.target_base_sha), \
             mock.patch.object(bridge, "push_to_verified_destination") as push:
            with self.assertRaisesRegex(bridge.BridgeError, "accepted main"):
                bridge.publish(args)
            push.assert_not_called()
            self.assertEqual([], forge_calls)
        args.base = "main"

        with mock.patch.object(bridge, "run", side_effect=routed_run), \
             mock.patch.object(bridge, "remote_head", side_effect=remote_for(candidate)), \
             mock.patch.object(bridge, "push_to_verified_destination") as push:
            with self.assertRaises(bridge.BridgeError):
                bridge.publish(args)
            push.assert_not_called()
            self.assertEqual([], forge_calls)

        with mock.patch.object(bridge, "run", side_effect=routed_run), \
             mock.patch.object(bridge, "remote_head", side_effect=remote_for(source_publication_base)), \
             mock.patch.object(bridge, "push_to_verified_destination", side_effect=RuntimeError("fake upload boundary")) as push:
            with self.assertRaisesRegex(RuntimeError, "fake upload boundary"):
                bridge.publish(args)
            push.assert_called_once()

        fixture.mc("dispatch", "--root", fixture.root, "--cell", "M001")
        result2 = fixture.result("M001")
        receipt2 = fixture.receipt("M001")
        adjudication2 = fixture.adjudication("M001", result2, receipt2, attempt=1)
        review2 = {**review, "cell_id": "M001", "candidate_sha": fixture.target_base_sha}
        review2.pop("publication_base_sha", None)
        review2_path = fixture.root / "candidate-lineage-review-m001.json"
        write_json(review2_path, review2)
        fixture.mc("settle", "--root", fixture.root, "--cell", "M001", "--attempt", "1",
                   "--result", result2, "--context-receipt", receipt2, "--adjudication", adjudication2,
                   "--lineage-review", review2_path)
        if coordination:
            release("M001")
            # A changed-main successor retains the predecessor's complete
            # provenance, then requires a fresh review of the admitted base.
            (fixture.target_repo / "main-context.txt").write_text("accepted main advanced\n", encoding="utf-8")
            fixture.git("add", "main-context.txt")
            fixture.git("commit", "-m", "advance accepted main")
            observed = fixture.git("rev-parse", "HEAD").stdout.strip()
            transfer = argparse.Namespace(root=str(fixture.root), cell="M000", successor="M002",
                                          frontier="F200", base_sha=observed)
            with mock.patch.object(bridge, "remote_head", return_value=observed), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                bridge.handoff(transfer)
            handoff = json.loads(output.getvalue())
            parent = fixture.state()["cells"]["M000"]
            self.assertEqual({"ref": parent["lineage_review_ref"], "sha256": parent["lineage_review_sha256"]},
                             handoff["accepted_evidence"]["lineage_review"])
            if reservations:
                self.assertEqual(parent["execution_reservation"]["binding_digest"],
                                 handoff["execution_reservation"]["binding_digest"])
            worktree = fixture.target_worktree("M002")
            fixture.mc("workspace", "register", "--root", fixture.root, "--cell", "M002",
                       "--workspace-id", "ws-M002", "--branch", "mcv6/m002", "--path", worktree)
            fixture.mc("dispatch", "--root", fixture.root, "--cell", "M002", "--workspace-id", "ws-M002")
            for head in (candidate, observed):
                subprocess.run(["git", "-C", str(worktree), "merge", "--no-edit", head],
                               check=True, capture_output=True, text=True)
            candidate = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"],
                                       check=True, capture_output=True, text=True).stdout.strip()
            result3 = fixture.result("M002", extra={"target_outcomes": [{
                "repository": "example/target", "baseline_sha": fixture.target_base_sha, "head_sha": candidate}]})
            receipt3 = fixture.receipt("M002")
            adjudication3 = fixture.adjudication("M002", result3, receipt3, attempt=1)
            review = {**review, "cell_id": "M002", "candidate_sha": candidate}
            write_json(review_path, review)
            successor_settle = ("settle", "--root", fixture.root, "--cell", "M002", "--attempt", "1",
                                "--result", result3, "--context-receipt", receipt3, "--adjudication", adjudication3,
                                "--lineage-review", review_path)
            stale = fixture.mc(*successor_settle, ok=False)
            self.assertIn("admitted scope base", stale.stderr)
            review["publication_base_sha"] = observed
            write_json(review_path, review)
            fixture.mc(*successor_settle)
            release("M002")
            fixture.mc("lineage", "verify", "--root", fixture.root, "--cell", "M002",
                       "--candidate", candidate, "--publication-base", observed)
            fixture.mc("lineage", "verify", "--root", fixture.root, "--cell", "M002",
                       "--candidate", candidate, "--publication-base", fixture.target_base_sha, ok=False)
            delivered = bridge.check_dependency_delivery(fixture.root, "M002", worktree, "example/target",
                                                         candidate, observed, "main", "unused-gh", {})
            self.assertEqual("SAME_SCOPE_HANDOFF", delivered[0]["state"])
            self.assertIn("lineage_review", delivered[0]["evidence"])
            self.assertEqual(parent["coordination"]["generation"], delivered[0]["coordination"]["generation"])
            if reservations:
                self.assertEqual(parent["execution_reservation"]["binding_digest"],
                                 delivered[0]["execution_reservation"]["binding_digest"])
            state_path = fixture.root / "control/EXECUTION_STATE.json"
            state_bytes = state_path.read_bytes()
            missing_custody = json.loads(state_bytes)
            del missing_custody["cells"]["M000"]["coordination"]
            try:
                write_json(state_path, missing_custody)
                invalid = fixture.mc("doctor", "--root", fixture.root, ok=False)
                self.assertIn("MC0410", invalid.stdout + invalid.stderr)
                with self.assertRaisesRegex(bridge.BridgeError, "missing required coordinated writer custody"):
                    bridge.check_dependency_delivery(fixture.root, "M002", worktree, "example/target",
                                                     candidate, observed, "main", "unused-gh", {})
            finally:
                state_path.write_bytes(state_bytes)
            parent_review = fixture.root / parent["lineage_review_ref"]
            parent_bytes = parent_review.read_bytes()
            try:
                parent_review.write_bytes(b"{}")
                with self.assertRaisesRegex(bridge.BridgeError, "lineage_review"):
                    bridge.check_dependency_delivery(fixture.root, "M002", worktree, "example/target",
                                                     candidate, observed, "main", "unused-gh", {})
            finally:
                parent_review.write_bytes(parent_bytes)
        fixture.mc("barrier", "accept", "--root", fixture.root, "--cell", "G100")
        fixture.mc("integrate", "--root", fixture.root)
        fixture.mc("dispatch", "--root", fixture.root, "--cell", "I000")
        integration_result = fixture.result("I000", extra={"target_outcomes": [{
            "repository": "example/target", "baseline_sha": fixture.target_base_sha, "head_sha": candidate,
        }]})
        integration_receipt = fixture.receipt("I000")
        fixture.raw_settle("I000", integration_result, integration_receipt)
        fixture.mc("qualify", "--root", fixture.root)
        fixture.mc("dispatch", "--root", fixture.root, "--cell", "Q000")
        q_result = fixture.result("Q000")
        q_receipt = fixture.receipt("Q000")
        q_adjudication = fixture.adjudication("Q000", q_result, q_receipt, attempt=1)
        q_settle = ("settle", "--root", fixture.root, "--cell", "Q000", "--attempt", "1",
                    "--result", q_result, "--context-receipt", q_receipt, "--adjudication", q_adjudication)
        fixture.mc(*q_settle, "--lineage-review", review_path, ok=False)
        fixture.mc(*q_settle)
        qualification = {
            "schema": "flyby/mission-control-qualification/16", "outcome": "ACCEPTED",
            "summary": "Synthetic exact-head lineage qualification.",
            "evidence": [{"kind": "fixture", "value": "local"}],
            "target_outcomes": [{"repository": "example/target", "baseline_sha": fixture.target_base_sha,
                                 "accepted_head_sha": candidate}],
            "requirement_accounting": {"accepted": ["REF-001"], "waived": []},
            "verification_accounting": {"run": list(fixture.packet("Q000")["acceptance"]),
                                        "waived": [], "not_run": []},
            "unresolved_defects": [], "explicit_limitations": [],
        }
        qualification_path = fixture.root / "synthetic-qualification.json"
        write_json(qualification_path, qualification)
        fixture.mc("qualify", "--root", fixture.root, "--result", qualification_path, ok=False)
        accepted_workspace = "ws-M002" if coordination else "ws-M000"
        final_review = {**review, "cell_id": "Q000", "workspace_id": accepted_workspace}
        final_review_path = fixture.root / "final-lineage-review.json"
        write_json(final_review_path, final_review)
        fixture.mc("qualify", "--root", fixture.root, "--result", qualification_path,
                   "--lineage-review", final_review_path, "--lineage-cell", "Q000")
        self.assertEqual("ACCEPTED", fixture.state()["lifecycle"])
        reconciliation = fixture.reference_workspace_reconciliation()
        target_reconciliation = reconciliation["target_repositories"][0]
        target_reconciliation["accepted_head_sha"] = candidate
        if coordination:
            successor_branch = copy.deepcopy(target_reconciliation["branches"][0])
            successor_branch.update(workspace_id="ws-M002", branch="mcv6/m002",
                                    worktree_path=str(fixture.target_worktree("M002").resolve()))
            target_reconciliation["branches"].append(successor_branch)
        for branch in target_reconciliation["branches"]:
            branch["remote_url"] = "https://github.com/example/target.git"
            branch["head_sha"] = subprocess.run(
                ["git", "-C", branch["worktree_path"], "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True).stdout.strip()
            if branch["workspace_id"] == accepted_workspace:
                branch["head_sha"] = candidate
                branch["disposition"] = "ACCEPTED_HEAD"
            else:
                branch["disposition"] = "SUPERSEDED_PRESERVED"
        reconciliation_path = fixture.root / "synthetic-reconciliation.json"
        write_json(reconciliation_path, reconciliation)
        fixture.mc("workspace", "load", "--root", fixture.root, "--file", reconciliation_path)
        fixture.mc("close", "--root", fixture.root)
        self.assertEqual("CLOSED", fixture.state()["lifecycle"])

        evidence.write_text("tampered", encoding="utf-8")
        forge_calls.clear()
        with mock.patch.object(bridge, "run", side_effect=routed_run), \
             mock.patch.object(bridge, "remote_head", side_effect=remote_for(fixture.target_base_sha)), \
             mock.patch.object(bridge, "push_to_verified_destination") as push:
            with self.assertRaises(bridge.BridgeError):
                bridge.publish(args)
            push.assert_not_called()
            self.assertEqual([], forge_calls)
        fixture.mc("doctor", "--root", fixture.root, ok=False)
        fixture.mc("lineage", "verify", "--root", fixture.root, "--cell", "M000",
                   "--candidate", candidate, "--publication-base", fixture.target_base_sha, ok=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
