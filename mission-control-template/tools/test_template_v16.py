#!/usr/bin/env python3
"""End-to-end golden lifecycle test for Mission Control template v16."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1]
SOURCE_MC = TEMPLATE / "tools" / "mc.py"
EXAMPLE = TEMPLATE / "examples" / "reference-mission"
BASELINE = ("A000", "A001", "A002", "A003", "A004")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    rendered = list(args)
    if len(rendered) > 1 and rendered[1] == "dispatch" and "--worker-identity" not in rendered:
        rendered.extend([
            "--worker-identity", "golden-worker",
            "--verifier-identity", "golden-verifier",
        ])
    if len(rendered) > 1 and rendered[1] == "dispatch" and "--workspace-id" not in rendered and "--cell" in rendered:
        cell = rendered[rendered.index("--cell") + 1]
        if cell in {"M000", "M001"}:
            rendered.extend(["--workspace-id", f"ws-{cell}"])
    proc = subprocess.run([sys.executable, *rendered], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(
            "command failed:\n  " + " ".join([sys.executable, *args]) +
            f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def run_fail(*args: str) -> subprocess.CompletedProcess[str]:
    rendered = list(args)
    if len(rendered) > 1 and rendered[1] == "dispatch" and "--worker-identity" not in rendered:
        rendered.extend([
            "--worker-identity", "golden-worker",
            "--verifier-identity", "golden-verifier",
        ])
    if len(rendered) > 1 and rendered[1] == "dispatch" and "--workspace-id" not in rendered and "--cell" in rendered:
        cell = rendered[rendered.index("--cell") + 1]
        if cell in {"M000", "M001"}:
            rendered.extend(["--workspace-id", f"ws-{cell}"])
    proc = subprocess.run([sys.executable, *rendered], capture_output=True, text=True)
    if proc.returncode == 0:
        raise RuntimeError(
            "command unexpectedly succeeded:\n  " + " ".join([sys.executable, *args]) +
            f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accepted_result(path: Path, cell_id: str, summary: str) -> None:
    value: dict[str, object] = {
        "schema": "flyby/mission-control-result/16",
        "cell_id": cell_id,
        "outcome": "ACCEPTED",
        "summary": summary,
        "evidence": [{"kind": "golden-test", "value": f"deterministic evidence for {cell_id}"}],
    }
    root = path.parent
    state_path = root / "control" / "EXECUTION_STATE.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        record = state.get("cells", {}).get(cell_id, {})
        workcell_ref = record.get("workcell_ref") if isinstance(record, dict) else None
        if isinstance(workcell_ref, str):
            packet = json.loads((root / workcell_ref).read_text(encoding="utf-8"))
            if packet.get("kind") == "MUTATION":
                target = packet["target"]
                value["target_outcomes"] = [{
                    "repository": target["repository"],
                    "baseline_sha": target["base_sha"].lower(),
                    "head_sha": target["base_sha"].lower(),
                }]
            elif packet.get("kind") in {"INTEGRATION", "QUALIFICATION"}:
                current = json.loads((root / "control" / "CURRENT_AUTHORITY.json").read_text(encoding="utf-8"))
                heads = dict(current["target_baselines"])
                dag = json.loads((root / "control" / "EXECUTION_DAG.json").read_text(encoding="utf-8"))
                if packet.get("kind") == "INTEGRATION":
                    integrated_mutations = []
                    for descriptor in dag["cells"]:
                        if descriptor.get("kind") != "MUTATION":
                            continue
                        mutation_record = state.get("cells", {}).get(descriptor["cell_id"], {})
                        if mutation_record.get("state") != "ACCEPTED":
                            continue
                        mutation_result = json.loads((root / mutation_record["result_ref"]).read_text(encoding="utf-8"))
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
                        integration_record = state.get("cells", {}).get(descriptor["cell_id"], {})
                        if integration_record.get("state") != "ACCEPTED":
                            continue
                        integration_result = json.loads((root / integration_record["result_ref"]).read_text(encoding="utf-8"))
                        for target_outcome in integration_result["target_outcomes"]:
                            heads[target_outcome["repository"]] = target_outcome["head_sha"]
                value["target_outcomes"] = [
                    {"repository": repository, "baseline_sha": baseline, "head_sha": heads[repository]}
                    for repository, baseline in sorted(current["target_baselines"].items())
                ]
    write_json(path, value)


def context_receipt(root: Path, cell_id: str, destination: Path) -> None:
    state = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
    workcell_ref = state["cells"][cell_id]["workcell_ref"]
    packet = json.loads((root / workcell_ref).read_text(encoding="utf-8"))
    manifest_ref = packet["context_manifest_ref"]
    manifest = json.loads((root / manifest_ref).read_text(encoding="utf-8"))
    required_context = [item["context_id"] for item in manifest["items"] if item.get("requirement") == "REQUIRED"]
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    write_json(destination, {
        "schema": "flyby/mission-control-context-receipt/1",
        "receipt_id": f"{cell_id}:golden-receipt",
        "cell_id": cell_id,
        "worker": {"identity": "golden-worker", "session_id": None},
        "base_head": packet["base_head"],
        "manifest_ref": manifest_ref,
        "manifest_hash": manifest_hash,
        "consumed": required_context,
        "partial_or_unavailable": [],
        "approved_extra_context": [],
        "capsules_used": [],
        "assumptions": [],
        "unknowns": [],
        "semantic_coverage": ["golden lifecycle contract"],
        "explicitly_not_covered": [],
        "estimated_context_consumed": None,
        "compaction_or_restart_events": [],
        "safe_reuse_scope": [],
        "unsafe_reuse_scope": ["golden test ends without session reuse"],
        "continuation": {
            "session_reusable": False,
            "session_id": None,
            "reason": "golden test intentionally ends the synthetic worker session",
        },
    })


def current_attempt(root: Path, cell_id: str) -> int:
    state = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
    return int(state["cells"][cell_id]["attempt"])


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def adjudication(
    root: Path,
    cell_id: str,
    result_path: Path,
    receipt_path: Path,
    destination: Path,
    *,
    decision: str = "ACCEPTED",
    verifier_identity: str = "golden-verifier",
    extra: dict[str, object] | None = None,
) -> None:
    state = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
    record = state["cells"][cell_id]
    packet = json.loads((root / record["workcell_ref"]).read_text(encoding="utf-8"))
    manifest = json.loads((root / packet["context_manifest_ref"]).read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    value: dict[str, object] = {
        "schema": "flyby/mission-control-adjudication/16",
        "cell_id": cell_id,
        "attempt": int(record["attempt"]),
        "decision": decision,
        "verifier": {"identity": verifier_identity, "session_id": None},
        "result_sha256": canonical_hash(result),
        "context_receipt_sha256": canonical_hash(receipt),
        "workcell_sha256": canonical_hash(packet),
        "context_manifest_sha256": canonical_hash(manifest),
        "verified_acceptance": list(packet.get("acceptance", [])) if decision == "ACCEPTED" else [],
        "evidence": [{"kind": "golden-verifier", "value": f"independently verified {cell_id}"}],
        "rationale": "Independent golden control-side adjudication.",
    }
    if extra:
        value.update(extra)
    write_json(destination, value)


def settle(root: Path, runtime: Path, cell_id: str, summary: str) -> None:
    result = root / f"{cell_id}-result.json"
    receipt = root / f"{cell_id}-context-receipt.json"
    decision = root / f"{cell_id}-adjudication.json"
    accepted_result(result, cell_id, summary)
    context_receipt(root, cell_id, receipt)
    adjudication(root, cell_id, result, receipt, decision)
    run(
        str(runtime), "settle", "--root", str(root), "--cell", cell_id,
        "--attempt", str(current_attempt(root, cell_id)),
        "--result", str(result), "--context-receipt", str(receipt),
        "--adjudication", str(decision),
    )


def main() -> int:
    run(str(TEMPLATE / "tests" / "test_source_review_turn_chain.py"))
    with tempfile.TemporaryDirectory(prefix="mcv16-golden-") as tmp:
        target_repo = Path(tmp) / "target-repo"
        target_repo.mkdir()
        subprocess.run(["git", "init", str(target_repo)], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(target_repo), "config", "user.email", "golden@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(target_repo), "config", "user.name", "Mission Control Golden"], check=True)
        (target_repo / "README.md").write_text("reference target\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(target_repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(target_repo), "commit", "-m", "reference target base"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(target_repo), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "-C", str(target_repo), "remote", "add", "origin", "https://example.invalid/target.git"], check=True)
        base_sha = subprocess.run(["git", "-C", str(target_repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip().lower()

        root = Path(tmp) / "mission-control-reference"
        root.mkdir()
        mission_payload = json.loads((EXAMPLE / "MISSION.json").read_text(encoding="utf-8"))
        mission_payload["target_repositories"][0]["baseline_sha"] = base_sha
        write_json(root / "MISSION.json", mission_payload)

        run(str(SOURCE_MC), "init", "--mission", str(root / "MISSION.json"))
        runtime = root / "runtime" / "tools" / "mc.py"
        run(str(runtime), "doctor", "--root", str(root))

        prior_root = Path(tmp) / "mission-control-reference-prior"
        prior_root.mkdir()
        prior_handoff = prior_root / "historical" / "previous-mission.json"
        prior_handoff.parent.mkdir(parents=True, exist_ok=True)
        write_json(prior_handoff, {"schema":"flyby/previous-mission-handoff/1","mission_id":"REFERENCE-MCV15","accepted_claims":["historical authority fixture"]})
        prior_mission = json.loads((EXAMPLE / "MISSION.json").read_text(encoding="utf-8"))
        prior_mission["mission_id"] = "REFERENCE-MCV16-PRIOR"
        prior_mission["previous_mission_handoff"] = "historical/previous-mission.json"
        prior_mission["previous_mission_handoff_sha256"] = file_sha256(prior_handoff)
        write_json(prior_root / "MISSION.json", prior_mission)
        run(str(SOURCE_MC), "init", "--mission", str(prior_root / "MISSION.json"))
        prior_runtime = prior_root / "runtime" / "tools" / "mc.py"
        run(str(prior_runtime), "doctor", "--root", str(prior_root))
        original_prior_handoff = prior_handoff.read_text(encoding="utf-8")
        write_json(prior_handoff, {"schema":"flyby/previous-mission-handoff/1","mission_id":"ATTACKER","accepted_claims":["drifted authority"]})
        run_fail(str(prior_runtime), "doctor", "--root", str(prior_root))
        prior_handoff.write_text(original_prior_handoff, encoding="utf-8")
        run(str(prior_runtime), "doctor", "--root", str(prior_root))
        dropped_prior_sources = prior_root / "sources-dropped-prior.json"
        prior_sources = json.loads((prior_root / "corpus" / "SOURCES.json").read_text(encoding="utf-8"))
        prior_sources["sources"] = [item for item in prior_sources["sources"] if item["id"] != "previous-mission-handoff"]
        write_json(dropped_prior_sources, prior_sources)
        run_fail(str(prior_runtime), "sources", "load", "--root", str(prior_root), "--file", str(dropped_prior_sources))
        bad_sources = root / "bad-sources.json"
        bad_source_payload = json.loads((EXAMPLE / "SOURCES.json").read_text(encoding="utf-8"))
        bad_source_payload["sources"][1].pop("disposition", None)
        write_json(bad_sources, bad_source_payload)
        run_fail(str(runtime), "sources", "load", "--root", str(root), "--file", str(bad_sources))
        missing_owner_sources = root / "sources-missing-owner.json"
        missing_owner_payload = json.loads((EXAMPLE / "SOURCES.json").read_text(encoding="utf-8"))
        missing_owner_payload["sources"] = [item for item in missing_owner_payload["sources"] if item["id"] != "owner-intent"]
        write_json(missing_owner_sources, missing_owner_payload)
        run_fail(str(runtime), "sources", "load", "--root", str(root), "--file", str(missing_owner_sources))
        reference_only_sources = root / "sources-reference-only.json"
        reference_only_payload = json.loads((EXAMPLE / "SOURCES.json").read_text(encoding="utf-8"))
        reference_only_payload["sources"][1]["disposition"] = "REFERENCE_ONLY"
        reference_only_payload["sources"][1]["copyright"]["usage_mode"] = "REFERENCE_ONLY"
        write_json(reference_only_sources, reference_only_payload)
        run(str(runtime), "sources", "load", "--root", str(root), "--file", str(reference_only_sources))
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(EXAMPLE / "PROVENANCE_SYNTHESIS.json"))
        authority_only_sources = root / "sources-authority-only.json"
        authority_only_payload = json.loads((EXAMPLE / "SOURCES.json").read_text(encoding="utf-8"))
        authority_only_payload["sources"][1]["disposition"] = "AUTHORITY_ONLY"
        authority_only_payload["sources"][1]["copyright"]["usage_mode"] = "AUTHORITY_ONLY"
        write_json(authority_only_sources, authority_only_payload)
        run(str(runtime), "sources", "load", "--root", str(root), "--file", str(authority_only_sources))
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(EXAMPLE / "PROVENANCE_SYNTHESIS.json"))
        moving_repo_sources = root / "sources-moving-repo-pin.json"
        moving_repo_payload = json.loads((EXAMPLE / "SOURCES.json").read_text(encoding="utf-8"))
        moving_repo_payload["sources"].append({
            "id":"moving-repository", "kind":"REPOSITORY", "locator":"https://example.invalid/repo.git", "role":"hostile moving ref",
            "pin":"main", "disposition":"SYNTHESIS_REQUIRED", "inspection_scope":["behavior"],
            "copyright":{"usage_mode":"CLEAN_ROOM_BEHAVIORAL_SYNTHESIS","rights_status":"VERIFIED","rights_basis":"hostile fixture clean-room boundary","code_copy_allowed":False,"text_copy_allowed":False,"structure_reuse_allowed":False,"obligations":[],"evidence_ref":"golden://hostile-rights","notes":"hostile fixture"}
        })
        write_json(moving_repo_sources, moving_repo_payload)
        run_fail(str(runtime), "sources", "load", "--root", str(root), "--file", str(moving_repo_sources))
        unverified_reuse_sources = root / "sources-unverified-reuse.json"
        unverified_payload = json.loads((EXAMPLE / "SOURCES.json").read_text(encoding="utf-8"))
        unverified_payload["sources"][1]["license"] = "MIT"
        unverified_payload["sources"][1]["copyright"].update({"usage_mode":"LICENSE_PERMITTED_REUSE","rights_status":"PENDING","rights_basis":"not yet verified at pin","code_copy_allowed":True,"text_copy_allowed":True,"structure_reuse_allowed":True,"evidence_ref":None})
        write_json(unverified_reuse_sources, unverified_payload)
        run_fail(str(runtime), "sources", "load", "--root", str(root), "--file", str(unverified_reuse_sources))
        run(str(runtime), "sources", "load", "--root", str(root), "--file", str(EXAMPLE / "SOURCES.json"))
        run_fail(str(runtime), "corpus", "load", "--root", str(root), "--file", str(EXAMPLE / "TARGET_CORPUS.json"))
        unbound_lineage_corpus = root / "target-corpus-unbound-lineage.json"
        unbound_lineage_payload = json.loads((EXAMPLE / "TARGET_CORPUS.json").read_text(encoding="utf-8"))
        unbound_lineage_payload["provenance_materialization"] = {"mode":"REQUIRED_EXISTING_TARGET_MANIFEST","target_refs":["sources_provenance.yaml"],"coverage_requirement_id":"MISSING-LINEAGE-REQ","validation_schema_ref":"sources_provenance.schema.json","authority":"LINEAGE_ONLY","acceptance":["must update lineage"]}
        write_json(unbound_lineage_corpus, unbound_lineage_payload)
        # Still blocked before provenance load, then specifically blocked on the missing lineage requirement after provenance is valid below.
        run_fail(str(runtime), "corpus", "load", "--root", str(root), "--file", str(unbound_lineage_corpus))
        incomplete_provenance = root / "provenance-incomplete-coverage.json"
        incomplete_payload = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        incomplete_payload["source_assessments"][0]["open_questions"] = ["unresolved material capability"]
        write_json(incomplete_provenance, incomplete_payload)
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(incomplete_provenance))
        if (EXAMPLE / "evidence").is_dir():
            shutil.copytree(EXAMPLE / "evidence", root / "evidence", dirs_exist_ok=True)

        shallow_multi_round = root / "provenance-shallow-multi-round.json"
        shallow_payload = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        shallow_payload["source_assessments"][0]["deep_review"]["strategy"] = "MULTI_ROUND_EXCORIATION"
        write_json(shallow_multi_round, shallow_payload)
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(shallow_multi_round))
        stale_review_provenance = root / "provenance-stale-review-digest.json"
        stale_review_payload = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        stale_review_payload["source_assessments"][0]["coverage_items"][0]["rationale"] += " changed after review"
        write_json(stale_review_provenance, stale_review_payload)
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(stale_review_provenance))
        forged_review_hash = root / "provenance-forged-review-hash.json"
        forged_review_payload = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        forged_review_payload["source_assessments"][0]["independent_review"]["review_sha256"] = "0" * 64
        write_json(forged_review_hash, forged_review_payload)
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(forged_review_hash))
        self_reviewed = root / "provenance-self-reviewed.json"
        self_reviewed_payload = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        self_reviewed_payload["source_assessments"][0]["independent_review"]["reviewer"] = "reference-golden-reviewer"
        write_json(self_reviewed, self_reviewed_payload)
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(self_reviewed))
        rejected_mechanism = root / "provenance-rejected-mechanism-bound.json"
        rejected_payload = json.loads((EXAMPLE / "PROVENANCE_SYNTHESIS.json").read_text(encoding="utf-8"))
        rejected_payload["mechanisms"][0]["disposition"] = "REJECTED"
        rejected_payload["mechanisms"][0]["rejection_reason"] = "hostile fixture rejects the mechanism but leaves target authority attached"
        write_json(rejected_mechanism, rejected_payload)
        run_fail(str(runtime), "provenance", "load", "--root", str(root), "--file", str(rejected_mechanism))
        run(str(runtime), "provenance", "load", "--root", str(root), "--file", str(EXAMPLE / "PROVENANCE_SYNTHESIS.json"))
        run_fail(str(runtime), "corpus", "load", "--root", str(root), "--file", str(unbound_lineage_corpus))
        hidden_source_corpus = root / "target-corpus-hidden-mechanism-source.json"
        hidden_source_payload = json.loads((EXAMPLE / "TARGET_CORPUS.json").read_text(encoding="utf-8"))
        hidden_source_payload["requirements"][0]["sources"] = ["owner-intent"]
        hidden_source_payload["requirements"][0].pop("derivation", None)
        write_json(hidden_source_corpus, hidden_source_payload)
        run_fail(str(runtime), "corpus", "load", "--root", str(root), "--file", str(hidden_source_corpus))
        run(str(runtime), "corpus", "load", "--root", str(root), "--file", str(EXAMPLE / "TARGET_CORPUS.json"))
        run(str(runtime), "baseline", "compile", "--root", str(root))

        frontier = root / "mutation-frontier.json"
        frontier_payload = json.loads((EXAMPLE / "MUTATION_FRONTIER.json").read_text(encoding="utf-8"))
        for frontier_cell in frontier_payload["cells"]:
            target = frontier_cell.get("target")
            if isinstance(target, dict) and target.get("repository") == "example/target":
                target["base_sha"] = base_sha
        write_json(frontier, frontier_payload)
        run_fail(str(runtime), "compile", "--root", str(root), "--frontier", str(frontier))

        for cell_id in BASELINE:
            run(str(runtime), "dispatch", "--root", str(root), "--cell", cell_id)
            if cell_id == "A000":
                good_result = root / "A000-result.json"
                good_receipt = root / "A000-context-receipt.json"
                accepted_result(good_result, "A000", "reference baseline audit accepted")
                context_receipt(root, "A000", good_receipt)

                bad_result = root / "A000-invalid-result.json"
                write_json(bad_result, {
                    "schema": "flyby/mission-control-result/16",
                    "cell_id": "A000",
                    "outcome": "ACCEPTED",
                    "summary": "missing evidence",
                    "evidence": [],
                })
                bad_result_adjudication = root / "A000-bad-result-adjudication.json"
                adjudication(root, "A000", bad_result, good_receipt, bad_result_adjudication)
                run_fail(
                    str(runtime), "settle", "--root", str(root), "--cell", "A000", "--attempt", "1",
                    "--result", str(bad_result), "--context-receipt", str(good_receipt),
                    "--adjudication", str(bad_result_adjudication),
                )

                bad_receipt = root / "A000-invalid-context-receipt.json"
                value = json.loads(good_receipt.read_text(encoding="utf-8"))
                value["base_head"] = "1111111111111111111111111111111111111111"
                write_json(bad_receipt, value)
                bad_receipt_adjudication = root / "A000-bad-receipt-adjudication.json"
                adjudication(root, "A000", good_result, bad_receipt, bad_receipt_adjudication)
                run_fail(
                    str(runtime), "settle", "--root", str(root), "--cell", "A000", "--attempt", "1",
                    "--result", str(good_result), "--context-receipt", str(bad_receipt),
                    "--adjudication", str(bad_receipt_adjudication),
                )

                same_worker_adjudication = root / "A000-same-worker-adjudication.json"
                adjudication(
                    root, "A000", good_result, good_receipt, same_worker_adjudication,
                    verifier_identity="golden-worker",
                )
                run_fail(
                    str(runtime), "settle", "--root", str(root), "--cell", "A000", "--attempt", "1",
                    "--result", str(good_result), "--context-receipt", str(good_receipt),
                    "--adjudication", str(same_worker_adjudication),
                )

                wrong_hash_adjudication = root / "A000-wrong-hash-adjudication.json"
                adjudication(
                    root, "A000", good_result, good_receipt, wrong_hash_adjudication,
                    extra={"result_sha256": "0" * 64},
                )
                run_fail(
                    str(runtime), "settle", "--root", str(root), "--cell", "A000", "--attempt", "1",
                    "--result", str(good_result), "--context-receipt", str(good_receipt),
                    "--adjudication", str(wrong_hash_adjudication),
                )

                good_adjudication = root / "A000-adjudication.json"
                adjudication(root, "A000", good_result, good_receipt, good_adjudication)
                run(
                    str(runtime), "settle", "--root", str(root), "--cell", "A000", "--attempt", "1",
                    "--result", str(good_result), "--context-receipt", str(good_receipt),
                    "--adjudication", str(good_adjudication),
                )
                before = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))["cells"]["A000"]
                run(str(runtime), "baseline", "compile", "--root", str(root))
                after = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))["cells"]["A000"]
                if before != after or after.get("state") != "ACCEPTED":
                    raise RuntimeError("idempotent baseline compile changed accepted A000 state/evidence")
            else:
                settle(root, runtime, cell_id, "reference baseline audit accepted")

        run(str(runtime), "baseline", "accept", "--root", str(root))

        stale = root / "stale-mutation-frontier.json"
        stale_value = json.loads(frontier.read_text(encoding="utf-8"))
        stale_value["frontier_id"] = "STALE"
        stale_value["cells"][0]["target"]["base_sha"] = "1111111111111111111111111111111111111111"
        write_json(stale, stale_value)
        run_fail(str(runtime), "compile", "--root", str(root), "--frontier", str(stale))

        run(str(runtime), "compile", "--root", str(root), "--frontier", str(frontier))
        worktrees: dict[str, Path] = {}
        integration_wt = os.environ.get("WORKTRUNK_MC_TEST_WT")
        if integration_wt:
            hook_dir = Path(tmp) / "git-hooks"
            hook_dir.mkdir()
            hook = hook_dir / "post-checkout"
            hook.write_text("#!/bin/sh\nprintf hook > HOOK_RAN\n", encoding="utf-8")
            hook.chmod(0o755)
            subprocess.run(["git", "-C", str(target_repo), "config", "core.hooksPath", str(hook_dir)], check=True)
        for cell in ("M000", "M001"):
            wt = Path(tmp) / f"target-{cell.lower()}"
            if integration_wt and cell == "M000":
                prepared = json.loads(run(str(runtime.parent / "wt_mission.py"), "prepare", "--root", str(root),
                    "--repo", str(target_repo), "--cell", cell, "--workspace-id", "ws-M000",
                    "--branch", "mcv6/m000", "--path", str(wt), "--wt", integration_wt,
                    "--expected-origin", "https://example.invalid/target.git",
                    "--worker", "golden-worker", "--verifier", "golden-verifier").stdout)
                if prepared.get("state") != "DISPATCHED":
                    raise RuntimeError("adapter did not dispatch the registered workspace")
                if (wt / "HOOK_RAN").exists():
                    raise RuntimeError("Git checkout hook ran before workspace registration")
            else:
                subprocess.run(["git", "-C", str(target_repo), "worktree", "add", "-b", f"mcv6/{cell.lower()}",
                                str(wt), base_sha], check=True, capture_output=True, text=True)
                if integration_wt:
                    marker = wt / "HOOK_RAN"
                    if not marker.is_file():
                        raise RuntimeError("Git checkout hook control did not run")
                    marker.unlink()
            worktrees[cell] = wt
        # Target-bearing cells cannot dispatch until exact branch/workspace identity is in the durable ledger.
        direct_missing_workspace = subprocess.run([
            sys.executable, str(runtime), "dispatch", "--root", str(root), "--cell",
            "M001" if integration_wt else "M000",
            "--worker-identity", "golden-worker", "--verifier-identity", "golden-verifier",
        ], capture_output=True, text=True)
        if direct_missing_workspace.returncode == 0:
            raise RuntimeError("target-bearing dispatch succeeded without registered workspace identity")
        wrong_cell = "M001" if integration_wt else "M000"
        wrong_path = worktrees["M000"] if integration_wt else worktrees["M001"]
        run_fail(str(runtime), "workspace", "register", "--root", str(root), "--cell", wrong_cell,
                 "--workspace-id", "ws-wrong-branch", "--branch", f"mcv6/{wrong_cell.lower()}", "--path", str(wrong_path))
        dirty_cell = "M001" if integration_wt else "M000"
        dirty_probe = worktrees[dirty_cell] / "UNTRACKED.txt"
        dirty_probe.write_text("hostile dirty registration\n", encoding="utf-8")
        run_fail(str(runtime), "workspace", "register", "--root", str(root), "--cell", dirty_cell, "--workspace-id", "ws-dirty", "--branch", f"mcv6/{dirty_cell.lower()}", "--path", str(worktrees[dirty_cell]))
        dirty_probe.unlink()
        registration_cells = ("M001",) if integration_wt else ("M000", "M001")
        registration_procs = [
            subprocess.Popen([sys.executable, str(runtime), "workspace", "register", "--root", str(root),
                              "--cell", cell, "--workspace-id", f"ws-{cell}", "--branch", f"mcv6/{cell.lower()}",
                              "--path", str(worktrees[cell])], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for cell in registration_cells
        ]
        registration_results = [proc.communicate() + (proc.returncode,) for proc in registration_procs]
        if any(result[2] != 0 for result in registration_results):
            raise RuntimeError(f"workspace registration failed: {registration_results}")
        ledger_after_concurrent = json.loads((root / "control" / "WORKSPACE_LEDGER.json").read_text(encoding="utf-8"))
        registered_target_ids = {item["workspace_id"] for item in ledger_after_concurrent["entries"] if item.get("kind") == "TARGET"}
        if registered_target_ids != {"ws-M000", "ws-M001"}:
            raise RuntimeError(f"concurrent workspace registration lost update: {sorted(registered_target_ids)}")
        run_fail(str(runtime), "workspace", "register", "--root", str(root), "--cell", "M001", "--workspace-id", "ws-duplicate-branch", "--branch", "mcv6/m000", "--path", str(worktrees["M001"]))
        if not integration_wt:
            run(str(runtime), "dispatch", "--root", str(root), "--cell", "M000")
        run_fail(str(runtime), "dispatch", "--root", str(root), "--cell", "M001")
        settle(root, runtime, "M000", "reference mutation accepted")
        if integration_wt:
            projected = json.loads(run(str(runtime.parent / "wt_mission.py"), "report",
                                       "--root", str(root), "--cell", "M000").stdout)
            if (projected["state"] != "ACCEPTED" or projected["worker_identity"] == projected["verifier_identity"]
                    or projected["workspace"]["head_sha"] != base_sha or not projected["workspace"]["clean"]):
                raise RuntimeError("adapter did not project the accepted scope and exact workspace")
        run_fail(str(runtime), "integrate", "--root", str(root))
        run(str(runtime), "dispatch", "--root", str(root), "--cell", "M001")
        settle(root, runtime, "M001", "serialized reference mutation accepted")

        result_path = root / "evidence" / "M000" / "attempt-0001" / "result.json"
        original_result = result_path.read_text(encoding="utf-8")
        tampered = json.loads(original_result)
        tampered["summary"] = "tampered after settlement"
        write_json(result_path, tampered)
        run_fail(str(runtime), "doctor", "--root", str(root))
        result_path.write_text(original_result, encoding="utf-8")
        run(str(runtime), "doctor", "--root", str(root))

        run(str(runtime), "barrier", "accept", "--root", str(root), "--cell", "G100")
        run(str(runtime), "integrate", "--root", str(root))
        run_fail(str(runtime), "compile", "--root", str(root), "--frontier", str(frontier))
        run(str(runtime), "dispatch", "--root", str(root), "--cell", "I000")
        settle(root, runtime, "I000", "typed integration accepted")

        run(str(runtime), "qualify", "--root", str(root))
        run(str(runtime), "dispatch", "--root", str(root), "--cell", "Q000")
        settle(root, runtime, "Q000", "typed qualification workcell accepted")
        qualification = root / "qualification-result.json"
        invalid_qualification = root / "qualification-invalid-accounting.json"
        write_json(invalid_qualification, {
            "schema": "flyby/mission-control-qualification/16",
            "outcome": "ACCEPTED",
            "summary": "hostile qualification omits target requirement accounting",
            "evidence": [{"kind": "golden-test", "value": "negative accounting proof"}],
            "target_outcomes": [{
                "repository": "example/target",
                "baseline_sha": base_sha,
                "accepted_head_sha": base_sha
            }],
            "requirement_accounting": {"accepted": [], "waived": []},
            "verification_accounting": {"run": ["golden lifecycle"], "waived": [], "not_run": []},
            "unresolved_defects": [],
            "explicit_limitations": []
        })
        run_fail(str(runtime), "qualify", "--root", str(root), "--result", str(invalid_qualification))
        forged_head = root / "qualification-forged-head.json"
        write_json(forged_head, {
            "schema": "flyby/mission-control-qualification/16",
            "outcome": "ACCEPTED",
            "summary": "hostile qualification claims an unproven target head",
            "evidence": [{"kind": "golden-test", "value": "negative target-head lineage proof"}],
            "target_outcomes": [{
                "repository": "example/target",
                "baseline_sha": base_sha,
                "accepted_head_sha": "ffffffffffffffffffffffffffffffffffffffff"
            }],
            "requirement_accounting": {"accepted": ["REF-001"], "waived": []},
            "verification_accounting": {"run": ["golden lifecycle"], "waived": [], "not_run": []},
            "unresolved_defects": [],
            "explicit_limitations": []
        })
        run_fail(str(runtime), "qualify", "--root", str(root), "--result", str(forged_head))
        q000_state = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))["cells"]["Q000"]
        q000_packet = json.loads((root / q000_state["workcell_ref"]).read_text(encoding="utf-8"))
        proven_verifications = list(q000_packet["acceptance"])
        forged_verification = root / "qualification-forged-verification.json"
        write_json(forged_verification, {
            "schema": "flyby/mission-control-qualification/16",
            "outcome": "ACCEPTED",
            "summary": "hostile qualification claims an unproven verification",
            "evidence": [{"kind": "golden-test", "value": "negative verification-lineage proof"}],
            "target_outcomes": [{
                "repository": "example/target",
                "baseline_sha": base_sha,
                "accepted_head_sha": base_sha
            }],
            "requirement_accounting": {"accepted": ["REF-001"], "waived": []},
            "verification_accounting": {
                "run": [*proven_verifications, "unproven terminal verification"],
                "waived": [],
                "not_run": []
            },
            "unresolved_defects": [],
            "explicit_limitations": []
        })
        run_fail(str(runtime), "qualify", "--root", str(root), "--result", str(forged_verification))
        write_json(qualification, {
            "schema": "flyby/mission-control-qualification/16",
            "outcome": "ACCEPTED",
            "summary": "reference candidate passes full golden qualification",
            "evidence": [{"kind": "golden-test", "value": "baseline, conflict-safe mutation, typed integration and typed qualification completed"}],
            "target_outcomes": [{
                "repository": "example/target",
                "baseline_sha": base_sha,
                "accepted_head_sha": base_sha
            }],
            "requirement_accounting": {"accepted": ["REF-001"], "waived": []},
            "verification_accounting": {
                "run": proven_verifications,
                "waived": [],
                "not_run": []
            },
            "unresolved_defects": [],
            "explicit_limitations": []
        })
        qualification_path = root / "handoff" / "QUALIFICATION.json"
        write_json(qualification_path, json.loads(qualification.read_text(encoding="utf-8")))
        run(str(runtime), "qualify", "--root", str(root), "--result", str(qualification))

        original_qualification = qualification_path.read_text(encoding="utf-8")
        tampered_qualification = json.loads(original_qualification)
        tampered_qualification["summary"] = "tampered after acceptance"
        write_json(qualification_path, tampered_qualification)
        run_fail(str(runtime), "doctor", "--root", str(root))
        qualification_path.write_text(original_qualification, encoding="utf-8")
        run(str(runtime), "doctor", "--root", str(root))
        run_fail(str(runtime), "close", "--root", str(root))
        workspace_input = root / "workspace-reconciliation-input.json"
        workspace_payload = json.loads((EXAMPLE / "WORKSPACE_RECONCILIATION.json").read_text(encoding="utf-8"))
        workspace_payload["control_workspaces"][0]["evidence"][0]["sha256"] = file_sha256(root / "control" / "CURRENT_AUTHORITY.json")
        workspace_payload["target_repositories"][0]["accepted_head_sha"] = base_sha
        empty_status_sha = hashlib.sha256(b"\n").hexdigest()
        for branch in workspace_payload["target_repositories"][0]["branches"]:
            cell = branch["workspace_id"].removeprefix("ws-")
            branch["head_sha"] = base_sha
            branch["worktree_path"] = str(worktrees[cell].resolve())
            branch["dirty"] = False
            branch["semantic_status_sha256"] = empty_status_sha
            branch["remote_url"] = "https://example.invalid/target.git"
            branch["evidence"][0]["sha256"] = file_sha256(qualification_path)
        write_json(workspace_input, workspace_payload)
        malformed_control_id = json.loads(workspace_input.read_text(encoding="utf-8"))
        malformed_control_id["control_workspaces"][0]["workspace_id"] = []
        malformed_control_id_path = root / "workspace-malformed-control-id.json"
        write_json(malformed_control_id_path, malformed_control_id)
        malformed_id_proc = run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(malformed_control_id_path))
        if "Traceback" in malformed_id_proc.stderr:
            raise RuntimeError("malformed workspace id leaked a traceback instead of schema-first rejection")
        forged_worktree = json.loads(workspace_input.read_text(encoding="utf-8"))
        forged_worktree["target_repositories"][0]["branches"][0]["worktree_path"] = str(target_repo.resolve())
        forged_worktree_path = root / "workspace-forged-worktree-path.json"
        write_json(forged_worktree_path, forged_worktree)
        run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(forged_worktree_path))
        forged_remote = json.loads(workspace_input.read_text(encoding="utf-8"))
        forged_remote["target_repositories"][0]["branches"][0]["remote_url"] = "https://attacker.invalid/target.git"
        forged_remote_path = root / "workspace-forged-remote.json"
        write_json(forged_remote_path, forged_remote)
        run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(forged_remote_path))
        dirty_live = worktrees["M000"] / "LIVE-DRIFT.txt"
        dirty_live.write_text("post-registration live drift\n", encoding="utf-8")
        run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(workspace_input))
        dirty_live.unlink()
        arbitrary_supersession = json.loads(workspace_input.read_text(encoding="utf-8"))
        arbitrary_supersession["historical_material"].append({
            "ref":"handoff/QUALIFICATION.json",
            "sha256":file_sha256(qualification_path),
            "disposition":"SUPERSEDED_EVIDENCE",
            "supersession_ref":"control/CURRENT_AUTHORITY.json",
            "supersession_sha256":file_sha256(root / "control" / "CURRENT_AUTHORITY.json")
        })
        arbitrary_supersession_path = root / "workspace-arbitrary-supersession.json"
        write_json(arbitrary_supersession_path, arbitrary_supersession)
        run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(arbitrary_supersession_path))
        missing_accepted = json.loads(workspace_input.read_text(encoding="utf-8"))
        missing_accepted["target_repositories"][0]["branches"] = []
        bad_workspace = root / "workspace-missing-accepted.json"
        write_json(bad_workspace, missing_accepted)
        run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(bad_workspace))
        malformed_workspace = json.loads(workspace_input.read_text(encoding="utf-8"))
        malformed_workspace["target_repositories"][0]["branches"] = None
        malformed_workspace_path = root / "workspace-malformed-branches.json"
        write_json(malformed_workspace_path, malformed_workspace)
        malformed_proc = run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(malformed_workspace_path))
        if "Traceback" in malformed_proc.stderr:
            raise RuntimeError("malformed workspace reconciliation leaked a traceback instead of clean rejection")
        escaped_evidence = json.loads(workspace_input.read_text(encoding="utf-8"))
        escaped_evidence["target_repositories"][0]["branches"][0]["evidence"][0]["ref"] = "../outside-evidence.json"
        escaped_workspace = root / "workspace-escaped-evidence.json"
        write_json(escaped_workspace, escaped_evidence)
        run_fail(str(runtime), "workspace", "load", "--root", str(root), "--file", str(escaped_workspace))
        run(str(runtime), "workspace", "load", "--root", str(root), "--file", str(workspace_input))
        workspace_path = root / "handoff" / "WORKSPACE_RECONCILIATION.json"
        original_workspace = workspace_path.read_text(encoding="utf-8")
        tampered_workspace = json.loads(original_workspace)
        tampered_workspace["target_repositories"][0]["accepted_head_sha"] = "ffffffffffffffffffffffffffffffffffffffff"
        write_json(workspace_path, tampered_workspace)
        run_fail(str(runtime), "doctor", "--root", str(root))
        workspace_path.write_text(original_workspace, encoding="utf-8")
        run(str(runtime), "doctor", "--root", str(root))

        accepted_qualification = json.loads(original_qualification)
        closure_path = root / "handoff" / "CLOSURE.json"
        write_json(closure_path, {
            "schema": "flyby/mission-control-closure/16",
            "mission_id": "REFERENCE-MCV16",
            "terminal_state": "CLOSED",
            "qualification_ref": "handoff/QUALIFICATION.json",
            "qualification_sha256": file_sha256(qualification_path),
            "workspace_reconciliation_ref": "handoff/WORKSPACE_RECONCILIATION.json",
            "workspace_reconciliation_sha256": file_sha256(workspace_path),
            "target_outcomes": accepted_qualification["target_outcomes"],
            "requirement_accounting": accepted_qualification["requirement_accounting"],
            "verification_accounting": accepted_qualification["verification_accounting"],
            "unresolved_defects": accepted_qualification["unresolved_defects"],
            "explicit_limitations": accepted_qualification["explicit_limitations"]
        })
        run(str(runtime), "close", "--root", str(root))
        run(str(runtime), "doctor", "--root", str(root))

        closure_path = root / "handoff" / "CLOSURE.json"
        original_closure = closure_path.read_text(encoding="utf-8")
        tampered_closure = json.loads(original_closure)
        tampered_closure["mission_id"] = "FOREIGN-MISSION"
        write_json(closure_path, tampered_closure)
        run_fail(str(runtime), "doctor", "--root", str(root))
        closure_path.write_text(original_closure, encoding="utf-8")
        run(str(runtime), "doctor", "--root", str(root))
        run(str(root / "runtime" / "tests" / "test_mission_control.py"), "--mission-root", str(root))

        state = json.loads((root / "control" / "EXECUTION_STATE.json").read_text(encoding="utf-8"))
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
        residency = json.loads((root / "control" / "SESSION_RESIDENCY.json").read_text(encoding="utf-8"))
        accepted_executable = set(BASELINE) | {"M000", "M001", "I000", "Q000"}
        resident_cells = {record["origin_cell"] for record in residency["records"]}
        if state.get("lifecycle") != "CLOSED" or closure.get("terminal_state") != "CLOSED":
            raise RuntimeError("golden mission did not reach CLOSED")
        if not accepted_executable <= resident_cells:
            raise RuntimeError("golden mission lost session-residency settlement evidence")

    print(json.dumps({
        "state": "PASS",
        "template": "flyby/mission-control-template/16",
        "golden_lifecycle": "CLOSED",
        "baseline_compile_idempotence": "PROVEN",
        "conflict_safe_admission": "PROVEN",
        "typed_integration_and_qualification": "PROVEN",
        "settlement_evidence_integrity": "PROVEN",
        "independent_adjudication": "PROVEN",
        "context_receipt_settlement": "PROVEN",
        "session_residency": "PROVEN",
        "qualification_and_closure_integrity": "PROVEN",
        "source_review_turn_chain": "PROVEN",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
