"""Outside-in transport binding, generation fencing and historical lookup."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_runtime_state_machine as lifecycle
import test_cell_coordination as coordination_tests

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
        self.observer = coordination_tests.CoordinationLifecycleTests()
        self.observer.fixture, self.observer.root = self.fixture, self.root

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
        self.assertEqual("ADMITTED", first["phase"])
        self.assertEqual(first, self.reserve(binding, "intent-M000"))
        self.reserve({**binding, "task_id": "another-task"}, "intent-M000", ok=False)
        second_binding = self.binding("M001")
        queued = self.reserve(second_binding, "intent-M001")
        self.assertEqual("QUEUED", queued["phase"])
        self.assertEqual(queued, self.reserve(second_binding, "intent-M001"))
        self.assertEqual(binding, self.action("inspect", "M000", first)["binding"])
        bad = {**first, "binding_digest": "f" * 64}
        self.action("launching", "M000", bad, "--executor-identity", "fixture-session:M000", ok=False)
        launched = self.action("launching", "M000", first, "--executor-identity", "fixture-session:M000")
        self.assertTrue(launched["launch_authorized"])
        self.assertFalse(self.action("launching", "M000", first, "--executor-identity", "fixture-session:M000")["launch_authorized"])
        self.action("unknown", "M000", first)
        self.action("release", "M000", first, ok=False)
        repo = self.fixture.target_worktree("M000")
        (repo / "owned").mkdir()
        (repo / "owned/change.txt").write_text("accepted fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "owned/change.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "candidate"], check=True, capture_output=True)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        result = self.fixture.result("M000", extra={"target_outcomes": [{"repository": "example/target",
                                      "baseline_sha": self.fixture.target_base_sha, "head_sha": head}]})
        self.fixture.raw_settle("M000", result, self.fixture.receipt("M000"))
        accepted = self.action("inspect", "M000", first)
        self.assertEqual("ACCEPTED", accepted["cell_state"])
        self.assertFalse(accepted["ownership_released"])
        self.assertEqual({"result_sha256", "context_receipt_sha256", "adjudication_sha256"}, set(accepted["evidence_hashes"]))
        self.assertEqual(hashlib.sha256(json.dumps(accepted["evidence_hashes"], sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(), accepted["evidence_digest"])
        self.observer.fence("M000")
        self.assertTrue(self.action("release", "M000", first)["ownership_released"])
        self.fixture.mc("coordination", "recover", "--root", self.root)
        self.assertEqual("ADMITTED", self.action("inspect", "M001", queued)["phase"])
        released = self.action("release", "M001", queued)
        self.assertTrue(released["released_without_launch"])
        renewed = self.reserve(second_binding, "intent-M001-renewed")
        self.assertGreater(renewed["fence"], queued["fence"])
        history = self.action("inspect", "M001", queued)
        self.assertFalse(history["current"])
        self.assertTrue(history["released_without_launch"])
        self.action("launching", "M001", queued, "--executor-identity", "old-session", ok=False)
        self.action("launching", "M001", renewed, "--executor-identity", "fixture-session:M001")
        failed = self.fixture.result("M001", "FAILED")
        self.fixture.raw_settle("M001", failed, self.fixture.receipt("M001"))
        self.observer.fence("M001")
        self.action("release", "M001", renewed)
        self.fixture.mc("retry", "--root", self.root, "--cell", "M001")
        old = self.action("inspect", "M001", renewed)
        self.assertFalse(old["current"])
        self.assertEqual("FAILED", old["cell_state"])
        self.assertTrue(old["evidence_hashes"])
        never_launched = self.action("inspect", "M001", queued)
        self.assertEqual("COMPILED", never_launched["cell_state"])
        self.assertEqual({}, never_launched["evidence_hashes"])
        self.action("launching", "M001", renewed, "--executor-identity", "old-session", ok=False)
        next_attempt = self.reserve(self.binding("M001", attempt=2), "intent-M001-attempt2")
        self.assertEqual(2, next_attempt["attempt"])
        self.assertGreater(next_attempt["fence"], renewed["fence"])
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
