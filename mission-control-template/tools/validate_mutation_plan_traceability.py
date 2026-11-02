#!/usr/bin/env python3
"""Bind structural mutation plans to canonical execution authority.

This validator is intentionally separate from schema validation. A structural
plan is useful only when it names the exact MUTATION cell, requirement set,
repository/base, and bounded write surface that Mission Control will actually
dispatch. It also checks the engineering-ledger trace rows so a requirement
cannot point at a cell that does not carry that requirement.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _norm(value: str) -> str | None:
    """Return a canonical mission-relative scope path or None when unsafe.

    Pure lexical prefix checks are insufficient: ``src/../outside`` starts with
    ``src/`` but escapes that boundary when interpreted by a filesystem. Keep
    this path law aligned with Mission Control's safe-scope model and normalize
    only separator/trailing-slash presentation, never dot traversal.
    """
    normalized = value.replace("\\", "/").rstrip("/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return None
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _inside(path: str, boundary: str) -> bool:
    candidate = _norm(path)
    owner = _norm(boundary)
    if candidate is None or owner is None:
        return False
    return candidate == owner or candidate.startswith(owner + "/")


def _overlap(left: str, right: str) -> bool:
    return _inside(left, right) or _inside(right, left)


def _validate_scope_paths(
    values: list[str],
    *,
    label: str,
    issues: list[str],
) -> None:
    for value in values:
        if _norm(value) is None:
            issues.append(f"{label} contains unsafe relative path {value!r}")


def collect_issues(root: Path) -> list[str]:
    root = root.resolve()
    dag_path = root / "control" / "EXECUTION_DAG.json"
    ledger_path = root / "corpus" / "ENGINEERING_LEDGER.json"
    plans_dir = root / "control" / "structural-mutation-plans"
    issues: list[str] = []
    for path, label in (
        (dag_path, "control/EXECUTION_DAG.json"),
        (ledger_path, "corpus/ENGINEERING_LEDGER.json"),
    ):
        if not path.is_file():
            issues.append(f"missing {label}")
    if issues:
        return issues

    dag = load_json(dag_path)
    ledger = load_json(ledger_path)
    dag_mission = dag.get("mission_id")
    ledger_mission = ledger.get("mission_id")
    if dag_mission != ledger_mission:
        issues.append(
            f"mission identity mismatch: execution DAG={dag_mission!r}, engineering ledger={ledger_mission!r}"
        )

    cells = {
        item.get("cell_id"): item
        for item in dag.get("cells", [])
        if isinstance(item, dict) and isinstance(item.get("cell_id"), str)
    }
    mutation_cells = {
        cell_id: cell for cell_id, cell in cells.items() if cell.get("kind") == "MUTATION"
    }

    traced_cells: set[str] = set()
    cell_requirements_from_ledger: dict[str, set[str]] = {}
    for row in ledger.get("traceability", []):
        if not isinstance(row, dict):
            continue
        requirement_id = row.get("requirement_id")
        for cell_id in row.get("cell_ids", []):
            if not isinstance(cell_id, str):
                continue
            traced_cells.add(cell_id)
            if isinstance(requirement_id, str):
                cell_requirements_from_ledger.setdefault(cell_id, set()).add(requirement_id)

    plans: dict[str, tuple[Path, dict[str, Any]]] = {}
    if plans_dir.is_dir():
        for path in sorted(plans_dir.glob("*.json")):
            try:
                plan = load_json(path)
            except Exception as exc:
                issues.append(f"{path.relative_to(root)}: {exc}")
                continue
            cell_id = plan.get("cell_id")
            if not isinstance(cell_id, str) or not cell_id:
                issues.append(f"{path.relative_to(root)}: missing cell_id")
                continue
            if path.stem != cell_id:
                issues.append(
                    f"{path.relative_to(root)}: filename must equal cell_id ({cell_id}.json)"
                )
            if cell_id in plans:
                issues.append(f"duplicate structural mutation plans for cell {cell_id}")
                continue
            plans[cell_id] = (path, plan)

    for cell_id in sorted(traced_cells):
        cell = cells.get(cell_id)
        if cell is None:
            issues.append(f"engineering ledger traces unknown cell {cell_id}")
            continue
        if cell.get("kind") != "MUTATION":
            issues.append(
                f"engineering ledger traces non-mutation cell {cell_id} as implementation work"
            )
            continue
        cell_requirements = {
            item for item in cell.get("requirement_ids", []) if isinstance(item, str)
        }
        ledger_requirements = cell_requirements_from_ledger.get(cell_id, set())
        missing_from_cell = sorted(ledger_requirements - cell_requirements)
        if missing_from_cell:
            issues.append(
                f"engineering ledger maps {cell_id} to requirements absent from the canonical cell: "
                f"{missing_from_cell}"
            )
        if cell_id not in plans:
            issues.append(f"mutation cell {cell_id} lacks structural mutation plan")

    for cell_id, (path, plan) in sorted(plans.items()):
        cell = mutation_cells.get(cell_id)
        if cell is None:
            issues.append(f"structural mutation plan {cell_id} has no canonical MUTATION cell")
            continue
        if cell_id not in traced_cells:
            issues.append(
                f"structural mutation plan {cell_id} is not referenced by engineering-ledger traceability"
            )

        if plan.get("mission_id") != dag_mission:
            issues.append(
                f"plan {cell_id} mission_id {plan.get('mission_id')!r} differs from DAG mission {dag_mission!r}"
            )

        cell_requirement_ids = {
            item for item in cell.get("requirement_ids", []) if isinstance(item, str)
        }
        plan_requirement_ids = plan.get("requirement_ids")
        if not isinstance(plan_requirement_ids, list) or not plan_requirement_ids:
            issues.append(f"plan {cell_id} lacks requirement_ids binding")
        else:
            normalized_requirements = {
                item for item in plan_requirement_ids if isinstance(item, str)
            }
            if normalized_requirements != cell_requirement_ids:
                issues.append(
                    f"plan {cell_id} requirement_ids {sorted(normalized_requirements)} differ from "
                    f"canonical cell {sorted(cell_requirement_ids)}"
                )

        target = cell.get("target", {})
        repository = target.get("repository") if isinstance(target, dict) else None
        base_sha = str(target.get("base_sha", "")).lower() if isinstance(target, dict) else ""
        if plan.get("repository") != repository:
            issues.append(
                f"plan {cell_id} repository {plan.get('repository')!r} differs from cell target {repository!r}"
            )
        if str(plan.get("base_sha", "")).lower() != base_sha:
            issues.append(f"plan {cell_id} base_sha differs from canonical cell base")

        owned_boundaries = [
            item for item in (target.get("owned_paths", []) if isinstance(target, dict) else [])
            if isinstance(item, str)
        ]
        _validate_scope_paths(
            owned_boundaries,
            label=f"canonical mutation cell {cell_id} owned_paths",
            issues=issues,
        )
        for surface in plan.get("surfaces", []):
            if not isinstance(surface, dict):
                continue
            surface_id = surface.get("surface_id")
            surface_owned = [
                item for item in surface.get("owned_paths", []) if isinstance(item, str)
            ]
            affected = [
                item for item in surface.get("expected_affected", []) if isinstance(item, str)
            ]
            unaffected = [
                item for item in surface.get("expected_unaffected", []) if isinstance(item, str)
            ]
            excluded = [
                item for item in surface.get("excluded_boundaries", []) if isinstance(item, str)
            ]
            for values, field in (
                (surface_owned, "owned_paths"),
                (affected, "expected_affected"),
                (unaffected, "expected_unaffected"),
                (excluded, "excluded_boundaries"),
            ):
                _validate_scope_paths(
                    values,
                    label=f"plan {cell_id} surface {surface_id} {field}",
                    issues=issues,
                )

            for owned_path in surface_owned:
                if not any(_inside(owned_path, boundary) for boundary in owned_boundaries):
                    issues.append(
                        f"plan {cell_id} surface {surface_id} path {owned_path!r} escapes canonical cell owned_paths"
                    )

            for affected_path in affected:
                if not any(_inside(affected_path, boundary) for boundary in surface_owned):
                    issues.append(
                        f"plan {cell_id} surface {surface_id} expected_affected {affected_path!r} "
                        "escapes the surface owned_paths"
                    )
                if not any(_inside(affected_path, boundary) for boundary in owned_boundaries):
                    issues.append(
                        f"plan {cell_id} surface {surface_id} expected_affected {affected_path!r} "
                        "escapes canonical cell owned_paths"
                    )
                if any(_overlap(affected_path, boundary) for boundary in excluded):
                    issues.append(
                        f"plan {cell_id} surface {surface_id} expected_affected {affected_path!r} "
                        "overlaps an excluded boundary"
                    )
                if any(_overlap(affected_path, boundary) for boundary in unaffected):
                    issues.append(
                        f"plan {cell_id} surface {surface_id} expected_affected {affected_path!r} "
                        "overlaps expected_unaffected"
                    )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    issues = collect_issues(Path(args.root))
    if issues:
        for item in issues:
            print(f"ERROR: {item}")
        return 1
    print("mutation plan traceability valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
