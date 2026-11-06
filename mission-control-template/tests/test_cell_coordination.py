"""Outside-in proofs of durable admission, scope gates and explicit safe release."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_runtime_state_machine as lifecycle

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coordination_under_test", ROOT / "tools/coordination_v1.py")
coord = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coord)


class PathOwnershipTests(unittest.TestCase):
    def test_opt_in_does_not_mutate_an_existing_frozen_legacy_mission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lifecycle.write_json(root / "MISSION.json", json.loads((lifecycle.EXAMPLE / "MISSION.json").read_text(encoding="utf-8")))
            command = [sys.executable, str(lifecycle.SOURCE_MC), "init", "--mission", str(root / "MISSION.json")]
            original = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, original.returncode, original.stderr)
            before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            rejected = subprocess.run([*command, "--cell-coordination"], capture_output=True, text=True)
            self.assertNotEqual(0, rejected.returncode)
            after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_file_directory_near_prefix_and_case_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp).resolve()
            (repo / "src").mkdir()
            paths = coord.scopes(repo, ["src/a", "src/ab", "src/lib/"], False)
            by_path = {item["path"]: item for item in paths}
            self.assertFalse(coord.overlaps(by_path["src/a"], by_path["src/ab"]))
            self.assertTrue(coord.overlaps(by_path["src/lib"], coord.scopes(repo, ["src/lib/a.py"], False)[0]))
            self.assertTrue(coord.overlaps(by_path["src/a"], coord.scopes(repo, ["src/a/child"], False)[0]))
            self.assertFalse(coord.contains(by_path["src/a"], "src/a/child"))
            self.assertTrue(coord.overlaps(by_path["src/a"], by_path["src/a"]))
            self.assertEqual(coord.scopes(repo, [r"src\a"], False), coord.scopes(repo, ["src/a"], False))
            self.assertFalse(coord.overlaps(coord.scopes(repo, ["src/A"], False)[0], by_path["src/a"]))
            self.assertTrue(coord.overlaps(coord.scopes(repo, ["src/A"], True)[0], by_path["src/a"]))
            self.assertTrue(coord.overlaps(coord.scopes(repo, ["src/"], False)[0], by_path["src/ab"]))
            left = {"conflict_class": "one", "claims": [], "repository_key": "parent/repo",
                    "workspace": {"workspace_path": str(repo), "git_common_dir": str(repo / ".git")},
                    "scopes": coord.scopes(repo, ["vendor/"], False)}
            nested = repo / "vendor"
            nested.mkdir()
            right = {"conflict_class": "two", "claims": [], "repository_key": "child/repo",
                     "workspace": {"workspace_path": str(nested), "git_common_dir": str(nested / ".git")},
                     "scopes": coord.scopes(nested, ["src.py"], False)}
            self.assertIn("physical_paths", coord.conflict(left, right))

    def test_malformed_metadata_absolute_and_pattern_claims_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for path in ("", ".", "./src", "../src", "a/../b", "/src", "C:/src", r"\\server\src",
                         "a//b", ".git/config", ".GIT/objects", ".git~1/config", "src/*", "src/[ab]", "src/?", "src/{a,b}", "a\0b"):
                with self.subTest(path=repr(path)), self.assertRaises(ValueError):
                    coord.scopes(Path(temp).resolve(), [path], False)

    def test_link_aliases_collide_and_escapes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "src").mkdir()
            junctions = []
            try:
                try:
                    (repo / "alias").symlink_to(repo / "src", target_is_directory=True)
                    (repo / "escape").symlink_to(root, target_is_directory=True)
                except OSError as exc:
                    if os.name != "nt":
                        self.skipTest(f"filesystem cannot create the symlink fixture: {exc}")
                    # NTFS junctions exercise the same physical-path boundary
                    # without changing Windows's symlink privilege setting.
                    for name, target in (("alias", repo / "src"), ("escape", root)):
                        link = repo / name
                        if link.is_symlink():
                            link.unlink()
                        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                                capture_output=True, text=True)
                        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                        junctions.append(link)
                self.assertTrue(coord.overlaps(coord.scopes(repo.resolve(), ["alias/a"], False)[0],
                                               coord.scopes(repo.resolve(), ["src/a"], False)[0]))
                with self.assertRaises(ValueError):
                    coord.scopes(repo.resolve(), ["escape/new.py"], False)
            finally:
                # Remove only the fixture junctions before temporary-directory
                # cleanup; the directory they reference is never removed here.
                for link in reversed(junctions):
                    link.rmdir()


class CoordinationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = lifecycle.RuntimeStateMachineSuite()
        original_source = self.fixture.source
        def source(*args, **kwargs):
            if args and args[0] == "init":
                args = (*args, "--cell-coordination")
            return original_source(*args, **kwargs)
        self.fixture.source = source
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        original_mc = self.fixture.mc
        def mc(*args, **kwargs):
            rendered = list(args)
            if rendered and rendered[0] == "settle" and "--cell" in rendered and "--generation" not in rendered:
                cell = str(rendered[rendered.index("--cell") + 1])
                request = self.fixture.state()["cells"].get(cell, {}).get("coordination")
                if request:
                    rendered.extend(["--generation", request["generation"], "--token", request["token"]])
            return original_mc(*rendered, **kwargs)
        self.fixture.mc = mc
        self.fixture.accept_baseline()
        self.root = self.fixture.root
        self.runtime = self.fixture.runtime

    def compile(self, *, paths=None, claims=None, dependencies=None, extra=True, controls=()):
        frontier = self.fixture.reference_frontier_payload()
        cells = [cell for cell in frontier["cells"] if cell.get("kind") == "MUTATION"]
        if extra:
            third = copy.deepcopy(cells[0])
            third["cell_id"] = "M002"
            frontier["cells"].insert(2, third)
            cells.append(third)
            next(cell for cell in frontier["cells"] if cell["cell_id"] == "G100")["dependencies"].append("M002")
        paths = paths or {"M000": ["src/a/"], "M001": ["src/ab/"], "M002": ["src/a/child.py"]}
        for cell in cells:
            cid = cell["cell_id"]
            cell["target"]["owned_paths"] = paths[cid]
            cell["conflict_class"] = "writer:" + cid
            cell["resource_claims"] = (claims or {}).get(cid, [])
            cell["dependencies"] = (dependencies or {}).get(cid, ["G000"])
        frontier["cells"].extend(copy.deepcopy(controls))
        path = self.root / "coordination-frontier.json"
        lifecycle.write_json(path, frontier)
        self.fixture.mc("compile", "--root", self.root, "--frontier", path)
        for cell in cells:
            cid = cell["cell_id"]
            self.fixture.mc("workspace", "register", "--root", self.root, "--cell", cid,
                            "--workspace-id", "ws-" + cid, "--branch", "mcv6/" + cid.lower(),
                            "--path", self.fixture.target_worktree(cid))

    def dispatch(self, cell):
        return json.loads(self.fixture.mc("dispatch", "--root", self.root, "--cell", cell,
                                         "--workspace-id", "ws-" + cell).stdout)

    def request(self, cell):
        return self.fixture.state()["cells"][cell]["coordination"]

    def transition(self, action, cell, *more, ok=True, request=None):
        req = request or self.request(cell)
        return self.fixture.mc("coordination", action, "--root", self.root, "--cell", cell,
                               "--generation", req["generation"], "--token", req["token"], *more, ok=ok)

    def launch(self, cell):
        return self.transition("launching", cell, "--executor-identity", "fixture-session:" + cell)

    def fence(self, cell):
        req = self.request(cell)
        evidence = self.root / "evidence" / f"operator-{cell}.json"
        lifecycle.write_json(evidence, {"fixture": "independent observer established this test's executor tree is stopped",
                                        "executor_identity": req["executor_identity"]})
        observation = {"schema": "flyby/mission-control-fence-observation/1", "kind": "INDEPENDENT_OPERATOR_CONFIRMATION",
                       "cell": cell, "attempt": self.fixture.state()["cells"][cell]["attempt"],
                       "generation": req["generation"], "token": req["token"],
                       "executor_identity": req["executor_identity"], "observer_identity": "runtime-state-verifier",
                       "termination_confirmed": True, "descendants_fenced": True,
                       "rationale": "Controlled test worker has stopped; test owns its execution tree.",
                       "evidence": [{"ref": evidence.relative_to(self.root).as_posix(), "sha256": lifecycle.sha256(evidence)}]}
        path = self.root / f"fence-{cell}.json"
        lifecycle.write_json(path, observation)
        self.transition("confirm-stop", cell, "--observation", path)
        return path

    def recover(self):
        return json.loads(self.fixture.mc("coordination", "recover", "--root", self.root).stdout)

    def git(self, cell, *args):
        repo = self.fixture.target_worktree(cell)
        return subprocess.check_output(["git", "-C", str(repo), *args])

    def commit(self, cell, paths):
        self.git(cell, "add", "--", *paths)
        self.git(cell, "-c", "user.name=Coordination Fixture", "-c", "user.email=coordination@example.invalid",
                 "commit", "-qm", "candidate")
        return self.git(cell, "rev-parse", "HEAD").decode().strip()

    def settle(self, cell, outcome="ACCEPTED", *, candidate=None, ok=True):
        result = self.fixture.result(cell, outcome)
        if candidate is not None:
            value = json.loads(result.read_text(encoding="utf-8"))
            value["target_outcomes"][0]["head_sha"] = candidate
            lifecycle.write_json(result, value)
        receipt = self.fixture.receipt(cell)
        return self.fixture.raw_settle(cell, result, receipt, ok=ok)

    def test_three_cells_parallel_queued_restart_result_is_not_release(self):
        self.compile()
        first, second, third = self.dispatch("M000"), self.dispatch("M001"), self.dispatch("M002")
        self.assertEqual(["ADMITTED", "ADMITTED", "QUEUED"], [first["phase"], second["phase"], third["phase"]])
        self.assertTrue(any("owned_paths" in blocker for blocker in third["blockers"]))
        self.assertEqual(third["token"], self.dispatch("M002")["token"])
        self.launch("M000")
        self.launch("M001")
        self.settle("M000")
        self.assertEqual("QUEUED", self.recover()["cells"][2]["phase"])
        self.transition("release", "M000", ok=False)
        self.transition("stop", "M000")
        self.transition("release", "M000", ok=False)
        # Every mc invocation is a new process; the queue and launch intent
        # survive controller replacement without relaunching any provider.
        replay = json.loads(self.launch("M000").stdout)
        self.assertFalse(replay["launch_authorized"])
        self.fence("M000")
        self.transition("release", "M000")
        recovered = {item["cell"]: item for item in self.recover()["cells"]}
        self.assertEqual("ADMITTED", recovered["M002"]["phase"])
        self.assertEqual(third["token"], recovered["M002"]["token"])
        self.assertEqual("LAUNCH_UNCERTAIN", recovered["M001"]["phase"])
        self.fixture.mc("doctor", "--root", self.root)

    def test_shared_contract_and_dependency_require_acceptance_and_safe_release(self):
        self.compile(paths={"M000": ["left/"], "M001": ["right/"], "M002": ["other/"]},
                     claims={"M000": ["api:shared"], "M001": ["api:shared"]}, dependencies={"M002": ["M000"]})
        self.dispatch("M000")
        peer, dependent = self.dispatch("M001"), self.dispatch("M002")
        self.assertTrue(any("resource:api:shared" in value for value in peer["blockers"]))
        self.assertTrue(any("dependency:M000" in value for value in dependent["blockers"]))
        self.launch("M000")
        self.settle("M000")
        self.recover()
        self.assertEqual("QUEUED", self.request("M002")["phase"])
        self.fence("M000")
        self.transition("release", "M000")
        self.recover()
        self.assertEqual(["ADMITTED", "ADMITTED"], [self.request(cell)["phase"] for cell in ("M001", "M002")])

    @staticmethod
    def audit(cell, *, dependencies=("G000",), conflict_class=None, claims=()):
        return {"cell_id": cell, "kind": "AUDIT", "dependencies": list(dependencies),
                "objective": "Audit mixed-cell admission", "acceptance": ["Independent audit evidence recorded"],
                "status": "PENDING", "conflict_class": conflict_class or "audit:" + cell,
                "resource_claims": list(claims), "consumer": "MUTATION_FRONTIER",
                "result_schema": "contracts/schemas/RESULT_SCHEMA.json"}

    def test_control_dispatch_respects_accepted_targets_until_safe_release(self):
        controls = [self.audit("A100", claims=["api:shared"]),
                    self.audit("A101", dependencies=["M000"]),
                    self.audit("A102", conflict_class="writer:M000"), self.audit("A103")]
        self.compile(claims={"M000": ["api:shared"]}, controls=controls)
        self.dispatch("M000")
        self.launch("M000")
        self.settle("M000")
        self.assertEqual("ACCEPTED", self.fixture.state()["cells"]["M000"]["state"])
        self.fixture.mc("dispatch", "--root", self.root, "--cell", "A103")

        def denied():
            for cell, reason in (("A100", "resource:api:shared"), ("A101", "dependency_release:M000"),
                                 ("A102", "conflict_class")):
                with self.subTest(phase=self.request("M000")["phase"], control=cell):
                    result = self.fixture.mc("dispatch", "--root", self.root, "--cell", cell, ok=False)
                    self.assertIn(reason, result.stderr)
                    self.assertEqual("COMPILED", self.fixture.state()["cells"][cell]["state"])
        denied()
        for action in ("running", "unknown", "stop"):
            self.transition(action, "M000")
            denied()
        self.fence("M000")
        self.assertEqual("STOP_CONFIRMED", self.request("M000")["phase"])
        denied()
        self.transition("release", "M000")
        for cell in ("A100", "A101", "A102"):
            self.fixture.mc("dispatch", "--root", self.root, "--cell", cell)
        self.fixture.mc("doctor", "--root", self.root)

    def test_target_queue_respects_dispatched_control_claim_and_doctor_rejects_bypass(self):
        self.compile(claims={"M000": ["api:shared"]},
                     controls=[self.audit("A100", claims=["api:shared"]), self.audit("A101", dependencies=["M001"])])
        self.fixture.mc("dispatch", "--root", self.root, "--cell", "A100")
        queued = self.dispatch("M000")
        self.assertEqual("QUEUED", queued["phase"])
        self.assertIn("active_control_claim:A100", queued["blockers"])
        self.dispatch("M001")
        self.launch("M001")
        self.settle("M001")
        self.fixture.settle("A100")
        self.recover()
        self.assertEqual("ADMITTED", self.request("M000")["phase"])
        # Model an invalid pre-fix/control-state restoration; doctor must not
        # certify a dependency that bypassed a still-owned accepted target.
        state = self.fixture.state()
        state["cells"]["A101"].update({"state": "DISPATCHED", "worker_identity": "runtime-state-worker",
                                       "verifier_identity": "runtime-state-verifier"})
        state["frontier"]["dispatched"] = sorted(set(state["frontier"]["dispatched"]) | {"A101"})
        lifecycle.write_json(self.root / "control/EXECUTION_STATE.json", state)
        invalid = self.fixture.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("control dispatch bypasses retained target ownership", invalid.stdout + invalid.stderr)

    def test_out_of_scope_committed_dirty_rename_deletion_and_untracked_are_denied(self):
        self.compile(paths={"M000": ["owned/"], "M001": ["elsewhere/"], "M002": ["other/"]})
        self.dispatch("M000")
        self.launch("M000")
        repo = self.fixture.target_worktree("M000")
        (repo / "owned").mkdir()
        (repo / "owned/valid.py").write_text("valid\n", encoding="utf-8")
        candidate = self.commit("M000", ["owned/valid.py"])
        (repo / "outside.py").write_text("untracked\n", encoding="utf-8")
        denial = self.settle("M000", candidate=candidate, ok=False)
        self.assertIn("outside.py", denial.stderr)
        self.git("M000", "add", "--", "outside.py")
        self.settle("M000", candidate=candidate, ok=False)
        candidate = self.commit("M000", ["outside.py"])
        self.settle("M000", candidate=candidate, ok=False)
        self.assertEqual("DISPATCHED", self.fixture.state()["cells"]["M000"]["state"])
        self.assertTrue(list((self.root / "evidence/M000/attempt-0001/scope-denials").glob("*.json")))
        # A rename crossing the boundary must expose both names without relying
        # on Git's rename similarity heuristic; deletion of README is outside.
        self.git("M000", "mv", "owned/valid.py", "moved.py")
        self.git("M000", "rm", "README.md")
        crossing = self.commit("M000", ["moved.py"])
        denied = self.settle("M000", candidate=crossing, ok=False)
        self.assertIn("moved.py", denied.stderr)
        self.assertIn("README.md", denied.stderr)
        self.assertEqual("LAUNCH_UNCERTAIN", self.request("M000")["phase"])

    @unittest.skipIf(os.name == "nt", "literal backslashes in filenames require POSIX")
    def test_literal_backslash_git_names_preserve_the_actual_scope_boundary(self):
        self.compile(paths={"M000": ["owned/"], "M001": ["elsewhere/"], "M002": ["other/"]})
        self.dispatch("M000")
        self.launch("M000")
        repo = self.fixture.target_worktree("M000")
        (repo / "owned").mkdir()
        inside = "owned/with" + chr(92) + "literal.py"
        (repo / inside).write_text("valid owned child\n", encoding="utf-8")
        allowed = self.commit("M000", [inside])
        coord.snapshot(self.request("M000")["binding"], allowed, self.fixture.target_base_sha, clean=True)
        outside = "owned" + chr(92) + "outside.py"
        self.assertEqual((outside,), Path(outside).parts)
        (repo / outside).write_text("outside the owned directory\n", encoding="utf-8")
        candidate = self.commit("M000", [outside])
        denied = self.settle("M000", candidate=candidate, ok=False)
        self.assertIn(outside, json.loads(denied.stderr)["offending_paths"])
        self.assertEqual("DISPATCHED", self.fixture.state()["cells"]["M000"]["state"])
        self.assertEqual("LAUNCH_UNCERTAIN", self.request("M000")["phase"])
        self.assertTrue((repo / outside).is_file())
        self.assertTrue(list((self.root / "evidence/M000/attempt-0001/scope-denials").glob("*.json")))

    def test_accepted_candidate_scope_proof_and_stale_publication(self):
        self.compile()
        self.dispatch("M000")
        self.launch("M000")
        repo = self.fixture.target_worktree("M000")
        (repo / "src/a").mkdir(parents=True)
        names = ["with space.py", "-leading.py", "unicode-\u96ea.py"]
        if os.name != "nt":
            names.append("with\nnewline.py")
        paths = ["src/a/" + name for name in names]
        for name in paths:
            (repo / name).write_text("candidate\n", encoding="utf-8")
        candidate = self.commit("M000", paths)
        self.settle("M000", candidate=candidate)
        # Exercise the real publication caller and frozen-runtime gate before
        # any forge lookup or push, with only network destinations stubbed.
        bridge_spec = importlib.util.spec_from_file_location("coordination_bridge", ROOT / "tools/wt_mission.py")
        bridge = importlib.util.module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge)
        from unittest import mock
        args = bridge.argparse.Namespace(root=str(self.root), cell="M000", base="main", gh="gh",
                                         title="Fixture", body="Fixture")
        calls = []
        original_run = bridge.run
        def observed_run(argv, **kwargs):
            calls.append(argv)
            return original_run(argv, **kwargs)
        with mock.patch.object(bridge, "github_origin", return_value=True), \
             mock.patch.object(bridge, "validate_push_destinations", return_value=["https://example.invalid/target.git"]), \
             mock.patch.object(bridge, "remote_head", return_value=self.fixture.target_base_sha), \
             mock.patch.object(bridge, "run", side_effect=observed_run), self.assertRaises(bridge.BridgeError):
            bridge.publish(args)
        self.assertFalse(any("push" in command or command[0] == "gh" for command in calls))
        self.fixture.mc("coordination", "verify", "--root", self.root, "--cell", "M000",
                        "--candidate", candidate, "--publication-base", self.fixture.target_base_sha, ok=False)
        self.fence("M000")
        self.transition("release", "M000")
        verify = ("coordination", "verify", "--root", self.root, "--cell", "M000", "--candidate", candidate,
                  "--publication-base", self.fixture.target_base_sha)
        self.fixture.mc(*verify)
        self.assertEqual("VERIFIED", json.loads(self.fixture.mc(*verify).stdout)["state"])
        fence_evidence = self.root / "evidence/operator-M000.json"
        original_fence = fence_evidence.read_bytes()
        try:
            fence_evidence.write_bytes(original_fence + b" ")
            self.fixture.mc(*verify, ok=False)
        finally:
            fence_evidence.write_bytes(original_fence)
        self.fixture.mc(*verify)
        (repo / paths[0]).write_text("late writer\n", encoding="utf-8")
        self.fixture.mc(*verify, ok=False)
        new_head = self.commit("M000", [paths[0]])
        self.assertNotEqual(candidate, new_head)
        self.fixture.mc(*verify, ok=False)

    def test_unfenced_live_writer_cancellation_and_stale_generation(self):
        self.compile()
        admitted = self.dispatch("M000")
        self.dispatch("M002")
        self.launch("M000")
        gate = Path(self.fixture.tmp.name) / "writer-exit"
        ready = Path(self.fixture.tmp.name) / "writer-ready"
        script = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('ready');\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.01)"
        process = subprocess.Popen([sys.executable, "-c", script, str(ready), str(gate)])
        try:
            self.wait_path(ready, process)
            self.transition("stop", "M000")
            self.settle("M000", "FAILED")
            self.transition("release", "M000", ok=False)
            self.fixture.mc("retry", "--root", self.root, "--cell", "M000", ok=False)
            self.recover()
            self.assertIsNone(process.poll())
            self.assertEqual("QUEUED", self.request("M002")["phase"])
        finally:
            gate.write_text("stop", encoding="utf-8")
            process.wait(timeout=10)
        self.assertEqual(0, process.returncode)
        # Parent exit alone still isn't treated as tree termination evidence.
        self.transition("release", "M000", ok=False)
        self.fence("M000")
        self.transition("release", "M000")
        self.fixture.mc("retry", "--root", self.root, "--cell", "M000")
        newer = self.dispatch("M000")
        self.assertEqual(2, newer["generation"])
        self.transition("unknown", "M000", request=admitted, ok=False)
        self.assertNotEqual(admitted["token"], newer["token"])
        fence_evidence = self.root / "evidence/operator-M000.json"
        original_fence = fence_evidence.read_bytes()
        try:
            fence_evidence.write_bytes(original_fence + b" ")
            self.fixture.mc("doctor", "--root", self.root, ok=False)
        finally:
            fence_evidence.write_bytes(original_fence)
        self.fixture.mc("doctor", "--root", self.root)

    def test_concurrent_requests_and_recovery_have_one_conflicting_admission(self):
        self.compile(paths={"M000": ["shared/"], "M001": ["shared/child.py"], "M002": ["independent/"]})
        ready = [Path(self.fixture.tmp.name) / f"ready-{index}" for index in range(3)]
        release = Path(self.fixture.tmp.name) / "request-release"
        wrapper = "import pathlib,subprocess,sys,time; pathlib.Path(sys.argv[1]).write_text('ready');\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.01)\np=subprocess.run(sys.argv[3:]); raise SystemExit(p.returncode)"
        processes = []
        for index, cell in enumerate(("M000", "M001", "M002")):
            temp = Path(self.fixture.tmp.name) / f"temp-{index}"
            temp.mkdir()
            command = [sys.executable, "-c", wrapper, str(ready[index]), str(release), sys.executable,
                       str(self.runtime), "dispatch", "--root", str(self.root), "--cell", cell,
                       "--workspace-id", "ws-" + cell, "--worker-identity", "runtime-state-worker",
                       "--verifier-identity", "runtime-state-verifier"]
            processes.append(subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              text=True, env=dict(os.environ, TEMP=str(temp), TMP=str(temp))))
        try:
            for path, process in zip(ready, processes):
                self.wait_path(path, process)
        finally:
            release.write_text("release", encoding="utf-8")
            outputs = [process.communicate(timeout=60) for process in processes]
        for process, (_, error) in zip(processes, outputs):
            self.assertEqual(0, process.returncode, error)
        results = [json.loads(output) for output, _ in outputs]
        self.assertEqual(["ADMITTED", "QUEUED"], sorted(item["phase"] for item in results[:2]))
        self.assertEqual("ADMITTED", results[2]["phase"])
        # Concurrent recovery is another transaction, never a second launch.
        recoveries = [subprocess.Popen([sys.executable, str(self.runtime), "coordination", "recover", "--root", str(self.root)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in recoveries:
            output, error = process.communicate(timeout=60)
            self.assertEqual(0, process.returncode, error)
            self.assertFalse(json.loads(output)["provider_launch_performed"])
        self.fixture.mc("doctor", "--root", self.root)

    def test_lost_admission_response_before_and_after_atomic_state_write(self):
        self.compile()
        for when, cell in (("before", "M000"), ("after", "M001")):
            script = '''
import importlib.util, os, pathlib, sys
spec=importlib.util.spec_from_file_location("fault_runtime", sys.argv[1])
mc=importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
save=mc._save_state
def fault(root,state):
    if sys.argv[3]=="before": os._exit(86)
    save(root,state)
    os._exit(86)
mc._save_state=fault
raise SystemExit(mc.main(["dispatch","--root",sys.argv[2],"--cell",sys.argv[4],"--workspace-id","ws-"+sys.argv[4],
                         "--worker-identity","runtime-state-worker","--verifier-identity","runtime-state-verifier"]))
'''
            proc = subprocess.run([sys.executable, "-c", script, str(self.runtime), str(self.root), when, cell], capture_output=True, text=True)
            self.assertEqual(86, proc.returncode, proc.stderr)
            before = self.fixture.state()["cells"][cell].get("coordination")
            admitted = self.dispatch(cell)
            self.assertEqual("ADMITTED", admitted["phase"])
            if before:
                self.assertEqual(before["token"], admitted["token"])
            self.assertEqual(admitted["token"], self.dispatch(cell)["token"])
        self.assertEqual(2, self.fixture.state()["coordination"]["next_order"])

    def test_new_runtime_full_lifecycle_and_frozen_copy_compatibility(self):
        old_settle = self.fixture.settle
        def settle(cell, *args, **kwargs):
            target = cell.startswith("M")
            if target:
                self.launch(cell)
            value = old_settle(cell, *args, **kwargs)
            if target:
                self.fence(cell)
                self.transition("release", cell)
            return value
        self.fixture.settle = settle
        # Setup already accepted the baseline. The fixture's method would do so
        # again, so run the remaining canonical lifecycle explicitly.
        self.fixture.compile_reference()
        for cell in ("M000", "M001"):
            self.dispatch(cell)
            self.fixture.settle(cell)
        self.fixture.mc("barrier", "accept", "--root", self.root, "--cell", "G100")
        self.fixture.mc("integrate", "--root", self.root)
        self.fixture.mc("dispatch", "--root", self.root, "--cell", "I000")
        self.fixture.settle("I000")
        self.fixture.mc("qualify", "--root", self.root)
        self.fixture.mc("dispatch", "--root", self.root, "--cell", "Q000")
        self.fixture.settle("Q000")
        current = json.loads((self.root / "control/CURRENT_AUTHORITY.json").read_text(encoding="utf-8"))
        qualification = {"schema": "flyby/mission-control-qualification/16", "outcome": "ACCEPTED",
                         "summary": "Capable runtime lifecycle qualification.",
                         "evidence": [{"kind": "coordination-lifecycle", "value": "accepted exact worktrees"}],
                         "target_outcomes": [{"repository": repository, "baseline_sha": base, "accepted_head_sha": base}
                                             for repository, base in sorted(current["target_baselines"].items())],
                         "requirement_accounting": {"accepted": ["REF-001"], "waived": []},
                         "verification_accounting": {"run": list(self.fixture.packet("Q000")["acceptance"]), "waived": [], "not_run": []},
                         "unresolved_defects": [], "explicit_limitations": []}
        input_path = self.root / "qualified.json"
        lifecycle.write_json(input_path, qualification)
        self.fixture.mc("qualify", "--root", self.root, "--result", input_path)
        reconciliation = self.root / "reconciliation.json"
        lifecycle.write_json(reconciliation, self.fixture.reference_workspace_reconciliation())
        self.fixture.mc("workspace", "load", "--root", self.root, "--file", reconciliation)
        self.fixture.mc("close", "--root", self.root)
        self.assertEqual("CLOSED", self.fixture.state()["lifecycle"])
        self.fixture.mc("doctor", "--root", self.root)
        lock = (self.root / "TEMPLATE_LOCK.json").read_bytes()
        import shutil
        copied = Path(self.fixture.tmp.name) / "copied-authority"
        shutil.copytree(self.root, copied)
        proc = subprocess.run([sys.executable, str(copied / "runtime/tools/mc.py"), "doctor", "--root", str(copied)], capture_output=True, text=True)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("moved or copied", proc.stderr)
        self.assertEqual(lock, (self.root / "TEMPLATE_LOCK.json").read_bytes())

    def test_changed_main_handoff_excludes_only_verified_inherited_changes(self):
        bare = Path(self.fixture.tmp.name) / "accepted-main.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.fixture.target_repo), "remote", "set-url", "origin", str(bare)], check=True)
        subprocess.run(["git", "-C", str(self.fixture.target_repo), "push", "origin", "HEAD:refs/heads/main"], check=True, capture_output=True)
        self.compile()
        self.dispatch("M000")
        self.launch("M000")
        source = self.fixture.target_worktree("M000")
        (source / "src/a").mkdir(parents=True)
        (source / "src/a/source.py").write_text("accepted source\n", encoding="utf-8")
        source_head = self.commit("M000", ["src/a/source.py"])
        self.settle("M000", candidate=source_head)
        self.fence("M000")
        self.transition("release", "M000")
        (self.fixture.target_repo / "inherited-main.py").write_text("accepted main\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.fixture.target_repo), "add", "inherited-main.py"], check=True)
        subprocess.run(["git", "-C", str(self.fixture.target_repo), "commit", "-qm", "advance accepted main"], check=True)
        observed = subprocess.check_output(["git", "-C", str(self.fixture.target_repo), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run(["git", "-C", str(self.fixture.target_repo), "push", "origin", "HEAD:refs/heads/main"], check=True, capture_output=True)
        handoff = self.fixture._run(self.runtime.parent / "wt_mission.py", "handoff", "--root", self.root,
                                    "--cell", "M000", "--successor", "M003", "--frontier", "F101", "--base-sha", observed)
        self.assertEqual(observed, json.loads(handoff.stdout)["scope_base_observation"]["sha"])
        successor = self.fixture.target_worktree("M003")
        self.fixture.mc("workspace", "register", "--root", self.root, "--cell", "M003", "--workspace-id", "ws-M003",
                        "--branch", "mcv6/m003", "--path", successor)
        self.dispatch("M003")
        self.launch("M003")
        self.git("M003", "merge", "--no-edit", source_head)
        self.git("M003", "merge", "--no-edit", observed)
        candidate = self.git("M003", "rev-parse", "HEAD").decode().strip()
        self.settle("M003", candidate=candidate)
        proof = json.loads((self.root / self.request("M003")["scope_proof_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(observed, proof["snapshot"]["base"])
        self.assertNotIn("inherited-main.py", proof["snapshot"]["paths"]["committed"])
        self.assertEqual(source_head, self.git("M000", "rev-parse", "HEAD").decode().strip())
        self.fence("M003")
        self.transition("release", "M003")
        self.fixture.mc("coordination", "verify", "--root", self.root, "--cell", "M003", "--candidate", candidate,
                        "--publication-base", observed)

    def test_fifo_eligible_requests_and_no_head_of_line_dependency_block(self):
        self.compile(paths={"M000": ["shared/"], "M001": ["shared/a.py"], "M002": ["shared/b.py"]},
                     dependencies={"M001": ["M000"]})
        waiting = self.dispatch("M001")
        self.assertEqual("QUEUED", waiting["phase"])
        # Earlier but ineligible M001 cannot reserve the directory or stop M000.
        active = self.dispatch("M000")
        peer = self.dispatch("M002")
        self.assertEqual("ADMITTED", active["phase"])
        self.assertEqual("QUEUED", peer["phase"])
        self.launch("M000")
        self.settle("M000")
        self.fence("M000")
        self.transition("release", "M000")
        self.recover()
        # M001 and M002 are disjoint siblings, so both eligible declarations
        # proceed despite their earlier common-directory writer.
        self.assertEqual(["ADMITTED", "ADMITTED"], [self.request(cell)["phase"] for cell in ("M001", "M002")])

    def test_queue_reassesses_base_and_records_explicit_new_generation(self):
        self.compile()
        self.dispatch("M000")
        queued = self.dispatch("M002")
        repo = self.fixture.target_worktree("M002")
        (repo / "outside.py").write_text("changed premise\n", encoding="utf-8")
        self.recover()
        self.assertTrue(any("reassessment:" in value for value in self.request("M002")["blockers"]))
        self.assertEqual(queued["token"], self.request("M002")["token"])
        # Explicitly remove only this fixture's synthetic dirt, then revoke and
        # reassess its declaration. No runtime operation cleans worker files.
        (repo / "outside.py").unlink()
        self.transition("release", "M002")
        self.transition("reassess", "M002", "--request-id", "M002:explicit-reassessment")
        current = self.request("M002")
        self.assertGreater(current["order"], queued["order"])
        self.assertEqual(queued["generation"] + 1, current["generation"])
        self.transition("launching", "M002", "--executor-identity", "stale-session", request=queued, ok=False)

    def test_registration_reconciles_and_rejects_a_competing_authority(self):
        self.compile()
        ledger = self.root / "control/WORKSPACE_LEDGER.json"
        original = ledger.read_bytes()
        replay = self.fixture.mc("workspace", "register", "--root", self.root, "--cell", "M000",
                                 "--workspace-id", "ws-M000", "--branch", "mcv6/m000",
                                 "--path", self.fixture.target_worktree("M000"))
        self.assertTrue(json.loads(replay.stdout)["reconciled"])
        self.assertEqual(original, ledger.read_bytes())
        runtime_spec = importlib.util.spec_from_file_location("registration_runtime", self.runtime)
        runtime = importlib.util.module_from_spec(runtime_spec)
        runtime_spec.loader.exec_module(runtime)
        other = Path(self.fixture.tmp.name) / "other-authority"
        other.mkdir()
        state = copy.deepcopy(self.fixture.state())
        state["coordination"].update({"instance_id": "different-instance", "authority_root": str(other.resolve())})
        entry = next(item for item in json.loads(original)["entries"] if item.get("workspace_id") == "ws-M000")
        with self.assertRaisesRegex(ValueError, "another coordination authority"):
            coord.register(vars(runtime), other.resolve(), state, entry)
        self.assertEqual(original, ledger.read_bytes())

    def test_mode_change_outside_scope_and_dirty_submodule_are_rejected(self):
        self.compile(paths={"M000": ["owned/", ".gitmodules"], "M001": ["elsewhere/"], "M002": ["other/"]})
        self.dispatch("M000")
        self.launch("M000")
        repo = self.fixture.target_worktree("M000")
        # Construct a real 160000 Git link and nested repository with native
        # Git commands. The shell-heavy `git submodule add` installer is not
        # part of the ownership mechanism and is unavailable in minimal hosts.
        module = repo / "owned/module"
        module.mkdir(parents=True)
        subprocess.run(["git", "init", str(module)], check=True, capture_output=True)
        (module / "tracked.py").write_text("nested base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(module), "add", "tracked.py"], check=True)
        subprocess.run(["git", "-C", str(module), "-c", "user.name=Module Fixture", "-c", "user.email=module@example.invalid",
                        "commit", "-qm", "nested base"], check=True)
        (repo / ".gitmodules").write_text('[submodule "fixture"]\n\tpath = owned/module\n\turl = ./fixture\n', encoding="utf-8")
        candidate = self.commit("M000", ["owned/module", ".gitmodules"])
        self.assertTrue(self.git("M000", "ls-files", "--stage", "--", "owned/module").startswith(b"160000 "))
        (repo / "owned/module/untracked.py").write_text("nested dirt\n", encoding="utf-8")
        self.settle("M000", candidate=candidate, ok=False)
        (repo / "owned/module/untracked.py").unlink()
        self.git("M000", "update-index", "--chmod=+x", "README.md")
        self.git("M000", "-c", "user.name=Coordination Fixture", "-c", "user.email=coordination@example.invalid",
                 "commit", "-qm", "out of scope mode change")
        candidate = self.git("M000", "rev-parse", "HEAD").decode().strip()
        denied = self.settle("M000", candidate=candidate, ok=False)
        self.assertIn("README.md", denied.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX symlink commit proof; Windows link creation requires a separately enabled privilege")
    def test_committed_symlink_type_and_escape_are_checked(self):
        self.compile()
        self.dispatch("M000")
        self.launch("M000")
        repo = self.fixture.target_worktree("M000")
        (repo / "src/a").mkdir(parents=True)
        (repo / "src/a/target").write_text("inside\n", encoding="utf-8")
        (repo / "src/a/link").symlink_to("target")
        candidate = self.commit("M000", ["src/a/target", "src/a/link"])
        # The link itself is a permitted Git type change when resolution stays
        # inside the admitted scope. An outside target fails before acceptance.
        proof = coord.snapshot(self.request("M000")["binding"], candidate, self.fixture.target_base_sha, clean=True)
        self.assertIn("src/a/link", proof["paths"]["committed"])
        (repo / "src/a/link").unlink()
        (repo / "src/a/link").symlink_to(Path(self.fixture.tmp.name))
        escaped = self.commit("M000", ["src/a/link"])
        self.settle("M000", candidate=escaped, ok=False)

    def test_faults_around_settlement_evidence_custody_state_and_safe_release(self):
        self.compile()
        self.dispatch("M000")
        self.launch("M000")
        result, receipt = self.fixture.result("M000", "FAILED"), self.fixture.receipt("M000")
        adjudication = self.fixture.adjudication("M000", result, receipt, attempt=1)
        request = self.request("M000")
        state_path, residency_path = self.root / "control/EXECUTION_STATE.json", self.root / "control/SESSION_RESIDENCY.json"
        state_bytes, residency_bytes = state_path.read_bytes(), residency_path.read_bytes()
        inputs = [str(result), str(receipt), str(adjudication)]
        wrapper = '''
import importlib.util, os, pathlib, sys
spec=importlib.util.spec_from_file_location("fault_settle",sys.argv[1])
mc=importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
write=mc.write_json
def fault(path,value):
    match=path.name==sys.argv[3]
    if match and sys.argv[4]=="before": os._exit(86)
    write(path,value)
    if match and sys.argv[4]=="after": os._exit(86)
mc.write_json=fault
raise SystemExit(mc.main(["settle","--root",sys.argv[2],"--cell","M000","--attempt","1",
                         "--result",sys.argv[5],"--context-receipt",sys.argv[6],"--adjudication",sys.argv[7],
                         "--generation",sys.argv[8],"--token",sys.argv[9]]))
'''
        import shutil
        for filename in ("result.json", "context_receipt.json", "adjudication.json", "SESSION_RESIDENCY.json", "scope_proof.json", "EXECUTION_STATE.json"):
            for when in ("before", "after"):
                with self.subTest(filename=filename, when=when):
                    # Restore only this test-owned synthetic authority fixture;
                    # no actual provider has been launched by these commands.
                    state_path.write_bytes(state_bytes)
                    residency_path.write_bytes(residency_bytes)
                    evidence = self.root / "evidence/M000/attempt-0001"
                    if evidence.exists():
                        shutil.rmtree(evidence)
                    proc = subprocess.run([sys.executable, "-c", wrapper, str(self.runtime), str(self.root), filename, when,
                                           *inputs, str(request["generation"]), request["token"]], capture_output=True, text=True)
                    self.assertEqual(86, proc.returncode, proc.stderr)
                    recovered = self.fixture._run(self.runtime.parent / "wt_mission.py", "settle", "--root", self.root,
                                                   "--cell", "M000", "--attempt", "1", "--result", result,
                                                   "--context-receipt", receipt, "--adjudication", adjudication,
                                                   "--generation", request["generation"], "--token", request["token"], "--reconcile")
                    self.assertEqual("FAILED", json.loads(recovered.stdout)["state"])
                    self.assertEqual(1, len(self.fixture.state()["cells"]["M000"]["attempt_history"]))
                    self.assertEqual("LAUNCH_UNCERTAIN", self.request("M000")["phase"])
        self.fence("M000")
        confirmed = state_path.read_bytes()
        release_wrapper = '''
import importlib.util, os, sys
spec=importlib.util.spec_from_file_location("release_runtime",sys.argv[1])
mc=importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
save=mc._save_state
def fault(root,state):
    if sys.argv[3]=="before": os._exit(86)
    save(root,state)
    os._exit(86)
mc._save_state=fault
raise SystemExit(mc.main(["coordination","release","--root",sys.argv[2],"--cell","M000",
                         "--generation",sys.argv[4],"--token",sys.argv[5]]))
'''
        for when in ("before", "after"):
            state_path.write_bytes(confirmed)
            proc = subprocess.run([sys.executable, "-c", release_wrapper, str(self.runtime), str(self.root), when,
                                   str(request["generation"]), request["token"]], capture_output=True, text=True)
            self.assertEqual(86, proc.returncode, proc.stderr)
            self.transition("release", "M000")
        # Lost release responses keep the same generation and proof.
        released = self.request("M000")
        self.transition("release", "M000")
        self.recover()
        self.assertEqual(released, self.request("M000"))

    @staticmethod
    def wait_path(path, process):
        deadline = time.monotonic() + 20
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not path.exists():
            raise AssertionError(f"controlled process did not reach barrier {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
