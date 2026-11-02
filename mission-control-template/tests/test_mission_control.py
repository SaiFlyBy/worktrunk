#!/usr/bin/env python3
"""Reusable Mission Control structural suite.

Run against any supported Mission Control root:
  python test_mission_control.py --mission-root <root>

Canonical v16 and the live v15-derived MCV6 layout are intentionally separate
adapters. Legacy compatibility never relaxes canonical-v16 invariants.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

MISSION_ROOT: Path | None = None


def _load_mc():
    tools = Path(__file__).resolve().parents[1] / "tools" / "mc.py"
    spec = importlib.util.spec_from_file_location("mission_control_mc", tools)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {tools}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load_mc()


class MissionControlSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if MISSION_ROOT is None:
            raise RuntimeError("--mission-root is required")
        cls.root = MISSION_ROOT.resolve()
        cls.layout = mc.detect_layout(cls.root)

    def test_01_layout_is_explicitly_supported(self) -> None:
        self.assertIn(self.layout, {"v16", "mcv6-legacy"}, f"unsupported layout: {self.layout}")

    def test_02_all_json_documents_parse(self) -> None:
        failures: list[str] = []
        for path in sorted(self.root.rglob("*.json")):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - diagnostic aggregation
                failures.append(f"{path.relative_to(self.root)}: {exc}")
        self.assertFalse(failures, "invalid JSON documents:\n" + "\n".join(failures))

    def test_03_structural_doctor_is_clean(self) -> None:
        issues = mc.collect_mission_issues(self.root)
        rendered = "\n".join(f"{x['code']}: {x['message']}" for x in issues)
        self.assertEqual([], issues, rendered)

    def test_04_canonical_graph_is_acyclic_and_closed(self) -> None:
        if self.layout == "v16":
            dag = mc.load_json(self.root / "control" / "EXECUTION_DAG.json")
            errors = mc._generic_graph_issues(dag["cells"], "cell_id", "dependencies")
        else:
            current = mc.load_json(self.root / "control" / "CURRENT_AUTHORITY.json")
            dag = mc.load_json(mc.resolve_ref(self.root, current["control"]["canonical_dag"]))
            errors = mc._generic_graph_issues(dag["cells"], "id", "depends_on")
        self.assertEqual([], errors, "\n".join(errors))

    def test_05_execution_state_exactly_covers_topology(self) -> None:
        if self.layout == "v16":
            dag = mc.load_json(self.root / "control" / "EXECUTION_DAG.json")
            state = mc.load_json(self.root / "control" / "EXECUTION_STATE.json")
            dag_ids = {c["cell_id"] for c in dag["cells"]}
        else:
            current = mc.load_json(self.root / "control" / "CURRENT_AUTHORITY.json")
            dag = mc.load_json(mc.resolve_ref(self.root, current["control"]["canonical_dag"]))
            state = mc.load_json(mc.resolve_ref(self.root, current["control"]["execution_state"]))
            dag_ids = {c["id"] for c in dag["cells"]}
        self.assertEqual(dag_ids, set(state["cells"]))

    def test_06_target_baselines_are_identical_across_authority(self) -> None:
        if self.layout == "v16":
            mission = mc.load_json(self.root / "MISSION.json")
            current = mc.load_json(self.root / "control" / "CURRENT_AUTHORITY.json")
            expected = {x["repository"]: x["baseline_sha"].lower() for x in mission["target_repositories"]}
            self.assertEqual(expected, current["target_baselines"])
        else:
            current = mc.load_json(self.root / "control" / "CURRENT_AUTHORITY.json")
            dag = mc.load_json(mc.resolve_ref(self.root, current["control"]["canonical_dag"]))
            state = mc.load_json(mc.resolve_ref(self.root, current["control"]["execution_state"]))
            baseline = current["target"]["baseline_sha"].lower()
            self.assertEqual(baseline, dag["target_base"].lower())
            self.assertEqual(baseline, state["target_base"]["sha"].lower())

    def test_07_compiled_packet_references_exist_and_identify_the_cell(self) -> None:
        if self.layout == "v16":
            state = mc.load_json(self.root / "control" / "EXECUTION_STATE.json")
            id_key = "cell_id"
        else:
            current = mc.load_json(self.root / "control" / "CURRENT_AUTHORITY.json")
            state = mc.load_json(mc.resolve_ref(self.root, current["control"]["execution_state"]))
            id_key = "cell_id"
        checked = 0
        for cid, record in state["cells"].items():
            if not isinstance(record, dict) or not record.get("workcell_ref"):
                continue
            path = mc.resolve_ref(self.root, record["workcell_ref"])
            self.assertTrue(path.is_file(), f"missing workcell {cid}: {path}")
            packet = mc.load_json(path)
            self.assertEqual(cid, packet.get(id_key), f"wrong packet referenced for {cid}")
            checked += 1
        if self.layout == "mcv6-legacy":
            self.assertGreater(checked, 0, "MCV6 has compiled cells but no packet reference was checked")

    def test_08_template_assets_are_byte_exact_for_the_active_layout(self) -> None:
        if self.layout == "v16":
            lock = mc.load_json(self.root / "TEMPLATE_LOCK.json")
            self.assertTrue(lock["assets"])
            for rel, expected in lock["assets"].items():
                path = self.root / rel
                self.assertTrue(path.is_file(), rel)
                self.assertEqual(expected, mc.sha256(path), rel)
            return

        manifest = mc.load_json(self.root / "template" / "MANIFEST.json")
        assets = manifest.get("implementation_assets", {})
        self.assertTrue(assets, "MCV6 embedded template declares no implementation assets")
        for name, rel in assets.items():
            embedded = self.root / "template" / rel
            live = self.root / rel
            self.assertTrue(embedded.is_file(), f"{name}: missing embedded asset {rel}")
            self.assertTrue(live.is_file(), f"{name}: missing live asset {rel}")
            self.assertEqual(mc.sha256(embedded), mc.sha256(live), f"{name}: embedded/live drift")

    def test_09_authority_layout_is_explicit_and_unambiguous(self) -> None:
        if self.layout == "v16":
            present = [rel for rel in mc.FORBIDDEN_V16_MIRRORS if (self.root / rel).exists()]
            self.assertEqual([], present)
            return

        present = [rel for rel in mc.FORBIDDEN_V16_MIRRORS if (self.root / rel).exists()]
        self.assertEqual(list(mc.FORBIDDEN_V16_MIRRORS), present)
        current = mc.load_json(self.root / "control" / "CURRENT_AUTHORITY.json")
        control = current["control"]
        self.assertEqual("control/PARALLEL_EXECUTION_DAG.json", control["canonical_dag"])
        self.assertEqual("control/EXECUTION_STATE.json", control["execution_state"])
        self.assertEqual("control/WORKCELL_COMPILER_CONTROL.json", control["compiler_control"])
        for key in ("canonical_dag", "execution_state", "compiler_control"):
            self.assertTrue(mc.resolve_ref(self.root, control[key]).is_file(), key)

    def test_10_layout_native_coherence_gate_passes(self) -> None:
        if self.layout == "v16":
            issues = mc.collect_mission_issues(self.root)
            rendered = "\n".join(f"{x['code']}: {x['message']}" for x in issues)
            self.assertEqual([], issues, rendered)
            return

        checker = self.root / "tools" / "check_control_coherence.py"
        self.assertTrue(checker.is_file(), "MCV6 native coherence checker missing")
        proc = subprocess.run(
            [sys.executable, str(checker), "--root", str(self.root)],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode, proc.stdout + "\n" + proc.stderr)

    def test_11_accepted_cells_have_layout_native_custody_evidence(self) -> None:
        if self.layout == "v16":
            dag = mc.load_json(self.root / "control" / "EXECUTION_DAG.json")
            state = mc.load_json(self.root / "control" / "EXECUTION_STATE.json")
            residency = mc.load_json(self.root / "control" / "SESSION_RESIDENCY.json")
            kinds = {cell["cell_id"]: cell["kind"] for cell in dag["cells"]}
            resident = {record["binding_id"]: record for record in residency["records"]}
            for cid, record in state["cells"].items():
                if record.get("state") != "ACCEPTED" or kinds.get(cid) == "BARRIER":
                    continue
                attempt = int(record["attempt"])
                binding_id = f"{cid}:attempt-{attempt:04d}"
                receipt_ref = record.get("context_receipt_ref")
                adjudication_ref = record.get("adjudication_ref")
                self.assertIsInstance(receipt_ref, str, cid)
                self.assertIsInstance(adjudication_ref, str, cid)
                receipt_path = mc.resolve_ref(self.root, receipt_ref)
                adjudication_path = mc.resolve_ref(self.root, adjudication_ref)
                self.assertTrue(receipt_path.is_file(), cid)
                self.assertTrue(adjudication_path.is_file(), cid)
                self.assertEqual(mc.sha256(adjudication_path), record.get("adjudication_sha256"), cid)
                self.assertIn(binding_id, resident, cid)
                self.assertEqual(receipt_ref, resident[binding_id]["context_receipt_ref"], cid)
                self.assertEqual(mc.sha256(receipt_path), resident[binding_id]["context_receipt_hash"], cid)
            return

        current = mc.load_json(self.root / "control" / "CURRENT_AUTHORITY.json")
        state = mc.load_json(self.root / "control" / "EXECUTION_STATE.json")
        baseline = current["target"]["baseline_sha"].lower()
        checked = 0
        for cid, record in state["cells"].items():
            if not isinstance(record, dict) or record.get("state") != "ACCEPTED" or not record.get("workcell_ref"):
                continue
            receipt_ref = record.get("context_receipt_ref")
            result_ref = record.get("result_ref")
            self.assertIsInstance(receipt_ref, str, cid)
            self.assertIsInstance(result_ref, str, cid)
            receipt_path = mc.resolve_ref(self.root, receipt_ref)
            result_path = mc.resolve_ref(self.root, result_ref)
            self.assertTrue(receipt_path.is_file(), cid)
            self.assertTrue(result_path.is_file(), cid)
            self.assertEqual(record.get("context_receipt_sha256"), mc.sha256(receipt_path), cid)
            self.assertEqual(record.get("result_sha256"), mc.sha256(result_path), cid)
            self.assertEqual(baseline, str(record.get("target_base", "")).lower(), cid)
            checked += 1
        self.assertGreater(checked, 0, "MCV6 has accepted workcells but no custody evidence was checked")

    def test_12_compiled_packets_match_layout_native_compiler_proof(self) -> None:
        if self.layout == "v16":
            dag = mc.load_json(self.root / "control" / "EXECUTION_DAG.json")
            state = mc.load_json(self.root / "control" / "EXECUTION_STATE.json")
            cells = {cell["cell_id"]: cell for cell in dag["cells"]}
            checked = 0
            for cid, record in state["cells"].items():
                ref = record.get("workcell_ref") if isinstance(record, dict) else None
                if not ref:
                    continue
                packet = mc.load_json(mc.resolve_ref(self.root, ref))
                expected_packet, expected_manifest = mc._build_cell_packet(self.root, packet["frontier_id"], cells[cid])
                self.assertEqual(expected_packet, packet, cid)
                manifest = mc.load_json(mc.resolve_ref(self.root, packet["context_manifest_ref"]))
                self.assertEqual(expected_manifest, manifest, cid)
                checked += 1
            self.assertGreater(checked, 0, "no compiled v16 packet was parity-checked")
            return

        proof_test = self.root / "tests" / "test_compiled_frontier_integrity.py"
        self.assertTrue(proof_test.is_file(), "MCV6 compiled-frontier parity proof missing")
        proc = subprocess.run(
            [sys.executable, str(proof_test)],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode, proc.stdout + "\n" + proc.stderr)

def main() -> int:
    global MISSION_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-root", required=True)
    args = parser.parse_args()
    MISSION_ROOT = Path(args.mission_root)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MissionControlSuite)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
