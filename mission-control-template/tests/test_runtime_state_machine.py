#!/usr/bin/env python3
"""Adversarial outside-in state-machine tests for Mission Control v16."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MC = ROOT / "tools" / "mc.py"
EXAMPLE = ROOT / "examples" / "reference-mission"
BASELINE = ("A000", "A001", "A002", "A003", "A004")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeStateMachineSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mcv16-state-")
        self.target_repo = Path(self.tmp.name) / "target-repo"
        self.target_repo.mkdir()
        subprocess.run(["git", "init", str(self.target_repo)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.target_repo), "config", "user.email", "runtime-state@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.target_repo), "config", "user.name", "Runtime State Suite"], check=True)
        (self.target_repo / "README.md").write_text("runtime-state target\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.target_repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.target_repo), "commit", "-m", "runtime-state target base"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(self.target_repo), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "-C", str(self.target_repo), "remote", "add", "origin", "https://example.invalid/target.git"], check=True)
        self.target_base_sha = subprocess.run(["git", "-C", str(self.target_repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip().lower()
        self.target_worktrees: dict[str, Path] = {}

        self.root = Path(self.tmp.name) / "mission"
        self.root.mkdir()
        mission = json.loads((EXAMPLE / "MISSION.json").read_text(encoding="utf-8"))
        mission["target_repositories"][0]["baseline_sha"] = self.target_base_sha
        write_json(self.root / "MISSION.json", mission)
        self.source("init", "--mission", self.root / "MISSION.json")
        if (EXAMPLE / "evidence").is_dir():
            shutil.copytree(EXAMPLE / "evidence", self.root / "evidence", dirs_exist_ok=True)
        self.runtime = self.root / "runtime" / "tools" / "mc.py"
        self.mc("sources", "load", "--root", self.root, "--file", EXAMPLE / "SOURCES.json")
        self.mc("provenance", "load", "--root", self.root, "--file", EXAMPLE / "PROVENANCE_SYNTHESIS.json")
        self.mc("corpus", "load", "--root", self.root, "--file", EXAMPLE / "TARGET_CORPUS.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, script: Path, *args: object, ok: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            capture_output=True,
            text=True,
        )
        if ok and proc.returncode != 0:
            self.fail(f"command failed: {args}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        if not ok and proc.returncode == 0:
            self.fail(f"command unexpectedly succeeded: {args}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        return proc

    def source(self, *args: object, ok: bool = True) -> subprocess.CompletedProcess[str]:
        return self._run(SOURCE_MC, *args, ok=ok)

    def mc(self, *args: object, ok: bool = True) -> subprocess.CompletedProcess[str]:
        rendered = list(args)
        if rendered and rendered[0] == "dispatch" and "--worker-identity" not in rendered:
            rendered.extend([
                "--worker-identity", "runtime-state-worker",
                "--verifier-identity", "runtime-state-verifier",
            ])
        if rendered and rendered[0] == "dispatch" and "--workspace-id" not in rendered and "--cell" in rendered:
            cell = str(rendered[rendered.index("--cell") + 1])
            if cell in {"M000", "M001"}:
                rendered.extend(["--workspace-id", f"ws-{cell}"])
        return self._run(self.runtime, *rendered, ok=ok)

    def state(self) -> dict:
        return json.loads((self.root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))

    def packet(self, cell_id: str) -> dict:
        state = self.state()
        return json.loads((self.root / state["cells"][cell_id]["workcell_ref"]).read_text(encoding="utf-8"))

    def result(self, cell_id: str, outcome: str = "ACCEPTED", *, extra: dict | None = None) -> Path:
        path = self.root / f"{cell_id}-{outcome.lower()}-result.json"
        value = {
            "schema": "flyby/mission-control-result/16",
            "cell_id": cell_id,
            "outcome": outcome,
            "summary": f"{cell_id} {outcome.lower()} runtime-state proof",
            "evidence": [{"kind": "runtime-state-test", "value": f"evidence:{cell_id}:{outcome}"}],
        }
        if outcome == "ACCEPTED":
            packet = self.packet(cell_id)
            if packet.get("kind") == "MUTATION":
                target = packet["target"]
                value["target_outcomes"] = [{
                    "repository": target["repository"],
                    "baseline_sha": target["base_sha"].lower(),
                    "head_sha": target["base_sha"].lower(),
                }]
            elif packet.get("kind") in {"INTEGRATION", "QUALIFICATION"}:
                current = json.loads((self.root / "control" / "CURRENT_AUTHORITY.json").read_text(encoding="utf-8"))
                heads = dict(current["target_baselines"])
                state = self.state()
                dag = json.loads((self.root / "control" / "EXECUTION_DAG.json").read_text(encoding="utf-8"))
                if packet.get("kind") == "INTEGRATION":
                    integrated_mutations = []
                    for descriptor in dag["cells"]:
                        if descriptor.get("kind") != "MUTATION":
                            continue
                        record = state["cells"].get(descriptor["cell_id"], {})
                        if record.get("state") != "ACCEPTED":
                            continue
                        mutation_result = json.loads((self.root / record["result_ref"]).read_text(encoding="utf-8"))
                        target_outcome = mutation_result["target_outcomes"][0]
                        integrated_mutations.append({
                            "cell_id": descriptor["cell_id"],
                            "repository": target_outcome["repository"],
                            "head_sha": target_outcome["head_sha"],
                        })
                    value["integrated_mutations"] = sorted(integrated_mutations, key=lambda item: item["cell_id"])
                else:
                    for descriptor in dag["cells"]:
                        if descriptor.get("kind") != "INTEGRATION":
                            continue
                        record = state["cells"].get(descriptor["cell_id"], {})
                        if record.get("state") != "ACCEPTED":
                            continue
                        integration_result = json.loads((self.root / record["result_ref"]).read_text(encoding="utf-8"))
                        for target_outcome in integration_result["target_outcomes"]:
                            heads[target_outcome["repository"]] = target_outcome["head_sha"]
                value["target_outcomes"] = [
                    {"repository": repository, "baseline_sha": baseline, "head_sha": heads[repository]}
                    for repository, baseline in sorted(current["target_baselines"].items())
                ]
        if extra:
            value.update(extra)
        write_json(path, value)
        return path

    def receipt(self, cell_id: str, *, extra: dict | None = None) -> Path:
        packet = self.packet(cell_id)
        path = self.root / f"{cell_id}-receipt.json"
        manifest_ref = packet["context_manifest_ref"]
        manifest = json.loads((self.root / manifest_ref).read_text(encoding="utf-8"))
        required_context = [item["context_id"] for item in manifest["items"] if item.get("requirement") == "REQUIRED"]
        manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        value = {
            "schema": "flyby/mission-control-context-receipt/1",
            "receipt_id": f"{cell_id}:runtime-state",
            "cell_id": cell_id,
            "worker": {"identity": "runtime-state-worker", "session_id": None},
            "base_head": packet["base_head"],
            "manifest_ref": manifest_ref,
            "manifest_hash": manifest_hash,
            "consumed": required_context,
            "partial_or_unavailable": [],
            "approved_extra_context": [],
            "capsules_used": [],
            "assumptions": [],
            "unknowns": [],
            "semantic_coverage": ["runtime state-machine behavior"],
            "explicitly_not_covered": [],
            "estimated_context_consumed": None,
            "compaction_or_restart_events": [],
            "safe_reuse_scope": [],
            "unsafe_reuse_scope": ["synthetic test worker is not reusable"],
            "continuation": {
                "session_reusable": False,
                "session_id": None,
                "reason": "synthetic runtime-state test session",
            },
        }
        if extra:
            value.update(extra)
        write_json(path, value)
        return path

    def adjudication(
        self,
        cell_id: str,
        result_path: Path,
        receipt_path: Path,
        *,
        attempt: int | None = None,
        decision: str | None = None,
        verifier_identity: str = "runtime-state-verifier",
        verifier_session: str | None = None,
        extra: dict | None = None,
    ) -> Path:
        packet = self.packet(cell_id)
        state = self.state()
        workcell_ref = state["cells"][cell_id]["workcell_ref"]
        manifest_ref = packet["context_manifest_ref"]
        result = json.loads(result_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        workcell = json.loads((self.root / workcell_ref).read_text(encoding="utf-8"))
        manifest = json.loads((self.root / manifest_ref).read_text(encoding="utf-8"))
        current_attempt = int(state["cells"][cell_id]["attempt"])
        mapped = {
            "ACCEPTED": "ACCEPTED", "REJECTED": "REJECTED", "FAILED": "FAILED",
            "BLOCKED": "BLOCKED", "PARTIAL": "CANDIDATE",
        }
        path = self.root / f"{cell_id}-adjudication.json"
        value = {
            "schema": "flyby/mission-control-adjudication/16",
            "cell_id": cell_id,
            "attempt": attempt if attempt is not None else current_attempt,
            "decision": decision or mapped[result["outcome"]],
            "verifier": {"identity": verifier_identity, "session_id": verifier_session},
            "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(),
            "context_receipt_sha256": hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(),
            "workcell_sha256": hashlib.sha256(json.dumps(workcell, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(),
            "context_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest(),
            "verified_acceptance": list(packet.get("acceptance", [])) if (decision or mapped[result["outcome"]]) == "ACCEPTED" else [],
            "evidence": [{"kind": "runtime-state-verifier", "value": f"verified:{cell_id}:{current_attempt}"}],
            "rationale": "Independent synthetic verifier adjudication for runtime-state testing.",
        }
        if extra:
            value.update(extra)
        write_json(path, value)
        return path

    def settle(self, cell_id: str, outcome: str = "ACCEPTED", *, attempt: int | None = None, decision: str | None = None) -> subprocess.CompletedProcess[str]:
        current = int(self.state()["cells"][cell_id]["attempt"])
        result_path = self.result(cell_id, outcome)
        receipt_path = self.receipt(cell_id)
        adjudication_path = self.adjudication(
            cell_id,
            result_path,
            receipt_path,
            attempt=attempt if attempt is not None else current,
            decision=decision,
        )
        return self.mc(
            "settle", "--root", self.root, "--cell", cell_id,
            "--attempt", attempt if attempt is not None else current,
            "--result", result_path,
            "--context-receipt", receipt_path,
            "--adjudication", adjudication_path,
        )

    def raw_settle(
        self,
        cell_id: str,
        result_path: Path,
        receipt_path: Path,
        *,
        attempt: int | None = None,
        decision: str | None = None,
        verifier_identity: str = "runtime-state-verifier",
        verifier_session: str | None = None,
        adjudication_extra: dict | None = None,
        ok: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        current = int(self.state()["cells"][cell_id]["attempt"])
        settlement_attempt = attempt if attempt is not None else current
        adjudication_path = self.adjudication(
            cell_id,
            result_path,
            receipt_path,
            attempt=settlement_attempt,
            decision=decision,
            verifier_identity=verifier_identity,
            verifier_session=verifier_session,
            extra=adjudication_extra,
        )
        return self.mc(
            "settle", "--root", self.root, "--cell", cell_id,
            "--attempt", settlement_attempt,
            "--result", result_path,
            "--context-receipt", receipt_path,
            "--adjudication", adjudication_path,
            ok=ok,
        )

    def accept_baseline(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        for cell_id in BASELINE:
            self.mc("dispatch", "--root", self.root, "--cell", cell_id)
            self.settle(cell_id)
        self.mc("baseline", "accept", "--root", self.root)

    def target_worktree(self, cell: str) -> Path:
        existing = self.target_worktrees.get(cell)
        if existing is not None:
            return existing
        worktree = Path(self.tmp.name) / f"target-{cell.lower()}"
        subprocess.run([
            "git", "-C", str(self.target_repo), "worktree", "add", "-b", f"mcv6/{cell.lower()}",
            str(worktree), self.target_base_sha,
        ], check=True, capture_output=True, text=True)
        self.target_worktrees[cell] = worktree
        return worktree

    def reference_frontier_payload(self) -> dict:
        payload = json.loads((EXAMPLE / "MUTATION_FRONTIER.json").read_text())
        for cell in payload.get("cells", []):
            target = cell.get("target") if isinstance(cell, dict) else None
            if isinstance(target, dict) and target.get("repository") == "example/target":
                target["base_sha"] = self.target_base_sha
        return payload

    def reference_frontier(self) -> Path:
        frontier = self.root / "reference-frontier.json"
        write_json(frontier, self.reference_frontier_payload())
        return frontier

    def compile_reference(self) -> None:
        frontier = self.reference_frontier()
        self.mc("compile", "--root", self.root, "--frontier", frontier)
        ledger = json.loads((self.root / "control" / "WORKSPACE_LEDGER.json").read_text(encoding="utf-8"))
        registered = {item["workspace_id"] for item in ledger["entries"]}
        for cell in ("M000", "M001"):
            wid = f"ws-{cell}"
            if wid not in registered:
                self.mc(
                    "workspace", "register", "--root", self.root, "--cell", cell,
                    "--workspace-id", wid, "--branch", f"mcv6/{cell.lower()}",
                    "--path", self.target_worktree(cell),
                )

    def complete_reference_to_accepted(self) -> None:
        self.accept_baseline()
        self.compile_reference()
        for cell_id in ("M000", "M001"):
            self.mc("dispatch", "--root", self.root, "--cell", cell_id)
            self.settle(cell_id)
        self.mc("barrier", "accept", "--root", self.root, "--cell", "G100")
        self.mc("integrate", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "I000")
        self.settle("I000")
        self.mc("qualify", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "Q000")
        self.settle("Q000")
        current = json.loads((self.root / "control" / "CURRENT_AUTHORITY.json").read_text(encoding="utf-8"))
        target_outcomes = [
            {"repository": repository, "baseline_sha": baseline, "accepted_head_sha": baseline}
            for repository, baseline in sorted(current["target_baselines"].items())
        ]
        qualification = {
            "schema": "flyby/mission-control-qualification/16",
            "outcome": "ACCEPTED",
            "summary": "Reference runtime-state qualification.",
            "evidence": [{"kind": "runtime-state", "value": "reference lifecycle accepted"}],
            "target_outcomes": target_outcomes,
            "requirement_accounting": {"accepted": ["REF-001"], "waived": []},
            "verification_accounting": {"run": list(self.packet("Q000")["acceptance"]), "waived": [], "not_run": []},
            "unresolved_defects": [],
            "explicit_limitations": [],
        }
        qualification_input = self.root / "qualification-accepted.json"
        write_json(qualification_input, qualification)
        self.mc("qualify", "--root", self.root, "--result", qualification_input)

    def reference_workspace_reconciliation(self) -> dict:
        payload = json.loads((EXAMPLE / "WORKSPACE_RECONCILIATION.json").read_text(encoding="utf-8"))
        payload["control_workspaces"][0]["evidence"][0]["sha256"] = sha256(self.root / "control" / "CURRENT_AUTHORITY.json")
        payload["target_repositories"][0]["accepted_head_sha"] = self.target_base_sha
        qualification_sha = sha256(self.root / "handoff" / "QUALIFICATION.json")
        empty_status_sha = hashlib.sha256(b"\n").hexdigest()
        for branch in payload["target_repositories"][0]["branches"]:
            cell = branch["workspace_id"].removeprefix("ws-")
            branch["head_sha"] = self.target_base_sha
            branch["worktree_path"] = str(self.target_worktree(cell).resolve())
            branch["dirty"] = False
            branch["semantic_status_sha256"] = empty_status_sha
            branch["remote_url"] = "https://example.invalid/target.git"
            branch["evidence"][0]["sha256"] = qualification_sha
        return payload

    def test_retry_is_attempt_scoped_and_rejects_late_result(self) -> None:
        self.accept_baseline()
        self.compile_reference()
        self.mc("dispatch", "--root", self.root, "--cell", "M000")
        self.settle("M000", "FAILED")
        first = self.state()["cells"]["M000"]
        self.assertEqual("FAILED", first["state"])
        self.assertEqual(1, first["attempt"])
        self.assertEqual(1, len(first["attempt_history"]))
        first_result = self.root / first["attempt_history"][0]["result_ref"]
        original_first = first_result.read_text(encoding="utf-8")

        self.mc("retry", "--root", self.root, "--cell", "M000")
        retried = self.state()["cells"]["M000"]
        self.assertEqual("COMPILED", retried["state"])
        self.assertEqual(2, retried["attempt"])
        self.assertEqual(1, len(retried["attempt_history"]))
        self.mc("dispatch", "--root", self.root, "--cell", "M000")

        stale_result = self.result("M000")
        stale_receipt = self.receipt("M000")
        stale = self.raw_settle(
            "M000", stale_result, stale_receipt, attempt=1, ok=False,
        )
        self.assertIn("late/stale settlement rejected", stale.stderr)
        self.assertEqual("DISPATCHED", self.state()["cells"]["M000"]["state"])

        self.settle("M000")
        accepted = self.state()["cells"]["M000"]
        self.assertEqual("ACCEPTED", accepted["state"])
        self.assertEqual([1, 2], [entry["attempt"] for entry in accepted["attempt_history"]])

        tampered = json.loads(original_first)
        tampered["summary"] = "tampered historical failed attempt"
        write_json(first_result, tampered)
        self.mc("doctor", "--root", self.root, ok=False)
        first_result.write_text(original_first, encoding="utf-8")
        self.mc("doctor", "--root", self.root)

    def test_settlement_resumes_after_residency_written_before_state(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "A000")
        result = self.result("A000")
        receipt = self.receipt("A000")
        adjudication = self.adjudication("A000", result, receipt, attempt=1)
        packet = self.packet("A000")
        evidence_root = self.root / "evidence" / "A000" / "attempt-0001"
        durable_result = evidence_root / "result.json"
        durable_receipt = evidence_root / "context_receipt.json"
        durable_adjudication = evidence_root / "adjudication.json"
        shutil.copyfile(result, durable_result) if evidence_root.exists() else evidence_root.mkdir(parents=True)
        if not durable_result.exists():
            shutil.copyfile(result, durable_result)
        shutil.copyfile(receipt, durable_receipt)
        shutil.copyfile(adjudication, durable_adjudication)
        receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
        binding = {
            "binding_id": "A000:attempt-0001",
            "worker_identity": receipt_value["worker"]["identity"],
            "provider": "UNSPECIFIED",
            "native_session_id": None,
            "native_session_state": "IDENTITY_UNAVAILABLE",
            "origin_cell": "A000",
            "origin_attempt": "attempt-0001",
            "target_repository": "CONTROL_ONLY",
            "target_base": packet["base_head"],
            "context_receipt_ref": "evidence/A000/attempt-0001/context_receipt.json",
            "context_receipt_hash": sha256(durable_receipt),
            "continuation_state": "NOT_REUSABLE",
            "provider_continuation_supported": None,
            "compaction_state": "NONE_RECORDED",
            "last_bound_cell": "A000",
            "remaining_context_budget_estimate": None,
            "last_observed_state": "UNKNOWN",
            "non_reuse_reason": receipt_value["continuation"]["reason"],
        }
        residency_path = self.root / "control" / "SESSION_RESIDENCY.json"
        residency = json.loads(residency_path.read_text(encoding="utf-8"))
        residency["records"].append(binding)
        write_json(residency_path, residency)
        self.assertEqual("DISPATCHED", self.state()["cells"]["A000"]["state"])

        self.mc(
            "settle", "--root", self.root, "--cell", "A000", "--attempt", 1,
            "--result", result, "--context-receipt", receipt, "--adjudication", adjudication,
        )
        self.assertEqual("ACCEPTED", self.state()["cells"]["A000"]["state"])
        self.mc("doctor", "--root", self.root)

    def test_compile_is_resumable_and_frontier_descriptor_is_immutable(self) -> None:
        self.accept_baseline()
        frontier = self.reference_frontier_payload()
        input_path = self.root / "reference-frontier.json"
        write_json(input_path, frontier)

        stored_path = self.root / "frontiers" / "F100" / "FRONTIER.json"
        write_json(stored_path, frontier)
        self.mc("doctor", "--root", self.root, ok=False)
        self.mc("compile", "--root", self.root, "--frontier", input_path)
        self.mc("doctor", "--root", self.root)

        stored_before = stored_path.read_text(encoding="utf-8")
        state_before = (self.root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8")
        changed = json.loads(json.dumps(frontier))
        changed["cells"][0]["objective"] += " changed"
        changed_path = self.root / "changed-frontier.json"
        write_json(changed_path, changed)
        rejected = self.mc("compile", "--root", self.root, "--frontier", changed_path, ok=False)
        self.assertIn("different immutable descriptor", rejected.stderr)
        self.assertEqual(stored_before, stored_path.read_text(encoding="utf-8"))
        self.assertEqual(state_before, (self.root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
        self.mc("doctor", "--root", self.root)

        cell = json.loads(json.dumps(frontier["cells"][0]))
        cell["cell_id"] = "M200"
        cell["objective"] = "Recover an interrupted frontier commit after the canonical DAG write."
        cell["conflict_class"] = "write:reference:m200"
        cell["resource_claims"] = ["reference-target-m200"]
        second = {"schema": "flyby/mission-control-frontier/16", "frontier_id": "F200", "cells": [cell]}
        second_path = self.root / "second-frontier.json"
        write_json(second_path, second)
        write_json(self.root / "frontiers" / "F200" / "FRONTIER.json", second)
        dag_path = self.root / "control" / "EXECUTION_DAG.json"
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
        dag["cells"].append(cell)
        dag["revision"] += 1
        write_json(dag_path, dag)
        broken = self.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("MC0177", broken.stderr)
        self.mc("compile", "--root", self.root, "--frontier", second_path)
        self.assertEqual("COMPILED", self.state()["cells"]["M200"]["state"])
        self.mc("doctor", "--root", self.root)

    def test_requirement_id_binding_without_acceptance_criteria_cannot_integrate(self) -> None:
        self.accept_baseline()
        frontier = self.reference_frontier_payload()
        frontier["cells"][0]["acceptance"] = ["typed mutation result is accepted"]
        frontier["cells"][1]["acceptance"] = ["second mutation is admitted only after the conflicting active mutation settles"]
        path = self.root / "missing-requirement-criteria-frontier.json"
        write_json(path, frontier)
        self.mc("compile", "--root", self.root, "--frontier", path)
        for cell_id in ("M000", "M001"):
            self.mc("workspace", "register", "--root", self.root, "--cell", cell_id,
                    "--workspace-id", f"ws-{cell_id}", "--branch", f"mcv6/{cell_id.lower()}",
                    "--path", self.target_worktree(cell_id))
        for cell_id in ("M000", "M001"):
            self.mc("dispatch", "--root", self.root, "--cell", cell_id)
            self.settle(cell_id)
        self.mc("barrier", "accept", "--root", self.root, "--cell", "G100")
        rejected = self.mc("integrate", "--root", self.root, ok=False)
        self.assertIn("acceptance criteria are not carried", rejected.stderr)
        self.assertEqual("MUTATION_READY", self.state()["lifecycle"])

    def test_post_baseline_barrier_cannot_infer_baseline_phase(self) -> None:
        self.accept_baseline()
        dag_path = self.root / "control" / "EXECUTION_DAG.json"
        state_path = self.root / "control" / "EXECUTION_STATE.json"
        before_dag = json.loads(dag_path.read_text(encoding="utf-8"))
        barrier = {
            "cell_id": "GDEAD",
            "kind": "BARRIER",
            "dependencies": ["G000"],
            "objective": "Demonstrate that post-baseline barriers cannot remain in baseline phase.",
            "acceptance": ["all dependencies are ACCEPTED"],
            "status": "PENDING",
            "conflict_class": "gate:dead-end-proof",
            "resource_claims": [],
        }
        frontier = {
            "schema": "flyby/mission-control-frontier/16",
            "frontier_id": "FDEAD",
            "cells": [barrier],
        }
        path = self.root / "dead-barrier-frontier.json"
        unverified_claim = json.loads(json.dumps(frontier))
        unverified_claim["frontier_id"] = "FCLAIM"
        unverified_claim["cells"][0]["cell_id"] = "GCLAIM"
        unverified_claim["cells"][0]["acceptance"] = ["manual signoff is complete"]
        claim_path = self.root / "barrier-unverified-claim.json"
        write_json(claim_path, unverified_claim)
        claim_rejected = self.mc("compile", "--root", self.root, "--frontier", claim_path, ok=False)
        self.assertIn("acceptance must be exactly", claim_rejected.stderr)
        self.assertFalse((self.root / "frontiers" / "FCLAIM" / "FRONTIER.json").exists())

        write_json(path, frontier)
        rejected = self.mc("compile", "--root", self.root, "--frontier", path, ok=False)
        self.assertIn("inferred phase is BASELINE", rejected.stderr)
        self.assertFalse((self.root / "frontiers" / "FDEAD" / "FRONTIER.json").exists())
        self.assertEqual(before_dag, json.loads(dag_path.read_text(encoding="utf-8")))
        self.assertEqual("BASELINE_ACCEPTED", self.state()["lifecycle"])

        drifted_dag = json.loads(json.dumps(before_dag))
        drifted_barrier = json.loads(json.dumps(barrier))
        drifted_barrier["acceptance"] = ["manual signoff is complete"]
        drifted_dag["cells"].append(drifted_barrier)
        drifted_dag["revision"] = int(drifted_dag["revision"]) + 1
        write_json(dag_path, drifted_dag)
        drifted_state = self.state()
        drifted_state["cells"]["GDEAD"] = {"state": "BLOCKED"}
        write_json(state_path, drifted_state)
        doctor = self.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("MC0259", doctor.stderr)
        self.assertIn("infers BASELINE phase", doctor.stderr)
        self.assertIn("MC0260", doctor.stderr)
        self.assertIn("non-topological acceptance clauses", doctor.stderr)

    def test_executable_cell_cannot_depend_on_later_phase(self) -> None:
        self.accept_baseline()
        source = self.reference_frontier_payload()
        mutation = json.loads(json.dumps(next(cell for cell in source["cells"] if cell["kind"] == "MUTATION")))
        integration = json.loads(json.dumps(next(cell for cell in source["cells"] if cell["kind"] == "INTEGRATION")))
        mutation["cell_id"] = "MREVERSE"
        mutation["dependencies"] = ["IREVERSE"]
        integration["cell_id"] = "IREVERSE"
        integration["dependencies"] = []
        frontier = {
            "schema": "flyby/mission-control-frontier/16",
            "frontier_id": "FREVERSE",
            "cells": [mutation, integration],
        }
        path = self.root / "reverse-phase-frontier.json"
        write_json(path, frontier)
        rejected = self.mc("compile", "--root", self.root, "--frontier", path, ok=False)
        self.assertIn("INVALID_PHASE_ORDER", rejected.stderr)
        self.assertIn("depends on later INTEGRATION authority", rejected.stderr)
        self.assertFalse((self.root / "frontiers" / "FREVERSE" / "FRONTIER.json").exists())
        self.assertEqual("BASELINE_ACCEPTED", self.state()["lifecycle"])

        dag_path = self.root / "control" / "EXECUTION_DAG.json"
        state_path = self.root / "control" / "EXECUTION_STATE.json"
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
        dag["cells"].extend([mutation, integration])
        dag["revision"] = int(dag["revision"]) + 1
        write_json(dag_path, dag)
        state = self.state()
        state["cells"]["MREVERSE"] = {"state": "PENDING"}
        state["cells"]["IREVERSE"] = {"state": "PENDING"}
        write_json(state_path, state)
        doctor = self.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("MC0261", doctor.stderr)
        self.assertIn("depends on later INTEGRATION authority", doctor.stderr)

    def test_dependency_phase_barrier_cannot_be_bypassed(self) -> None:
        self.accept_baseline()
        self.compile_reference()
        for cell_id in ("M000", "M001"):
            self.mc("dispatch", "--root", self.root, "--cell", cell_id)
            self.settle(cell_id)
        blocked = self.mc("integrate", "--root", self.root, ok=False)
        self.assertIn("G100", blocked.stderr)
        self.mc("barrier", "accept", "--root", self.root, "--cell", "G100")
        self.mc("integrate", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "Q000", ok=False)
        self.mc("dispatch", "--root", self.root, "--cell", "I000")
        self.settle("I000")
        self.mc("qualify", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "I000", ok=False)
        self.mc("dispatch", "--root", self.root, "--cell", "Q000")

    def test_result_and_receipt_contracts_reject_unknown_fields(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "A000")
        bad_result = self.result("A000", extra={"unexpected": True})
        self.raw_settle("A000", bad_result, self.receipt("A000"), attempt=1, ok=False)
        bad_receipt = self.receipt("A000", extra={"unexpected": True})
        self.raw_settle("A000", self.result("A000"), bad_receipt, attempt=1, ok=False)
        null_hash = self.receipt("A000", extra={"manifest_hash": None})
        self.raw_settle("A000", self.result("A000"), null_hash, attempt=1, ok=False)
        missing_required = self.receipt("A000", extra={"consumed": []})
        self.raw_settle("A000", self.result("A000"), missing_required, attempt=1, ok=False)
        unknown_context = self.receipt("A000")
        unknown_value = json.loads(unknown_context.read_text(encoding="utf-8"))
        unknown_value["consumed"].append("NOT_IN_MANIFEST")
        write_json(unknown_context, unknown_value)
        self.raw_settle("A000", self.result("A000"), unknown_context, attempt=1, ok=False)
        self.settle("A000")

    def test_independent_adjudication_controls_authoritative_state(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        same_custody = self.mc(
            "dispatch", "--root", self.root, "--cell", "A000",
            "--worker-identity", "same-custody", "--verifier-identity", "same-custody",
            ok=False,
        )
        self.assertIn("distinct worker and verifier identities", same_custody.stderr)
        self.mc("dispatch", "--root", self.root, "--cell", "A000")

        worker_accept = self.result("A000")
        receipt = self.receipt("A000")
        rejected = self.raw_settle(
            "A000", worker_accept, receipt, attempt=1, decision="REJECTED",
        )
        self.assertIn('"state": "REJECTED"', rejected.stdout)
        first = self.state()["cells"]["A000"]
        self.assertEqual("REJECTED", first["state"])
        self.assertEqual("ACCEPTED", json.loads((self.root / first["result_ref"]).read_text(encoding="utf-8"))["outcome"])

        self.mc("retry", "--root", self.root, "--cell", "A000")
        self.mc("dispatch", "--root", self.root, "--cell", "A000")
        result2 = self.result("A000")
        receipt2 = self.receipt("A000")
        substituted_worker_receipt = self.receipt(
            "A000",
            extra={"worker": {"identity": "substituted-worker", "session_id": None}},
        )
        substituted_worker = self.raw_settle(
            "A000", result2, substituted_worker_receipt, attempt=2, ok=False,
        )
        self.assertIn("worker identity must match dispatch assignment", substituted_worker.stderr)
        receipt2 = self.receipt("A000")
        substituted_verifier = self.raw_settle(
            "A000", result2, receipt2, attempt=2,
            verifier_identity="substituted-verifier", ok=False,
        )
        self.assertIn("verifier identity must match dispatch assignment", substituted_verifier.stderr)
        same_worker = self.raw_settle(
            "A000", result2, receipt2, attempt=2,
            verifier_identity="runtime-state-worker", ok=False,
        )
        self.assertIn("verifier identity must differ from worker identity", same_worker.stderr)
        wrong_hash = self.raw_settle(
            "A000", result2, receipt2, attempt=2,
            adjudication_extra={"result_sha256": "0" * 64}, ok=False,
        )
        self.assertIn("result_sha256 must bind", wrong_hash.stderr)
        missing_acceptance = self.raw_settle(
            "A000", result2, receipt2, attempt=2,
            adjudication_extra={"verified_acceptance": []}, ok=False,
        )
        self.assertIn("verified_acceptance must exactly cover", missing_acceptance.stderr)
        worker_failed = self.result("A000", "FAILED")
        cannot_upgrade = self.raw_settle(
            "A000", worker_failed, receipt2, attempt=2, decision="ACCEPTED", ok=False,
        )
        self.assertIn("ACCEPTED adjudication requires an ACCEPTED worker claim", cannot_upgrade.stderr)

        self.settle("A000", attempt=2)
        accepted = self.state()["cells"]["A000"]
        self.assertEqual("ACCEPTED", accepted["state"])
        adjudication_path = self.root / accepted["adjudication_ref"]
        original = adjudication_path.read_text(encoding="utf-8")
        tampered = json.loads(original)
        tampered["rationale"] = "tampered verifier rationale"
        write_json(adjudication_path, tampered)
        doctor = self.mc("doctor", "--root", self.root, ok=False)
        self.assertTrue("MC0256" in doctor.stderr or "MC0216" in doctor.stderr)
        adjudication_path.write_text(original, encoding="utf-8")
        self.mc("doctor", "--root", self.root)

    def test_hostile_frontier_identifiers_cannot_escape_mission_root(self) -> None:
        self.accept_baseline()
        frontier = self.reference_frontier_payload()
        frontier["frontier_id"] = "../ESCAPE"
        path = self.root / "hostile-frontier.json"
        write_json(path, frontier)
        self.mc("compile", "--root", self.root, "--frontier", path, ok=False)
        self.assertFalse((self.root.parent / "ESCAPE").exists())

        frontier["frontier_id"] = "FHOSTILE"
        frontier["cells"][0]["cell_id"] = "../CELL"
        write_json(path, frontier)
        self.mc("compile", "--root", self.root, "--frontier", path, ok=False)
        self.assertFalse((self.root.parent / "CELL.json").exists())

        frontier = self.reference_frontier_payload()
        frontier["frontier_id"] = "FHOSTILE"
        frontier["cells"][0]["target"]["owned_paths"] = ["../outside"]
        write_json(path, frontier)
        self.mc("compile", "--root", self.root, "--frontier", path, ok=False)

        frontier = self.reference_frontier_payload()
        frontier["frontier_id"] = "CON"
        write_json(path, frontier)
        reserved_frontier = self.mc("compile", "--root", self.root, "--frontier", path, ok=False)
        self.assertIn("frontier_id", reserved_frontier.stderr)

        frontier = self.reference_frontier_payload()
        frontier["frontier_id"] = "FRESERVED"
        frontier["cells"][0]["cell_id"] = "NUL"
        write_json(path, frontier)
        reserved_cell = self.mc("compile", "--root", self.root, "--frontier", path, ok=False)
        self.assertIn("cell_id", reserved_cell.stderr)

    def test_doctor_fails_closed_on_reference_escape(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        state_path = self.root / "control" / "EXECUTION_STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["cells"]["A000"]["workcell_ref"] = "../../outside.json"
        write_json(state_path, state)
        proc = self.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("MC0101", proc.stderr)
        self.assertIn("escapes root", proc.stderr)

    def test_init_rejects_duplicate_targets_and_partial_generated_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcv16-invalid-init-") as tmp:
            duplicate_root = Path(tmp) / "duplicate"
            duplicate_root.mkdir()
            mission = json.loads((EXAMPLE / "MISSION.json").read_text(encoding="utf-8"))
            second = dict(mission["target_repositories"][0])
            second["baseline_sha"] = "1" * 40
            mission["target_repositories"].append(second)
            write_json(duplicate_root / "MISSION.json", mission)
            self._run(SOURCE_MC, "init", "--mission", duplicate_root / "MISSION.json", ok=False)
            self.assertFalse((duplicate_root / "control").exists())

            partial_root = Path(tmp) / "partial"
            partial_root.mkdir()
            shutil.copy2(EXAMPLE / "MISSION.json", partial_root / "MISSION.json")
            (partial_root / "evidence").mkdir()
            self._run(SOURCE_MC, "init", "--mission", partial_root / "MISSION.json", ok=False)
            self.assertFalse((partial_root / "control").exists())

    def test_doctor_rejects_aggregate_state_drift(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        state_path = self.root / "control" / "EXECUTION_STATE.json"
        original = state_path.read_text(encoding="utf-8")

        state = json.loads(original)
        state["frontier"]["compiled"].remove("A000")
        write_json(state_path, state)
        self.mc("doctor", "--root", self.root, ok=False)

        state = json.loads(original)
        state["lifecycle"] = "BASELINE_ACCEPTED"
        write_json(state_path, state)
        self.mc("doctor", "--root", self.root, ok=False)

        state_path.write_text(original, encoding="utf-8")
        self.mc("doctor", "--root", self.root)

    def test_retry_is_phase_aware_for_integration_and_qualification(self) -> None:
        self.accept_baseline()
        self.compile_reference()
        for cell_id in ("M000", "M001"):
            self.mc("dispatch", "--root", self.root, "--cell", cell_id)
            self.settle(cell_id)
        self.mc("barrier", "accept", "--root", self.root, "--cell", "G100")
        self.mc("integrate", "--root", self.root)

        self.mc("dispatch", "--root", self.root, "--cell", "I000")
        self.settle("I000", "FAILED")
        self.mc("retry", "--root", self.root, "--cell", "I000")
        self.assertEqual(2, self.state()["cells"]["I000"]["attempt"])
        self.mc("dispatch", "--root", self.root, "--cell", "I000")
        self.settle("I000")

        self.mc("qualify", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "Q000")
        self.settle("Q000", "FAILED")
        self.mc("retry", "--root", self.root, "--cell", "Q000")
        self.assertEqual(2, self.state()["cells"]["Q000"]["attempt"])
        self.mc("dispatch", "--root", self.root, "--cell", "Q000")
        self.settle("Q000")
        self.mc("doctor", "--root", self.root)

    def test_concurrent_dispatches_preserve_all_canonical_transitions(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        processes = [
            subprocess.Popen(
                [sys.executable, str(self.runtime), "dispatch", "--root", str(self.root), "--cell", cell_id,
                 "--worker-identity", f"runtime-state-worker-{cell_id}",
                 "--verifier-identity", f"runtime-state-verifier-{cell_id}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for cell_id in BASELINE
        ]
        results = [(*process.communicate(), process.returncode) for process in processes]
        failures = [result for result in results if result[2] != 0]
        self.assertEqual([], failures, failures)
        state = self.state()
        self.assertEqual(set(BASELINE), set(state["frontier"]["dispatched"]))
        self.assertTrue(all(state["cells"][cell_id]["state"] == "DISPATCHED" for cell_id in BASELINE))
        self.mc("doctor", "--root", self.root)

    def test_template_lock_asset_reference_cannot_escape_mission_root(self) -> None:
        lock_path = self.root / "TEMPLATE_LOCK.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["assets"]["../../outside.txt"] = "0" * 64
        write_json(lock_path, lock)
        proc = self.mc("doctor", "--root", self.root, ok=False)
        self.assertTrue("unsafe" in proc.stderr.lower() or "MC0101" in proc.stderr)

    def test_doctor_binds_frontier_and_corpus_provenance(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        frontier_path = self.root / "frontiers" / "F000" / "FRONTIER.json"
        original_frontier = frontier_path.read_text(encoding="utf-8")
        frontier = json.loads(original_frontier)
        frontier["cells"][0]["objective"] = "tampered authored objective"
        write_json(frontier_path, frontier)
        self.mc("doctor", "--root", self.root, ok=False)
        frontier_path.write_text(original_frontier, encoding="utf-8")
        self.mc("doctor", "--root", self.root)

        corpus_path = self.root / "corpus" / "TARGET_MUTATIONS.json"
        original_corpus = corpus_path.read_text(encoding="utf-8")
        corpus = json.loads(original_corpus)
        corpus["mission_id"] = "FOREIGN-MISSION"
        write_json(corpus_path, corpus)
        self.mc("doctor", "--root", self.root, ok=False)
        corpus_path.write_text(original_corpus, encoding="utf-8")

        source_path = self.root / "corpus" / "SOURCES.json"
        original_sources = source_path.read_text(encoding="utf-8")
        sources = json.loads(original_sources)
        sources["mission_id"] = "FOREIGN-MISSION"
        write_json(source_path, sources)
        self.mc("doctor", "--root", self.root, ok=False)
        source_path.write_text(original_sources, encoding="utf-8")
        self.mc("doctor", "--root", self.root)

    def test_init_rejects_control_target_custody_collision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcv16-custody-") as tmp:
            root = Path(tmp) / "collision"
            root.mkdir()
            mission = json.loads((EXAMPLE / "MISSION.json").read_text(encoding="utf-8"))
            mission["control_repository"] = mission["target_repositories"][0]["repository"]
            write_json(root / "MISSION.json", mission)
            self._run(SOURCE_MC, "init", "--mission", root / "MISSION.json", ok=False)
            self.assertFalse((root / "control").exists())

    def test_semantic_input_loads_are_transactional_and_freeze_after_baseline(self) -> None:
        corpus_path = self.root / "corpus" / "TARGET_MUTATIONS.json"
        corpus_before = corpus_path.read_bytes()
        bad_corpus = json.loads((EXAMPLE / "TARGET_CORPUS.json").read_text(encoding="utf-8"))
        bad_corpus["requirements"][0]["sources"] = ["missing-source"]
        bad_corpus_path = self.root / "bad-corpus.json"
        write_json(bad_corpus_path, bad_corpus)
        rolled_back = self.mc("corpus", "load", "--root", self.root, "--file", bad_corpus_path, ok=False)
        self.assertIn("LOAD_ROLLED_BACK", rolled_back.stderr)
        self.assertEqual(corpus_before, corpus_path.read_bytes())

        bad_target_corpus = json.loads((EXAMPLE / "TARGET_CORPUS.json").read_text(encoding="utf-8"))
        bad_target_corpus["requirements"][0]["targets"] = ["example/outside-mission"]
        bad_target_path = self.root / "bad-target-corpus.json"
        write_json(bad_target_path, bad_target_corpus)
        rejected_target = self.mc("corpus", "load", "--root", self.root, "--file", bad_target_path, ok=False)
        self.assertIn("repositories outside mission authority", rejected_target.stderr)
        self.assertEqual(corpus_before, corpus_path.read_bytes())

        sources_path = self.root / "corpus" / "SOURCES.json"
        sources_before = sources_path.read_bytes()
        bad_sources = json.loads((EXAMPLE / "SOURCES.json").read_text(encoding="utf-8"))
        bad_sources["sources"].append({
            "id": "repo-unpinned",
            "kind": "REPOSITORY",
            "locator": "example/unpinned",
            "role": "hostile unpinned donor"
        })
        bad_sources_path = self.root / "bad-sources.json"
        write_json(bad_sources_path, bad_sources)
        rolled_back = self.mc("sources", "load", "--root", self.root, "--file", bad_sources_path, ok=False)
        self.assertIn("LOAD_ROLLED_BACK", rolled_back.stderr)
        self.assertEqual(sources_before, sources_path.read_bytes())

        self.mc("baseline", "compile", "--root", self.root)
        frozen = self.mc("sources", "load", "--root", self.root, "--file", EXAMPLE / "SOURCES.json", ok=False)
        self.assertIn("only before baseline compilation", frozen.stderr)
        frozen_corpus = self.mc("corpus", "load", "--root", self.root, "--file", EXAMPLE / "TARGET_CORPUS.json", ok=False)
        self.assertIn("only before baseline compilation", frozen_corpus.stderr)

    def test_mutation_requirement_target_scope_cannot_escape_frozen_corpus(self) -> None:
        self.accept_baseline()
        frontier = self.reference_frontier_payload()
        frontier["frontier_id"] = "FTARGETSCOPE"
        frontier["cells"] = [json.loads(json.dumps(frontier["cells"][0]))]
        frontier["cells"][0]["cell_id"] = "MTARGETSCOPE"
        frontier["cells"][0]["target"]["repository"] = "example/outside-requirement"
        path = self.root / "wrong-requirement-target-frontier.json"
        write_json(path, frontier)
        rejected = self.mc("compile", "--root", self.root, "--frontier", path, ok=False)
        self.assertIn("requirement REF-001 is scoped to repositories ['example/target']", rejected.stderr)
        self.assertFalse((self.root / "frontiers" / "FTARGETSCOPE" / "FRONTIER.json").exists())

        corpus_path = self.root / "corpus" / "TARGET_MUTATIONS.json"
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        corpus["requirements"][0]["targets"] = ["example/outside-mission"]
        write_json(corpus_path, corpus)
        doctor = self.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("MC0262", doctor.stderr)
        self.assertIn("repositories outside mission authority", doctor.stderr)

    def test_final_qualification_head_must_equal_integrated_head(self) -> None:
        self.accept_baseline()
        self.compile_reference()
        for cell_id in ("M000", "M001"):
            self.mc("dispatch", "--root", self.root, "--cell", cell_id)
            self.settle(cell_id)
        self.mc("barrier", "accept", "--root", self.root, "--cell", "G100")
        self.mc("integrate", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "I000")

        incomplete_integration = self.result("I000")
        incomplete_value = json.loads(incomplete_integration.read_text(encoding="utf-8"))
        incomplete_value["integrated_mutations"] = incomplete_value["integrated_mutations"][:-1]
        write_json(incomplete_integration, incomplete_value)
        incomplete_receipt = self.receipt("I000")
        incomplete = self.raw_settle("I000", incomplete_integration, incomplete_receipt, attempt=1, ok=False)
        self.assertIn("must exactly bind accepted mutation cells", incomplete.stderr)

        wrong_integration = self.result("I000")
        wrong_value = json.loads(wrong_integration.read_text(encoding="utf-8"))
        wrong_value["integrated_mutations"][0]["head_sha"] = "d" * 40
        write_json(wrong_integration, wrong_value)
        wrong_receipt = self.receipt("I000")
        wrong = self.raw_settle("I000", wrong_integration, wrong_receipt, attempt=1, ok=False)
        self.assertIn("must exactly match its accepted mutation result head", wrong.stderr)

        self.settle("I000")
        self.mc("qualify", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "Q000")

        current = json.loads((self.root / "control" / "CURRENT_AUTHORITY.json").read_text(encoding="utf-8"))
        repository, baseline = next(iter(current["target_baselines"].items()))
        divergent_head = "f" * 40 if baseline != "f" * 40 else "e" * 40
        q_result = self.result("Q000", extra={
            "target_outcomes": [{
                "repository": repository,
                "baseline_sha": baseline,
                "head_sha": divergent_head,
            }]
        })
        q_receipt = self.receipt("Q000")
        q_rejected = self.raw_settle("Q000", q_result, q_receipt, attempt=1, ok=False)
        self.assertIn("must equal accepted INTEGRATION head", q_rejected.stderr)
        self.assertEqual("DISPATCHED", self.state()["cells"]["Q000"]["state"])
        self.settle("Q000")

        qualification = {
            "schema": "flyby/mission-control-qualification/16",
            "outcome": "ACCEPTED",
            "summary": "Hostile qualification tries to replace the integrated head.",
            "evidence": [{"kind": "runtime-state", "value": "phase-head-lineage negative proof"}],
            "target_outcomes": [{
                "repository": repository,
                "baseline_sha": baseline,
                "accepted_head_sha": divergent_head,
            }],
            "requirement_accounting": {"accepted": ["REF-001"], "waived": []},
            "verification_accounting": {
                "run": list(self.packet("Q000")["acceptance"]),
                "waived": [],
                "not_run": [],
            },
            "unresolved_defects": [],
            "explicit_limitations": [],
        }
        path = self.root / "qualification-divergent-head.json"
        write_json(path, qualification)
        rejected = self.mc("qualify", "--root", self.root, "--result", path, ok=False)
        self.assertIn("accepted_head_sha is not proven by accepted QUALIFICATION cell evidence", rejected.stderr)
        self.assertEqual("QUALIFYING", self.state()["lifecycle"])

    def test_frozen_requirement_waiver_needs_no_mutation_but_must_match_final_accounting(self) -> None:
        corpus = json.loads((EXAMPLE / "TARGET_CORPUS.json").read_text(encoding="utf-8"))
        corpus["requirements"].append({
            "id": "REF-002",
            "name": "Explicitly waived reference requirement",
            "sources": ["owner-intent"],
            "targets": ["example/target"],
            "acceptance": ["waiver is frozen before baseline compilation"],
            "waiver": {
                "reason": "Synthetic requirement is intentionally outside the reference mutation scope.",
                "authority": "reference-owner"
            }
        })
        corpus_path = self.root / "waived-corpus.json"
        write_json(corpus_path, corpus)
        self.mc("corpus", "load", "--root", self.root, "--file", corpus_path)
        self.accept_baseline()

        illegal = self.reference_frontier_payload()
        illegal["frontier_id"] = "FWAIVED"
        illegal["cells"] = [json.loads(json.dumps(illegal["cells"][0]))]
        illegal["cells"][0]["cell_id"] = "MWAIVED"
        illegal["cells"][0]["requirement_ids"] = ["REF-002"]
        illegal["cells"][0]["conflict_class"] = "write:waived"
        illegal["cells"][0]["resource_claims"] = ["waived-reference-target"]
        illegal_path = self.root / "illegal-waived-frontier.json"
        write_json(illegal_path, illegal)
        rejected = self.mc("compile", "--root", self.root, "--frontier", illegal_path, ok=False)
        self.assertIn("frozen waived requirements", rejected.stderr)

        self.compile_reference()
        for cell_id in ("M000", "M001"):
            self.mc("dispatch", "--root", self.root, "--cell", cell_id)
            self.settle(cell_id)
        self.mc("barrier", "accept", "--root", self.root, "--cell", "G100")
        self.mc("integrate", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "I000")
        self.settle("I000")
        self.mc("qualify", "--root", self.root)
        self.mc("dispatch", "--root", self.root, "--cell", "Q000")
        self.settle("Q000")

        current = json.loads((self.root / "control" / "CURRENT_AUTHORITY.json").read_text(encoding="utf-8"))
        target_outcomes = [
            {"repository": repository, "baseline_sha": baseline, "accepted_head_sha": baseline}
            for repository, baseline in sorted(current["target_baselines"].items())
        ]
        proven_verifications = list(self.packet("Q000")["acceptance"])
        qualification = {
            "schema": "flyby/mission-control-qualification/16",
            "outcome": "ACCEPTED",
            "summary": "Reference qualification with a frozen pre-baseline waiver.",
            "evidence": [{"kind": "runtime-state", "value": "waiver accounting verified"}],
            "target_outcomes": target_outcomes,
            "requirement_accounting": {
                "accepted": ["REF-001"],
                "waived": [{
                    "requirement_id": "REF-002",
                    "reason": "Synthetic requirement is intentionally outside the reference mutation scope.",
                    "authority": "reference-owner"
                }]
            },
            "verification_accounting": {"run": proven_verifications, "waived": [], "not_run": []},
            "unresolved_defects": [],
            "explicit_limitations": ["REF-002 was explicitly waived before baseline compilation."]
        }
        missing_waiver = json.loads(json.dumps(qualification))
        missing_waiver["requirement_accounting"]["waived"] = []
        missing_path = self.root / "qualification-missing-waiver.json"
        write_json(missing_path, missing_waiver)
        rejected = self.mc("qualify", "--root", self.root, "--result", missing_path, ok=False)
        self.assertIn("frozen corpus waivers", rejected.stderr)

        changed_waiver = json.loads(json.dumps(qualification))
        changed_waiver["requirement_accounting"]["waived"][0]["reason"] = "late rewritten reason"
        changed_path = self.root / "qualification-changed-waiver.json"
        write_json(changed_path, changed_waiver)
        rejected = self.mc("qualify", "--root", self.root, "--result", changed_path, ok=False)
        self.assertIn("must exactly match frozen corpus", rejected.stderr)

        qualification_path = self.root / "qualification-waiver.json"
        write_json(qualification_path, qualification)
        self.mc("qualify", "--root", self.root, "--result", qualification_path)
        self.assertEqual("ACCEPTED", self.state()["lifecycle"])

    def test_baseline_compile_requires_nonempty_target_corpus(self) -> None:
        write_json(self.root / "corpus" / "TARGET_MUTATIONS.json", {
            "schema": "flyby/mission-control-target-corpus/16",
            "mission_id": "REFERENCE-MCV16",
            "provenance_materialization": {
                "mode": "TARGET_HAS_NO_LINEAGE_MANIFEST",
                "target_refs": [],
                "coverage_requirement_id": None,
                "validation_schema_ref": None,
                "authority": "LINEAGE_ONLY",
                "acceptance": ["Synthetic empty-corpus fixture explicitly has no target lineage manifest."]
            },
            "requirements": []
        })
        rejected = self.mc("baseline", "compile", "--root", self.root, ok=False)
        self.assertIn("non-empty target corpus", rejected.stderr)
        self.assertEqual("BOOTSTRAPPED", self.state()["lifecycle"])
        self.assertEqual("PENDING", self.state()["cells"]["A000"]["state"])
        self.assertEqual("BLOCKED", self.state()["cells"]["G000"]["state"])

        all_waived = json.loads((EXAMPLE / "TARGET_CORPUS.json").read_text(encoding="utf-8"))
        all_waived["requirements"][0]["waiver"] = {
            "reason": "Synthetic all-waived mission has no executable mutation work.",
            "authority": "reference-owner"
        }
        write_json(self.root / "corpus" / "TARGET_MUTATIONS.json", all_waived)
        rejected = self.mc("baseline", "compile", "--root", self.root, ok=False)
        self.assertIn("at least one active non-waived target requirement", rejected.stderr)
        self.assertEqual("BOOTSTRAPPED", self.state()["lifecycle"])

    def test_bootstrap_invalid_status_blocks_transitions_and_has_pristine_recovery(self) -> None:
        current_path = self.root / "control" / "CURRENT_AUTHORITY.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["status"] = "BOOTSTRAP_INVALID"
        write_json(current_path, current)
        write_json(self.root / "control" / "BOOTSTRAP_INVALID.json", {"issues": [{"code": "synthetic"}]})

        doctor = self.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("MC0250", doctor.stderr)
        blocked = self.mc("baseline", "compile", "--root", self.root, ok=False)
        self.assertIn("MC0250", blocked.stderr)

        repaired = self.source(
            "repair", "bootstrap", "--root", self.root,
            "--template-root", ROOT,
        )
        self.assertIn("GENERATED_BOOTSTRAP_ASSETS_AND_INVALID_STATUS", repaired.stdout)
        self.assertFalse((self.root / "control" / "BOOTSTRAP_INVALID.json").exists())
        self.assertEqual("BOOTSTRAPPED", json.loads(current_path.read_text(encoding="utf-8"))["status"])
        self.mc("doctor", "--root", self.root)

    def test_bootstrap_invalid_recovery_refuses_nonpristine_execution(self) -> None:
        self.mc("baseline", "compile", "--root", self.root)
        current_path = self.root / "control" / "CURRENT_AUTHORITY.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["status"] = "BOOTSTRAP_INVALID"
        write_json(current_path, current)
        write_json(self.root / "control" / "BOOTSTRAP_INVALID.json", {"issues": [{"code": "synthetic"}]})
        rejected = self.source(
            "repair", "bootstrap", "--root", self.root,
            "--template-root", ROOT, ok=False,
        )
        self.assertIn("REPAIR_BLOCKED", rejected.stderr)
        self.assertIn("lifecycle advanced", rejected.stderr)
        self.assertEqual("BOOTSTRAP_INVALID", json.loads(current_path.read_text(encoding="utf-8"))["status"])

    def test_bootstrap_repair_removes_unlocked_generated_assets(self) -> None:
        stale = self.root / "runtime" / "tools" / "stale_helper.py"
        stale.write_text("print('stale')\n", encoding="utf-8")
        doctor = self.mc("doctor", "--root", self.root, ok=False)
        self.assertIn("MC0255", doctor.stderr)
        repaired = self.source(
            "repair", "bootstrap", "--root", self.root,
            "--template-root", ROOT,
        )
        self.assertIn("GENERATED_BOOTSTRAP_ASSETS_ONLY", repaired.stdout)
        self.assertFalse(stale.exists())
        self.mc("doctor", "--root", self.root)

    def test_bootstrap_repair_restores_only_generated_assets(self) -> None:
        control_paths = [
            self.root / "control" / name
            for name in (
                "CURRENT_AUTHORITY.json", "EXECUTION_DAG.json", "EXECUTION_STATE.json",
                "COMPILER_CONTROL.json", "SESSION_RESIDENCY.json", "WORKSPACE_LEDGER.json",
            )
        ]
        control_before = {path: path.read_bytes() for path in control_paths}
        policy = self.root / "contracts" / "policies" / "CONTROL_LAWS.md"
        policy.write_text(policy.read_text(encoding="utf-8") + "\nTAMPERED\n", encoding="utf-8")
        self.mc("doctor", "--root", self.root, ok=False)

        repaired = self.source(
            "repair", "bootstrap", "--root", self.root,
            "--template-root", ROOT,
        )
        self.assertIn("GENERATED_BOOTSTRAP_ASSETS_ONLY", repaired.stdout)
        self.assertNotIn("TAMPERED", policy.read_text(encoding="utf-8"))
        for path, original in control_before.items():
            self.assertEqual(original, path.read_bytes(), path.name)
        self.mc("doctor", "--root", self.root)

    def test_bootstrap_repair_rolls_back_when_control_is_invalid(self) -> None:
        policy = self.root / "contracts" / "policies" / "CONTROL_LAWS.md"
        policy.write_text(policy.read_text(encoding="utf-8") + "\nKEEP-ON-ROLLBACK\n", encoding="utf-8")
        lock_path = self.root / "TEMPLATE_LOCK.json"
        lock_before = lock_path.read_bytes()
        policy_before = policy.read_bytes()
        current_path = self.root / "control" / "CURRENT_AUTHORITY.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["execution_dag"] = "control/WRONG.json"
        write_json(current_path, current)
        current_before = current_path.read_bytes()

        failed = self.source(
            "repair", "bootstrap", "--root", self.root,
            "--template-root", ROOT, ok=False,
        )
        self.assertIn("REPAIR_ROLLED_BACK", failed.stderr)
        self.assertEqual(policy_before, policy.read_bytes())
        self.assertEqual(lock_before, lock_path.read_bytes())
        self.assertEqual(current_before, current_path.read_bytes())

    def test_bootstrap_repair_refuses_template_upgrade(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcv16-repair-upgrade-") as tmp:
            alternate = Path(tmp) / "mission-control-template"
            shutil.copytree(ROOT, alternate)
            policy = alternate / "policies" / "CONTROL_LAWS.md"
            policy.write_text(policy.read_text(encoding="utf-8") + "\nUNLOCKED-UPGRADE\n", encoding="utf-8")
            mission_before = {
                path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            }
            blocked = self.source(
                "repair", "bootstrap", "--root", self.root,
                "--template-root", alternate, ok=False,
            )
            self.assertIn("cannot perform a template upgrade", blocked.stderr)
            mission_after = {
                path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(mission_before, mission_after)

    def test_bootstrap_repair_refuses_missing_template_lock(self) -> None:
        lock_path = self.root / "TEMPLATE_LOCK.json"
        lock_path.unlink()
        policy = self.root / "contracts" / "policies" / "CONTROL_LAWS.md"
        policy.write_text(policy.read_text(encoding="utf-8") + "\nMUST-NOT-BE-REPAIRED\n", encoding="utf-8")
        policy_before = policy.read_bytes()
        blocked = self.source(
            "repair", "bootstrap", "--root", self.root,
            "--template-root", ROOT, ok=False,
        )
        self.assertIn("cannot prove which template bytes are authoritative", blocked.stderr)
        self.assertFalse(lock_path.exists())
        self.assertEqual(policy_before, policy.read_bytes())

    def test_bootstrap_repair_refuses_non_v16_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcv16-repair-guard-") as tmp:
            legacy = Path(tmp) / "legacy"
            (legacy / "control").mkdir(parents=True)
            write_json(legacy / "control" / "CURRENT_AUTHORITY.json", {"schema": "flyby/mcv6-current-authority/2"})
            self._run(
                SOURCE_MC, "repair", "bootstrap", "--root", legacy,
                "--template-root", ROOT, ok=False,
            )
            self.assertFalse((legacy / "runtime").exists())
            self.assertFalse((legacy / "TEMPLATE_LOCK.json").exists())

    def test_candidate9_workspace_register_git_custody_and_dirty_state_rejection(self) -> None:
        self.accept_baseline()
        frontier = self.reference_frontier()
        self.mc("compile", "--root", self.root, "--frontier", frontier)
        target_dir = self.target_worktree("M000")

        (target_dir / "dirty.txt").write_text("uncommitted dirty file", encoding="utf-8")
        dirty_proc = self.mc("workspace", "register", "--root", self.root, "--cell", "M000", "--workspace-id", "ws-dirty", "--branch", "mcv6/m000", "--path", str(target_dir), ok=False)
        self.assertIn("must be clean", dirty_proc.stderr)
        (target_dir / "dirty.txt").unlink()

        subprocess.run(["git", "-C", str(target_dir), "checkout", "-b", "wrong-branch"], check=True, capture_output=True, text=True)
        branch_proc = self.mc("workspace", "register", "--root", self.root, "--cell", "M000", "--workspace-id", "ws-branch", "--branch", "mcv6/m000", "--path", str(target_dir), ok=False)
        self.assertIn("branch mismatch", branch_proc.stderr)
        subprocess.run(["git", "-C", str(target_dir), "checkout", "mcv6/m000"], check=True, capture_output=True, text=True)

        (target_dir / "new.txt").write_text("new commit", encoding="utf-8")
        subprocess.run(["git", "-C", str(target_dir), "add", "."], check=True)
        subprocess.run(["git", "-C", str(target_dir), "commit", "-m", "advance"], check=True, capture_output=True, text=True)
        head_proc = self.mc("workspace", "register", "--root", self.root, "--cell", "M000", "--workspace-id", "ws-head", "--branch", "mcv6/m000", "--path", str(target_dir), ok=False)
        self.assertIn("exact compiled base", head_proc.stderr)

    def test_candidate9_mechanism_source_omitted_from_requirement_rejected(self) -> None:
        corpus = json.loads((EXAMPLE / "TARGET_CORPUS.json").read_text(encoding="utf-8"))
        requirement = corpus["requirements"][0]
        self.assertIn("reference-method", requirement["sources"])
        requirement["sources"] = [sid for sid in requirement["sources"] if sid != "reference-method"]
        corpus_file = self.root / "omitted-source-corpus.json"
        write_json(corpus_file, corpus)
        rejected = self.mc("corpus", "load", "--root", self.root, "--file", corpus_file, ok=False)
        self.assertIn("MC0351", rejected.stderr)
    def test_candidate9_rejected_mechanism_bidirectional_closure(self) -> None:
        prov = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        prov["mechanisms"][0]["disposition"] = "REJECTED"
        prov["mechanisms"][0]["rejection_reason"] = "Rejected during review"
        prov["mechanisms"][0]["target_requirements"] = ["REF-001"]
        prov_file = self.root / "rejected-mech-target.json"
        write_json(prov_file, prov)
        proc = self.mc("provenance", "load", "--root", self.root, "--file", prov_file, ok=False)
        self.assertIn("MC0350", proc.stderr)

        prov["mechanisms"][0]["target_requirements"] = []
        write_json(prov_file, prov)
        proc2 = self.mc("provenance", "load", "--root", self.root, "--file", prov_file, ok=False)
        self.assertIn("MC0352", proc2.stderr)

    def test_candidate9_independent_review_receipt_and_custody_enforced(self) -> None:
        prov = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        prov["source_assessments"][0]["independent_review"]["reviewer"] = "reference-golden-reviewer"
        prov["source_assessments"][0]["independent_review"]["reviewer_identity"] = "reference-golden-reviewer"
        prov["source_assessments"][0]["independent_review"]["extractor_identity"] = "reference-golden-reviewer"
        prov_file = self.root / "same-custody-prov.json"
        write_json(prov_file, prov)
        proc = self.mc("provenance", "load", "--root", self.root, "--file", prov_file, ok=False)
        self.assertIn("MC0355", proc.stderr)

        prov["source_assessments"][0]["independent_review"]["reviewer"] = "reference-golden-verifier"
        prov["source_assessments"][0]["independent_review"]["reviewer_identity"] = "reference-golden-verifier"
        prov["source_assessments"][0]["independent_review"]["extractor_identity"] = "reference-golden-reviewer"
        prov["source_assessments"][0]["independent_review"]["review_ref"] = "evidence/reviews/nonexistent.json"
        write_json(prov_file, prov)
        proc2 = self.mc("provenance", "load", "--root", self.root, "--file", prov_file, ok=False)
        self.assertIn("MC0357", proc2.stderr)

    def test_candidate9_superseded_evidence_typed_hash_authority_enforced(self) -> None:
        self.complete_reference_to_accepted()
        old_evidence = self.root / "historical" / "old-evidence.json"
        write_json(old_evidence, {"schema":"historical-evidence/1","claim":"superseded candidate"})
        recon = self.reference_workspace_reconciliation()
        recon["historical_material"].append({
            "ref": old_evidence.relative_to(self.root).as_posix(),
            "sha256": sha256(old_evidence),
            "disposition": "SUPERSEDED_EVIDENCE",
            "supersession_ref": "historical/nonexistent-supersession.json",
            "supersession_sha256": "1" * 64,
        })
        recon_file = self.root / "superseded-missing.json"
        write_json(recon_file, recon)
        proc = self.mc("workspace", "load", "--root", self.root, "--file", recon_file, ok=False)
        self.assertIn("historical supersession ref missing", proc.stderr)
    def test_candidate9_workspace_load_short_circuits_schema_errors(self) -> None:
        malformed = {"schema": "wrong-schema", "not_a_valid_field": 123}
        malformed_file = self.root / "malformed-workspace.json"
        write_json(malformed_file, malformed)
        proc = self.mc("workspace", "load", "--root", self.root, "--file", malformed_file, ok=False)
        self.assertIn("REJECTED", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
    def test_candidate9_previous_mission_handoff_pin_and_digest_enforced(self) -> None:
        mission_payload = json.loads((EXAMPLE / "MISSION.json").read_text(encoding="utf-8"))
        mission_payload["previous_mission_handoff_sha256"] = "f" * 64
        mission_file = self.root / "bad-pin-mission.json"
        write_json(mission_file, mission_payload)
        with tempfile.TemporaryDirectory(prefix="mcv16-bad-pin-") as bad_tmp:
            bad_root = Path(bad_tmp) / "mission"
            bad_root.mkdir()
            shutil.copy2(mission_file, bad_root / "MISSION.json")
            proc = self.source("init", "--mission", bad_root / "MISSION.json", ok=False)
            self.assertIn("previous_mission_handoff_sha256", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
