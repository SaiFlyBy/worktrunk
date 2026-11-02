#!/usr/bin/env python3
"""Generic fail-closed mutation-frontier descriptor preflight.

Instantiate mission-specific schema names/paths as needed, but preserve these invariants:
exact durable mutation-ready frontier, topology dependency/conflict agreement, exact target
baseline, non-overlapping authored write ownership unless explicitly modeled, and evidence-backed reuse.
The durable runnable frontier may also contain evaluation/readout cells; mutation descriptors bind
only the mutation-ready subset while coherence continues to account for the full runnable frontier.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("descriptor", type=Path)
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--current", default="control/CURRENT_AUTHORITY.json")
    p.add_argument("--topology", default="control/PARALLEL_EXECUTION_DAG.json")
    p.add_argument("--state", default="control/EXECUTION_STATE.json")
    args = p.parse_args()

    try:
        root = args.root
        desc = load(args.descriptor)
        current = load(root / args.current)
        topology = load(root / args.topology)
        state = load(root / args.state)

        cells = desc.get("cells", [])
        ids = [c.get("id") for c in cells]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate descriptor cell id")

        topo_cells = {c.get("id"): c for c in topology.get("cells", [])}
        frontier = state.get("next_frontier", {})
        durable_ready = frontier.get("dependency_ready", [])
        mutation_ready = frontier.get("mutation_ready")
        if mutation_ready is None:
            mutation_ready = [
                cid for cid in durable_ready
                if topo_cells.get(cid, {}).get("kind") in {"MUTATION", "OPTIONAL_MUTATION"}
            ]
        if not set(mutation_ready) <= set(durable_ready):
            raise ValueError("mutation_ready is not a subset of dependency_ready")
        if any(topo_cells.get(cid, {}).get("kind") not in {"MUTATION", "OPTIONAL_MUTATION"} for cid in mutation_ready):
            raise ValueError("mutation_ready contains non-mutation cell")
        if sorted(ids) != sorted(mutation_ready):
            raise ValueError(f"descriptor cell set != durable mutation-ready frontier: descriptor={sorted(ids)} mutation_ready={sorted(mutation_ready)}")

        target_baseline = current.get("target_baseline")
        if target_baseline is not None and desc.get("target_base") != target_baseline:
            raise ValueError("descriptor target base != CURRENT_AUTHORITY target baseline")

        owned: dict[str, str] = {}
        for cell in cells:
            cid = cell["id"]
            topo = topo_cells.get(cid)
            if topo is None:
                raise ValueError(f"{cid}: absent from canonical topology")
            if topo.get("kind") not in {"MUTATION", "OPTIONAL_MUTATION"}:
                raise ValueError(f"{cid}: not a mutation cell")
            if cell.get("conflict_class") != topo.get("conflict_class"):
                raise ValueError(f"{cid}: conflict class mismatch")
            declared = sorted(d.get("id") for d in cell.get("dependencies", []))
            expected = sorted(topo.get("depends_on", []))
            if declared != expected:
                raise ValueError(f"{cid}: dependency mismatch expected={expected} declared={declared}")
            if any(not d.get("evidence_ref") for d in cell.get("dependencies", [])):
                raise ValueError(f"{cid}: dependency without evidence_ref")
            if not cell.get("owned_write_scope"):
                raise ValueError(f"{cid}: empty owned_write_scope")
            for path in cell["owned_write_scope"]:
                if path in owned:
                    raise ValueError(f"accidental exact write overlap: {path} owned by {owned[path]} and {cid}")
                owned[path] = cid

            reuse = cell.get("reuse_adjudication")
            if reuse is not None:
                source_ref = reuse.get("source_context_receipt_ref")
                if not isinstance(source_ref, str):
                    raise ValueError(f"{cid}: reuse source receipt missing")
                receipt_path = root / source_ref
                if not receipt_path.is_file():
                    raise ValueError(f"{cid}: reuse source receipt does not exist: {source_ref}")
                receipt = load(receipt_path)
                consumed = set(receipt.get("consumed_manifest_paths", []) or receipt.get("consumed", []))
                already = set(reuse.get("already_covered", []))
                if not already <= consumed:
                    raise ValueError(f"{cid}: ALREADY_COVERED exceeds immutable source receipt")
                if not already <= set(cell.get("target_context", [])):
                    raise ValueError(f"{cid}: ALREADY_COVERED exceeds target cell context")
                if reuse.get("receipt_rewritten", False):
                    raise ValueError(f"{cid}: source receipt rewrite forbidden")

        print(json.dumps({"state":"PASS","frontier_id":desc.get("frontier_id"),"durable_ready":durable_ready,"mutation_ready":mutation_ready,"cells":len(cells),"write_paths":len(owned)}, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"state":"FAIL","error":str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
