"""Outside-in transport binding, generation fencing and historical lookup."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_runtime_state_machine as lifecycle
from reservation_fixture import ReservationProtocol

ROOT = Path(__file__).resolve().parents[1]


class ReservationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = lifecycle.RuntimeStateMachineSuite()
        original_source = self.fixture.source
        def source(*args, **kwargs):
            if args and args[0] == "init":
                args = (*args, "--execution-reservations")
            return original_source(*args, **kwargs)
        self.fixture.source = source
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        original_mc = self.fixture.mc
        def mc(*args, **kwargs):
            rendered = list(args)
            if rendered and rendered[0] == "settle" and "--generation" not in rendered:
                cell = str(rendered[rendered.index("--cell") + 1])
                request = self.fixture.state()["cells"].get(cell, {}).get("coordination")
                if request:
                    rendered.extend(["--generation", request["generation"], "--token", request["token"]])
                    rendered.extend(["--binding-digest", self.fixture.state()["cells"][cell]["execution_reservation"]["binding_digest"]])
            return original_mc(*rendered, **kwargs)
        self.fixture.mc = mc
        self.root = self.fixture.root
        self.fixture.accept_baseline()
        frontier = self.fixture.reference_frontier_payload()
        for cell in frontier["cells"]:
            if cell.get("target"):
                cell["target"]["owned_paths"] = ["owned/"]
        path = self.root / "reservation-frontier.json"
        lifecycle.write_json(path, frontier)
        self.fixture.mc("compile", "--root", self.root, "--frontier", path)
        for cell in ("M000", "M001"):
            self.fixture.mc("workspace", "register", "--root", self.root, "--cell", cell,
                            "--workspace-id", "ws-" + cell, "--branch", "mcv6/" + cell.lower(),
                            "--path", self.fixture.target_worktree(cell))
        self.protocol = ReservationProtocol(self.fixture)
        original_receipt = self.fixture.receipt
        def receipt(cell, **kwargs):
            path = original_receipt(cell, **kwargs)
            return self.protocol.receipt_session(path, cell)
        self.fixture.receipt = receipt

    def binding(self, cell, *, attempt=1):
        return {"mission_id": self.fixture.state()["mission_id"],
                "mission_instance_id": self.fixture.state()["mission_instance_id"],
                "cell_id": cell, "attempt": attempt, "workspace_id": "ws-" + cell,
                "workspace_path": str(self.fixture.target_worktree(cell).resolve()),
                "workspace_origin": "https://example.invalid/target.git", "repository": "example/target",
                "base_sha": self.fixture.target_base_sha,
                "worker_identity": "runtime-state-worker", "verifier_identity": "runtime-state-verifier",
                "task_id": "task:" + cell, "seat_id": "seat-1", "worker_id": "worker-1",
                "claim_id": "claim:" + cell, "claim_generation": 1, "worker_generation": 1,
                "project_id": "project-1", "provider": "codex", "account_id": None, "node_id": "node-1"}

    def reserve(self, binding, intent, *, ok=True):
        path = self.root / "transport-binding.json"
        lifecycle.write_json(path, binding)
        proc = self.fixture.mc("execution", "reserve", "--root", self.root,
                               "--binding", path, "--launch-intent-id", intent, ok=ok)
        return json.loads(proc.stdout) if ok else proc

    def action(self, action, cell, reservation, *more, ok=True):
        proc = self.fixture.mc("execution", action, "--root", self.root, "--cell", cell,
                               "--reservation-id", reservation["reservation_id"], "--fence", reservation["fence"],
                               "--binding-digest", reservation["binding_digest"], *more, ok=ok)
        return json.loads(proc.stdout) if ok else proc

    def state_bytes(self):
        return (self.root / "control/EXECUTION_STATE.json").read_bytes()

    def corrupt_state_rejected(self, mutate):
        path = self.root / "control/EXECUTION_STATE.json"
        before = path.read_bytes()
        value = json.loads(before)
        mutate(value)
        try:
            lifecycle.write_json(path, value)
            self.fixture.mc("doctor", "--root", self.root, ok=False)
        finally:
            path.write_bytes(before)

    def concurrent_launch(self, reservation):
        processes = []
        for index in range(2):
            temp = self.root / f"launcher-temp-{index}"
            temp.mkdir()
            env = dict(os.environ, TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
            command = [sys.executable, str(self.fixture.runtime), "execution", "launching", "--root", str(self.root),
                       "--cell", "M000", "--reservation-id", reservation["reservation_id"],
                       "--fence", str(reservation["fence"]), "--binding-digest", reservation["binding_digest"],
                       "--executor-identity", "fixture-session:M000"]
            processes.append(subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env))
        values = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            self.assertEqual(0, process.returncode, stderr)
            values.append(json.loads(stdout))
        self.assertEqual([False, True], sorted(value["launch_authorized"] for value in values))
        self.assertEqual([False, True], sorted(value["transitioned"] for value in values))
        self.assertEqual({reservation["reservation_id"]}, {value["reservation_id"] for value in values})

    def test_bound_admission_launch_settlement_release_and_historical_recovery(self):
        binding = self.binding("M000")
        for change in ({"claim_generation": True}, {"attempt": 2}, {"workspace_origin": "https://other.invalid/repo"},
                       {"mission_instance_id": "another-instance"}, {"task_id": " task-1"}):
            before = (self.root / "control/EXECUTION_STATE.json").read_bytes()
            self.reserve({**binding, **change}, "invalid", ok=False)
            self.assertEqual(before, (self.root / "control/EXECUTION_STATE.json").read_bytes())
        path = self.root / "duplicate-binding.json"
        path.write_text('{"cell_id":"M000","cell_id":"M001"}', encoding="utf-8")
        duplicate = self.fixture.mc("execution", "reserve", "--root", self.root, "--binding", path,
                                    "--launch-intent-id", "duplicate", ok=False)
        self.assertIn("duplicate", duplicate.stderr)
        self.fixture.mc("dispatch", "--root", self.root, "--cell", "M000", ok=False)
        first = self.reserve(binding, "intent-M000")
        self.assertEqual("RESERVED", first["phase"])
        self.assertEqual("ADMITTED", first["coordination_phase"])
        self.assertEqual(first, self.reserve(binding, "intent-M000"))
        self.reserve({**binding, "task_id": "another-task"}, "intent-M000", ok=False)
        second_binding = self.binding("M001")
        queued = self.reserve(second_binding, "intent-M001")
        self.assertEqual("QUEUED", queued["phase"])
        self.assertEqual(queued, self.reserve(second_binding, "intent-M001"))
        self.assertEqual(binding, self.action("inspect", "M000", first)["binding"])
        # The old coordination/retry entry points must not bypass the transport digest.
        for action in ("launching", "running", "unknown", "stop", "confirm-stop", "release", "reassess", "relinquish"):
            more = (["--workspace-id", "ws-M000"] if action == "relinquish" else
                    ["--generation", first["fence"], "--token", first["reservation_id"]])
            if action == "launching":
                more += ["--executor-identity", "bypass"]
            elif action == "confirm-stop":
                more += ["--observation", self.root / "does-not-exist.json"]
            before = self.state_bytes()
            denied = self.fixture.mc("coordination", action, "--root", self.root, "--cell", "M000", *more, ok=False)
            self.assertIn("use execution", denied.stderr)
            self.assertEqual(before, self.state_bytes())
        # This preflight must happen before creating a worktree or invoking wt.
        before = self.state_bytes()
        worktrees = subprocess.run(["git", "-C", str(self.fixture.target_repo), "worktree", "list", "--porcelain"],
                                  check=True, capture_output=True).stdout
        denied = subprocess.run([sys.executable, str(ROOT / "tools/wt_mission.py"), "prepare", "--root", str(self.root),
                                 "--cell", "M000", "--repo", str(self.fixture.target_repo), "--workspace-id", "new-workspace",
                                 "--branch", "must-not-exist", "--worker", "worker", "--verifier", "verifier",
                                 "--wt", "missing-wt-program"], capture_output=True, text=True)
        self.assertNotEqual(0, denied.returncode)
        self.assertIn("execution reserve", denied.stderr)
        self.assertEqual(before, self.state_bytes())
        self.assertEqual(worktrees, subprocess.run(["git", "-C", str(self.fixture.target_repo), "worktree", "list", "--porcelain"],
                                                  check=True, capture_output=True).stdout)
        bad = {**first, "binding_digest": "f" * 64}
        self.action("launching", "M000", bad, "--executor-identity", "fixture-session:M000", ok=False)
        self.concurrent_launch(first)
        self.assertFalse(self.action("launching", "M000", first, "--executor-identity", "fixture-session:M000")["launch_authorized"])
        self.action("unknown", "M000", first)
        self.action("release", "M000", first, ok=False)
        session_path, session = self.protocol.observation("M000", "session")
        before = self.state_bytes()
        for change in ({"fence": True}, {"attempt": 2}, {"binding_digest": "f" * 64}, {"launch_intent_id": "wrong-intent"}):
            lifecycle.write_json(session_path, {**session, **change})
            self.fixture.mc("execution", "running", "--root", self.root, "--observation", session_path, ok=False)
            self.assertEqual(before, self.state_bytes())
        session_path.write_text('{"cell_id":"M000","cell_id":"M001"}', encoding="utf-8")
        duplicate = self.fixture.mc("execution", "running", "--root", self.root, "--observation", session_path, ok=False)
        self.assertIn("duplicate", duplicate.stderr)
        self.protocol.running("M000", context_session="independently-mapped-context-session")
        repo = self.fixture.target_worktree("M000")
        (repo / "owned").mkdir()
        (repo / "owned/change.txt").write_text("accepted fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "owned/change.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "candidate"], check=True, capture_output=True)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        result = self.fixture.result("M000", extra={"target_outcomes": [{"repository": "example/target",
                                      "baseline_sha": self.fixture.target_base_sha, "head_sha": head}]})
        receipt = self.fixture.receipt("M000")
        missing_terminal = self.fixture.raw_settle("M000", result, receipt, ok=False)
        self.assertIn("terminal observations", missing_terminal.stderr)
        self.protocol.terminal("M000")
        terminal = self.action("inspect", "M000", first)
        self.assertEqual("TERMINAL", terminal["phase"])
        self.assertTrue(terminal["terminal_ref"])
        wrong_receipt = json.loads(receipt.read_text(encoding="utf-8"))
        wrong_receipt["worker"]["session_id"] = "unrelated-provider-session"
        lifecycle.write_json(receipt, wrong_receipt)
        wrong = self.fixture.raw_settle("M000", result, receipt, ok=False)
        self.assertIn("ContextReceipt session", wrong.stderr)
        self.protocol.receipt_session(receipt, "M000")
        adjudication = self.fixture.adjudication("M000", result, receipt)
        before = self.state_bytes()
        request = self.fixture.state()["cells"]["M000"]["coordination"]
        denied = self.fixture._run(self.fixture.runtime, "settle", "--root", self.root, "--cell", "M000", "--attempt", 1,
                                  "--result", result, "--context-receipt", receipt, "--adjudication", adjudication,
                                  "--generation", request["generation"], "--token", request["token"], ok=False)
        self.assertIn("binding digest", denied.stderr)
        self.assertEqual(before, self.state_bytes())
        self.fixture.raw_settle("M000", result, receipt)
        accepted = self.action("inspect", "M000", first)
        self.assertEqual("ACCEPTED", accepted["cell_state"])
        self.assertEqual("SETTLED", accepted["phase"])
        self.assertFalse(accepted["ownership_released"])
        self.assertEqual({"result_sha256", "context_receipt_sha256", "adjudication_sha256"}, set(accepted["evidence_hashes"]))
        self.assertEqual(hashlib.sha256(json.dumps(accepted["evidence_hashes"], sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(), accepted["evidence_digest"])
        for action, key in (("running", "session_observation_ref"), ("terminal", "terminal_observation_ref")):
            value = json.loads((self.root / self.protocol.current("M000")[key]).read_text(encoding="utf-8"))
            changed_observation = self.root / "changed-observation.json"
            lifecycle.write_json(changed_observation, {**value, "observation_id": "late-replacement"})
            before = self.state_bytes()
            denied = self.fixture.mc("execution", action, "--root", self.root, "--observation", changed_observation, ok=False)
            self.assertIn("immutable", denied.stderr)
            self.assertEqual(before, self.state_bytes())
        self.corrupt_state_rejected(lambda state: state["cells"]["M000"]["coordination"].update(executor_identity=None))
        self.assertTrue(self.action("release", "M000", first)["ownership_released"])
        self.fixture.mc("coordination", "recover", "--root", self.root)
        self.assertEqual("RESERVED", self.action("inspect", "M001", queued)["phase"])
        released = self.action("release", "M001", queued)
        self.assertTrue(released["released_without_launch"])
        renewed = self.reserve(second_binding, "intent-M001-renewed")
        self.assertGreater(renewed["fence"], queued["fence"])
        history = self.action("inspect", "M001", queued)
        self.assertFalse(history["current"])
        self.assertTrue(history["released_without_launch"])
        archived = self.fixture.state()["cells"]["M001"]["execution_reservation_history"][0]
        release_path = self.root / archived["prelaunch_release_ref"]
        release_bytes = release_path.read_bytes()
        try:
            lifecycle.write_json(release_path, {**json.loads(release_bytes), "binding_digest": "f" * 64})
            self.corrupt_state_rejected(lambda state: state["cells"]["M001"]["execution_reservation_history"][0].update(
                prelaunch_release_sha256=lifecycle.sha256(release_path)))
        finally:
            release_path.write_bytes(release_bytes)
        self.corrupt_state_rejected(lambda state: state["cells"]["M001"].pop("execution_reservation_history"))
        self.corrupt_state_rejected(lambda state: state["cells"]["M001"]["execution_reservation_history"].append(
            copy.deepcopy(state["cells"]["M001"]["execution_reservation_history"][0])))
        self.action("launching", "M001", queued, "--executor-identity", "old-session", ok=False)
        self.action("launching", "M001", renewed, "--executor-identity", "fixture-session:M001")
        self.action("unknown", "M001", renewed)
        # Definite no-launch recovery is distinct from prelaunch release and provider termination.
        no_launch_path, no_launch = self.protocol.observation("M001", "no-launch")
        before = self.state_bytes()
        denied = self.fixture.mc("execution", "release-no-launch", "--root", self.root, "--observation", no_launch_path, ok=False)
        self.assertIn("independent confirmation", denied.stderr)
        self.assertEqual(before, self.state_bytes())
        for change in ({"fence": True}, {"launch_authority_revoked": False}, {"start_not_occurred": False},
                       {"binding_digest": "f" * 64}, {"launch_intent_id": "another-intent"}):
            lifecycle.write_json(no_launch_path, {**no_launch, **change})
            self.fixture.mc("execution", "release-no-launch", "--root", self.root, "--observation", no_launch_path, ok=False)
            self.assertEqual(before, self.state_bytes())
        lifecycle.write_json(no_launch_path, no_launch)
        self.protocol.fence("M001", no_launch["source_evidence"])
        released = json.loads(self.fixture.mc("execution", "release-no-launch", "--root", self.root,
                                            "--observation", no_launch_path).stdout)
        self.assertEqual("RELEASED_NO_LAUNCH", released["phase"])
        self.assertEqual("COMPILED", released["cell_state"])
        self.assertEqual({}, released["evidence_hashes"])
        self.assertFalse(released["current"])
        failed_reservation = self.reserve(second_binding, "intent-M001-provider-failed")
        replay = json.loads(self.fixture.mc("execution", "release-no-launch", "--root", self.root,
                                          "--observation", no_launch_path).stdout)
        self.assertEqual(released["release_receipt_sha256"], replay["release_receipt_sha256"])
        self.assertFalse(replay["current"])
        lifecycle.write_json(no_launch_path, {**no_launch, "observation_id": "conflicting-replay"})
        self.fixture.mc("execution", "release-no-launch", "--root", self.root, "--observation", no_launch_path, ok=False)
        lifecycle.write_json(no_launch_path, no_launch)
        self.action("launching", "M001", renewed, "--executor-identity", "old-session", ok=False)
        self.action("launching", "M001", failed_reservation, "--executor-identity", "provider-failed:M001")
        self.protocol.running("M001")
        self.protocol.terminal("M001", outcome="FAILED")
        cannot_accept = self.fixture.raw_settle("M001", self.fixture.result("M001"), self.fixture.receipt("M001"), ok=False)
        self.assertIn("failure or cancellation", cannot_accept.stderr)
        failed = self.fixture.result("M001", "FAILED")
        self.fixture.raw_settle("M001", failed, self.fixture.receipt("M001"))
        self.action("release", "M001", failed_reservation)
        before = self.state_bytes()
        denied = self.fixture.mc("retry", "--root", self.root, "--cell", "M001", ok=False)
        self.assertIn("execution retry", denied.stderr)
        self.assertEqual(before, self.state_bytes())
        self.action("retry", "M001", {**failed_reservation, "binding_digest": "f" * 64}, ok=False)
        self.action("retry", "M001", failed_reservation)
        old = self.action("inspect", "M001", failed_reservation)
        self.assertFalse(old["current"])
        self.assertEqual("FAILED", old["cell_state"])
        self.assertTrue(old["evidence_hashes"])
        never_launched = self.action("inspect", "M001", queued)
        self.assertEqual("COMPILED", never_launched["cell_state"])
        self.assertEqual({}, never_launched["evidence_hashes"])
        self.action("launching", "M001", failed_reservation, "--executor-identity", "old-session", ok=False)
        next_attempt = self.reserve(self.binding("M001", attempt=2), "intent-M001-attempt2")
        self.assertEqual(2, next_attempt["attempt"])
        self.assertGreater(next_attempt["fence"], failed_reservation["fence"])
        self.fixture.mc("doctor", "--root", self.root)


class ReservationAdoptionTests(unittest.TestCase):
    def test_new_opt_in_and_lineage_composition_are_sealed_without_upgrading_legacy(self):
        with tempfile.TemporaryDirectory(prefix="mc-reservation-adoption-") as temp:
            for lineage in (False, True):
                root = Path(temp) / str(lineage)
                root.mkdir()
                (root / "MISSION.json").write_bytes((ROOT / "examples/reference-mission/MISSION.json").read_bytes())
                command = [sys.executable, str(ROOT / "tools/mc.py"), "init", "--mission", str(root / "MISSION.json"),
                           "--execution-reservations"]
                if lineage:
                    command.append("--lineage-preservation")
                proc = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(0, proc.returncode, proc.stderr)
                state = json.loads((root / "control/EXECUTION_STATE.json").read_text(encoding="utf-8"))
                lock_path = root / "TEMPLATE_LOCK.json"
                before = lock_path.read_bytes()
                lock = json.loads(before)
                cap = json.loads((root / "contracts/capabilities/execution-reservation-v1.json").read_text(encoding="utf-8"))
                self.assertEqual(state["schema"], cap["execution_state_schema"])
                self.assertEqual("flyby/mission-control-execution-state/21", state["schema"])
                self.assertIn("runtime/tools/execution_reservation.py", lock["assets"])
                rejected = subprocess.run(command, capture_output=True, text=True)
                self.assertNotEqual(0, rejected.returncode)
                self.assertEqual(before, lock_path.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
