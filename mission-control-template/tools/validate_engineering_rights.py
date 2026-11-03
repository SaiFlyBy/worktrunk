#!/usr/bin/env python3
"""Cross-check engineering-ledger implementation reuse against canonical source rights.

The provenance-synthesis contract remains the authority for source review and
rights admission. This validator closes the later engineering-ledger boundary:
a ledger entry may not claim direct/adapted implementation reuse unless every
named reuse source authorizes it at the exact admitted source record, and source
obligations may not disappear during target synthesis.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REUSE_IMPLEMENTATION_MODES = {"ADAPTED_IMPLEMENTATION", "DIRECT_REUSE", "MIXED"}
COPY_CAPABLE_SOURCE_MODES = {"OWNER_AUTHORIZED_REUSE", "LICENSE_PERMITTED_REUSE"}
COPY_CAPABLE_LEDGER_MODES = {
    "OWNER_AUTHORIZED_REUSE", "LICENSE_PERMITTED_REUSE", "MIXED_RIGHTS_AWARE_SYNTHESIS"
}
NONCOPY_IMPLEMENTATION_MODES = {"PARAPHRASED_SYNTHESIS", "NONE"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def collect_issues(root: Path) -> list[str]:
    root = root.resolve()
    sources_path = root / "corpus" / "SOURCES.json"
    ledger_path = root / "corpus" / "ENGINEERING_LEDGER.json"
    issues: list[str] = []
    if not sources_path.is_file():
        issues.append("missing corpus/SOURCES.json")
    if not ledger_path.is_file():
        issues.append("missing corpus/ENGINEERING_LEDGER.json")
    if issues:
        return issues

    sources_doc = load_json(sources_path)
    ledger = load_json(ledger_path)
    sources = {
        item.get("id"): item
        for item in sources_doc.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    for entry in ledger.get("entries", []):
        if not isinstance(entry, dict):
            continue
        mechanism_id = str(entry.get("mechanism_id"))
        implementation = entry.get("implementation", {})
        rights = entry.get("rights", {})
        reuse_mode = implementation.get("reuse_mode") if isinstance(implementation, dict) else None
        reuse_source_ids = rights.get("reuse_source_ids", []) if isinstance(rights, dict) else []
        source_ids = entry.get("source_ids", [])
        use_mode = rights.get("use_mode") if isinstance(rights, dict) else None
        ledger_obligations = set(rights.get("obligations", [])) if isinstance(rights, dict) else set()
        notice_refs = rights.get("notice_or_attribution_refs", []) if isinstance(rights, dict) else []

        unknown_entry_sources = sorted(set(source_ids) - set(sources))
        if unknown_entry_sources:
            issues.append(f"{mechanism_id}: unknown source_ids {unknown_entry_sources}")
        unknown_reuse_sources = sorted(set(reuse_source_ids) - set(sources))
        if unknown_reuse_sources:
            issues.append(f"{mechanism_id}: unknown reuse_source_ids {unknown_reuse_sources}")
        outside_lineage = sorted(set(reuse_source_ids) - set(source_ids))
        if outside_lineage:
            issues.append(f"{mechanism_id}: reuse_source_ids are outside mechanism source_ids: {outside_lineage}")

        if reuse_mode in REUSE_IMPLEMENTATION_MODES:
            if not reuse_source_ids:
                issues.append(f"{mechanism_id}: {reuse_mode} requires at least one reuse_source_id")
            if use_mode not in COPY_CAPABLE_LEDGER_MODES:
                issues.append(
                    f"{mechanism_id}: {reuse_mode} cannot use ledger rights mode {use_mode!r}"
                )
        elif reuse_mode in NONCOPY_IMPLEMENTATION_MODES:
            if reuse_source_ids:
                issues.append(
                    f"{mechanism_id}: {reuse_mode} must not name implementation reuse_source_ids"
                )
        else:
            issues.append(f"{mechanism_id}: unknown implementation reuse_mode {reuse_mode!r}")

        source_obligations: set[str] = set()
        for source_id in reuse_source_ids:
            source = sources.get(source_id)
            if not isinstance(source, dict):
                continue
            copyright_record = source.get("copyright")
            if not isinstance(copyright_record, dict):
                issues.append(f"{mechanism_id}: reuse source {source_id} lacks copyright record")
                continue
            source_mode = copyright_record.get("usage_mode")
            rights_status = copyright_record.get("rights_status")
            if rights_status != "VERIFIED":
                issues.append(
                    f"{mechanism_id}: reuse source {source_id} rights are not VERIFIED: {rights_status!r}"
                )
            if source_mode not in COPY_CAPABLE_SOURCE_MODES:
                issues.append(
                    f"{mechanism_id}: reuse source {source_id} usage_mode {source_mode!r} does not authorize implementation reuse"
                )
            if reuse_mode in REUSE_IMPLEMENTATION_MODES and copyright_record.get("code_copy_allowed") is not True:
                issues.append(
                    f"{mechanism_id}: reuse source {source_id} does not authorize code copy/adaptation"
                )
            if reuse_mode in {"ADAPTED_IMPLEMENTATION", "MIXED"} and copyright_record.get("structure_reuse_allowed") is not True:
                issues.append(
                    f"{mechanism_id}: reuse source {source_id} does not authorize structural adaptation"
                )
            source_obligations.update(copyright_record.get("obligations", []))

        missing_obligations = sorted(source_obligations - ledger_obligations)
        if missing_obligations:
            issues.append(
                f"{mechanism_id}: engineering ledger drops source obligations: {missing_obligations}"
            )
        if ledger_obligations and not notice_refs and reuse_mode in REUSE_IMPLEMENTATION_MODES:
            issues.append(
                f"{mechanism_id}: implementation reuse has obligations but no notice_or_attribution_refs"
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
    print("engineering rights closure valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
