#!/usr/bin/env python3
"""Run the complete high-assurance Mission Control engineering gate.

Individual validators remain useful diagnostics. This command is the canonical
aggregate gate for missions that adopt the high-assurance engineering contract,
so collection coverage, source-evidence custody, CI-waiver custody, semantic
engineering closure, rights closure, and structural-plan execution traceability
cannot accidentally be qualified in isolation.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

import validate_ci_waiver_evidence
import validate_engineering_contracts
import validate_engineering_rights
import validate_mutation_plan_traceability
import validate_source_collections
import validate_source_surface_evidence


IssueCollector = Callable[[], list[str]]


def collect_issues(root: Path, phase: str) -> list[str]:
    root = root.resolve()
    checks: list[tuple[str, IssueCollector]] = [
        (
            "source_collections",
            lambda: validate_source_collections.collect_issues(root, phase),
        ),
        (
            "source_surface_evidence",
            lambda: validate_source_surface_evidence.collect_issues(root, phase),
        ),
        (
            "engineering_contracts",
            lambda: validate_engineering_contracts.collect_issues(root, phase),
        ),
        (
            "engineering_rights",
            lambda: validate_engineering_rights.collect_issues(root),
        ),
        (
            "ci_waiver_evidence",
            lambda: validate_ci_waiver_evidence.collect_issues(root),
        ),
    ]

    # A design may be intentionally validated before the mutation frontier is
    # compiled. From pre-mutation onward, execution-plan traceability is
    # mandatory and cannot be skipped merely because the plan directory or DAG
    # was omitted.
    if phase in {"pre-mutation", "qualification"}:
        checks.append(
            (
                "mutation_plan_traceability",
                lambda: validate_mutation_plan_traceability.collect_issues(root),
            )
        )

    issues: list[str] = []
    for name, collector in checks:
        try:
            component_issues = collector()
        except Exception as exc:
            issues.append(f"{name}: validator failed: {exc}")
            continue
        issues.extend(f"{name}: {item}" for item in component_issues)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--phase",
        choices=("design", "pre-mutation", "qualification"),
        default="design",
    )
    args = parser.parse_args()
    issues = collect_issues(Path(args.root), args.phase)
    if issues:
        for item in issues:
            print(f"ERROR: {item}")
        return 1
    print(f"high-assurance engineering gate valid for phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
