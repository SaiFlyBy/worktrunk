#!/usr/bin/env python3
"""Generic Mission Control cross-authority coherence preflight."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--current", default="control/CURRENT_AUTHORITY.json")
    p.add_argument("--topology", default="control/PARALLEL_EXECUTION_DAG.json")
    p.add_argument("--state", default="control/EXECUTION_STATE.json")
    p.add_argument("--compiler-control", default="control/WORKCELL_COMPILER_CONTROL.json")
    p.add_argument("--executor-protocol", default="EXECUTOR_PROTOCOL.md")
    args = p.parse_args()

    root = args.root
    current = load(root / args.current)
    topology = load(root / args.topology)
    state = load(root / args.state)
    compiler = load(root / args.compiler_control)
    failures: list[str] = []

    def check(ok: bool, msg: str) -> None:
        if not ok:
            failures.append(msg)

    canonical = current.get("control", {}).get("canonical_dag_schema")
    check(bool(canonical), "CURRENT_AUTHORITY lacks canonical_dag_schema")
    check(topology.get("schema") == canonical, "topology/current authority drift")
    state_schema = state.get("canonical_topology", {}).get("schema") or state.get("topology", {}).get("schema")
    check(state_schema == canonical, "execution state topology drift")
    check(compiler.get("canonical_dag_schema") == canonical, "compiler topology drift")

    barriers = topology.get("global_barriers", [])
    check(all("status" not in b and "state" not in b for b in barriers), "runtime status in topology")
    check({b.get("id") for b in barriers} <= set(topology.get("barrier_contracts", {})), "barrier contract missing")

    dispatch = compiler.get("dispatch_law", {})
    check(dispatch.get("dynamic_cell_state_does_not_rewrite_topology") is True, "topology/state separation missing")
    check(dispatch.get("runtime_status_in_canonical_topology_allowed") is False, "runtime topology status allowed")
    check(dispatch.get("control_coherence_must_pass_before_new_dispatch") is True, "coherence preflight not mandatory")
    check(dispatch.get("target_mutation_base_source") == "CompiledWorkCell.base", "target mutation base is not CompiledWorkCell.base")
    check(dispatch.get("control_evidence_branch_separate_from_target_candidate") is True, "control evidence/target candidate conflated")
    check(dispatch.get("mutation_compiler_full_packet_parity_required_before_product_dispatch") is True, "mutation compiler parity gate not mandatory")
    check(dispatch.get("mutation_compiler_check_uses_same_compile_cell_path_as_materialization") is True, "check/materialization compile path diverges")
    check(dispatch.get("mutation_compiler_check_may_differ_from_materialization_only_by_filesystem_writes") is True, "check/materialization equivalence law missing")
    check(dispatch.get("constraint_aware_schema_template_generation_required") is True, "constraint-aware template generation not mandatory")
    check(dispatch.get("orchestrator_must_capture_provider_native_session_identity_when_exposed") is True, "session identity capture law missing")
    check(dispatch.get("identity_unavailable_must_be_explicit") is True, "identity-unavailable law missing")
    check(dispatch.get("worker_identity_is_not_session_identity") is True, "worker/session identity conflation allowed")
    check(dispatch.get("candidate_session_runtime_resolved_from_residency_registry") is True, "runtime session resolution law missing")

    executor = root / args.executor_protocol
    check(executor.is_file(), "executor protocol missing")
    if executor.is_file():
        text = executor.read_text(encoding="utf-8")
        check("TARGET_BASE = CompiledWorkCell.base.repository + branch + head" in text, "executor ancestry law missing")
        check("not a target mutation base" in text, "executor cross-repository rejection missing")

    required_assets = (
        "WORKCELL_SCHEMA.json", "CONTEXT_MANIFEST_SCHEMA.json", "CONTEXT_RECEIPT_SCHEMA.json",
        "CONTEXT_AMENDMENT_SCHEMA.json", "CORE_MUTATION_CONTRACT_SCHEMA.json",
        "SESSION_REUSE_ADJUDICATION_SCHEMA.json", "SESSION_RESIDENCY_REGISTRY_SCHEMA.json",
        "tools/compile_mutation_frontier.py", "tools/compile_frontier_guarded.py",
        "tools/check_mutation_compiler_parity.py", "tools/schema_template.py",
        "tools/validate_json_schema_subset.py",
    )
    for rel in required_assets:
        check((root / rel).is_file(), f"required executable template asset missing: {rel}")

    mut = root / "tools" / "compile_mutation_frontier.py"
    if mut.is_file():
        src = mut.read_text(encoding="utf-8")
        check("def compile_cell(" in src, "mutation compiler lacks shared compile_cell path")
        check("compiled = [compile_cell(" in src, "check/materialization do not share compile_cell")
        check("CONTEXT_RECEIPT_SCHEMA.json" in src, "mutation compiler does not load ContextReceipt schema")
        check("context_receipt_contract" in src, "mutation compiler does not bind ContextReceipt contract")
        check("WORKCELL_SCHEMA.json" in src, "mutation compiler does not validate Workcell schema")
        check("from schema_template import template_value" in src, "mutation compiler bypasses constraint-aware schema template generator")

    guarded = root / "tools" / "compile_frontier_guarded.py"
    if guarded.is_file():
        src = guarded.read_text(encoding="utf-8")
        check("check_mutation_compiler_parity.py" in src, "guarded compiler does not invoke parity gate")

    parity = root / "tools" / "check_mutation_compiler_parity.py"
    if parity.is_file():
        src = parity.read_text(encoding="utf-8")
        check('"--check"' in src and '"--destination"' in src, "parity gate does not exercise dry-run and materialization")
        check("INDEX_AUDIT" in src, "parity gate does not audit materialized packet set")

    schema_template = root / "tools" / "schema_template.py"
    if schema_template.is_file():
        src = schema_template.read_text(encoding="utf-8")
        check("minItems" in src and "minLength" in src, "schema template generator ignores cardinality constraints")

    reuse = compiler.get("session_reuse", {})
    check(reuse.get("default_mode") == "REUSE_IF_RECEIPT_MATCHES", "reuse default regression")
    check(reuse.get("fresh_only_requires_explicit_reason") is True, "FRESH_ONLY reason not required")
    check(reuse.get("stop_destroys_session") is False, "STOP destroys session")
    check(reuse.get("residency_registry_schema") == "SESSION_RESIDENCY_REGISTRY_SCHEMA.json", "session residency schema drift")
    check(reuse.get("native_session_identity_capture") == "MANDATORY_WHEN_PROVIDER_EXPOSES_CONTINUATION_HANDLE", "native session capture drift")
    check(reuse.get("identity_absence") == "EXPLICIT_IDENTITY_UNAVAILABLE", "session identity absence became ambiguous")
    check(reuse.get("worker_identity_substitutes_for_session_identity") is False, "worker identity substitutes for session identity")
    check(reuse.get("candidate_session_resolution") == "RUNTIME_FROM_RESIDENCY_REGISTRY_NOT_STATIC_DESCRIPTOR_GUESS", "candidate-session resolution drift")

    output = compiler.get("output_settlement", {})
    check(output.get("aggregate_normalization") == "FORBIDDEN", "aggregate normalization allowed")
    arts = set(output.get("structured_artifacts", []))
    check({"result.json", "context_receipt.json"} <= arts, "strict settlement omits result or ContextReceipt")

    if failures:
        print(json.dumps({"state": "FAIL", "failures": failures}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({
        "state": "PASS",
        "canonical_dag_schema": canonical,
        "target_mutation_base_source": "CompiledWorkCell.base",
        "structured_artifacts": sorted(arts),
        "mutation_compiler_parity": "REQUIRED_AND_MECHANICALLY_BOUND",
        "constraint_aware_templates": "REQUIRED",
        "session_residency": "REQUIRED_WHEN_ADDRESSABLE",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
