#!/usr/bin/env python3
"""Generic deterministic product-mutation frontier compiler template.

`--check` and materialization share the exact same in-memory per-cell compilation path.
An instantiated mission supplies exact target-requirement mappings and scopes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from compile_frontier import canonical
from schema_template import template_value
from validate_json_schema_subset import validate, validate_schema_keywords

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = ROOT / "mission-control-template"


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise ValueError(msg)


def load(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(obj, dict), f"{path} must contain an object")
    return obj


def validate_instance(name: str, value: Any, schema: dict[str, Any], cid: str) -> None:
    errors = validate(value, schema, schema)
    require(not errors, f"{cid}: generated {name} invalid: {errors}")


def build_manifest(desc: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    target, control = desc["target_base"], desc["control_base"]
    items: list[dict[str, Any]] = []
    idx = 1
    for locator in cell["target_context"]:
        items.append({"context_id":f"{cell['id']}-{idx:02d}","kind":"FILE","source":target["repository"],"locator":locator,"version":target["head"],"purpose":f"Pinned target implementation context for {cell['id']}","requirement":"REQUIRED","freshness":f"PINNED_EXACT_COMMIT:{target['head']}","influence_class":"TARGET_SOURCE"})
        idx += 1
    for locator in cell["control_context"]:
        items.append({"context_id":f"{cell['id']}-{idx:02d}","kind":"RECEIPT" if "receipt" in locator.lower() or "evidence" in locator.lower() else "FILE","source":control["repository"],"locator":locator,"version":control["head"],"purpose":f"Accepted Mission Control authority/evidence for {cell['id']}","requirement":"REQUIRED","freshness":f"PINNED_CONTROL_COMMIT:{control['head']}","influence_class":"CONTROL_AUTHORITY_OR_ACCEPTED_EVIDENCE"})
        idx += 1
    return {"schema":"flyby/mission-control-context-manifest/1","manifest_id":f"{desc['frontier_id']}-{cell['id']}","cell_id":cell["id"],"base_head":target["head"],"items":items,"capsules":[],"manifest_hash_policy":"CANONICAL_JSON_SHA256"}


def build_receipt_template(desc: dict[str, Any], cell: dict[str, Any], manifest_ref: str, base_template: dict[str, Any]) -> dict[str, Any]:
    obj = json.loads(json.dumps(base_template))
    obj.update({"schema":"flyby/mission-control-context-receipt/1","receipt_id":f"{desc['frontier_id']}-{cell['id']}-CONTEXT","cell_id":cell["id"],"worker":{"identity":"<WORKER_ID>","session_id":None},"base_head":desc["target_base"]["head"],"manifest_ref":manifest_ref,"manifest_hash":None,"consumed":[],"partial_or_unavailable":[],"approved_extra_context":[],"capsules_used":[],"assumptions":[],"unknowns":[],"semantic_coverage":[],"explicitly_not_covered":[],"estimated_context_consumed":None,"compaction_or_restart_events":[],"safe_reuse_scope":[],"unsafe_reuse_scope":[],"continuation":{"session_reusable":False,"session_id":None,"reason":"<WORKER_FILL>"}})
    return obj


def compile_cell(desc: dict[str, Any], cell: dict[str, Any], destination: Path, requirement_map: dict[str, Any], schemas: dict[str, dict[str, Any]], hashes: dict[str, str], bases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cid = cell["id"]
    expected = sorted(requirement_map.get(cid, []))
    declared = sorted(cell.get("applicable_target_requirements", []))
    require(declared == expected, f"{cid}: target requirement set mismatch expected={expected} declared={declared}")
    for field in ("target_context", "control_context", "owned_write_scope", "conflict_class", "dependencies", "core_mutation_contract"):
        require(field in cell, f"{cid}: missing {field}")
    require(cell["target_context"] and cell["owned_write_scope"], f"{cid}: target context/write scope cannot be empty")

    root = destination / desc["frontier_id"] / cid
    paths = {"core":root/"core_mutation_contract.json","manifest":root/"context_manifest.json","result_schema":root/"result_schema.json","result_template":root/"result_template.json","receipt_schema":root/"context_receipt_schema.json","receipt_template":root/"context_receipt_template.json","reuse":root/"reuse_adjudication.json","workcell":root/"workcell.json","context_receipt":root/"context_receipt.json"}

    core = dict(cell["core_mutation_contract"])
    core.update({"schema":"flyby/mission-control-core-mutation-contract/1","contract_id":f"{desc['frontier_id']}-{cid}-CORE","cell_id":cid,"target_base":desc["target_base"],"owned_write_scope":cell["owned_write_scope"],"applicable_target_requirements":declared,"conflict_class":cell["conflict_class"]})
    validate_instance("core mutation contract", core, schemas["core"], cid)

    manifest = build_manifest(desc, cell)
    validate_instance("context manifest", manifest, schemas["manifest"], cid)

    result_tpl = json.loads(json.dumps(bases["result"]))
    fill = {"cell_id":cid,"target_base":desc["target_base"]["head"],"core_contract_ref":paths["core"].as_posix(),"context_receipt_ref":paths["context_receipt"].as_posix(),"stop_confirmed":False}
    for key, value in fill.items():
        if key in schemas["result"].get("properties", {}):
            result_tpl[key] = value
    if "applicable_target_requirements" in schemas["result"].get("properties", {}):
        result_tpl["applicable_target_requirements"] = declared
    validate_instance("result template", result_tpl, schemas["result"], cid)

    receipt_tpl = build_receipt_template(desc, cell, paths["manifest"].as_posix(), bases["receipt"])
    validate_instance("context receipt template", receipt_tpl, schemas["receipt"], cid)

    reuse_obj: dict[str, Any] | None = None
    reuse_ref: str | None = None
    if cell.get("reuse_adjudication") is not None:
        reuse_obj = dict(cell["reuse_adjudication"])
        reuse_obj.update({"schema":"flyby/mission-control-session-reuse-adjudication/1","adjudication_id":f"{desc['frontier_id']}-{cid}-REUSE","target_cell":cid,"target_base":desc["target_base"]["head"],"receipt_rewritten":False,"authority_law":"Reuse may extend compiler routing permission for proven context coverage but never rewrites the source receipt, transfers prior cell authority, or skips the new workcell/context contract."})
        validate_instance("reuse adjudication", reuse_obj, schemas["reuse"], cid)
        reuse_ref = paths["reuse"].as_posix()

    requirement_refs = cell.get("target_requirement_acceptance_refs", {})
    bindings = [{"id":rid,"acceptance_refs":requirement_refs.get(rid,[f"target-requirement:{rid}"])} for rid in declared]
    result_validate = f"python {desc['result_validator']} {paths['result_schema'].as_posix()} <CELL_CONTROL_OUTPUT_ROOT>/result.json"
    receipt_validate = f"python {desc['result_validator']} {paths['receipt_schema'].as_posix()} <CELL_CONTROL_OUTPUT_ROOT>/context_receipt.json"
    workcell = {"schema":"flyby/mission-control-workcell/1","cell_id":cid,"source_dag_cell":cid,"compiler":{"identity":"MISSION_CONTROL_DETERMINISTIC_MUTATION_FRONTIER_COMPILER","version":"3"},"base":desc["target_base"],"objective":core["objective"],"why_ready":cell.get("why_ready","Dependencies accepted in durable execution state."),"core_mutation_contract_ref":paths["core"].as_posix(),"target_requirement_bindings":bindings,"reuse_adjudication_ref":reuse_ref,"acceptance":core["acceptance"]+[f"Satisfy target requirement {rid} acceptance." for rid in declared],"negative_tests":core["negative_tests"],"owned_scope":cell["owned_write_scope"],"prohibited_scope":core["prohibited_scope"],"semantic_authority":["IMPLEMENT_EXACT_CORE_MUTATION_CONTRACT","SATISFY_APPLICABLE_TARGET_REQUIREMENTS","REPAIR_WITHIN_OWNED_SCOPE_ONLY","NO_NEXT_CELL_AUTHORITY"],"conflict_class":cell["conflict_class"],"dependencies":[{"id":d["id"],"receipt_ref":d["evidence_ref"]} for d in cell["dependencies"]],"context_manifest_ref":paths["manifest"].as_posix(),"allowed_context_expansion":"APPROVED_AMENDMENT_ONLY","mutation_policy":"MUTATION_REQUIRED","result_contract":{"schema_ref":paths["result_schema"].as_posix(),"schema_sha256":hashes["result"],"template_ref":paths["result_template"].as_posix(),"precommit_validator":result_validate,"representation_repair_policy":"SAME_ATTEMPT_CORRECTION_BEFORE_SETTLEMENT"},"context_receipt_contract":{"schema_ref":paths["receipt_schema"].as_posix(),"schema_sha256":hashes["receipt"],"template_ref":paths["receipt_template"].as_posix(),"precommit_validator":receipt_validate,"representation_repair_policy":"SAME_ATTEMPT_CORRECTION_BEFORE_SETTLEMENT"},"local_verification":core["verification"]+["all changed target paths are inside owned_scope","result and context receipt validate before settlement","git diff --check passes"],"return_contract":["result.json","context_receipt.json","REPORT.md","target branch/head","STOP_CELL_NOT_SESSION"],"stop_condition":"Finish this cell and stop its authority. The orchestrator may separately rebind a still-valid session.","session_reuse_policy":{"mode":"REUSE_IF_RECEIPT_MATCHES","candidate_session":None,"minimum_safe_reuse_scope":[],"preferred_peer_cells":cell.get("preferred_peer_cells",[]),"fresh_session_reason":None}}
    validate_instance("workcell", workcell, schemas["workcell"], cid)

    return {"paths":paths,"core":core,"manifest":manifest,"result_template":result_tpl,"receipt_template":receipt_tpl,"reuse":reuse_obj,"workcell":workcell,"index":{"cell_id":cid,"workcell":paths["workcell"].as_posix(),"core_mutation_contract":paths["core"].as_posix(),"context_manifest":paths["manifest"].as_posix(),"result_schema_sha256":hashes["result"],"context_receipt_schema_sha256":hashes["receipt"],"reuse_adjudication":reuse_ref,"owned_write_scope":cell["owned_write_scope"],"applicable_target_requirements":declared}}


def write_compiled(compiled: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> None:
    paths: dict[str, Path] = compiled["paths"]
    paths["workcell"].parent.mkdir(parents=True, exist_ok=True)
    payloads = {"core":compiled["core"],"manifest":compiled["manifest"],"result_schema":schemas["result"],"result_template":compiled["result_template"],"receipt_schema":schemas["receipt"],"receipt_template":compiled["receipt_template"],"workcell":compiled["workcell"]}
    if compiled["reuse"] is not None:
        payloads["reuse"] = compiled["reuse"]
    for key, value in payloads.items():
        paths[key].write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("descriptor", type=Path)
    p.add_argument("--destination", type=Path, default=Path(".mission-control/compiled"))
    p.add_argument("--cell", action="append", default=[])
    p.add_argument("--check", action="store_true")
    args = p.parse_args()

    desc = load(args.descriptor)
    require(desc.get("schema") == "flyby/mission-control-mutation-frontier-descriptor/1", "unexpected mutation descriptor schema")
    schema_paths = {"core":TEMPLATE/"CORE_MUTATION_CONTRACT_SCHEMA.json","workcell":TEMPLATE/"WORKCELL_SCHEMA.json","manifest":TEMPLATE/"CONTEXT_MANIFEST_SCHEMA.json","receipt":TEMPLATE/"CONTEXT_RECEIPT_SCHEMA.json","reuse":TEMPLATE/"SESSION_REUSE_ADJUDICATION_SCHEMA.json","result":ROOT/desc["result_schema"]}
    schemas = {name:load(path) for name,path in schema_paths.items()}
    for schema in schemas.values():
        validate_schema_keywords(schema)
    hashes = {"result":hashlib.sha256(canonical(schemas["result"])).hexdigest(),"receipt":hashlib.sha256(canonical(schemas["receipt"])).hexdigest()}
    result_base = template_value(schemas["result"], schemas["result"])
    receipt_base = template_value(schemas["receipt"], schemas["receipt"])
    require(isinstance(result_base,dict) and isinstance(receipt_base,dict), "structured schemas must produce object templates")
    bases = {"result":result_base,"receipt":receipt_base}

    requirement_map = desc.get("target_requirement_map", {})
    require(isinstance(requirement_map,dict), "target_requirement_map must be an object")
    selected = set(args.cell) if args.cell else None
    known = {c.get("id") for c in desc.get("cells",[])}
    if selected is not None:
        require(not (selected-known), f"unknown cells: {sorted(selected-known)}")
    cells = [c for c in desc.get("cells",[]) if selected is None or c.get("id") in selected]
    require(cells, "no cells selected")

    compiled = [compile_cell(desc,cell,args.destination,requirement_map,schemas,hashes,bases) for cell in cells]
    if args.check:
        print(json.dumps({"state":"PASS","frontier_id":desc["frontier_id"],"cells":len(compiled),"full_packet_dry_run":"PASS","check_materialization_parity":"SAME_COMPILE_CELL_PATH","core_contracts":"SCHEMA_VALID","context_manifests":"SCHEMA_VALID","result_templates":"SCHEMA_VALID","context_receipt_templates":"SCHEMA_VALID","reuse_adjudications":"SCHEMA_VALID","workcells":"SCHEMA_VALID","target_requirement_bindings":"EXACT"}))
        return 0

    for item in compiled:
        write_compiled(item, schemas)
    root = args.destination / desc["frontier_id"]
    root.mkdir(parents=True, exist_ok=True)
    out = root / "INDEX.json"
    out.write_text(json.dumps({"schema":"flyby/mission-control-compiled-mutation-frontier-index/3","cells":[item["index"] for item in compiled]}, indent=2)+"\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
