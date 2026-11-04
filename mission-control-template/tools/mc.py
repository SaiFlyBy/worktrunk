#!/usr/bin/env python3
"""Mission Control v16 operator CLI and reusable structural checks.

Standard-library only by design. Operators use this file; internal template details
are compiled into a mission during `init`.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
from schema_subset import validate as validate_schema_instance, validate_schema_keywords

TEMPLATE_SCHEMA = "flyby/mission-control-template/16"
MISSION_SCHEMA = "flyby/mission-control-mission/16"
RESULT_SCHEMA = "flyby/mission-control-result/16"
STATE_SCHEMA = "flyby/mission-control-execution-state/16"
DAG_SCHEMA = "flyby/mission-control-execution-dag/16"
AUTHORITY_SCHEMA = "flyby/mission-control-authority/16"
FRONTIER_SCHEMA = "flyby/mission-control-frontier/16"
BARRIER_ACCEPTANCE = "all dependencies are ACCEPTED"
LIFECYCLE = (
    "BOOTSTRAPPED",
    "BASELINE_READY",
    "BASELINE_ACCEPTED",
    "MUTATION_READY",
    "INTEGRATING",
    "QUALIFYING",
    "ACCEPTED",
    "CLOSED",
)
CELL_STATES = {
    "PENDING", "COMPILED", "DISPATCHED", "CANDIDATE", "ACCEPTED",
    "REJECTED", "BLOCKED", "FAILED", "STALE", "SUPERSEDED", "CANCELLED",
}
BASELINE_AUDITS = {
    "A000": "Inventory required tests, CI, skips, expected failures and verification commands.",
    "A001": "Capture reproducible performance and resource baselines with raw evidence references.",
    "A002": "Inventory architecture, authority boundaries, persistent state and runtime ownership.",
    "A003": "Inventory admitted provenance, source pins, licenses and source-to-requirement lineage.",
    "A004": "Inventory execution environment, runner/provider capabilities and hard platform constraints.",
}
FORBIDDEN_V16_MIRRORS = (
    "00_CURRENT_AUTHORITY.json",
    "CANONICAL_EXECUTION_DAG.json",
    "EXECUTION_STATE.json",
    "template",
)
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
GENERATED_ASSET_ROOTS = (
    "contracts/schemas",
    "contracts/policies",
    "runtime/tools",
    "runtime/tests",
)


def _safe_scope_path(value: str) -> bool:
    if not value or value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        return False
    normalized = value.replace("\\", "/")
    return all(segment not in {"", ".", ".."} for segment in normalized.split("/"))


def generated_asset_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for rel_root in GENERATED_ASSET_ROOTS:
        asset_root = root / rel_root
        if not asset_root.is_dir():
            continue
        for path in asset_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if "__pycache__" in relative.parts or path.suffix == ".pyc":
                continue
            files[relative.as_posix()] = path
    return files


@contextlib.contextmanager
def mission_control_lock(root: Path, timeout_seconds: float = 30.0):
    resolved = root.resolve()
    lock_dir = Path(tempfile.gettempdir()) / "flyby-mission-control-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).hexdigest()
    lock_path = lock_dir / f"{key}.lock"
    handle = lock_path.open("a+b")
    if lock_path.stat().st_size == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + timeout_seconds
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            while not locked:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Mission Control lock timeout for {resolved}")
                    time.sleep(0.05)
        else:
            import fcntl
            while not locked:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Mission Control lock timeout for {resolved}")
                    time.sleep(0.05)
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_immutable_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        existing = load_json(path)
        if existing != value:
            raise ValueError(f"immutable evidence conflict at {path}")
        return
    write_json(path, value)


def schema_errors(root: Path, schema_ref: str, value: Any) -> list[str]:
    schema_path = resolve_ref(root, schema_ref)
    schema = load_json(schema_path)
    validate_schema_keywords(schema)
    return validate_schema_instance(value, schema, schema, schema_path=schema_path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_ref(root: Path, ref: str) -> Path:
    base = root.resolve()
    candidate = Path(ref)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    elif candidate.parts and candidate.parts[0] == base.name:
        resolved = (base.parent / candidate).resolve()
    else:
        resolved = (base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"mission reference escapes root: {ref}")
    return resolved


def issue(code: str, message: str, likely: str, repair: str) -> dict[str, str]:
    return {"code": code, "message": message, "likely": likely, "repair": repair}


def valid_control_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        and all(char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in value)
        and value not in WINDOWS_RESERVED_NAMES
    )


def validate_mission_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema", "mission_id", "control_repository", "authoritative_working_branch",
        "target_repositories", "previous_mission_handoff", "previous_mission_handoff_sha256", "owner_intent", "hard_boundaries",
    }
    unknown = set(spec) - required
    missing = required - set(spec)
    if unknown:
        errors.append(f"unknown MISSION.json fields: {sorted(unknown)}")
    if missing:
        errors.append(f"missing MISSION.json fields: {sorted(missing)}")
    if spec.get("schema") != MISSION_SCHEMA:
        errors.append(f"schema must be {MISSION_SCHEMA}")
    for name in ("mission_id", "control_repository", "authoritative_working_branch"):
        if not isinstance(spec.get(name), str) or not spec.get(name, "").strip():
            errors.append(f"{name} must be a non-empty string")
    targets = spec.get("target_repositories")
    if not isinstance(targets, list) or not targets:
        errors.append("target_repositories must be a non-empty list")
    else:
        repositories: list[str] = []
        for index, target in enumerate(targets):
            if not isinstance(target, dict) or set(target) != {"repository", "baseline_sha"}:
                errors.append(f"target_repositories[{index}] must contain only repository and baseline_sha")
                continue
            repository = target["repository"]
            if not isinstance(repository, str) or not repository.strip():
                errors.append(f"target_repositories[{index}].repository must be non-empty")
            else:
                repositories.append(repository)
            value = target["baseline_sha"]
            if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdefABCDEF" for c in value):
                errors.append(f"target_repositories[{index}].baseline_sha must be a 40-hex SHA")
        duplicates = sorted({repo for repo in repositories if repositories.count(repo) > 1})
        if duplicates:
            errors.append(f"target_repositories contains duplicate repository identities: {duplicates}")
        control_repository = spec.get("control_repository")
        if isinstance(control_repository, str) and control_repository in repositories:
            errors.append("control_repository must not also be a target repository; control and target custody are separate")
    intents = spec.get("owner_intent")
    if not isinstance(intents, list) or not intents or not all(isinstance(x, str) and x.strip() for x in intents):
        errors.append("owner_intent must contain at least one non-empty string")
    bounds = spec.get("hard_boundaries")
    if not isinstance(bounds, list) or not all(isinstance(x, str) and x.strip() for x in bounds):
        errors.append("hard_boundaries must be a list of non-empty strings")
    handoff = spec.get("previous_mission_handoff")
    handoff_sha = spec.get("previous_mission_handoff_sha256")
    if handoff is not None and not isinstance(handoff, str):
        errors.append("previous_mission_handoff must be a string or null")
    if handoff:
        if not isinstance(handoff_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", handoff_sha):
            errors.append("previous_mission_handoff_sha256 must be a 64-lowercase-hex digest when previous_mission_handoff is set")
    elif handoff_sha is not None:
        errors.append("previous_mission_handoff_sha256 must be null when previous_mission_handoff is null")
    return errors


def _accepted_result_heads(root: Path, kind: str) -> tuple[dict[str, set[str]], list[str]]:
    errors: list[str] = []
    heads: dict[str, set[str]] = {}
    dag = load_json(root / "control" / "EXECUTION_DAG.json")
    state = load_json(root / "control" / "EXECUTION_STATE.json")
    for cell in dag.get("cells", []):
        if not isinstance(cell, dict) or cell.get("kind") != kind:
            continue
        cell_id = cell.get("cell_id")
        record = state.get("cells", {}).get(cell_id, {}) if isinstance(state.get("cells"), dict) else {}
        if not isinstance(record, dict) or record.get("state") != "ACCEPTED":
            continue
        result_ref = record.get("result_ref")
        if not isinstance(result_ref, str):
            errors.append(f"accepted {kind} cell {cell_id} lacks result_ref")
            continue
        result_path = resolve_ref(root, result_ref)
        if not result_path.is_file():
            errors.append(f"accepted {kind} cell {cell_id} result is missing")
            continue
        accepted_result = load_json(result_path)
        for outcome in accepted_result.get("target_outcomes", []):
            if not isinstance(outcome, dict):
                continue
            repository = outcome.get("repository")
            head_sha = outcome.get("head_sha")
            if isinstance(repository, str) and isinstance(head_sha, str):
                heads.setdefault(repository, set()).add(head_sha)
    return heads, errors


def _accepted_mutation_inputs(root: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    errors: list[str] = []
    inputs: dict[str, dict[str, str]] = {}
    dag = load_json(root / "control" / "EXECUTION_DAG.json")
    state = load_json(root / "control" / "EXECUTION_STATE.json")
    for cell in dag.get("cells", []):
        if not isinstance(cell, dict) or cell.get("kind") != "MUTATION":
            continue
        cell_id = cell.get("cell_id")
        record = state.get("cells", {}).get(cell_id, {}) if isinstance(state.get("cells"), dict) else {}
        if not isinstance(record, dict) or record.get("state") != "ACCEPTED":
            continue
        result_ref = record.get("result_ref")
        if not isinstance(result_ref, str):
            errors.append(f"accepted MUTATION cell {cell_id} lacks result_ref")
            continue
        result_path = resolve_ref(root, result_ref)
        if not result_path.is_file():
            errors.append(f"accepted MUTATION cell {cell_id} result is missing")
            continue
        mutation_result = load_json(result_path)
        outcomes = mutation_result.get("target_outcomes", [])
        if not isinstance(outcomes, list) or len(outcomes) != 1 or not isinstance(outcomes[0], dict):
            errors.append(f"accepted MUTATION cell {cell_id} lacks one canonical target_outcome")
            continue
        repository = outcomes[0].get("repository")
        head_sha = outcomes[0].get("head_sha")
        if not isinstance(repository, str) or not isinstance(head_sha, str):
            errors.append(f"accepted MUTATION cell {cell_id} target outcome is incomplete")
            continue
        inputs[str(cell_id)] = {"repository": repository, "head_sha": head_sha}
    return inputs, errors


def validate_result(
    root: Path,
    result: dict[str, Any],
    cell_id: str,
    packet: dict[str, Any] | None = None,
) -> list[str]:
    errors = schema_errors(root, "contracts/schemas/RESULT_SCHEMA.json", result)
    if result.get("cell_id") != cell_id:
        errors.append(f"result cell_id must be {cell_id}")
    if packet is None:
        return errors

    kind = packet.get("kind")
    integrated_mutations = result.get("integrated_mutations")
    if kind != "INTEGRATION" and integrated_mutations is not None:
        errors.append(f"{kind} result must not claim integrated_mutations")
    if result.get("outcome") != "ACCEPTED":
        return errors

    outcomes = result.get("target_outcomes")
    if kind == "AUDIT":
        if outcomes is not None:
            errors.append("AUDIT result must not claim target_outcomes")
        return errors
    if kind not in {"MUTATION", "INTEGRATION", "QUALIFICATION"}:
        return errors
    if not isinstance(outcomes, list) or not outcomes:
        errors.append(f"ACCEPTED {kind} result requires non-empty target_outcomes")
        return errors

    repositories = [item.get("repository") for item in outcomes if isinstance(item, dict)]
    if len(repositories) != len(set(repositories)):
        errors.append(f"ACCEPTED {kind} result target_outcomes repositories must be unique")
    target_map = load_json(root / "control" / "CURRENT_AUTHORITY.json").get("target_baselines", {})
    current_heads = {
        item.get("repository"): item.get("head_sha")
        for item in outcomes
        if isinstance(item, dict) and isinstance(item.get("repository"), str)
    }
    for item in outcomes:
        if not isinstance(item, dict):
            continue
        repository = item.get("repository")
        if repository not in target_map:
            errors.append(f"ACCEPTED {kind} result targets unbound repository: {repository}")
        elif item.get("baseline_sha") != target_map[repository]:
            errors.append(f"ACCEPTED {kind} result baseline_sha differs from current authority for {repository}")

    if kind == "MUTATION":
        target = packet.get("target")
        if not isinstance(target, dict):
            errors.append("ACCEPTED MUTATION result has no compiled target authority")
        elif len(outcomes) != 1:
            errors.append("ACCEPTED MUTATION result must report exactly one target_outcome")
        elif outcomes[0].get("repository") != target.get("repository") or outcomes[0].get("baseline_sha") != str(target.get("base_sha", "")).lower():
            errors.append("ACCEPTED MUTATION result target_outcome differs from compiled target/base")
        return errors

    if set(repositories) != set(target_map):
        errors.append(f"ACCEPTED {kind} result must exactly cover mission targets: {sorted(target_map)}")

    if kind == "INTEGRATION":
        expected_inputs, input_errors = _accepted_mutation_inputs(root)
        errors.extend(input_errors)
        if not expected_inputs:
            errors.append("ACCEPTED INTEGRATION result requires accepted mutation inputs")
        if not isinstance(integrated_mutations, list) or not integrated_mutations:
            errors.append("ACCEPTED INTEGRATION result requires non-empty integrated_mutations")
        else:
            input_ids = [item.get("cell_id") for item in integrated_mutations if isinstance(item, dict)]
            if len(input_ids) != len(set(input_ids)):
                errors.append("ACCEPTED INTEGRATION result integrated_mutations cell_ids must be unique")
            if set(input_ids) != set(expected_inputs):
                errors.append(
                    f"ACCEPTED INTEGRATION result must exactly bind accepted mutation cells; missing={sorted(set(expected_inputs) - set(input_ids))}, unknown={sorted(set(input_ids) - set(expected_inputs))}"
                )
            for item in integrated_mutations:
                if not isinstance(item, dict):
                    continue
                mutation_id = item.get("cell_id")
                expected = expected_inputs.get(str(mutation_id))
                if expected is not None and (
                    item.get("repository") != expected["repository"] or item.get("head_sha") != expected["head_sha"]
                ):
                    errors.append(f"ACCEPTED INTEGRATION input {mutation_id} must exactly match its accepted mutation result head")

        prior_heads, prior_errors = _accepted_result_heads(root, "INTEGRATION")
        errors.extend(prior_errors)
        for repository, heads in prior_heads.items():
            if len(heads) != 1:
                errors.append(f"previously accepted INTEGRATION cells disagree on target head for {repository}: {sorted(heads)}")
            elif repository in current_heads and current_heads[repository] not in heads:
                errors.append(f"ACCEPTED INTEGRATION head for {repository} must match previously accepted INTEGRATION head {next(iter(heads))}")
        return errors

    integration_heads, integration_errors = _accepted_result_heads(root, "INTEGRATION")
    errors.extend(integration_errors)
    for repository in target_map:
        heads = integration_heads.get(repository, set())
        if len(heads) != 1:
            errors.append(f"ACCEPTED QUALIFICATION result requires exactly one accepted INTEGRATION head for {repository}; got {sorted(heads)}")
        elif current_heads.get(repository) not in heads:
            errors.append(f"ACCEPTED QUALIFICATION head for {repository} must equal accepted INTEGRATION head {next(iter(heads))}")
    return errors


def validate_context_receipt(root: Path, receipt: dict[str, Any], cell_id: str, manifest_ref: str, base_head: str) -> list[str]:
    errors = schema_errors(root, "contracts/schemas/CONTEXT_RECEIPT_SCHEMA.json", receipt)
    if receipt.get("cell_id") != cell_id:
        errors.append(f"ContextReceipt cell_id must be {cell_id}")
    if receipt.get("base_head") != base_head:
        errors.append("ContextReceipt base_head differs from compiled workcell")
    if receipt.get("manifest_ref") != manifest_ref:
        errors.append("ContextReceipt manifest_ref differs from compiled workcell")
    return errors


def validate_context_accounting(root: Path, receipt: dict[str, Any], packet: dict[str, Any], outcome: str) -> list[str]:
    errors: list[str] = []
    manifest_ref = packet.get("context_manifest_ref")
    if not isinstance(manifest_ref, str):
        return ["compiled workcell lacks context_manifest_ref"]
    manifest_path = resolve_ref(root, manifest_ref)
    if not manifest_path.is_file():
        return ["compiled ContextManifest is missing"]
    manifest = load_json(manifest_path)
    expected_hash = canonical_json_sha256(manifest)
    if receipt.get("manifest_hash") != expected_hash:
        errors.append("ContextReceipt manifest_hash must equal the canonical JSON SHA-256 of the compiled ContextManifest")

    items = manifest.get("items", [])
    if not isinstance(items, list):
        return errors + ["compiled ContextManifest items must be a list"]
    known_ids = {
        str(item.get("context_id"))
        for item in items
        if isinstance(item, dict) and isinstance(item.get("context_id"), str)
    }
    required_ids = {
        str(item.get("context_id"))
        for item in items
        if isinstance(item, dict) and item.get("requirement") == "REQUIRED" and isinstance(item.get("context_id"), str)
    }
    consumed = receipt.get("consumed", [])
    consumed_ids = set(consumed) if isinstance(consumed, list) else set()
    if isinstance(consumed, list) and len(consumed) != len(consumed_ids):
        errors.append("ContextReceipt consumed context ids must be unique")
    unknown_consumed = consumed_ids - known_ids
    if unknown_consumed:
        errors.append(f"ContextReceipt consumed unknown context ids: {sorted(unknown_consumed)}")

    partial = receipt.get("partial_or_unavailable", [])
    partial_ids: list[str] = []
    if isinstance(partial, list):
        partial_ids = [
            str(item.get("context_id"))
            for item in partial
            if isinstance(item, dict) and isinstance(item.get("context_id"), str)
        ]
    if len(partial_ids) != len(set(partial_ids)):
        errors.append("ContextReceipt partial_or_unavailable context ids must be unique")
    unknown_partial = set(partial_ids) - known_ids
    if unknown_partial:
        errors.append(f"ContextReceipt partial_or_unavailable references unknown context ids: {sorted(unknown_partial)}")
    duplicated_accounting = consumed_ids & set(partial_ids)
    if duplicated_accounting:
        errors.append(f"ContextReceipt cannot both consume and mark unavailable the same context: {sorted(duplicated_accounting)}")

    if outcome == "ACCEPTED":
        missing = required_ids - consumed_ids
        if missing:
            errors.append(f"ACCEPTED result requires every REQUIRED context item to be consumed: {sorted(missing)}")
    else:
        accounted = consumed_ids | set(partial_ids)
        missing = required_ids - accounted
        if missing:
            errors.append(f"non-accepted result must account for every REQUIRED context item: {sorted(missing)}")
    return errors


def adjudication_state(decision: Any) -> str | None:
    return {
        "ACCEPTED": "ACCEPTED",
        "REJECTED": "REJECTED",
        "FAILED": "FAILED",
        "BLOCKED": "BLOCKED",
        "CANDIDATE": "CANDIDATE",
    }.get(decision)


def validate_adjudication(
    root: Path,
    adjudication: dict[str, Any],
    cell_id: str,
    attempt: int,
    result: dict[str, Any],
    receipt: dict[str, Any],
    packet: dict[str, Any],
    *,
    expected_worker_identity: str | None = None,
    expected_verifier_identity: str | None = None,
) -> list[str]:
    errors = schema_errors(root, "contracts/schemas/ADJUDICATION_SCHEMA.json", adjudication)
    if adjudication.get("cell_id") != cell_id:
        errors.append(f"adjudication cell_id must be {cell_id}")
    if adjudication.get("attempt") != attempt:
        errors.append(f"adjudication attempt must be {attempt}")

    verifier = adjudication.get("verifier")
    worker = receipt.get("worker")
    if isinstance(verifier, dict) and isinstance(worker, dict):
        if expected_worker_identity is not None and worker.get("identity") != expected_worker_identity:
            errors.append(f"ContextReceipt worker identity must match dispatch assignment {expected_worker_identity}")
        if expected_verifier_identity is not None and verifier.get("identity") != expected_verifier_identity:
            errors.append(f"adjudication verifier identity must match dispatch assignment {expected_verifier_identity}")
        if verifier.get("identity") == worker.get("identity"):
            errors.append("adjudication verifier identity must differ from worker identity")
        verifier_session = verifier.get("session_id")
        worker_session = worker.get("session_id")
        if verifier_session is not None and worker_session is not None and verifier_session == worker_session:
            errors.append("adjudication verifier session_id must differ from worker session_id")

    manifest_ref = packet.get("context_manifest_ref")
    workcell_ref = None
    state = load_json(root / "control" / "EXECUTION_STATE.json")
    record = state.get("cells", {}).get(cell_id, {}) if isinstance(state.get("cells"), dict) else {}
    if isinstance(record, dict):
        workcell_ref = record.get("workcell_ref")
    if not isinstance(workcell_ref, str):
        errors.append("adjudication cannot bind a missing workcell_ref")
        return errors
    workcell_path = resolve_ref(root, workcell_ref)
    manifest_path = resolve_ref(root, str(manifest_ref))
    if adjudication.get("result_sha256") != canonical_json_sha256(result):
        errors.append("adjudication result_sha256 must bind the canonical worker result")
    if adjudication.get("context_receipt_sha256") != canonical_json_sha256(receipt):
        errors.append("adjudication context_receipt_sha256 must bind the canonical ContextReceipt")
    if workcell_path.is_file() and adjudication.get("workcell_sha256") != canonical_json_sha256(load_json(workcell_path)):
        errors.append("adjudication workcell_sha256 must bind the canonical CompiledWorkCell")
    if manifest_path.is_file() and adjudication.get("context_manifest_sha256") != canonical_json_sha256(load_json(manifest_path)):
        errors.append("adjudication context_manifest_sha256 must bind the canonical ContextManifest")

    decision = adjudication.get("decision")
    verified_acceptance = adjudication.get("verified_acceptance")
    if decision == "ACCEPTED":
        if result.get("outcome") != "ACCEPTED":
            errors.append("ACCEPTED adjudication requires an ACCEPTED worker claim")
        expected_acceptance = packet.get("acceptance", [])
        if not isinstance(verified_acceptance, list) or set(verified_acceptance) != set(expected_acceptance) or len(verified_acceptance) != len(expected_acceptance):
            errors.append("ACCEPTED adjudication verified_acceptance must exactly cover the CompiledWorkCell acceptance criteria")
    elif verified_acceptance != []:
        errors.append("non-ACCEPTED adjudication verified_acceptance must be empty")
    if adjudication_state(decision) is None:
        errors.append(f"unsupported adjudication decision: {decision}")
    return errors


def requirement_dispositions(corpus: dict[str, Any]) -> tuple[set[str], dict[str, dict[str, str]]]:
    active: set[str] = set()
    waived: dict[str, dict[str, str]] = {}
    for requirement in corpus.get("requirements", []):
        if not isinstance(requirement, dict) or not isinstance(requirement.get("id"), str):
            continue
        requirement_id = requirement["id"]
        waiver = requirement.get("waiver")
        if isinstance(waiver, dict):
            waived[requirement_id] = {
                "reason": str(waiver.get("reason", "")),
                "authority": str(waiver.get("authority", "")),
            }
        else:
            active.add(requirement_id)
    return active, waived


def requirement_acceptance_gaps(corpus: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, list[str]]:
    active, _ = requirement_dispositions(corpus)
    requirements = {
        requirement.get("id"): requirement
        for requirement in corpus.get("requirements", [])
        if isinstance(requirement, dict) and isinstance(requirement.get("id"), str)
    }
    gaps: dict[str, list[str]] = {}
    for requirement_id in sorted(active):
        expected = set(requirements.get(requirement_id, {}).get("acceptance", []))
        covered = {
            criterion
            for cell in cells
            if cell.get("kind") == "MUTATION" and requirement_id in cell.get("requirement_ids", [])
            for criterion in cell.get("acceptance", [])
            if isinstance(criterion, str)
        }
        missing = sorted(expected - covered)
        if missing:
            gaps[requirement_id] = missing
    return gaps


def requirement_target_gaps(corpus: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, list[str]]:
    active, _ = requirement_dispositions(corpus)
    requirements = {
        requirement.get("id"): requirement
        for requirement in corpus.get("requirements", [])
        if isinstance(requirement, dict) and isinstance(requirement.get("id"), str)
    }
    gaps: dict[str, list[str]] = {}
    for requirement_id in sorted(active):
        expected = set(requirements.get(requirement_id, {}).get("targets", []))
        covered = {
            str(cell.get("target", {}).get("repository"))
            for cell in cells
            if cell.get("kind") == "MUTATION"
            and requirement_id in cell.get("requirement_ids", [])
            and isinstance(cell.get("target"), dict)
            and isinstance(cell.get("target", {}).get("repository"), str)
        }
        missing = sorted(expected - covered)
        if missing:
            gaps[requirement_id] = missing
    return gaps


def requirement_target_acceptance_gaps(corpus: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, list[str]]:
    active, _ = requirement_dispositions(corpus)
    requirements = {
        requirement.get("id"): requirement
        for requirement in corpus.get("requirements", [])
        if isinstance(requirement, dict) and isinstance(requirement.get("id"), str)
    }
    gaps: dict[str, list[str]] = {}
    for requirement_id in sorted(active):
        requirement = requirements.get(requirement_id, {})
        expected = set(requirement.get("acceptance", []))
        for repository in sorted(set(requirement.get("targets", []))):
            covered = {
                criterion
                for cell in cells
                if cell.get("kind") == "MUTATION"
                and requirement_id in cell.get("requirement_ids", [])
                and isinstance(cell.get("target"), dict)
                and cell.get("target", {}).get("repository") == repository
                for criterion in cell.get("acceptance", [])
                if isinstance(criterion, str)
            }
            missing = sorted(expected - covered)
            if missing:
                gaps[f"{requirement_id}@{repository}"] = missing
    return gaps


def validate_qualification_accounting(root: Path, qualification: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    current = load_json(root / "control" / "CURRENT_AUTHORITY.json")
    corpus = load_json(root / "corpus" / "TARGET_MUTATIONS.json")
    target_map = current.get("target_baselines", {})

    outcomes = qualification.get("target_outcomes", [])
    outcome_repositories = [item.get("repository") for item in outcomes if isinstance(item, dict)] if isinstance(outcomes, list) else []
    if len(outcome_repositories) != len(set(outcome_repositories)):
        errors.append("qualification target_outcomes repository identities must be unique")
    if set(outcome_repositories) != set(target_map):
        errors.append(f"qualification target_outcomes must exactly cover mission targets: {sorted(target_map)}")
    for item in outcomes if isinstance(outcomes, list) else []:
        if not isinstance(item, dict):
            continue
        repository = item.get("repository")
        if repository in target_map and item.get("baseline_sha") != target_map[repository]:
            errors.append(f"qualification baseline_sha differs from current authority for {repository}")

    state: dict[str, Any] = {}
    try:
        dag, state = _load_v16(root)
        qualification_cells = [cell["cell_id"] for cell in dag.get("cells", []) if cell.get("kind") == "QUALIFICATION"]
        integration_cells = [cell["cell_id"] for cell in dag.get("cells", []) if cell.get("kind") == "INTEGRATION"]
    except Exception as exc:
        qualification_cells = []
        integration_cells = []
        errors.append(f"cannot load qualification/integration evidence: {exc}")
    if not qualification_cells:
        errors.append("final qualification requires at least one typed QUALIFICATION cell")
    if not integration_cells:
        errors.append("final qualification requires at least one typed INTEGRATION cell")
    integrated_heads: dict[str, set[str]] = {repository: set() for repository in target_map}
    for cell_id in integration_cells:
        record = state.get("cells", {}).get(cell_id, {})
        if record.get("state") != "ACCEPTED":
            continue
        result_ref = record.get("result_ref")
        if not isinstance(result_ref, str):
            continue
        try:
            cell_result = load_json(resolve_ref(root, result_ref))
        except Exception:
            continue
        for item in cell_result.get("target_outcomes", []):
            if not isinstance(item, dict):
                continue
            repository = item.get("repository")
            head_sha = item.get("head_sha")
            if repository in integrated_heads and isinstance(head_sha, str):
                integrated_heads[repository].add(head_sha)
    for repository, heads in integrated_heads.items():
        if len(heads) != 1:
            errors.append(f"accepted INTEGRATION cells must prove exactly one target head for {repository}; got {sorted(heads)}")

    proven_heads: dict[str, set[str]] = {repository: set() for repository in target_map}
    for cell_id in qualification_cells:
        record = state.get("cells", {}).get(cell_id, {})
        if record.get("state") != "ACCEPTED":
            continue
        result_ref = record.get("result_ref")
        if not isinstance(result_ref, str):
            continue
        try:
            cell_result = load_json(resolve_ref(root, result_ref))
        except Exception:
            continue
        for item in cell_result.get("target_outcomes", []):
            if not isinstance(item, dict):
                continue
            repository = item.get("repository")
            head_sha = item.get("head_sha")
            if repository in proven_heads and isinstance(head_sha, str):
                proven_heads[repository].add(head_sha)
    for repository, heads in proven_heads.items():
        if len(heads) != 1:
            errors.append(f"accepted QUALIFICATION cells must prove exactly one target head for {repository}; got {sorted(heads)}")
        integrated = integrated_heads.get(repository, set())
        if len(heads) == 1 and len(integrated) == 1 and heads != integrated:
            errors.append(f"accepted QUALIFICATION head must equal accepted INTEGRATION head for {repository}; integration={sorted(integrated)}, qualification={sorted(heads)}")
    for item in outcomes if isinstance(outcomes, list) else []:
        if not isinstance(item, dict):
            continue
        repository = item.get("repository")
        expected_heads = proven_heads.get(repository, set())
        if len(expected_heads) == 1 and item.get("accepted_head_sha") not in expected_heads:
            errors.append(f"qualification accepted_head_sha is not proven by accepted QUALIFICATION cell evidence for {repository}")

    requirements = corpus.get("requirements", [])
    requirement_ids = [item.get("id") for item in requirements if isinstance(item, dict)] if isinstance(requirements, list) else []
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("target mutation corpus requirement ids must be unique")
    active_requirements, frozen_waivers = requirement_dispositions(corpus)
    accounting = qualification.get("requirement_accounting", {})
    accepted = accounting.get("accepted", []) if isinstance(accounting, dict) else []
    waived = accounting.get("waived", []) if isinstance(accounting, dict) else []
    waived_ids = [item.get("requirement_id") for item in waived if isinstance(item, dict)] if isinstance(waived, list) else []
    if len(waived_ids) != len(set(waived_ids)):
        errors.append("qualification waived requirement ids must be unique")
    accepted_set = set(accepted) if isinstance(accepted, list) else set()
    if accepted_set != active_requirements:
        errors.append(f"qualification accepted requirements must exactly equal active target requirements; missing={sorted(active_requirements - accepted_set)}, unknown={sorted(accepted_set - active_requirements)}")
    qualification_waivers = {
        item.get("requirement_id"): {
            "reason": item.get("reason"),
            "authority": item.get("authority"),
        }
        for item in waived if isinstance(item, dict) and isinstance(item.get("requirement_id"), str)
    } if isinstance(waived, list) else {}
    if set(qualification_waivers) != set(frozen_waivers):
        errors.append(f"qualification waived requirements must exactly equal frozen corpus waivers; missing={sorted(set(frozen_waivers) - set(qualification_waivers))}, unknown={sorted(set(qualification_waivers) - set(frozen_waivers))}")
    for requirement_id, frozen in frozen_waivers.items():
        if qualification_waivers.get(requirement_id) != frozen:
            errors.append(f"qualification waiver for {requirement_id} must exactly match frozen corpus reason/authority")
    waived_set = set(qualification_waivers)

    dag = load_json(root / "control" / "EXECUTION_DAG.json")
    state = load_json(root / "control" / "EXECUTION_STATE.json")
    proven_verifications: set[str] = set()
    for cell in dag.get("cells", []):
        if not isinstance(cell, dict) or cell.get("kind") != "QUALIFICATION":
            continue
        cell_id = cell.get("cell_id")
        record = state.get("cells", {}).get(cell_id, {}) if isinstance(state.get("cells"), dict) else {}
        if not isinstance(record, dict) or record.get("state") != "ACCEPTED":
            continue
        workcell_ref = record.get("workcell_ref")
        if not isinstance(workcell_ref, str):
            continue
        packet = load_json(resolve_ref(root, workcell_ref))
        proven_verifications.update(str(value) for value in packet.get("acceptance", []) if isinstance(value, str))

    verification = qualification.get("verification_accounting", {})
    run = set(verification.get("run", [])) if isinstance(verification, dict) and isinstance(verification.get("run"), list) else set()
    if run != proven_verifications:
        errors.append(f"qualification verification_accounting.run must exactly equal acceptance criteria proven by accepted QUALIFICATION workcells; missing={sorted(proven_verifications - run)}, unproven={sorted(run - proven_verifications)}")
    not_run = set(verification.get("not_run", [])) if isinstance(verification, dict) and isinstance(verification.get("not_run"), list) else set()
    verification_waivers = verification.get("waived", []) if isinstance(verification, dict) else []
    waived_verifications = [item.get("verification") for item in verification_waivers if isinstance(item, dict)] if isinstance(verification_waivers, list) else []
    if len(waived_verifications) != len(set(waived_verifications)):
        errors.append("qualification waived verification identities must be unique")
    waived_verification_set = set(waived_verifications)
    overlaps = (run & not_run) | (run & waived_verification_set) | (not_run & waived_verification_set)
    if overlaps:
        errors.append(f"qualification verification accounting categories must be disjoint: {sorted(overlaps)}")

    has_exceptions = bool(waived_set or waived_verification_set or not_run or qualification.get("unresolved_defects"))
    limitations = qualification.get("explicit_limitations", [])
    if has_exceptions and not limitations:
        errors.append("qualification with waivers, not-run verification, or unresolved defects requires explicit_limitations")
    return errors


def validate_attempt_history(root: Path, cell_id: str, record: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    attempt = record.get("attempt")
    history = record.get("attempt_history")
    if not isinstance(attempt, int) or attempt < 1:
        return ["current attempt must be an integer >= 1"]
    if not isinstance(history, list):
        return ["attempt_history must be a list"]

    settled_states = {"CANDIDATE", "ACCEPTED", "REJECTED", "FAILED", "BLOCKED"}
    assigned_states = settled_states | {"DISPATCHED"}
    worker_identity = record.get("worker_identity")
    verifier_identity = record.get("verifier_identity")
    if record.get("state") in assigned_states:
        if not isinstance(worker_identity, str) or not worker_identity.strip():
            errors.append("active/settled attempt lacks preassigned worker_identity")
        if not isinstance(verifier_identity, str) or not verifier_identity.strip():
            errors.append("active/settled attempt lacks preassigned verifier_identity")
        if isinstance(worker_identity, str) and worker_identity == verifier_identity:
            errors.append("active/settled attempt worker and verifier identities must differ")
    elif worker_identity is not None or verifier_identity is not None:
        errors.append("non-dispatched COMPILED attempt must not retain custody assignments")
    expected_history_len = attempt if record.get("state") in settled_states else attempt - 1
    if len(history) != expected_history_len:
        errors.append(f"attempt_history length {len(history)} does not match current attempt/state ({attempt}, {record.get('state')})")

    expected_attempts = list(range(1, len(history) + 1))
    actual_attempts = [item.get("attempt") if isinstance(item, dict) else None for item in history]
    if actual_attempts != expected_attempts:
        errors.append(f"attempt_history must be consecutive from 1; got {actual_attempts}")

    for index, item in enumerate(history, start=1):
        if not isinstance(item, dict):
            errors.append(f"attempt {index} history entry is not an object")
            continue
        item_worker_identity = item.get("worker_identity")
        item_verifier_identity = item.get("verifier_identity")
        if not isinstance(item_worker_identity, str) or not item_worker_identity.strip():
            errors.append(f"attempt {index} lacks preassigned worker_identity")
        if not isinstance(item_verifier_identity, str) or not item_verifier_identity.strip():
            errors.append(f"attempt {index} lacks preassigned verifier_identity")
        if isinstance(item_worker_identity, str) and item_worker_identity == item_verifier_identity:
            errors.append(f"attempt {index} worker and verifier identities must differ")
        result_ref = item.get("result_ref")
        receipt_ref = item.get("context_receipt_ref")
        adjudication_ref = item.get("adjudication_ref")
        expected_prefix = f"evidence/{cell_id}/attempt-{index:04d}/"
        if result_ref != expected_prefix + "result.json":
            errors.append(f"attempt {index} result_ref is not canonical")
        if receipt_ref != expected_prefix + "context_receipt.json":
            errors.append(f"attempt {index} context_receipt_ref is not canonical")
        if adjudication_ref != expected_prefix + "adjudication.json":
            errors.append(f"attempt {index} adjudication_ref is not canonical")
        result_path = resolve_ref(root, str(result_ref))
        receipt_path = resolve_ref(root, str(receipt_ref))
        adjudication_path = resolve_ref(root, str(adjudication_ref))
        if not result_path.is_file():
            errors.append(f"attempt {index} result evidence is missing")
            continue
        if not receipt_path.is_file():
            errors.append(f"attempt {index} ContextReceipt is missing")
            continue
        if not adjudication_path.is_file():
            errors.append(f"attempt {index} adjudication evidence is missing")
            continue
        if item.get("result_sha256") != sha256(result_path):
            errors.append(f"attempt {index} result hash drift")
        if item.get("context_receipt_sha256") != sha256(receipt_path):
            errors.append(f"attempt {index} ContextReceipt hash drift")
        if item.get("adjudication_sha256") != sha256(adjudication_path):
            errors.append(f"attempt {index} adjudication hash drift")
        try:
            result = load_json(result_path)
            receipt = load_json(receipt_path)
            adjudication = load_json(adjudication_path)
            errors.extend(f"attempt {index}: {error}" for error in validate_result(root, result, cell_id, packet))
            errors.extend(
                f"attempt {index}: {error}"
                for error in validate_context_receipt(root, receipt, cell_id, packet["context_manifest_ref"], packet["base_head"])
            )
            errors.extend(
                f"attempt {index}: {error}"
                for error in validate_context_accounting(root, receipt, packet, str(result.get("outcome")))
            )
            errors.extend(
                f"attempt {index}: {error}"
                for error in validate_adjudication(
                    root,
                    adjudication,
                    cell_id,
                    index,
                    result,
                    receipt,
                    packet,
                    expected_worker_identity=item.get("worker_identity") if isinstance(item.get("worker_identity"), str) else None,
                    expected_verifier_identity=item.get("verifier_identity") if isinstance(item.get("verifier_identity"), str) else None,
                )
            )
            expected_state = adjudication_state(adjudication.get("decision"))
            if item.get("state") != expected_state:
                errors.append(f"attempt {index} history state {item.get('state')} disagrees with adjudication decision {adjudication.get('decision')}")
            if index < attempt and item.get("state") == "ACCEPTED":
                errors.append(f"attempt {index} was ACCEPTED but a later attempt exists")
        except Exception as exc:
            errors.append(f"attempt {index} evidence cannot be validated: {exc}")

    if history and record.get("state") in settled_states:
        last = history[-1]
        for key in (
            "worker_identity", "verifier_identity", "result_ref", "result_sha256",
            "context_receipt_ref", "context_receipt_sha256", "adjudication_ref", "adjudication_sha256",
        ):
            if record.get(key) != last.get(key):
                errors.append(f"top-level {key} does not match the latest settled attempt")
        if record.get("state") != last.get("state"):
            errors.append("top-level state does not match the latest settled attempt")
    return errors


def _dag_cycles(cells: list[dict[str, Any]], id_key: str, deps_key: str) -> list[str]:
    graph = {str(cell[id_key]): list(cell.get(deps_key, [])) for cell in cells if id_key in cell}
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[str] = []

    def walk(node: str, trail: list[str]) -> None:
        if node in visiting:
            cycles.append(" -> ".join(trail + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph:
                walk(dep, trail + [node])
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        walk(node, [])
    return cycles


def _generic_graph_issues(cells: list[dict[str, Any]], id_key: str, deps_key: str) -> list[str]:
    errors: list[str] = []
    ids = [str(c.get(id_key, "")) for c in cells]
    if any(not value for value in ids):
        errors.append("one or more DAG cells lack an id")
    if len(ids) != len(set(ids)):
        errors.append("DAG cell ids are not unique")
    known = set(ids)
    for cell in cells:
        cid = str(cell.get(id_key, ""))
        deps = cell.get(deps_key, [])
        if not isinstance(deps, list):
            errors.append(f"{cid} dependencies are not a list")
            continue
        if cid in deps:
            errors.append(f"{cid} depends on itself")
        unknown = set(map(str, deps)) - known
        if unknown:
            errors.append(f"{cid} has unknown dependencies {sorted(unknown)}")
    cycles = _dag_cycles(cells, id_key, deps_key)
    if cycles:
        errors.append(f"DAG contains cycles: {cycles}")
    return errors


def detect_layout(root: Path) -> str:
    mission = root / "MISSION.json"
    if mission.is_file():
        return "v16"
    current = root / "control" / "CURRENT_AUTHORITY.json"
    if current.is_file():
        try:
            schema = str(load_json(current).get("schema", ""))
            if schema.startswith("flyby/mcv6-current-authority/"):
                return "mcv6-legacy"
        except Exception:
            return "mcv6-legacy"
    return "unknown"


def _collect_v16_issues(root: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    required = (
        "MISSION.json", "TEMPLATE_LOCK.json", "control/CURRENT_AUTHORITY.json",
        "control/EXECUTION_DAG.json", "control/EXECUTION_STATE.json", "control/COMPILER_CONTROL.json",
        "control/SESSION_RESIDENCY.json", "control/WORKSPACE_LEDGER.json", "corpus/TARGET_MUTATIONS.json", "corpus/SOURCES.json", "corpus/PROVENANCE_SYNTHESIS.json",
        "contracts/schemas/MISSION_SCHEMA.json", "contracts/schemas/CELL_SCHEMA.json", "contracts/schemas/WORKCELL_SCHEMA.json", "contracts/schemas/RESULT_SCHEMA.json",
        "contracts/schemas/ADJUDICATION_SCHEMA.json", "contracts/schemas/CONTEXT_MANIFEST_SCHEMA.json", "contracts/schemas/CONTEXT_RECEIPT_SCHEMA.json",
        "contracts/schemas/SESSION_RESIDENCY_REGISTRY_SCHEMA.json", "contracts/schemas/QUALIFICATION_SCHEMA.json",
        "contracts/schemas/CLOSURE_SCHEMA.json", "contracts/schemas/WORKSPACE_RECONCILIATION_SCHEMA.json", "contracts/schemas/WORKSPACE_LEDGER_SCHEMA.json", "contracts/schemas/TEMPLATE_LOCK_SCHEMA.json",
        "contracts/schemas/CURRENT_AUTHORITY_SCHEMA.json", "contracts/schemas/EXECUTION_DAG_SCHEMA.json",
        "contracts/schemas/COMPILER_CONTROL_SCHEMA.json", "contracts/schemas/TARGET_CORPUS_SCHEMA.json",
        "contracts/schemas/SOURCE_REGISTRY_SCHEMA.json", "contracts/schemas/PROVENANCE_SYNTHESIS_SCHEMA.json", "runtime/tools/mc.py", "runtime/tools/schema_subset.py",
        "runtime/tests/test_mission_control.py",
    )
    for rel in required:
        if not (root / rel).is_file():
            out.append(issue("MC0163", f"required generated asset missing: {rel}",
                             "mission was manually assembled, partially initialized, or drifted",
                             "rerun `mc repair bootstrap --root <mission> --template-root <template>`"))
    for rel in FORBIDDEN_V16_MIRRORS:
        if (root / rel).exists():
            out.append(issue("MC0164", f"forbidden duplicate v16 authority/layout path exists: {rel}",
                             "legacy layout was copied into a canonical v16 mission",
                             "remove the duplicate after confirming canonical control/* authority"))
    if out:
        return out
    try:
        spec = load_json(root / "MISSION.json")
        for error in validate_mission_spec(spec):
            out.append(issue("MC0160", error, "MISSION.json violates its author-input contract", "correct MISSION.json and rerun doctor"))
        lock = load_json(root / "TEMPLATE_LOCK.json")
        current = load_json(root / "control/CURRENT_AUTHORITY.json")
        dag = load_json(root / "control/EXECUTION_DAG.json")
        state = load_json(root / "control/EXECUTION_STATE.json")
        compiler = load_json(root / "control/COMPILER_CONTROL.json")
        residency = load_json(root / "control/SESSION_RESIDENCY.json")
        workspace_ledger = load_json(root / "control/WORKSPACE_LEDGER.json")
        target_corpus = load_json(root / "corpus/TARGET_MUTATIONS.json")
        source_registry = load_json(root / "corpus/SOURCES.json")
        provenance_synthesis = load_json(root / "corpus/PROVENANCE_SYNTHESIS.json")
    except Exception as exc:
        out.append(issue("MC0161", f"generated JSON cannot be parsed: {exc}", "partial write or manual edit", "restore from version control or rerun bootstrap repair"))
        return out

    for error in schema_errors(root, "contracts/schemas/MISSION_SCHEMA.json", spec):
        out.append(issue("MC0160", f"MISSION.json schema violation: {error}", "MISSION.json violates the canonical author-input schema", "correct MISSION.json and rerun doctor"))
    for error in schema_errors(root, "contracts/schemas/EXECUTION_STATE_SCHEMA.json", state):
        out.append(issue("MC0162", f"execution-state schema violation: {error}", "mutable execution state is malformed", "restore or repair execution state before any transition"))
    for schema_ref, value, code, label in (
        ("contracts/schemas/TEMPLATE_LOCK_SCHEMA.json", lock, "MC0221", "TEMPLATE_LOCK"),
        ("contracts/schemas/CURRENT_AUTHORITY_SCHEMA.json", current, "MC0222", "CURRENT_AUTHORITY"),
        ("contracts/schemas/EXECUTION_DAG_SCHEMA.json", dag, "MC0223", "EXECUTION_DAG"),
        ("contracts/schemas/COMPILER_CONTROL_SCHEMA.json", compiler, "MC0224", "COMPILER_CONTROL"),
        ("contracts/schemas/TARGET_CORPUS_SCHEMA.json", target_corpus, "MC0225", "TARGET_MUTATIONS"),
        ("contracts/schemas/SOURCE_REGISTRY_SCHEMA.json", source_registry, "MC0226", "SOURCES"),
        ("contracts/schemas/PROVENANCE_SYNTHESIS_SCHEMA.json", provenance_synthesis, "MC0270", "PROVENANCE_SYNTHESIS"),
        ("contracts/schemas/WORKSPACE_LEDGER_SCHEMA.json", workspace_ledger, "MC0309", "WORKSPACE_LEDGER"),
    ):
        for error in schema_errors(root, schema_ref, value):
            out.append(issue(code, f"{label} schema violation: {error}", "canonical generated control shape drifted", "restore the generated artifact from its canonical schema/compiler"))

    mid = spec.get("mission_id")
    if workspace_ledger.get("mission_id") != mid:
        out.append(issue("MC0310", "WORKSPACE_LEDGER mission_id differs from current mission", "workspace registration was copied from another mission", "restore the mission-bound workspace ledger"))
    ledger_entries = workspace_ledger.get("entries", []) if isinstance(workspace_ledger, dict) else []
    ledger_ids = [entry.get("workspace_id") for entry in ledger_entries if isinstance(entry, dict)] if isinstance(ledger_entries, list) else []
    if len(ledger_ids) != len(set(ledger_ids)):
        out.append(issue("MC0311", "WORKSPACE_LEDGER workspace ids are not unique", "workspace identity is ambiguous", "retain one immutable registration per workspace id"))
    control_entries = [entry for entry in ledger_entries if isinstance(entry, dict) and entry.get("kind") == "CONTROL"] if isinstance(ledger_entries, list) else []
    if len(control_entries) != 1:
        out.append(issue("MC0312", f"WORKSPACE_LEDGER requires exactly one CONTROL entry; got {len(control_entries)}", "canonical control workspace identity is ambiguous", "restore exactly one mission control registration"))
    elif control_entries[0].get("repository") != spec.get("control_repository") or control_entries[0].get("branch") != spec.get("authoritative_working_branch"):
        out.append(issue("MC0313", "WORKSPACE_LEDGER CONTROL entry differs from MISSION authority", "workspace ledger points at a different control repository/branch", "restore the mission-declared control repository and authoritative branch"))
    dag_by_id = {cell.get("cell_id"): cell for cell in dag.get("cells", []) if isinstance(cell, dict)}
    target_branch_keys: set[tuple[str, str]] = set()
    for entry in ledger_entries if isinstance(ledger_entries, list) else []:
        if not isinstance(entry, dict) or entry.get("kind") != "TARGET":
            continue
        cell_id = entry.get("registered_cell")
        cell = dag_by_id.get(cell_id)
        if not isinstance(cell, dict):
            out.append(issue("MC0314", f"workspace {entry.get('workspace_id')} references unknown cell {cell_id}", "target workspace escaped the canonical execution DAG", "register target workspaces only against compiled target-bearing cells"))
            continue
        target = cell.get("target")
        if not isinstance(target, dict):
            out.append(issue("MC0315", f"workspace {entry.get('workspace_id')} is registered to non-target cell {cell_id}", "workspace identity is not tied to target authority", "register only target-bearing cells"))
            continue
        if entry.get("repository") != target.get("repository") or entry.get("base_sha") != str(target.get("base_sha", "")).lower():
            out.append(issue("MC0316", f"workspace {entry.get('workspace_id')} repository/base differs from cell {cell_id}", "target workspace could mutate the wrong repository/base", "re-register the exact compiled target repository and base"))
        key = (str(entry.get("repository")), str(entry.get("branch")))
        if key in target_branch_keys:
            out.append(issue("MC0317", f"duplicate target branch registration: {key[0]}:{key[1]}", "multiple workspace ids claim one target branch", "retain one canonical workspace registration per repository/branch"))
        target_branch_keys.add(key)

    if lock.get("template_schema") != TEMPLATE_SCHEMA:
        out.append(issue("MC0165", "TEMPLATE_LOCK template schema mismatch", "template/runtime drift", "re-bootstrap from the intended template revision"))
    source_state = lock.get("template_source_state")
    template_commit = lock.get("template_commit")
    base_commit = lock.get("template_base_commit")
    if source_state == "CLEAN_COMMIT":
        if not isinstance(template_commit, str) or len(template_commit) != 40 or template_commit != base_commit:
            out.append(issue("MC0169", "clean template provenance lacks one exact commit", "TEMPLATE_LOCK overstates or lost source provenance", "re-bootstrap from a clean committed template"))
    elif source_state == "DIRTY_WORKTREE":
        if template_commit is not None or not isinstance(base_commit, str) or len(base_commit) != 40:
            out.append(issue("MC0169", "dirty template provenance is inconsistent", "TEMPLATE_LOCK could falsely identify uncommitted assets as a commit", "re-bootstrap and retain DIRTY_WORKTREE with only a base commit"))
    elif source_state == "UNVERSIONED":
        if template_commit is not None or base_commit is not None:
            out.append(issue("MC0169", "unversioned template provenance contains commit claims", "TEMPLATE_LOCK claims Git provenance that was not established", "remove commit claims or bootstrap from a versioned template"))
    else:
        out.append(issue("MC0169", f"unknown template_source_state: {source_state}", "template provenance is ambiguous", "re-bootstrap with canonical source-state metadata"))
    assets = lock.get("assets")
    if not isinstance(assets, dict) or not assets:
        out.append(issue("MC0166", "TEMPLATE_LOCK has no asset hashes", "bootstrap did not seal runtime/contracts", "rerun bootstrap repair"))
    else:
        for rel, expected in assets.items():
            try:
                if not isinstance(rel, str) or not _safe_scope_path(rel):
                    raise ValueError(f"invalid locked asset path: {rel}")
                path = resolve_ref(root, rel)
            except Exception as exc:
                out.append(issue("MC0167", f"locked asset reference is unsafe: {rel}: {exc}", "TEMPLATE_LOCK asset path escaped or violated canonical relative-path rules", "restore the generated lock from bootstrap provenance"))
                continue
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                out.append(issue("MC0168", f"locked asset hash is invalid for {rel}", "TEMPLATE_LOCK contains a malformed digest", "restore the generated lock from bootstrap provenance"))
            elif not path.is_file():
                out.append(issue("MC0167", f"locked asset missing: {rel}", "generated runtime drift", "restore locked asset with bootstrap repair"))
            elif sha256(path) != expected:
                out.append(issue("MC0168", f"locked asset hash mismatch: {rel}", "generated runtime/contract was edited after bootstrap", "either restore it or intentionally re-bootstrap with a new template lock"))
        locked_paths = {rel for rel in assets if isinstance(rel, str)}
        unlocked = sorted(set(generated_asset_files(root)) - locked_paths)
        if unlocked:
            out.append(issue("MC0255", f"generated runtime/contract files are not sealed by TEMPLATE_LOCK: {unlocked}", "stale or manually added generated assets can bypass template provenance", "remove the unlocked generated assets or restore the exact locked template"))

    mid = spec.get("mission_id")
    if current.get("schema") != AUTHORITY_SCHEMA or current.get("mission_id") != mid:
        out.append(issue("MC0170", "CURRENT_AUTHORITY schema/mission identity mismatch", "authority was copied or manually edited", "regenerate control authority"))
    invalid_marker = root / "control" / "BOOTSTRAP_INVALID.json"
    if current.get("status") != "BOOTSTRAPPED":
        out.append(issue("MC0250", f"CURRENT_AUTHORITY bootstrap status is {current.get('status')}", "bootstrap validation failed and authoritative transitions must remain blocked", "repair the bootstrap from a trusted template revision before continuing"))
        if not invalid_marker.is_file():
            out.append(issue("MC0251", "BOOTSTRAP_INVALID authority lacks its diagnostic marker", "bootstrap failure evidence was removed independently from authority", "restore or regenerate the bootstrap-invalid diagnostic before repair"))
    elif invalid_marker.exists():
        out.append(issue("MC0252", "stale BOOTSTRAP_INVALID diagnostic exists under BOOTSTRAPPED authority", "bootstrap recovery left contradictory operator evidence", "remove the stale marker through `mc repair bootstrap`"))
    if target_corpus.get("mission_id") != mid:
        out.append(issue("MC0227", "TARGET_MUTATIONS mission_id differs from current mission", "target corpus was copied from or edited for another mission", "restore the mission-bound target corpus"))
    requirements = target_corpus.get("requirements", [])
    requirement_ids = [item.get("id") for item in requirements if isinstance(item, dict)] if isinstance(requirements, list) else []
    if len(requirement_ids) != len(set(requirement_ids)):
        out.append(issue("MC0242", "TARGET_MUTATIONS requirement ids are not unique", "requirement identity is ambiguous", "assign one unique immutable id per target requirement"))
    active_requirement_ids, frozen_requirement_waivers = requirement_dispositions(target_corpus)
    provenance_materialization = target_corpus.get("provenance_materialization", {})
    if isinstance(provenance_materialization, dict):
        materialization_mode = provenance_materialization.get("mode")
        target_refs = provenance_materialization.get("target_refs", [])
        coverage_requirement_id = provenance_materialization.get("coverage_requirement_id")
        validation_schema_ref = provenance_materialization.get("validation_schema_ref")
        if materialization_mode in {"REQUIRED_EXISTING_TARGET_MANIFEST", "REQUIRED_NEW_TARGET_MANIFEST"}:
            if not isinstance(target_refs, list) or not target_refs:
                out.append(issue("MC0325", "target provenance materialization requires at least one target ref", "lineage update can be declared without an actual target artifact", "record the exact existing/new provenance manifest paths"))
            if not isinstance(validation_schema_ref, str) or not validation_schema_ref:
                out.append(issue("MC0342", "target provenance materialization lacks validation_schema_ref", "lineage output has no machine-checkable target shape", "bind an explicit versioned schema for the target provenance manifest"))
            if coverage_requirement_id not in set(requirement_ids):
                out.append(issue("MC0326", f"target provenance materialization coverage requirement is missing: {coverage_requirement_id}", "target lineage update is not connected to executable mutation authority", "bind provenance_materialization.coverage_requirement_id to a real target requirement"))
            elif coverage_requirement_id not in active_requirement_ids:
                out.append(issue("MC0327", f"target provenance materialization requirement is waived/inactive: {coverage_requirement_id}", "a required target lineage update could be bypassed by waiver", "keep the lineage materialization requirement active until qualification"))
        elif materialization_mode == "TARGET_HAS_NO_LINEAGE_MANIFEST":
            if target_refs or coverage_requirement_id is not None or validation_schema_ref is not None:
                out.append(issue("MC0328", "TARGET_HAS_NO_LINEAGE_MANIFEST carries target refs, schema or coverage requirement", "the no-manifest declaration contradicts executable lineage metadata", "clear target_refs/validation_schema_ref/coverage_requirement_id or declare a required manifest mode"))
    invalid_requirement_ids = [value for value in requirement_ids if not valid_control_id(value)]
    if invalid_requirement_ids:
        out.append(issue("MC0249", f"TARGET_MUTATIONS contains unsafe requirement ids: {invalid_requirement_ids}", "requirement ids are not portable control identities", "use 1-64 character uppercase control ids and avoid reserved Windows device names"))
    if source_registry.get("mission_id") != mid:
        out.append(issue("MC0228", "SOURCES mission_id differs from current mission", "source registry was copied from or edited for another mission", "restore the mission-bound source registry"))
    sources = source_registry.get("sources", [])
    source_by_id_required = {item.get("id"): item for item in sources if isinstance(item, dict)}
    owner_source = source_by_id_required.get("owner-intent")
    if not isinstance(owner_source, dict) or owner_source.get("kind") != "OWNER_INTENT" or owner_source.get("locator") != "MISSION.json#owner_intent":
        out.append(issue("MC0303", "mandatory owner-intent source is missing or changed", "semantic source replacement dropped mission owner authority", "restore owner-intent -> MISSION.json#owner_intent"))
    previous_handoff = spec.get("previous_mission_handoff")
    previous_source = source_by_id_required.get("previous-mission-handoff")
    if previous_handoff:
        expected_handoff_sha = spec.get("previous_mission_handoff_sha256")
        if not isinstance(previous_source, dict) or previous_source.get("kind") != "PREVIOUS_MISSION" or previous_source.get("locator") != previous_handoff or previous_source.get("disposition") != "SYNTHESIS_REQUIRED":
            out.append(issue("MC0304", "mandatory previous-mission handoff source is missing, changed, or not synthesis-required", "prior mission provenance could be silently dropped or bypass current synthesis", "restore the exact previous-mission-handoff source and complete its source assessment"))
        elif previous_source.get("pin") != expected_handoff_sha:
            out.append(issue("MC0363", "previous-mission handoff source does not bind the mission-declared immutable digest", "prior-mission authority can change without invalidating source identity", "bind previous-mission-handoff.pin to previous_mission_handoff_sha256 exactly"))
        try:
            previous_path = resolve_ref(root, previous_handoff)
        except Exception as exc:
            out.append(issue("MC0364", f"previous-mission handoff ref is invalid: {exc}", "prior-mission authority escaped mission custody", "use a mission-local immutable handoff artifact"))
        else:
            if not previous_path.is_file():
                out.append(issue("MC0365", f"previous-mission handoff artifact is missing: {previous_handoff}", "a locator without content was treated as inherited authority", "materialize the handoff artifact before initialization"))
            elif sha256(previous_path) != expected_handoff_sha:
                out.append(issue("MC0366", "previous-mission handoff content digest differs from mission authority", "prior-mission content drifted after admission", "restore the exact handoff bytes or update the mission through explicit new authority"))
    elif previous_source is not None:
        out.append(issue("MC0305", "previous-mission-handoff source exists without mission authority", "source registry introduced foreign prior-mission authority", "remove the unapproved previous-mission source or declare it in MISSION.json"))
    if provenance_synthesis.get("mission_id") != mid:
        out.append(issue("MC0271", "PROVENANCE_SYNTHESIS mission_id differs from current mission", "provenance synthesis was copied from or edited for another mission", "restore the mission-bound synthesis matrix"))
    source_ids = [item.get("id") for item in sources if isinstance(item, dict)] if isinstance(sources, list) else []
    if len(source_ids) != len(set(source_ids)):
        out.append(issue("MC0243", "SOURCES source ids are not unique", "provenance identity is ambiguous", "assign one unique immutable id per admitted source"))
    source_id_set = set(source_ids)
    synthesis_kinds = {"PREVIOUS_MISSION", "REPOSITORY", "RESEARCH", "DOCUMENT"}
    authorizing_dispositions = {"SYNTHESIS_REQUIRED", "ADJUDICATED_SYNTHESIS"}
    mission_target_repositories = {
        target.get("repository")
        for target in spec.get("target_repositories", [])
        if isinstance(target, dict) and isinstance(target.get("repository"), str)
    }
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict):
            continue
        kind = source.get("kind")
        disposition = source.get("disposition")
        pin = source.get("pin")
        if kind == "REPOSITORY" and disposition in authorizing_dispositions:
            if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", pin):
                out.append(issue("MC0244", f"repository source {source.get('id')} lacks an exact 40-hex commit pin", "donor provenance can drift after admission", "record the exact immutable repository commit before synthesis"))
        elif kind == "PREVIOUS_MISSION" and disposition == "SYNTHESIS_REQUIRED":
            if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", pin):
                out.append(issue("MC0309", f"previous-mission source {source.get('id')} lacks an exact 64-hex content pin", "prior mission handoff provenance can drift after admission", "record the exact immutable 64-hex SHA-256 pin before synthesis"))
            else:
                loc = source.get("locator")
                if isinstance(loc, str) and "://" not in loc:
                    try:
                        p_path = resolve_ref(root, loc)
                    except Exception:
                        pass
                    else:
                        if p_path.is_file() and sha256(p_path) != pin.lower():
                            out.append(issue("MC0367", f"previous-mission source {source.get('id')} content digest mismatch", "handoff artifact content changed after source registration", "update pin or restore exact handoff artifact"))
        elif kind in {"RESEARCH", "DOCUMENT"} and disposition in authorizing_dispositions:
            moving = {"main", "master", "head", "latest", "trunk", "develop", "development"}
            if not isinstance(pin, str) or not pin.strip() or pin.strip().lower() in moving:
                out.append(issue("MC0306", f"{kind.lower()} source {source.get('id')} lacks an immutable version/content pin", "research/document provenance can drift after assessment", "record an immutable version, DOI revision, arXiv version, or content digest before synthesis"))
    for requirement in requirements if isinstance(requirements, list) else []:
        if not isinstance(requirement, dict):
            continue
        unknown_sources = set(requirement.get("sources", [])) - source_id_set
        if unknown_sources:
            out.append(issue("MC0245", f"requirement {requirement.get('id')} references unknown sources: {sorted(unknown_sources)}", "target requirement provenance is not admitted in SOURCES.json", "load the source registry before accepting the target corpus"))
        unknown_targets = set(requirement.get("targets", [])) - mission_target_repositories
        if unknown_targets:
            out.append(issue(
                "MC0262",
                f"requirement {requirement.get('id')} targets repositories outside mission authority: {sorted(unknown_targets)}",
                "target requirement scope escaped the repositories frozen in MISSION.json",
                "correct the target corpus before baseline compilation or restore the frozen corpus from authority",
            ))
    mechanisms = provenance_synthesis.get("mechanisms", []) if isinstance(provenance_synthesis, dict) else []
    mechanism_ids = [item.get("id") for item in mechanisms if isinstance(item, dict)] if isinstance(mechanisms, list) else []
    if len(mechanism_ids) != len(set(mechanism_ids)):
        out.append(issue("MC0272", "PROVENANCE_SYNTHESIS mechanism ids are not unique", "mechanism identity is ambiguous", "assign one unique immutable id per source-derived mechanism"))
    mechanism_id_set = set(mechanism_ids)
    mechanism_by_id = {str(item.get("id")): item for item in mechanisms if isinstance(item, dict) and isinstance(item.get("id"), str)}
    synthesis_required_sources = {
        item.get("id") for item in sources
        if isinstance(item, dict) and item.get("disposition") in authorizing_dispositions
    }
    mechanism_source_ids: set[str] = set()
    requirement_to_mechanisms: dict[str, set[str]] = {}
    for mechanism in mechanisms if isinstance(mechanisms, list) else []:
        if not isinstance(mechanism, dict):
            continue
        mechanism_sources = set(mechanism.get("source_ids", []))
        unknown = mechanism_sources - source_id_set
        source_by_id_for_mechanism = {item.get("id"): item for item in sources if isinstance(item, dict)}
        non_authorizing = sorted(
            sid for sid in mechanism_sources
            if isinstance(source_by_id_for_mechanism.get(sid), dict)
            and source_by_id_for_mechanism[sid].get("kind") in synthesis_kinds
            and source_by_id_for_mechanism[sid].get("disposition") not in authorizing_dispositions
        )
        if non_authorizing:
            out.append(issue("MC0302", f"mechanism {mechanism.get('id')} cites non-authorizing sources: {non_authorizing}", "reference-only/rejected material became mutation mechanism authority", "remove those sources or re-admit them through complete synthesis"))
        if unknown:
            out.append(issue("MC0273", f"mechanism {mechanism.get('id')} references unknown sources: {sorted(unknown)}", "provenance synthesis escaped source admission", "bind mechanisms only to admitted source ids"))
        mechanism_source_ids.update(mechanism.get("source_ids", []))
        disposition = mechanism.get("disposition")
        target_requirements = set(mechanism.get("target_requirements", []))
        if disposition == "REJECTED":
            if not mechanism.get("rejection_reason"):
                out.append(issue("MC0274", f"rejected mechanism {mechanism.get('id')} lacks rejection_reason", "silent omission can masquerade as synthesis", "record why the mechanism is intentionally rejected"))
            if target_requirements:
                out.append(issue("MC0350", f"rejected mechanism {mechanism.get('id')} still binds target requirements: {sorted(target_requirements)}", "rejected source behavior remained mutation authority", "clear target_requirements for rejected mechanisms and remove every requirement binding to them"))
        elif not target_requirements:
            out.append(issue("MC0275", f"non-rejected mechanism {mechanism.get('id')} has no target requirement binding", "useful provenance was analyzed but not converted into target authority", "bind the mechanism to one or more target requirements or reject it explicitly"))
        if disposition != "REJECTED":
            for rid in target_requirements:
                requirement_to_mechanisms.setdefault(rid, set()).add(str(mechanism.get("id")))
    source_assessments = provenance_synthesis.get("source_assessments", []) if isinstance(provenance_synthesis, dict) else []
    assessment_ids = [item.get("source_id") for item in source_assessments if isinstance(item, dict)] if isinstance(source_assessments, list) else []
    if len(assessment_ids) != len(set(assessment_ids)):
        out.append(issue("MC0290", "PROVENANCE_SYNTHESIS source assessment ids are not unique", "source-level coverage review is ambiguous", "retain exactly one coverage assessment per synthesis-required source"))
    assessment_id_set = set(assessment_ids)
    if (source_assessments or mechanisms or requirements) and synthesis_required_sources != assessment_id_set:
        out.append(issue("MC0291", f"source assessment coverage differs from authorizing synthesis sources: missing={sorted(synthesis_required_sources-assessment_id_set)} extra={sorted(assessment_id_set-synthesis_required_sources)}", "source-level mechanism coverage was not independently accounted", "add exactly one complete source assessment for every authorizing synthesis source"))
    mechanisms_by_source: dict[str, set[str]] = {}
    for mechanism in mechanisms if isinstance(mechanisms, list) else []:
        if isinstance(mechanism, dict):
            for sid in mechanism.get("source_ids", []):
                mechanisms_by_source.setdefault(str(sid), set()).add(str(mechanism.get("id")))
    source_records = {item.get("id"): item for item in sources if isinstance(item, dict)}
    provenance_version = provenance_synthesis.get("schema")
    for assessment in source_assessments if isinstance(source_assessments, list) else []:
        if not isinstance(assessment, dict):
            continue
        sid = assessment.get("source_id")
        if sid not in source_id_set:
            out.append(issue("MC0292", f"source assessment references unknown source {sid}", "coverage review escaped source admission", "bind source assessments only to admitted source ids"))
            continue
        if assessment.get("coverage_status") != "COMPLETE" or assessment.get("open_questions"):
            out.append(issue("MC0293", f"source assessment {sid} is not complete or has open questions", "source analysis was promoted before coverage questions were resolved", "resolve every material question before baseline compilation"))
        source_record = source_records.get(sid, {}) if isinstance(source_records.get(sid, {}), dict) else {}
        source_disposition = source_record.get("disposition")
        if source_disposition == "ADJUDICATED_SYNTHESIS":
            adjudication = assessment.get("adjudication_evidence")
            if not isinstance(adjudication, dict) or adjudication.get("state") != "VERIFIED" or adjudication.get("admission") != "READY_FOR_AUTHORITY_ADMISSION":
                out.append(issue("MC0380", f"source assessment {sid} lacks VERIFIED adjudication evidence ready for authority admission", "a pre-adjudication source could bypass independent source review", "bind a hash-verified terminal adjudication receipt and candidate snapshot"))
            else:
                for ref_key,sha_key,label in (("receipt_ref","receipt_sha256","adjudication receipt"),("candidate_ref","candidate_sha256","adjudicated candidate")):
                    ref=adjudication.get(ref_key); expected=adjudication.get(sha_key)
                    if not isinstance(ref,str) or not ref:
                        out.append(issue("MC0381", f"source assessment {sid} lacks {label} ref", "adjudicated provenance cannot be traced", "record a mission-local immutable adjudication ref"))
                        continue
                    try:
                        evidence_path=resolve_ref(root,ref)
                    except Exception as exc:
                        out.append(issue("MC0382", f"source assessment {sid} {label} ref invalid: {exc}", "adjudication evidence escaped mission custody", "use a mission-local evidence path"))
                        continue
                    if not evidence_path.is_file():
                        out.append(issue("MC0383", f"source assessment {sid} {label} missing: {ref}", "adjudication locator was treated as evidence", "materialize the exact evidence bytes"))
                    elif expected != sha256(evidence_path):
                        out.append(issue("MC0384", f"source assessment {sid} {label} hash drift", "adjudication evidence can change without invalidating authority", "bind the exact evidence sha256"))
        else:
            deep_review = assessment.get("deep_review", {})
            if not isinstance(deep_review, dict):
                deep_review = {}
            if deep_review.get("state") != "COMPLETE":
                out.append(issue("MC0310", f"source assessment {sid} lacks COMPLETE source qualification", "rights mode was incorrectly allowed to substitute for source understanding", "complete the source assessment and preserve its evidence"))
            else:
                rounds = deep_review.get("rounds", [])
                if not isinstance(rounds, list):
                    rounds = []
                if provenance_version == "flyby/mission-control-provenance-synthesis/16":
                    minimum_rounds = deep_review.get("minimum_rounds")
                    if deep_review.get("strategy") != "ADAPTIVE_MULTI_ROUND_EXCORIATION":
                        out.append(issue("MC0311", f"source assessment {sid} does not use the legacy review strategy", "the evidence does not meet the mission's frozen legacy contract", "retain the strategy required by the legacy contract"))
                    if not isinstance(minimum_rounds, int) or minimum_rounds < 3 or len(rounds) < minimum_rounds:
                        out.append(issue("MC0312", f"source assessment {sid} completed fewer than its legacy minimum review rounds", "legacy evidence does not meet its frozen qualification contract", "complete the review required by the legacy mission"))
                elif provenance_version == "flyby/mission-control-provenance-synthesis/17":
                    if deep_review.get("strategy") != "EVIDENCE_BASED_QUALIFICATION":
                        out.append(issue("MC0311", f"source assessment {sid} does not use evidence-based qualification", "the assessment uses a different contract than its declared version", "record the qualification required by this mission's contract"))
                    if not rounds:
                        out.append(issue("MC0312", f"source assessment {sid} has no evidence-backed qualification", "an unexamined source can be treated as qualified", "record at least one assessment with its exact evidence"))
                    for row in rounds:
                        if not isinstance(row, dict):
                            continue
                        ref, expected = row.get("evidence_ref"), row.get("evidence_sha256")
                        if not isinstance(ref, str) or not ref:
                            out.append(issue("MC0390", f"source assessment {sid} qualification lacks an evidence ref", "the assessment cannot be inspected", "record a mission-local evidence ref and sha256"))
                            continue
                        try:
                            evidence_path = resolve_ref(root, ref)
                        except Exception as exc:
                            out.append(issue("MC0391", f"source assessment {sid} evidence ref invalid: {exc}", "qualification evidence escaped mission custody", "use a mission-local evidence path"))
                            continue
                        if not evidence_path.is_file():
                            out.append(issue("MC0392", f"source assessment {sid} qualification evidence missing: {ref}", "a locator was treated as evidence", "materialize the exact assessment evidence"))
                        elif expected != sha256(evidence_path):
                            out.append(issue("MC0393", f"source assessment {sid} qualification evidence hash drift: {ref}", "qualification evidence can change without invalidating review", "bind the exact assessment evidence sha256"))
                else:
                    out.append(issue("MC0394", f"source assessment {sid} has unknown provenance contract {provenance_version}", "unknown qualification rules cannot grant source authority", "use a supported provenance contract"))
                round_numbers = [row.get("round") for row in rounds if isinstance(row, dict)]
                if round_numbers != list(range(1, len(rounds) + 1)):
                    out.append(issue("MC0354", f"source assessment {sid} qualification records are duplicated, skipped, or reordered", "source assessment custody is ambiguous", "number assessment records contiguously from 1"))
                convergence = deep_review.get("convergence", {})
                if not isinstance(convergence, dict) or convergence.get("material_omissions_remaining") is not False:
                    out.append(issue("MC0313", f"source assessment {sid} has unresolved material omissions", "the mission can promote while material source questions remain unassessed", "resolve material omissions before qualification"))
                if deep_review.get("uninspected_critical_partitions"):
                    out.append(issue("MC0329", f"source assessment {sid} still has uninspected critical partitions", "important source scope remains unread", "inspect each critical partition or justify its removal before qualification"))
                if not rounds or not isinstance(rounds[-1], dict) or rounds[-1].get("disposition") != "COMPLETE":
                    out.append(issue("MC0330", f"source assessment {sid} final assessment is not COMPLETE", "qualification has no explicit completion event", "record completion after material gaps are resolved"))
        expected_bound = mechanisms_by_source.get(str(sid), set())
        contributions = assessment.get("mechanism_contributions", [])
        contribution_ids = [item.get("contribution_id") for item in contributions if isinstance(item, dict)]
        if len(contribution_ids) != len(contributions) or len(contribution_ids) != len(set(contribution_ids)):
            out.append(issue("MC0331", f"source assessment {sid} contribution ids are missing/duplicated", "source-local mechanism custody is ambiguous", "give every source contribution a stable unique contribution_id"))
        contribution_mids: set[str] = set()
        source_record = source_records.get(sid, {}) if isinstance(source_records.get(sid, {}), dict) else {}
        source_rights = source_record.get("copyright", {}) if isinstance(source_record, dict) else {}
        source_mode = source_rights.get("usage_mode") if isinstance(source_rights, dict) else None
        for contribution in contributions if isinstance(contributions, list) else []:
            if not isinstance(contribution, dict):
                continue
            contribution_mid = contribution.get("mechanism_id")
            contribution_mids.add(str(contribution_mid))
            if contribution_mid not in mechanism_id_set:
                out.append(issue("MC0332", f"source assessment {sid} contribution references unknown mechanism {contribution_mid}", "source-local review drifted from global synthesis", "bind contribution records only to admitted mechanisms"))
            else:
                source_refs = set(next((m.get("source_ids", []) for m in mechanisms if isinstance(m, dict) and m.get("id") == contribution_mid), []))
                if sid not in source_refs:
                    out.append(issue("MC0333", f"source assessment {sid} contribution binds mechanism {contribution_mid} that does not cite the source", "shared mechanisms can accidentally inherit unrelated source review authority", "make source-local contribution and mechanism source_ids agree"))
            if contribution.get("rights_mode") != source_mode:
                out.append(issue("MC0334", f"source assessment {sid} contribution rights mode differs from source registry", "reuse decisions can silently outlive rights changes", "bind contribution rights_mode to the exact admitted source rights"))
            if contribution.get("reuse_class") in {"DIRECT_REUSE", "ADAPTED_IMPLEMENTATION", "MIXED"}:
                if source_mode not in {"OWNER_AUTHORIZED_REUSE", "LICENSE_PERMITTED_REUSE"}:
                    out.append(issue("MC0335", f"source assessment {sid} contribution claims implementation reuse without reusable rights", "copyrighted implementation can leak through a source-local record", "use behavioral synthesis or verify reusable rights"))
                missing_obligations = set(source_rights.get("obligations", [])) - set(contribution.get("obligations", []))
                if missing_obligations:
                    out.append(issue("MC0336", f"source assessment {sid} contribution omits obligations: {sorted(missing_obligations)}", "attribution/license duties can be lost between source review and implementation", "carry exact source obligations into every direct/adapted contribution"))
        if contribution_mids != expected_bound:
            out.append(issue("MC0337", f"source assessment {sid} contribution accounting differs from synthesis: contributions={sorted(contribution_mids)} synthesis={sorted(expected_bound)}", "per-source review custody does not cover its full mechanism contribution set", "bind one or more contribution records to every source-owned mechanism"))
        if source_disposition != "ADJUDICATED_SYNTHESIS":
            review = assessment.get("independent_review", {})
            if not isinstance(review, dict) or review.get("state") != "VERIFIED":
                out.append(issue("MC0294", f"source assessment {sid} lacks independent VERIFIED review", "the extraction thread can certify its own omissions", "obtain independent review after adaptive source convergence"))
            else:
                review_payload = {"source_id": assessment.get("source_id"), "inspected_locators": assessment.get("inspected_locators", []), "coverage_items": assessment.get("coverage_items", []), "open_questions": assessment.get("open_questions", []), "deep_review": deep_review, "mechanism_contributions": contributions}
                review_digest = hashlib.sha256(json.dumps(review_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                contribution_digest = hashlib.sha256(json.dumps(contributions, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                source_record = source_records.get(sid)
                source_record_digest = canonical_json_sha256(source_record) if isinstance(source_record, dict) else None
                if review.get("coverage_sha256") != review_digest:
                    out.append(issue("MC0307", f"source assessment {sid} independent review does not bind exact deep-review coverage", "review identity can be reused after source coverage changes", "re-review exact adaptive coverage and record coverage_sha256"))
                if review.get("contributions_sha256") != contribution_digest:
                    out.append(issue("MC0338", f"source assessment {sid} independent review does not bind exact source-local contributions", "a shared mechanism edit can falsely invalidate or validate unrelated source review custody", "bind source-local contribution records separately from the global mechanism graph"))
                if review.get("source_record_sha256") != source_record_digest:
                    out.append(issue("MC0353", f"source assessment {sid} independent review does not bind exact admitted source identity", "review evidence can outlive a source locator/pin/rights change", "record source_record_sha256 for the exact admitted source registry record"))
                reviewer = review.get("reviewer")
                reviewer_identity = review.get("reviewer_identity")
                extractor_identity = review.get("extractor_identity")
                extractor_identities = {
                    str(round_item.get("reviewer")) for round_item in deep_review.get("rounds", [])
                    if isinstance(round_item, dict) and isinstance(round_item.get("reviewer"), str) and round_item.get("reviewer")
                }
                if not isinstance(reviewer, str) or not reviewer:
                    out.append(issue("MC0354", f"source assessment {sid} independent review lacks reviewer display identity", "review custody is anonymous", "record a stable reviewer identity distinct from the source extraction/deep-review owner"))
                if not isinstance(reviewer_identity, str) or not reviewer_identity:
                    out.append(issue("MC0367", f"source assessment {sid} independent review lacks reviewer_identity", "review custody is not machine-comparable", "record a stable reviewer_identity"))
                elif isinstance(reviewer, str) and reviewer and reviewer != reviewer_identity:
                    out.append(issue("MC0372", f"source assessment {sid} reviewer display identity differs from reviewer_identity", "human-readable and machine-comparable review custody disagree", "make reviewer and reviewer_identity name the same independent reviewer"))
                if not isinstance(extractor_identity, str) or not extractor_identity:
                    out.append(issue("MC0368", f"source assessment {sid} independent review lacks extractor_identity", "independence cannot be proven against extraction custody", "record the source extraction/deep-review custody identity"))
                if isinstance(extractor_identity, str) and ((isinstance(reviewer_identity, str) and reviewer_identity == extractor_identity) or (isinstance(reviewer, str) and reviewer == extractor_identity)):
                    out.append(issue("MC0355", f"source assessment {sid} independent reviewer must not equal extractor identity", "the extraction owner can certify its own omissions", "use reviewer identities distinct from extractor_identity"))
                if isinstance(extractor_identity, str) and extractor_identities and extractor_identity not in extractor_identities:
                    out.append(issue("MC0370", f"source assessment {sid} extractor_identity does not match deep-review round custody: {extractor_identity}", "review metadata can name a different extractor than the actual review trajectory", "bind extractor_identity to the deep-review round reviewer identity"))
                if isinstance(reviewer_identity, str) and reviewer_identity in extractor_identities:
                    out.append(issue("MC0371", f"source assessment {sid} reviewer_identity reuses deep-review custody: {reviewer_identity}", "the extraction thread can certify its own omissions", "use a distinct independent reviewer identity"))
                review_ref = review.get("review_ref")
                if not isinstance(review_ref, str) or not review_ref:
                    out.append(issue("MC0308", f"source assessment {sid} independent review lacks review_ref", "review custody cannot be traced", "record a mission-local hash-bound independent-review receipt"))
                else:
                    try:
                        review_path = resolve_ref(root, review_ref)
                    except Exception as exc:
                        out.append(issue("MC0356", f"source assessment {sid} independent review ref is invalid: {review_ref}: {exc}", "review custody escaped mission authority", "use a mission-local review receipt path"))
                    else:
                        if not review_path.is_file():
                            out.append(issue("MC0357", f"source assessment {sid} missing independent review receipt: {review_ref}", "a locator was treated as verification evidence", "materialize and hash-bind the independent-review receipt"))
                        else:
                            if review.get("review_sha256") != sha256(review_path):
                                out.append(issue("MC0358", f"source assessment {sid} independent review receipt hash drift", "review evidence can be replaced without invalidating authority", "record the exact review receipt sha256"))
                            try:
                                receipt = load_json(review_path)
                                receipt_schema_errors = schema_errors(root, "contracts/schemas/SOURCE_INDEPENDENT_REVIEW_SCHEMA.json", receipt)
                            except Exception as exc:
                                out.append(issue("MC0359", f"source assessment {sid} independent review receipt cannot be validated: {exc}", "review receipt is malformed or its schema is unavailable", "repair the typed independent-review receipt and schema"))
                            else:
                                if receipt_schema_errors:
                                    out.append(issue("MC0360", f"source assessment {sid} independent review receipt schema errors: {receipt_schema_errors}", "review receipt is not typed authority", "repair the independent-review receipt to the canonical schema"))
                                if receipt.get("source_id") != sid or receipt.get("reviewer") != reviewer or receipt.get("reviewer_identity") != reviewer_identity or receipt.get("extractor_identity") != extractor_identity:
                                    out.append(issue("MC0361", f"source assessment {sid} independent review receipt identity mismatch", "review receipt can be replayed across sources, reviewers, or extractor custody", "bind source_id, reviewer, reviewer_identity and extractor_identity identically in assessment and receipt"))
                                if receipt.get("source_record_sha256") != source_record_digest or receipt.get("coverage_sha256") != review_digest or receipt.get("contributions_sha256") != contribution_digest:
                                    out.append(issue("MC0362", f"source assessment {sid} independent review receipt digest mismatch", "review receipt does not cover the exact source/deep-review/contribution state", "reissue the review receipt over the exact admitted source and assessment digests"))
        bound: set[str] = set()
        for coverage in assessment.get("coverage_items", []):
            if not isinstance(coverage, dict):
                continue
            mids = set(coverage.get("mechanism_ids", [])); disposition = coverage.get("disposition")
            if disposition == "BOUND_TO_MECHANISM" and not mids:
                out.append(issue("MC0295", f"source assessment {sid} has BOUND_TO_MECHANISM item without mechanism ids", "coverage narrative is not connected to executable synthesis", "bind the capability to exact mechanism ids"))
            if disposition != "BOUND_TO_MECHANISM" and mids:
                out.append(issue("MC0296", f"source assessment {sid} attaches mechanism ids to {disposition} item", "rejected/already-satisfied coverage is ambiguously represented as a mutation mechanism", "use mechanism ids only for BOUND_TO_MECHANISM coverage items"))
            unknown_mids = mids - mechanism_id_set
            if unknown_mids:
                out.append(issue("MC0297", f"source assessment {sid} references unknown mechanisms: {sorted(unknown_mids)}", "coverage review drifted from synthesis mechanisms", "restore exact mechanism references"))
            for mechanism_id in mids & mechanism_id_set:
                source_refs = set(next((m.get("source_ids", []) for m in mechanisms if isinstance(m, dict) and m.get("id") == mechanism_id), []))
                if sid not in source_refs:
                    out.append(issue("MC0298", f"source assessment {sid} binds mechanism {mechanism_id} that does not cite the source", "source coverage claims unsupported ownership of a mechanism", "make source assessment and mechanism source_ids agree"))
            bound.update(mids)
        if bound != expected_bound:
            out.append(issue("MC0299", f"source assessment {sid} mechanism accounting differs from synthesis: assessment={sorted(bound)} synthesis={sorted(expected_bound)}", "some extracted mechanisms are missing from source-level coverage or vice versa", "make source coverage inventory exhaustive and bidirectional"))
    cross_source = provenance_synthesis.get("cross_source_synthesis", {}) if isinstance(provenance_synthesis, dict) else {}
    if (source_assessments or mechanisms or requirements) and (not isinstance(cross_source, dict) or cross_source.get("state") != "VERIFIED"):
        out.append(issue("MC0339", "cross-source synthesis is not VERIFIED", "source-local reviews can converge while shared mechanism composition remains unreviewed", "after source-local convergence independently synthesize and bind the final global mechanism graph"))
    elif isinstance(cross_source, dict) and cross_source.get("state") == "VERIFIED":
        mechanism_graph_digest = hashlib.sha256(json.dumps(mechanisms, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if cross_source.get("mechanism_graph_sha256") != mechanism_graph_digest:
            out.append(issue("MC0340", "cross-source synthesis does not bind exact global mechanism graph", "shared mechanism edits can bypass cross-source review", "re-run cross-source synthesis and record the exact mechanism graph digest"))
        hypotheses=cross_source.get("combination_hypotheses",[])
        intercepts=cross_source.get("intercept_matrix",[])
        intercept_digest=hashlib.sha256(json.dumps(intercepts,sort_keys=True,separators=(",", ":")).encode("utf-8")).hexdigest()
        hypothesis_digest=hashlib.sha256(json.dumps(hypotheses,sort_keys=True,separators=(",", ":")).encode("utf-8")).hexdigest()
        if cross_source.get("intercept_matrix_sha256") != intercept_digest:
            out.append(issue("MC0355", "cross-source synthesis does not bind exact intercept matrix", "a non-colliding intercept edit can bypass the global mechanism-graph digest", "record and verify the canonical intercept_matrix_sha256"))
        if cross_source.get("combination_hypotheses_sha256") != hypothesis_digest:
            out.append(issue("MC0356", "cross-source synthesis does not bind exact hypothesis set", "combination dispositions can drift after review", "record and verify the canonical combination_hypotheses_sha256"))
        evidence_ref=cross_source.get("evidence_ref")
        if not isinstance(evidence_ref, str) or not evidence_ref:
            out.append(issue("MC0341", "cross-source synthesis lacks evidence_ref", "global synthesis custody cannot be traced", "record the independent synthesis/review evidence locator"))
        elif "://" not in evidence_ref:
            try:
                evidence_path=resolve_ref(root,evidence_ref)
            except Exception:
                out.append(issue("MC0357", "cross-source synthesis evidence_ref is unsafe", "global synthesis evidence can escape mission custody", "use one canonical mission-relative evidence path"))
            else:
                if not evidence_path.is_file():
                    out.append(issue("MC0358", "cross-source synthesis evidence_ref is missing", "global synthesis can cite nonexistent evidence", "materialize the exact reviewed evidence artifact"))
                elif cross_source.get("evidence_sha256") != sha256(evidence_path):
                    out.append(issue("MC0359", "cross-source synthesis evidence hash drift", "review evidence can change without invalidating authority", "bind evidence_sha256 to the exact reviewed artifact"))
        hypothesis_ids=[h.get("id") for h in hypotheses if isinstance(h,dict)] if isinstance(hypotheses,list) else []
        if len(hypothesis_ids)!=len(hypotheses) or len(hypothesis_ids)!=len(set(hypothesis_ids)):
            out.append(issue("MC0360", "cross-source hypothesis ids are missing or duplicated", "combination dispositions are ambiguous", "assign one unique stable id to every cross-source hypothesis"))
        for hypothesis in hypotheses if isinstance(hypotheses,list) else []:
            if not isinstance(hypothesis,dict): continue
            h_sources=set(hypothesis.get("source_ids",[])); result_ids=set(hypothesis.get("result_mechanism_ids",[])); status=hypothesis.get("status")
            if len(h_sources)<2 or h_sources-set(source_id_set):
                out.append(issue("MC0343", f"cross-source hypothesis {hypothesis.get('id')} has invalid sources", "combination synthesis is not grounded in admitted sources", "bind each hypothesis to at least two admitted source ids"))
            if result_ids-mechanism_id_set:
                out.append(issue("MC0344", f"cross-source hypothesis {hypothesis.get('id')} references unknown result mechanisms", "combination disposition drifted from the final mechanism graph", "bind only final mechanism ids"))
            if status=="PENDING":
                out.append(issue("MC0345", f"cross-source hypothesis {hypothesis.get('id')} remains PENDING", "global synthesis can seal before high-value combinations are adjudicated", "ADOPT or REJECT every cross-source hypothesis"))
            if status=="ADOPTED" and not result_ids:
                out.append(issue("MC0346", f"adopted cross-source hypothesis {hypothesis.get('id')} has no result mechanism", "adoption exists only in prose", "bind the adopted combination to final mechanism ids"))
            if status=="ADOPTED" and result_ids:
                result_sources=set()
                for result_id in result_ids & mechanism_id_set:
                    result_sources.update(next((m.get("source_ids",[]) for m in mechanisms if isinstance(m,dict) and m.get("id")==result_id),[]))
                if not h_sources <= result_sources:
                    out.append(issue("MC0361", f"adopted cross-source hypothesis {hypothesis.get('id')} result does not preserve all contributing sources", "an existing single-source mechanism can be mislabeled as a cross-source synthesis result", "bind adoption to a result mechanism whose source_ids preserve every contributing source"))
            if status=="REJECTED" and result_ids:
                out.append(issue("MC0347", f"rejected cross-source hypothesis {hypothesis.get('id')} still binds mechanisms", "rejection and mechanism authority contradict", "clear result mechanisms or adopt the hypothesis"))
        represented=set(); signatures={}; entries=[]
        for entry in intercepts if isinstance(intercepts,list) else []:
            if not isinstance(entry,dict): continue
            mechanism_id=entry.get("mechanism_id"); represented.add(mechanism_id)
            if mechanism_id not in mechanism_id_set:
                out.append(issue("MC0348", f"runtime intercept references unknown mechanism {mechanism_id}", "intercept map drifted from the final mechanism graph", "bind intercepts only to final mechanisms"))
            conflicts=set(entry.get("conflicts_with",[]))
            if mechanism_id in conflicts or conflicts-mechanism_id_set:
                out.append(issue("MC0349", f"runtime intercept {mechanism_id} has invalid conflicts_with", "collision metadata cannot be trusted", "reference only other final mechanism ids"))
            sig=(entry.get("phase"),entry.get("composition_mode"),tuple(sorted(entry.get("state_in",[]))),tuple(sorted(entry.get("state_out",[]))))
            if sig in signatures:
                out.append(issue("MC0350", f"runtime intercept duplicate signature: {signatures[sig]} and {mechanism_id}", "semantically identical mechanisms survived cross-source deduplication", "unify identical intercept signatures into one FlyBy mechanism with multi-source contributions"))
            else:
                signatures[sig]=mechanism_id
            entries.append(entry)
        missing_intercepts=mechanism_id_set-represented
        if missing_intercepts:
            out.append(issue("MC0351", f"final mechanisms lack runtime/control intercepts: {sorted(missing_intercepts)}", "mechanism composition order/collisions cannot be reviewed", "map every final mechanism to at least one execution/control intercept"))
        for idx,left in enumerate(entries):
            for right in entries[idx+1:]:
                if left.get("phase")!=right.get("phase"): continue
                overlap=set(left.get("state_out",[])) & set(right.get("state_out",[]))
                if not overlap: continue
                if left.get("execution_order")==right.get("execution_order"):
                    out.append(issue("MC0352", f"runtime intercept collision at {left.get('phase')} order {left.get('execution_order')} on {sorted(overlap)}", "two mechanisms mutate the same output without deterministic order", "unify or give an explicit nonconflicting execution order"))
                if left.get("composition_mode")=="DISCRETE_EXCLUSIVE" or right.get("composition_mode")=="DISCRETE_EXCLUSIVE":
                    out.append(issue("MC0353", f"exclusive runtime intercept collision at {left.get('phase')} on {sorted(overlap)}", "exclusive mechanisms compete for the same output", "unify them or reject one during cross-source synthesis"))
    missing_synthesis = sorted(synthesis_required_sources - mechanism_source_ids)
    if (mechanisms or requirements) and missing_synthesis:
        out.append(issue("MC0276", f"authorizing synthesis sources have no mechanism records: {missing_synthesis}", "source registration was mistaken for effective provenance use", "extract and disposition mechanisms before baseline compilation"))
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict):
            continue
        if source.get("kind") in synthesis_kinds:
            disposition = source.get("disposition")
            if disposition not in {"SYNTHESIS_REQUIRED", "ADJUDICATED_SYNTHESIS", "REFERENCE_ONLY", "REJECTED", "AUTHORITY_ONLY"}:
                out.append(issue("MC0283", f"source {source.get('id')} lacks explicit provenance disposition", "external design evidence could bypass mechanism accounting by remaining unclassified", "classify the source as SYNTHESIS_REQUIRED, ADJUDICATED_SYNTHESIS, REFERENCE_ONLY, REJECTED, or AUTHORITY_ONLY"))
            if not source.get("inspection_scope"):
                out.append(issue("MC0284", f"source {source.get('id')} lacks bounded inspection_scope", "the mission cannot show what part of a large source was intentionally assessed", "record the mechanisms/sections/interfaces that are in scope for inspection"))
            if disposition in authorizing_dispositions and source.get("kind") in {"REPOSITORY", "RESEARCH", "DOCUMENT"}:
                copyright_info = source.get("copyright")
                if not isinstance(copyright_info, dict):
                    out.append(issue("MC0277", f"source {source.get('id')} lacks rights-aware copyright posture", "source-derived implementation has no verified reuse boundary", "record usage mode, rights basis, permissions, obligations and evidence"))
                else:
                    mode = copyright_info.get("usage_mode")
                    rights_status = copyright_info.get("rights_status")
                    if mode not in {"OWNER_AUTHORIZED_REUSE", "LICENSE_PERMITTED_REUSE", "CLEAN_ROOM_BEHAVIORAL_SYNTHESIS"}:
                        out.append(issue("MC0277", f"source {source.get('id')} has non-authorizing usage mode {mode}", "authorizing synthesis source lacks a valid implementation-use boundary", "use owner-authorized, license-permitted or clean-room synthesis"))
                    if mode in {"OWNER_AUTHORIZED_REUSE", "LICENSE_PERMITTED_REUSE"}:
                        if rights_status != "VERIFIED" or not copyright_info.get("rights_basis") or not copyright_info.get("evidence_ref"):
                            out.append(issue("MC0314", f"source {source.get('id')} claims reusable rights without verified evidence", "direct/adapted reuse could exceed actual rights", "verify ownership/license at the exact source revision and record evidence_ref plus obligations"))
                    if mode == "LICENSE_PERMITTED_REUSE" and not source.get("license"):
                        out.append(issue("MC0315", f"source {source.get('id')} claims license-permitted reuse without license identity", "license obligations cannot be reconstructed", "record the exact license/SPDX identity and evidence"))
                    if mode == "CLEAN_ROOM_BEHAVIORAL_SYNTHESIS" and any(copyright_info.get(key) is not False for key in ("code_copy_allowed", "text_copy_allowed", "structure_reuse_allowed")):
                        out.append(issue("MC0316", f"source {source.get('id')} clean-room posture permits direct reuse", "rights mode and permissions contradict each other", "disable code/text/structure reuse or select a verified reuse mode"))
    requirement_id_set = set(requirement_ids)
    source_by_id_global = {item.get("id"): item for item in sources if isinstance(item, dict)}
    for mechanism in mechanisms if isinstance(mechanisms, list) else []:
        if isinstance(mechanism, dict):
            posture = mechanism.get("copyright_posture", {})
            mode = posture.get("mode") if isinstance(posture, dict) else None
            reuse_source_ids = set(posture.get("reuse_source_ids", [])) if isinstance(posture, dict) else set()
            copied_code = posture.get("copied_code") is True if isinstance(posture, dict) else False
            copied_text = posture.get("copied_text") is True if isinstance(posture, dict) else False
            reused_structure = posture.get("distinctive_structure_reused") is True if isinstance(posture, dict) else False
            reuse_class = posture.get("reuse_class") if isinstance(posture, dict) else None
            if mode == "CLEAN_ROOM_BEHAVIORAL_SYNTHESIS" and (copied_code or copied_text or reused_structure or reuse_source_ids):
                out.append(issue("MC0317", f"mechanism {mechanism.get('id')} clean-room posture contains direct reuse", "mechanism rights declaration contradicts its implementation evidence", "remove direct reuse or bind it to a verified owner/license reuse mode"))
            if (copied_code or copied_text or reused_structure or reuse_class in {"ADAPTED_IMPLEMENTATION", "DIRECT_REUSE", "MIXED"}) and not reuse_source_ids and mode != "CLEAN_ROOM_BEHAVIORAL_SYNTHESIS":
                out.append(issue("MC0318", f"mechanism {mechanism.get('id')} direct/adapted reuse lacks reuse_source_ids", "the exact source granting reuse rights is ambiguous", "bind every reused implementation element to exact admitted source ids"))
            unknown_reuse = reuse_source_ids - set(mechanism.get("source_ids", []))
            if unknown_reuse:
                out.append(issue("MC0319", f"mechanism {mechanism.get('id')} reuses undeclared sources: {sorted(unknown_reuse)}", "reuse lineage escaped mechanism provenance", "reuse only sources already declared by the mechanism"))
            mechanism_obligations = set(posture.get("obligations", [])) if isinstance(posture, dict) else set()
            for reuse_sid in sorted(reuse_source_ids):
                src = source_by_id_global.get(reuse_sid)
                cr = src.get("copyright", {}) if isinstance(src, dict) else {}
                src_mode = cr.get("usage_mode") if isinstance(cr, dict) else None
                if src_mode not in {"OWNER_AUTHORIZED_REUSE", "LICENSE_PERMITTED_REUSE"} or cr.get("rights_status") != "VERIFIED":
                    out.append(issue("MC0320", f"mechanism {mechanism.get('id')} reuses {reuse_sid} without verified reuse rights", "implementation may exceed admitted rights", "verify source rights or revert this mechanism to clean-room synthesis"))
                    continue
                if copied_code and cr.get("code_copy_allowed") is not True:
                    out.append(issue("MC0321", f"mechanism {mechanism.get('id')} copies code from {reuse_sid} without code-copy permission", "reuse exceeds admitted permission", "adapt without copying or update rights evidence"))
                if copied_text and cr.get("text_copy_allowed") is not True:
                    out.append(issue("MC0322", f"mechanism {mechanism.get('id')} copies text from {reuse_sid} without text-copy permission", "reuse exceeds admitted permission", "paraphrase or update rights evidence"))
                if reused_structure and cr.get("structure_reuse_allowed") is not True:
                    out.append(issue("MC0323", f"mechanism {mechanism.get('id')} reuses structure from {reuse_sid} without structure permission", "reuse exceeds admitted permission", "derive a target-native structure or update rights evidence"))
                missing_obligations = set(cr.get("obligations", [])) - mechanism_obligations
                if missing_obligations:
                    out.append(issue("MC0324", f"mechanism {mechanism.get('id')} omits source obligations for {reuse_sid}: {sorted(missing_obligations)}", "license/ownership obligations can be lost during implementation", "carry all source obligations into the mechanism reuse record"))
            unknown_requirements = set(mechanism.get("target_requirements", [])) - requirement_id_set
            if requirements and unknown_requirements:
                out.append(issue("MC0278", f"mechanism {mechanism.get('id')} references unknown target requirements: {sorted(unknown_requirements)}", "synthesis and target corpus drifted", "restore bidirectional mechanism/requirement accounting"))
    for requirement in requirements if isinstance(requirements, list) else []:
        if not isinstance(requirement, dict):
            continue
        declared_mechanisms = set(requirement.get("mechanisms", []))
        requirement_source_ids = set(requirement.get("sources", []))
        bound_mechanism_source_ids = set()
        for mech_id in declared_mechanisms:
            mech_obj = mechanism_by_id.get(str(mech_id))
            if isinstance(mech_obj, dict):
                mech_sources = set(mech_obj.get("source_ids", []))
                bound_mechanism_source_ids.update(mech_sources)
                missing_from_req = mech_sources - requirement_source_ids
                if missing_from_req:
                    out.append(issue(
                        "MC0351",
                        f"requirement {requirement.get('id')} binds mechanism {mech_id} with source ids omitted from requirement.sources: {sorted(missing_from_req)}",
                        "mechanism source lineage was omitted from target requirement",
                        "include all mechanism source ids in requirement.sources or remove the mechanism binding",
                    ))
        effective_source_ids = requirement_source_ids | bound_mechanism_source_ids
        source_kinds = {
            item.get("kind") for item in sources
            if isinstance(item, dict) and item.get("id") in effective_source_ids
        }
        source_driven = bool(source_kinds & synthesis_kinds)
        source_by_id = {item.get("id"): item for item in sources if isinstance(item, dict)}
        rejected_bound_mechanisms = sorted(
            str(mech_id) for mech_id in declared_mechanisms
            if isinstance(mechanism_by_id.get(str(mech_id)), dict) and mechanism_by_id[str(mech_id)].get("disposition") == "REJECTED"
        )
        if rejected_bound_mechanisms:
            out.append(issue("MC0352", f"requirement {requirement.get('id')} binds rejected mechanisms: {rejected_bound_mechanisms}", "rejected mechanisms remained target authority through the corpus", "remove rejected mechanism ids from the requirement and synthesis target bindings"))
        prohibited_requirement_sources = sorted(
            sid for sid in requirement_source_ids
            if isinstance(source_by_id.get(sid), dict)
            and source_by_id[sid].get("kind") in synthesis_kinds
            and source_by_id[sid].get("disposition") not in authorizing_dispositions
        )
        if prohibited_requirement_sources:
            out.append(issue("MC0300", f"requirement {requirement.get('id')} cites non-authorizing sources: {prohibited_requirement_sources}", "REFERENCE_ONLY/REJECTED material was allowed to influence target authority", "remove the citation from the requirement or re-admit the source with an authorizing synthesis disposition and complete source assessment"))
        if source_driven:
            if not declared_mechanisms:
                out.append(issue("MC0279", f"source-driven requirement {requirement.get('id')} has no mechanism bindings", "target corpus jumped directly from citation to mutation", "bind the requirement to provenance mechanism ids and a FlyBy derivation"))
            derivation = requirement.get("derivation")
            if not isinstance(derivation, dict):
                out.append(issue("MC0280", f"source-driven requirement {requirement.get('id')} lacks derivation contract", "source behavior is not translated into target-native architecture", "record owned abstraction, composition, preservation, non-goals, verification and copyright posture"))
            else:
                posture = derivation.get("copyright_posture")
                if posture not in {"CLEAN_ROOM_BEHAVIORAL_SYNTHESIS", "OWNER_AUTHORIZED_REUSE", "LICENSE_PERMITTED_REUSE", "MIXED_RIGHTS_AWARE_SYNTHESIS"}:
                    out.append(issue("MC0349", f"source-driven requirement {requirement.get('id')} has invalid copyright posture: {posture}", "derivation copyright posture is not a recognized rights mode", "set copyright_posture to a valid rights posture"))
        for sid in sorted(requirement_source_ids):
            source = source_by_id.get(sid)
            if not isinstance(source, dict) or source.get("disposition") not in authorizing_dispositions:
                continue
            bound_for_source = {
                mech_id for mech_id in declared_mechanisms
                if mech_id in mechanism_id_set and sid in set(next((m.get("source_ids", []) for m in mechanisms if isinstance(m, dict) and m.get("id") == mech_id), []))
            }
            if not bound_for_source:
                out.append(issue("MC0301", f"requirement {requirement.get('id')} cites authorizing synthesis source {sid} but none of its declared mechanisms cite that source", "source-level requirement provenance can be nominal rather than causal", "bind at least one exact mechanism from that source or remove the source from the requirement"))
        unknown_mechanisms = declared_mechanisms - mechanism_id_set
        if unknown_mechanisms:
            out.append(issue("MC0281", f"requirement {requirement.get('id')} references unknown mechanisms: {sorted(unknown_mechanisms)}", "target corpus escaped the provenance synthesis matrix", "bind only to mechanisms in PROVENANCE_SYNTHESIS.json"))
        reverse = requirement_to_mechanisms.get(str(requirement.get("id")), set())
        if declared_mechanisms != reverse:
            out.append(issue("MC0282", f"requirement {requirement.get('id')} mechanism accounting differs from synthesis matrix: corpus={sorted(declared_mechanisms)} synthesis={sorted(reverse)}", "source -> mechanism -> requirement lineage is not bidirectional", "make TARGET_MUTATIONS and PROVENANCE_SYNTHESIS agree exactly"))
    expected_refs = {
        "execution_dag": "control/EXECUTION_DAG.json",
        "execution_state": "control/EXECUTION_STATE.json",
        "compiler_control": "control/COMPILER_CONTROL.json",
        "session_residency": "control/SESSION_RESIDENCY.json",
        "workspace_ledger": "control/WORKSPACE_LEDGER.json",
        "target_mutation_corpus": "corpus/TARGET_MUTATIONS.json",
        "source_registry": "corpus/SOURCES.json",
        "provenance_synthesis": "corpus/PROVENANCE_SYNTHESIS.json",
    }
    for key, expected in expected_refs.items():
        if current.get(key) != expected:
            out.append(issue("MC0171", f"CURRENT_AUTHORITY {key} must be {expected}", "duplicate/renamed authority path introduced drift", "restore canonical v16 path"))
    if dag.get("schema") != DAG_SCHEMA or dag.get("mission_id") != mid:
        out.append(issue("MC0172", "execution DAG schema/mission mismatch", "topology does not belong to current authority", "recompile topology from current mission authority"))
    cells = dag.get("cells", [])
    if not isinstance(cells, list):
        out.append(issue("MC0173", "execution DAG cells must be a list", "invalid topology representation", "recompile DAG"))
        cells = []
    graph_errors = _generic_graph_issues(cells, "cell_id", "dependencies")
    for error in graph_errors:
        out.append(issue("MC0174", error, "invalid canonical topology", "repair DAG before dispatch"))
    if not graph_errors:
        for error in _phase_order_violations(dag):
            out.append(issue(
                "MC0261",
                error,
                "an executable workcell depends on authority from a later lifecycle phase and can be silently promoted past its declared execution boundary",
                "reverse the dependency so MUTATION precedes INTEGRATION and INTEGRATION precedes QUALIFICATION",
            ))
        for cell in cells:
            cid = cell.get("cell_id")
            if cell.get("kind") == "BARRIER" and cid != "G000" and _cell_phase(dag, str(cid)) == "BASELINE":
                out.append(issue(
                    "MC0259",
                    f"post-baseline barrier {cid} infers BASELINE phase",
                    "a barrier compiled after G000 depends only on baseline authority and can never be accepted from the post-baseline lifecycle",
                    "make the barrier depend transitively on a MUTATION, INTEGRATION, or QUALIFICATION cell",
                ))
    for cell in cells:
        cid = cell.get("cell_id")
        for error in schema_errors(root, "contracts/schemas/CELL_SCHEMA.json", cell):
            out.append(issue("MC0225", f"cell {cid} schema violation: {error}", "canonical DAG contains a malformed cell descriptor", "restore/recompile the cell from the canonical schema"))
        if not isinstance(cell.get("conflict_class"), str) or not cell.get("conflict_class", "").strip():
            out.append(issue("MC0174", f"cell {cid} lacks conflict_class", "parallel safety metadata was omitted", "recompile topology with an explicit conflict class"))
        claims = cell.get("resource_claims")
        if not isinstance(claims, list) or not all(isinstance(x, str) and x.strip() for x in claims) or len(claims) != len(set(claims)):
            out.append(issue("MC0174", f"cell {cid} has invalid resource_claims", "parallel resource authority is ambiguous", "recompile topology with unique typed resource claims"))
        if cell.get("kind") == "BARRIER" and cell.get("acceptance") != [BARRIER_ACCEPTANCE]:
            out.append(issue(
                "MC0260",
                f"barrier {cid} has non-topological acceptance clauses",
                "barrier state is derived only from dependency acceptance, so arbitrary acceptance text would become an unverified authoritative claim",
                f"set barrier acceptance exactly to {BARRIER_ACCEPTANCE!r}",
            ))
    ids = {str(c.get("cell_id")) for c in cells}
    canonical_cells = {str(cell.get("cell_id")): cell for cell in cells}
    frontier_root = root / "frontiers"
    memberships: dict[str, str] = {}
    frontier_files = sorted(frontier_root.glob("*/FRONTIER.json")) if frontier_root.is_dir() else []
    if not frontier_files:
        out.append(issue("MC0229", "mission has no stored frontier descriptors", "canonical DAG lost its authored/compiler-input provenance", "restore F000 and all compiled frontier descriptors"))
    for frontier_path in frontier_files:
        try:
            frontier = load_json(frontier_path)
            frontier_id = frontier.get("frontier_id")
            if frontier_path.parent.name != frontier_id:
                out.append(issue("MC0230", f"frontier directory/name mismatch: {frontier_path.parent.name} != {frontier_id}", "frontier provenance path no longer identifies its descriptor", "restore the frontier under its canonical frontier_id directory"))
            for error in _validate_frontier(frontier):
                out.append(issue("MC0231", f"frontier {frontier_id} invalid: {error}", "stored compiler input no longer satisfies the frontier contract", "restore the accepted frontier descriptor"))
            for descriptor in frontier.get("cells", []):
                if not isinstance(descriptor, dict) or not isinstance(descriptor.get("cell_id"), str):
                    continue
                cid = descriptor["cell_id"]
                if cid in memberships and memberships[cid] != frontier_id:
                    out.append(issue("MC0232", f"cell {cid} appears in multiple frontiers: {memberships[cid]}, {frontier_id}", "cell provenance is ambiguous", "retain exactly one source frontier per canonical cell"))
                memberships[cid] = str(frontier_id)
                if cid not in canonical_cells:
                    out.append(issue("MC0233", f"frontier {frontier_id} contains non-canonical cell {cid}", "stored frontier and canonical DAG diverged", "restore the frontier/DAG pair from the accepted compiler transition"))
                elif descriptor != canonical_cells[cid]:
                    out.append(issue("MC0234", f"frontier descriptor drift for canonical cell {cid}", "authored compiler input no longer matches canonical DAG authority", "restore the immutable frontier descriptor or explicitly supersede the DAG"))
        except Exception as exc:
            out.append(issue("MC0235", f"cannot validate stored frontier {frontier_path.relative_to(root)}: {exc}", "frontier provenance is corrupt", "restore the frontier descriptor before any transition"))
    missing_frontier_provenance = sorted(ids - set(memberships))
    if missing_frontier_provenance:
        out.append(issue("MC0236", f"canonical cells lack source frontier provenance: {missing_frontier_provenance}", "DAG contains cells that cannot be traced to a stored compiler input", "restore each cell's immutable source frontier"))

    if state.get("schema") != STATE_SCHEMA or state.get("mission_id") != mid:
        out.append(issue("MC0175", "execution state schema/mission mismatch", "state belongs to a different mission/revision", "regenerate execution state"))
    lifecycle = state.get("lifecycle")
    if lifecycle not in LIFECYCLE:
        out.append(issue("MC0176", f"invalid lifecycle state: {lifecycle}", "manual/unsupported lifecycle transition", "use mc lifecycle commands"))
    workspace_reconciliation_path = root / "handoff" / "WORKSPACE_RECONCILIATION.json"
    if workspace_reconciliation_path.is_file():
        try:
            reconciliation = load_json(workspace_reconciliation_path)
            for error in schema_errors(root, "contracts/schemas/WORKSPACE_RECONCILIATION_SCHEMA.json", reconciliation):
                out.append(issue("MC0285", f"workspace reconciliation invalid: {error}", "workspace/candidate closure accounting is malformed", "repair or regenerate WORKSPACE_RECONCILIATION.json"))
            if reconciliation.get("mission_id") != mid:
                out.append(issue("MC0286", "workspace reconciliation mission_id differs from current authority", "foreign reconciliation artifact was attached", "restore this mission's reconciliation artifact"))
            qualification_for_reconciliation = root / "handoff" / "QUALIFICATION.json"
            if qualification_for_reconciliation.is_file():
                for error in validate_workspace_reconciliation_accounting(root, reconciliation, load_json(qualification_for_reconciliation)):
                    out.append(issue("MC0287", f"workspace reconciliation accounting invalid: {error}", "workspace/candidate state does not reconcile to accepted qualification", "repair workspace reconciliation before closure"))
        except Exception as exc:
            out.append(issue("MC0285", f"workspace reconciliation cannot be validated: {exc}", "reconciliation artifact is corrupt", "repair or remove the artifact until it can be regenerated"))

    if lifecycle in {"ACCEPTED", "CLOSED"}:
        qualification_ref = state.get("qualification_ref")
        qualification_path = resolve_ref(root, str(qualification_ref))
        if qualification_ref != "handoff/QUALIFICATION.json" or not qualification_path.is_file():
            out.append(issue("MC0202", "accepted mission lacks canonical qualification evidence", "qualification artifact was removed or state advanced without proof", "restore qualification evidence or invalidate the lifecycle state"))
        else:
            if state.get("qualification_sha256") != sha256(qualification_path):
                out.append(issue("MC0203", "qualification evidence hash drift", "qualification changed after acceptance", "restore immutable qualification evidence or invalidate acceptance"))
            try:
                qualification = load_json(qualification_path)
                qualification_errors = schema_errors(root, "contracts/schemas/QUALIFICATION_SCHEMA.json", qualification)
                qualification_errors.extend(validate_qualification_accounting(root, qualification))
                for error in qualification_errors:
                    out.append(issue("MC0204", f"qualification evidence invalid: {error}", "qualification no longer satisfies its contract", "restore valid evidence or invalidate acceptance"))
            except Exception as exc:
                out.append(issue("MC0204", f"qualification evidence cannot be validated: {exc}", "qualification artifact is corrupt", "restore valid evidence or invalidate acceptance"))
    if lifecycle == "CLOSED":
        closure_ref = state.get("closure_ref")
        closure_path = resolve_ref(root, str(closure_ref))
        if closure_ref != "handoff/CLOSURE.json" or not closure_path.is_file():
            out.append(issue("MC0205", "closed mission lacks canonical closure evidence", "closure artifact was removed or state advanced without proof", "restore closure evidence or invalidate CLOSED"))
        else:
            if state.get("closure_sha256") != sha256(closure_path):
                out.append(issue("MC0206", "closure evidence hash drift", "closure changed after CLOSED", "restore immutable closure evidence or invalidate CLOSED"))
            try:
                closure = load_json(closure_path)
                for error in schema_errors(root, "contracts/schemas/CLOSURE_SCHEMA.json", closure):
                    out.append(issue("MC0207", f"closure evidence invalid: {error}", "closure no longer satisfies its contract", "restore valid closure evidence or invalidate CLOSED"))
                if closure.get("mission_id") != mid:
                    out.append(issue("MC0208", "closure mission_id differs from current authority", "foreign closure artifact was attached", "restore the mission's own closure evidence"))
                if closure.get("qualification_sha256") != state.get("qualification_sha256"):
                    out.append(issue("MC0209", "closure qualification hash differs from accepted qualification", "closure does not bind the accepted proof", "regenerate closure from the immutable accepted qualification"))
                workspace_ref = closure.get("workspace_reconciliation_ref")
                workspace_path = resolve_ref(root, str(workspace_ref))
                if workspace_ref != "handoff/WORKSPACE_RECONCILIATION.json" or not workspace_path.is_file():
                    out.append(issue("MC0288", "closure lacks canonical workspace reconciliation", "mission closed while external workspace/candidate state remained unbound", "restore the final reconciliation artifact or invalidate CLOSED"))
                elif closure.get("workspace_reconciliation_sha256") != sha256(workspace_path):
                    out.append(issue("MC0289", "closure workspace reconciliation hash drift", "reconciliation changed after closure", "restore immutable reconciliation evidence or invalidate CLOSED"))
                qualification = load_json(root / "handoff" / "QUALIFICATION.json")
                for key in ("target_outcomes", "requirement_accounting", "verification_accounting", "unresolved_defects", "explicit_limitations"):
                    if closure.get(key) != qualification.get(key):
                        out.append(issue("MC0241", f"closure {key} differs from accepted qualification", "closure accounting was changed independently from accepted evidence", "regenerate closure deterministically from QUALIFICATION.json"))
            except Exception as exc:
                out.append(issue("MC0207", f"closure evidence cannot be validated: {exc}", "closure artifact is corrupt", "restore valid closure evidence or invalidate CLOSED"))
    state_cells = state.get("cells", {})
    if not isinstance(state_cells, dict) or set(state_cells) != ids:
        out.append(issue("MC0177", "execution-state cell set differs from canonical DAG", "topology/state mutated independently", "reconcile through mc compile; never hand-edit one side"))
    else:
        for cid, record in state_cells.items():
            if not isinstance(record, dict):
                out.append(issue("MC0178", f"invalid state record for {cid}", "execution-state cell record is not an object", "restore execution state before any transition"))
                continue
            if record.get("state") not in CELL_STATES:
                out.append(issue("MC0178", f"invalid state record for {cid}", "unsupported state transition", "settle/recompile through mc commands"))
                continue
            canonical_cell = next((c for c in cells if c.get("cell_id") == cid), None)
            workcell = record.get("workcell_ref")
            needs_workcell = canonical_cell and canonical_cell.get("kind") != "BARRIER" and record.get("state") in {"COMPILED", "DISPATCHED", "CANDIDATE", "ACCEPTED", "REJECTED", "FAILED", "BLOCKED"}
            if needs_workcell and not isinstance(workcell, str):
                out.append(issue("MC0179", f"cell {cid} state {record.get('state')} lacks workcell_ref", "executable state outlived its compiled packet", "restore or deterministically recompile the packet"))
            if needs_workcell and isinstance(workcell, str):
                workcell_path = resolve_ref(root, workcell)
                if not workcell_path.is_file():
                    out.append(issue("MC0179", f"workcell_ref missing for {cid}: {workcell}", "compiled state outlived its packet", "recompile the affected frontier"))
                else:
                    try:
                        packet = load_json(workcell_path)
                        cell = next((c for c in cells if c.get("cell_id") == cid), None)
                        frontier_id = packet.get("frontier_id")
                        if not cell or not isinstance(frontier_id, str):
                            raise ValueError("packet lacks canonical cell/frontier identity")
                        expected_packet, expected_manifest = _build_cell_packet(root, frontier_id, cell)
                        for error in schema_errors(root, "contracts/schemas/WORKCELL_SCHEMA.json", packet):
                            out.append(issue("MC0254", f"compiled workcell schema violation for {cid}: {error}", "materialized workcell escaped its executable contract", "invalidate and deterministically recompile the cell"))
                        if packet != expected_packet:
                            out.append(issue("MC0187", f"compiled packet parity drift for {cid}", "materialized packet no longer equals pure compiler output", "invalidate and deterministically recompile the cell"))
                        manifest_ref = packet.get("context_manifest_ref")
                        manifest_path = resolve_ref(root, str(manifest_ref))
                        if not manifest_path.is_file():
                            out.append(issue("MC0188", f"context manifest missing for {cid}", "compiled context disappeared after materialization", "recompile packet and exact context together"))
                        else:
                            materialized_manifest = load_json(manifest_path)
                            for error in schema_errors(root, "contracts/schemas/CONTEXT_MANIFEST_SCHEMA.json", materialized_manifest):
                                out.append(issue("MC0253", f"ContextManifest schema violation for {cid}: {error}", "materialized context escaped its executable contract", "recompile packet and exact context together"))
                            if materialized_manifest != expected_manifest:
                                out.append(issue("MC0188", f"context manifest parity drift for {cid}", "compiled context changed independently from the cell packet", "recompile packet and exact context together"))
                        for error in validate_attempt_history(root, cid, record, packet):
                            out.append(issue("MC0216", f"attempt lineage invalid for {cid}: {error}", "retry/settlement history is incomplete or was mutated", "restore immutable attempt evidence or invalidate/re-execute the cell"))
                    except Exception as exc:
                        out.append(issue("MC0189", f"cannot verify compiled packet parity for {cid}: {exc}", "packet/context corruption", "recompile the affected frontier"))
            settled = canonical_cell and canonical_cell.get("kind") != "BARRIER" and record.get("state") in {"CANDIDATE", "ACCEPTED", "REJECTED", "FAILED", "BLOCKED"}
            if settled:
                result_ref = record.get("result_ref")
                receipt_ref = record.get("context_receipt_ref")
                adjudication_ref = record.get("adjudication_ref")
                result_path = resolve_ref(root, str(result_ref))
                receipt_path = resolve_ref(root, str(receipt_ref))
                adjudication_path = resolve_ref(root, str(adjudication_ref))
                if not isinstance(result_ref, str) or not result_path.is_file():
                    out.append(issue("MC0190", f"settled cell {cid} lacks durable result_ref", "settlement lost required structured evidence", "restore evidence or invalidate settlement"))
                elif record.get("result_sha256") != sha256(result_path):
                    out.append(issue("MC0198", f"settled result hash drift for {cid}", "result evidence changed after settlement", "restore immutable result evidence or invalidate settlement"))
                if not isinstance(receipt_ref, str) or not receipt_path.is_file():
                    out.append(issue("MC0190", f"settled cell {cid} lacks durable context_receipt_ref", "settlement lost required structured evidence", "restore evidence or invalidate settlement"))
                elif record.get("context_receipt_sha256") != sha256(receipt_path):
                    out.append(issue("MC0199", f"settled ContextReceipt hash drift for {cid}", "context evidence changed after settlement", "restore immutable ContextReceipt or invalidate settlement"))
                if not isinstance(adjudication_ref, str) or not adjudication_path.is_file():
                    out.append(issue("MC0255", f"settled cell {cid} lacks durable adjudication_ref", "worker claim was settled without independent control adjudication evidence", "restore adjudication evidence or invalidate settlement"))
                elif record.get("adjudication_sha256") != sha256(adjudication_path):
                    out.append(issue("MC0256", f"settled adjudication hash drift for {cid}", "control adjudication changed after settlement", "restore immutable adjudication evidence or invalidate settlement"))
                if result_path.is_file() and receipt_path.is_file() and adjudication_path.is_file() and isinstance(workcell, str) and resolve_ref(root, workcell).is_file():
                    try:
                        packet = load_json(resolve_ref(root, workcell))
                        settled_result = load_json(result_path)
                        settled_receipt = load_json(receipt_path)
                        settled_adjudication = load_json(adjudication_path)
                        settlement_errors = validate_result(root, settled_result, cid, packet)
                        settlement_errors.extend(validate_context_receipt(root, settled_receipt, cid, packet["context_manifest_ref"], packet["base_head"]))
                        settlement_errors.extend(validate_context_accounting(root, settled_receipt, packet, str(settled_result.get("outcome"))))
                        settlement_errors.extend(validate_adjudication(
                            root,
                            settled_adjudication,
                            cid,
                            int(record.get("attempt", 0)),
                            settled_result,
                            settled_receipt,
                            packet,
                            expected_worker_identity=record.get("worker_identity") if isinstance(record.get("worker_identity"), str) else None,
                            expected_verifier_identity=record.get("verifier_identity") if isinstance(record.get("verifier_identity"), str) else None,
                        ))
                        expected_state = adjudication_state(settled_adjudication.get("decision"))
                        if expected_state != record.get("state"):
                            settlement_errors.append(f"adjudication decision maps to {expected_state}, state records {record.get('state')}")
                        for error in settlement_errors:
                            out.append(issue("MC0200", f"settlement evidence invalid for {cid}: {error}", "settled evidence no longer satisfies its compiled contracts", "restore original evidence or invalidate/re-execute the cell"))
                    except Exception as exc:
                        out.append(issue("MC0201", f"cannot validate settlement evidence for {cid}: {exc}", "settlement evidence or workcell is corrupt", "restore original evidence or invalidate/re-execute the cell"))

        frontier_state = state.get("frontier", {})
        if not isinstance(frontier_state, dict):
            out.append(issue("MC0210", "execution-state frontier summary is not an object", "aggregate state was corrupted", "rebuild execution state from canonical cell records"))
        else:
            expected_compiled = {cid for cid, record in state_cells.items() if isinstance(record, dict) and isinstance(record.get("workcell_ref"), str)}
            expected_dispatched = {cid for cid, record in state_cells.items() if isinstance(record, dict) and record.get("state") == "DISPATCHED"}
            expected_accepted = {cid for cid, record in state_cells.items() if isinstance(record, dict) and record.get("state") == "ACCEPTED"}
            for key, expected in (("compiled", expected_compiled), ("dispatched", expected_dispatched), ("accepted", expected_accepted)):
                actual = frontier_state.get(key)
                if not isinstance(actual, list) or set(actual) != expected or len(actual) != len(set(actual)):
                    out.append(issue("MC0211", f"frontier.{key} disagrees with canonical cell records", "aggregate frontier state drifted independently", "rebuild the frontier summary from execution-state cell records"))

        baseline_gate = state_cells.get("G000", {}).get("state") if isinstance(state_cells.get("G000"), dict) else None
        if lifecycle in {"BASELINE_ACCEPTED", "MUTATION_READY", "INTEGRATING", "QUALIFYING", "ACCEPTED", "CLOSED"} and baseline_gate != "ACCEPTED":
            out.append(issue("MC0212", f"lifecycle {lifecycle} requires accepted G000", "lifecycle advanced without the baseline gate", "restore G000 acceptance or roll lifecycle back"))
        mutation_ids = [c.get("cell_id") for c in cells if c.get("kind") == "MUTATION"]
        if lifecycle in {"BASELINE_ACCEPTED", "MUTATION_READY", "INTEGRATING", "QUALIFYING", "ACCEPTED", "CLOSED"} and not requirement_ids:
            out.append(issue("MC0247", f"lifecycle {lifecycle} requires a non-empty target mutation corpus", "baseline was accepted without durable target requirements", "load the canonical target corpus before crossing G000"))
        if lifecycle in {"INTEGRATING", "QUALIFYING", "ACCEPTED", "CLOSED"}:
            covered_requirements = {
                requirement_id
                for cell in cells if cell.get("kind") == "MUTATION"
                for requirement_id in cell.get("requirement_ids", [])
            }
            missing_bindings = active_requirement_ids - covered_requirements
            if missing_bindings:
                out.append(issue("MC0248", f"active target requirements lack mutation-cell bindings: {sorted(missing_bindings)}", "integration began without implementation authority for every non-waived target requirement", "compile mutation cells that bind every active target requirement before integration"))
            criterion_gaps = requirement_acceptance_gaps(target_corpus, cells)
            if criterion_gaps:
                out.append(issue("MC0258", f"active requirement acceptance criteria are not carried by bound mutation cells: {criterion_gaps}", "execution contracts can be accepted without covering the frozen requirement acceptance clauses", "add every frozen requirement acceptance clause to one or more bound mutation-cell acceptance contracts before integration"))
            target_gaps = requirement_target_gaps(target_corpus, cells)
            if target_gaps:
                out.append(issue(
                    "MC0263",
                    f"active requirement target repositories lack bound mutation coverage: {target_gaps}",
                    "a requirement can appear implemented while one or more repositories in its frozen target scope received no mutation authority",
                    "compile bound mutation cells covering every repository listed in each active requirement targets field",
                ))
            target_criterion_gaps = requirement_target_acceptance_gaps(target_corpus, cells)
            if target_criterion_gaps:
                out.append(issue(
                    "MC0265",
                    f"active requirement acceptance criteria are not carried on every targeted repository: {target_criterion_gaps}",
                    "global requirement accounting can appear complete while one targeted repository never receives authority for one or more frozen acceptance clauses",
                    "carry every frozen acceptance clause through bound mutation-cell contracts on every repository targeted by the requirement",
                ))
            required = _cells_through_phase(dag, "MUTATION")
            incomplete = [cid for cid in required if state_cells.get(cid, {}).get("state") != "ACCEPTED"]
            if not mutation_ids or incomplete:
                out.append(issue("MC0213", f"lifecycle {lifecycle} requires all mutation-phase cells accepted; incomplete={incomplete}", "integration began before the mutation phase settled", "complete/repair mutation-phase cells or roll lifecycle back"))
        if lifecycle in {"QUALIFYING", "ACCEPTED", "CLOSED"}:
            required = _cells_through_phase(dag, "INTEGRATION")
            incomplete = [cid for cid in required if state_cells.get(cid, {}).get("state") != "ACCEPTED"]
            if incomplete:
                out.append(issue("MC0214", f"lifecycle {lifecycle} has incomplete integration-phase cells: {incomplete}", "qualification began before integration evidence settled", "complete/repair integration-phase cells or roll lifecycle back"))
        if lifecycle in {"ACCEPTED", "CLOSED"}:
            required = _cells_through_phase(dag, "QUALIFICATION")
            incomplete = [cid for cid in required if state_cells.get(cid, {}).get("state") != "ACCEPTED"]
            if incomplete:
                out.append(issue("MC0215", f"lifecycle {lifecycle} has incomplete qualification-phase cells: {incomplete}", "mission acceptance bypassed qualification workcells/barriers", "complete/repair qualification-phase cells or invalidate acceptance"))
    if compiler.get("schema") != "flyby/mission-control-compiler-control/16":
        out.append(issue("MC0180", "compiler control schema mismatch", "bootstrap/compiler drift", "restore generated compiler control"))
    required_compiler_laws = {
        "aggregate_normalization": "FORBIDDEN",
        "compiler_parity": "PURE_PACKET_RECONSTRUCTION",
        "independent_adjudication_required": True,
        "preassigned_custody_required": True,
        "context_receipt_required": True,
        "session_residency_required": True,
    }
    for key, expected in required_compiler_laws.items():
        if compiler.get(key) != expected:
            out.append(issue("MC0191", f"compiler law drift: {key}", "v16 simplified away a retained safety contract", "restore canonical compiler control"))
    parallel = compiler.get("parallelism", {})
    if parallel.get("conflict_class_required") is not True or parallel.get("resource_claims_required") is not True:
        out.append(issue("MC0192", "compiler conflict/resource safety law missing", "parallel admission could ignore conflicting work", "restore conflict-safe compiler control"))
    residency_schema_errors = schema_errors(root, "contracts/schemas/SESSION_RESIDENCY_REGISTRY_SCHEMA.json", residency)
    if residency_schema_errors:
        for error in residency_schema_errors:
            out.append(issue("MC0193", f"session residency registry invalid: {error}", "continuation identity is no longer durable", "restore control/SESSION_RESIDENCY.json"))
    else:
        records = residency.get("records", [])
        binding_ids = [record.get("binding_id") for record in records]
        if len(binding_ids) != len(set(binding_ids)):
            out.append(issue("MC0217", "session residency binding_id values are not unique", "two settlements claim the same durable attempt identity", "restore one immutable binding per settled attempt"))
        bindings = {str(record.get("binding_id")): record for record in records if isinstance(record, dict)}
        expected_bindings: dict[str, tuple[str, dict[str, Any]]] = {}
        for cid, state_record in state_cells.items():
            if not isinstance(state_record, dict):
                continue
            for attempt_entry in state_record.get("attempt_history", []):
                if not isinstance(attempt_entry, dict) or not isinstance(attempt_entry.get("attempt"), int):
                    continue
                binding_id = f"{cid}:attempt-{attempt_entry['attempt']:04d}"
                expected_bindings[binding_id] = (cid, attempt_entry)
        missing = sorted(set(expected_bindings) - set(bindings))
        extra = sorted(set(bindings) - set(expected_bindings))
        if missing:
            out.append(issue("MC0197", f"settled attempts lack session residency bindings: {missing}", "settlement skipped continuation identity capture", "restore bindings from immutable attempt receipts"))
        for binding_id in extra:
            binding = bindings.get(binding_id)
            recoverable = False
            if isinstance(binding, dict) and ":attempt-" in binding_id:
                cid, suffix = binding_id.rsplit(":attempt-", 1)
                if suffix.isdigit():
                    attempt_number = int(suffix)
                    state_record = state_cells.get(cid, {})
                    result_path = root / "evidence" / cid / f"attempt-{attempt_number:04d}" / "result.json"
                    receipt_path = root / "evidence" / cid / f"attempt-{attempt_number:04d}" / "context_receipt.json"
                    adjudication_path = root / "evidence" / cid / f"attempt-{attempt_number:04d}" / "adjudication.json"
                    recoverable = (
                        isinstance(state_record, dict)
                        and state_record.get("state") == "DISPATCHED"
                        and state_record.get("attempt") == attempt_number
                        and result_path.is_file()
                        and receipt_path.is_file()
                        and adjudication_path.is_file()
                        and binding.get("origin_cell") == cid
                        and binding.get("origin_attempt") == f"attempt-{attempt_number:04d}"
                        and binding.get("context_receipt_ref") == receipt_path.relative_to(root).as_posix()
                        and binding.get("context_receipt_hash") == sha256(receipt_path)
                    )
            if recoverable:
                out.append(issue("MC0220", f"settlement transaction is resumable for {binding_id}", "residency/evidence committed before execution state during an interrupted settlement", "rerun the exact same `mc settle` attempt to complete the transaction"))
            else:
                out.append(issue("MC0218", f"session residency contains binding without a settled attempt: {binding_id}", "residency and execution state diverged", "remove the orphan binding or restore its exact attempt history"))
        for binding_id, (cid, attempt_entry) in expected_bindings.items():
            binding = bindings.get(binding_id)
            if not isinstance(binding, dict):
                continue
            receipt_ref = attempt_entry.get("context_receipt_ref")
            receipt_path = resolve_ref(root, str(receipt_ref))
            if binding.get("origin_cell") != cid:
                out.append(issue("MC0219", f"session binding {binding_id} has wrong origin_cell", "residency points at a foreign cell", "restore binding identity from attempt history"))
            if binding.get("origin_attempt") != f"attempt-{attempt_entry['attempt']:04d}":
                out.append(issue("MC0219", f"session binding {binding_id} has wrong origin_attempt", "residency points at a foreign attempt", "restore binding identity from attempt history"))
            if binding.get("context_receipt_ref") != receipt_ref:
                out.append(issue("MC0219", f"session binding {binding_id} references a different ContextReceipt", "residency no longer binds the settled attempt", "restore binding from immutable attempt history"))
            if not receipt_path.is_file():
                out.append(issue("MC0195", f"session binding {binding_id} references missing ContextReceipt", "residency outlived settlement evidence", "restore receipt or invalidate binding"))
            elif binding.get("context_receipt_hash") != sha256(receipt_path):
                out.append(issue("MC0196", f"session binding ContextReceipt hash drift for {binding_id}", "settled receipt changed after binding", "restore immutable receipt and registry binding"))
    target_map = {t["repository"]: t["baseline_sha"].lower() for t in spec.get("target_repositories", []) if isinstance(t, dict) and "repository" in t and "baseline_sha" in t}
    if current.get("target_baselines") != target_map:
        out.append(issue("MC0181", "CURRENT_AUTHORITY target baselines differ from MISSION.json", "target pin changed outside the author input/authority transition", "re-bootstrap or perform an explicit reviewed rebase transition"))
    requirement_id_set = set(requirement_ids)
    requirements_by_id = {
        requirement.get("id"): requirement
        for requirement in requirements if isinstance(requirements, list) and isinstance(requirement, dict) and isinstance(requirement.get("id"), str)
    }
    for cell in cells:
        if cell.get("kind") != "MUTATION":
            continue
        cell_requirements = set(cell.get("requirement_ids", []))
        unknown_requirements = cell_requirements - requirement_id_set
        if unknown_requirements:
            out.append(issue("MC0246", f"mutation {cell.get('cell_id')} references unknown requirements: {sorted(unknown_requirements)}", "execution topology escaped the canonical target corpus", "bind mutation cells only to requirement ids in TARGET_MUTATIONS.json"))
        waived_requirements = cell_requirements & set(frozen_requirement_waivers)
        if waived_requirements:
            out.append(issue("MC0257", f"mutation {cell.get('cell_id')} references frozen waived requirements: {sorted(waived_requirements)}", "execution authority was created for requirements explicitly waived before baseline compilation", "remove waived requirement ids from mutation cells or revise the frozen corpus before baseline compilation"))
        target = cell.get("target", {})
        repository = target.get("repository") if isinstance(target, dict) else None
        for requirement_id in sorted(cell_requirements & requirement_id_set):
            allowed_targets = set(requirements_by_id[requirement_id].get("targets", []))
            if repository not in allowed_targets:
                out.append(issue(
                    "MC0264",
                    f"mutation {cell.get('cell_id')} targets {repository} but requirement {requirement_id} is scoped to repositories {sorted(allowed_targets)}",
                    "mutation authority is bound to a requirement on the wrong target repository",
                    "recompile the mutation against a repository listed in the frozen requirement targets field",
                ))
        base_sha = str(target.get("base_sha", "")).lower() if isinstance(target, dict) else ""
        if repository not in target_map:
            out.append(issue("MC0184", f"mutation {cell.get('cell_id')} targets an unbound repository: {repository}", "mutation escaped MISSION.json target custody", "bind the repository in MISSION.json through an explicit authority revision"))
        elif base_sha != target_map[repository]:
            out.append(issue("MC0185", f"mutation {cell.get('cell_id')} base SHA differs from current target authority", "stale or foreign mutation packet", "recompile from the exact current target baseline"))
        if not isinstance(target, dict) or not target.get("owned_paths"):
            out.append(issue("MC0186", f"mutation {cell.get('cell_id')} has no owned write scope", "mutation authority is broader than its packet", "declare non-empty target.owned_paths"))
    for cid in BASELINE_AUDITS:
        cell = next((c for c in cells if c.get("cell_id") == cid), None)
        if not cell or cell.get("kind") != "AUDIT":
            out.append(issue("MC0182", f"mandatory baseline audit missing or wrong kind: {cid}", "generic baseline was removed/rewritten", "restore the built-in baseline frontier"))
    barrier = next((c for c in cells if c.get("cell_id") == "G000"), None)
    if not barrier or barrier.get("kind") != "BARRIER" or set(barrier.get("dependencies", [])) != set(BASELINE_AUDITS):
        out.append(issue("MC0183", "G000 baseline barrier does not bind all mandatory audits", "baseline gate was weakened", "restore G000 dependencies"))
    return out


def _collect_mcv6_issues(root: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    try:
        current = load_json(root / "control/CURRENT_AUTHORITY.json")
        control = current.get("control", {})
        dag_path = resolve_ref(root, str(control.get("canonical_dag", "control/PARALLEL_EXECUTION_DAG.json")))
        state_path = resolve_ref(root, str(control.get("execution_state", "control/EXECUTION_STATE.json")))
        compiler_path = resolve_ref(root, str(control.get("compiler_control", "control/WORKCELL_COMPILER_CONTROL.json")))
        dag = load_json(dag_path)
        state = load_json(state_path)
        load_json(compiler_path)
    except Exception as exc:
        return [issue("MCV6-001", f"MCV6 control authority cannot be loaded: {exc}", "missing/corrupt legacy control artifact", "restore the exact MCV6 branch artifact before execution")]
    if current.get("control", {}).get("root") != root.name:
        out.append(issue("MCV6-002", "CURRENT_AUTHORITY control.root does not match tested directory", "mission root was moved/aliased without authority migration", "test the canonical root or update authority in a reviewed revision"))
    canonical = control.get("canonical_dag_schema")
    if dag.get("schema") != canonical:
        out.append(issue("MCV6-003", "MCV6 DAG schema differs from CURRENT_AUTHORITY", "topology/current authority drift", "restore canonical DAG revision"))
    mission_id = current.get("mission_id")
    if dag.get("program") != mission_id or state.get("program") != mission_id:
        out.append(issue("MCV6-004", "MCV6 program identity differs across authority/DAG/state", "copied or stale control artifact", "reconcile to one mission identity"))
    target = current.get("target", {})
    baseline = str(target.get("baseline_sha", "")).lower()
    if str(dag.get("target_base", "")).lower() != baseline or str(state.get("target_base", {}).get("sha", "")).lower() != baseline:
        out.append(issue("MCV6-005", "MCV6 target baseline differs across authority/DAG/state", "target rebase was not propagated coherently", "publish a reviewed authority/topology/state revision"))
    cells = dag.get("cells", [])
    if not isinstance(cells, list):
        cells = []
        out.append(issue("MCV6-006", "MCV6 DAG cells are not a list", "corrupt topology", "restore DAG"))
    for error in _generic_graph_issues(cells, "id", "depends_on"):
        out.append(issue("MCV6-007", error, "invalid MCV6 canonical topology", "repair via explicit DAG revision"))
    ids = {str(c.get("id")) for c in cells}
    state_cells = state.get("cells", {})
    if not isinstance(state_cells, dict) or set(state_cells) != ids:
        out.append(issue("MCV6-008", "MCV6 execution-state cell set differs from DAG", "topology/state drift", "reconcile state to canonical DAG"))
    barriers = {str(x.get("id")) for x in dag.get("global_barriers", []) if isinstance(x, dict)}
    for bid in barriers:
        cell = next((c for c in cells if c.get("id") == bid), None)
        contract = dag.get("barrier_contracts", {}).get(bid, {})
        if not cell or cell.get("kind") != "barrier":
            out.append(issue("MCV6-009", f"barrier {bid} missing as DAG barrier cell", "barrier topology drift", "restore barrier cell"))
        elif set(cell.get("depends_on", [])) != set(contract.get("requires", [])):
            out.append(issue("MCV6-010", f"barrier {bid} dependencies differ from barrier contract", "barrier acceptance was weakened/drifted", "restore exact barrier contract"))
    for cid, record in (state_cells.items() if isinstance(state_cells, dict) else []):
        if not isinstance(record, dict):
            out.append(issue("MCV6-011", f"invalid state record for {cid}", "state corruption", "restore execution state"))
            continue
        workcell_ref = record.get("workcell_ref")
        if record.get("state") in {"COMPILED", "RUNNING", "CANDIDATE", "ACCEPTED"} and workcell_ref:
            path = resolve_ref(root, str(workcell_ref))
            if not path.is_file():
                out.append(issue("MCV6-012", f"compiled workcell missing for {cid}: {workcell_ref}", "packet/state drift", "restore or recompile packet before dispatch"))
            else:
                try:
                    workcell = load_json(path)
                    if workcell.get("cell_id") != cid or workcell.get("source_dag_cell") != cid:
                        out.append(issue("MCV6-013", f"workcell identity mismatch for {cid}", "wrong packet referenced by execution state", "recompile exact cell packet"))
                    head = str(workcell.get("base", {}).get("head", "")).lower()
                    if head and head != baseline:
                        out.append(issue("MCV6-014", f"workcell {cid} target base differs from frozen baseline", "stale/foreign compiled packet", "invalidate and recompile from accepted target base"))
                except Exception as exc:
                    out.append(issue("MCV6-015", f"workcell {cid} cannot be parsed: {exc}", "corrupt packet", "recompile exact cell packet"))
    checker = root / "tools" / "check_control_coherence.py"
    if not checker.is_file():
        out.append(issue("MCV6-016", "MCV6 native coherence checker is missing", "legacy mission lost its authoritative compatibility gate", "restore tools/check_control_coherence.py"))
    else:
        proc = subprocess.run([sys.executable, str(checker), "--root", str(root)], cwd=root, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "native coherence checker failed").strip().replace("\n", " | ")[:600]
            out.append(issue("MCV6-017", f"MCV6 native coherence checker failed: {detail}", "legacy control laws are violated even if the generic adapter parses", "repair the native MCV6 coherence failure; do not weaken the adapter"))
    return out


def collect_mission_issues(root: Path) -> list[dict[str, str]]:
    root = root.resolve()
    layout = detect_layout(root)
    try:
        if layout == "v16":
            return _collect_v16_issues(root)
        if layout == "mcv6-legacy":
            return _collect_mcv6_issues(root)
    except Exception as exc:
        return [issue(
            "MC0101",
            f"Mission Control coherence evaluation failed closed: {exc}",
            "a control reference escaped the mission root or a malformed artifact violated a checker precondition",
            "repair the reported control/reference corruption; do not bypass doctor",
        )]
    return [issue("MC0100", f"unsupported Mission Control layout at {root}", "root is not canonical v16 or recognized live MCV6", "point --root at the mission root or migrate/adapter the layout explicitly")]


def _template_root_from_source_cli() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "TEMPLATE.json").is_file():
        raise RuntimeError("init must run from the source mission-control-template/tools/mc.py")
    return root


def _template_provenance(template_root: Path) -> dict[str, str | None]:
    try:
        commit_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=template_root, check=True, capture_output=True, text=True,
        )
        base_commit = commit_proc.stdout.strip()
        if len(base_commit) != 40:
            raise ValueError("git HEAD is not a 40-character object id")
        # A portable template may be extracted inside an unrelated or ignored
        # Git worktree. Do not attribute its bytes to that enclosing commit.
        repo_proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=template_root,
            check=True, capture_output=True, text=True,
        )
        repo_root = Path(repo_proc.stdout.strip()).resolve()
        sources = [template_root / "TEMPLATE.json"] + [
            source for source, _ in _template_asset_pairs(template_root, template_root)
        ]
        relative_sources = [source.resolve().relative_to(repo_root).as_posix() for source in sources]
        tracked_proc = subprocess.run(
            ["git", "ls-files", "--cached", "--full-name", "-v", "-z", "--", *relative_sources],
            cwd=repo_root, check=True, capture_output=True,
        )
        tracked: dict[str, str] = {}
        for entry in tracked_proc.stdout.split(b"\0"):
            if not entry:
                continue
            if len(entry) < 3 or entry[1:2] != b" ":
                raise ValueError("unexpected git index entry")
            tracked[entry[2:].decode("utf-8", errors="strict")] = chr(entry[0])
        if relative_sources[0] not in tracked:
            return {"template_source_state": "UNVERSIONED", "template_commit": None, "template_base_commit": None}
        # Git status may intentionally skip files marked assume-unchanged or
        # skip-worktree. Such a checkout cannot prove its copied bytes clean.
        hidden_by_index = any(flag.islower() or flag.upper() == "S" for flag in tracked.values())
        status_proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "."],
            cwd=template_root,
            check=True,
            capture_output=True,
            text=True,
        )
        if status_proc.stdout.strip() or hidden_by_index or not set(relative_sources).issubset(tracked):
            return {
                "template_source_state": "DIRTY_WORKTREE",
                "template_commit": None,
                "template_base_commit": base_commit,
            }
        return {
            "template_source_state": "CLEAN_COMMIT",
            "template_commit": base_commit,
            "template_base_commit": base_commit,
        }
    except Exception:
        return {
            "template_source_state": "UNVERSIONED",
            "template_commit": None,
            "template_base_commit": None,
        }


def _template_asset_pairs(template_root: Path, root: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for source_dir, destination_dir in (
        (template_root / "schemas", root / "contracts" / "schemas"),
        (template_root / "policies", root / "contracts" / "policies"),
    ):
        for source in sorted(source_dir.rglob("*")):
            if source.is_file():
                pairs.append((source, destination_dir / source.relative_to(source_dir)))
    pairs.extend((
        (template_root / "tools" / "mc.py", root / "runtime" / "tools" / "mc.py"),
        (template_root / "tools" / "wt_mission.py", root / "runtime" / "tools" / "wt_mission.py"),
        (template_root / "tools" / "schema_subset.py", root / "runtime" / "tools" / "schema_subset.py"),
        (template_root / "tests" / "test_mission_control.py", root / "runtime" / "tests" / "test_mission_control.py"),
    ))
    return pairs


def _copy_assets(template_root: Path, root: Path) -> list[str]:
    copied: list[str] = []
    for source, destination in _template_asset_pairs(template_root, root):
        if not source.is_file():
            raise FileNotFoundError(f"template asset missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination.relative_to(root).as_posix())
    return copied


def _baseline_cells() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for cid, objective in BASELINE_AUDITS.items():
        cells.append({
            "cell_id": cid,
            "kind": "AUDIT",
            "dependencies": [],
            "objective": objective,
            "acceptance": ["typed result is evidence-backed", "no target mutation occurred", "unknown/unrun coverage remains explicit"],
            "status": "PENDING",
            "conflict_class": f"read:baseline:{cid.lower()}",
            "resource_claims": [],
            "consumer": "G000 baseline acceptance",
            "result_schema": "contracts/schemas/RESULT_SCHEMA.json",
        })
    cells.append({
        "cell_id": "G000",
        "kind": "BARRIER",
        "dependencies": list(BASELINE_AUDITS),
        "objective": "Accept the frozen current-state, verification, performance, provenance and environment baseline.",
        "acceptance": [BARRIER_ACCEPTANCE],
        "status": "PENDING",
        "conflict_class": "gate:baseline",
        "resource_claims": [],
    })
    return cells


def cmd_init(args: argparse.Namespace) -> int:
    template_root = _template_root_from_source_cli()
    mission_file = Path(args.mission).resolve()
    if not mission_file.is_file():
        print(f"MISSION.json not found: {mission_file}", file=sys.stderr)
        return 2
    spec = load_json(mission_file)
    errors = validate_mission_spec(spec)
    if errors:
        print(json.dumps({"state": "BOOTSTRAP_INVALID", "errors": errors}, indent=2), file=sys.stderr)
        return 1
    root = mission_file.parent
    generated = [
        root / "TEMPLATE_LOCK.json", root / "control", root / "runtime", root / "contracts",
        root / "corpus", root / "frontiers", root / "evidence", root / "handoff",
    ]
    existing = [path.relative_to(root).as_posix() for path in generated if path.exists()]
    if existing:
        print(f"mission root is not clean; generated paths already exist: {existing}. Use repair or a fresh mission root.", file=sys.stderr)
        return 1
    for rel in ("control", "corpus", "contracts/schemas", "contracts/policies", "runtime/tools", "runtime/tests", "frontiers/F000", "evidence", "handoff"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    copied = _copy_assets(template_root, root)
    target_map = {t["repository"]: t["baseline_sha"].lower() for t in spec["target_repositories"]}
    current = {
        "schema": AUTHORITY_SCHEMA,
        "mission_id": spec["mission_id"],
        "template_schema": TEMPLATE_SCHEMA,
        "mission_ref": "MISSION.json",
        "template_lock_ref": "TEMPLATE_LOCK.json",
        "execution_dag": "control/EXECUTION_DAG.json",
        "execution_state": "control/EXECUTION_STATE.json",
        "compiler_control": "control/COMPILER_CONTROL.json",
        "session_residency": "control/SESSION_RESIDENCY.json",
        "workspace_ledger": "control/WORKSPACE_LEDGER.json",
        "target_mutation_corpus": "corpus/TARGET_MUTATIONS.json",
        "source_registry": "corpus/SOURCES.json",
        "provenance_synthesis": "corpus/PROVENANCE_SYNTHESIS.json",
        "target_baselines": target_map,
        "status": "BOOTSTRAPPED",
    }
    cells = _baseline_cells()
    dag = {"schema": DAG_SCHEMA, "mission_id": spec["mission_id"], "revision": 1, "cells": cells}
    state_cells = {c["cell_id"]: {"state": "BLOCKED" if c["kind"] == "BARRIER" else "PENDING"} for c in cells}
    state = {
        "schema": STATE_SCHEMA,
        "mission_id": spec["mission_id"],
        "lifecycle": "BOOTSTRAPPED",
        "topology_ref": "control/EXECUTION_DAG.json",
        "cells": state_cells,
        "frontier": {"compiled": [], "dispatched": [], "accepted": []},
    }
    compiler = {
        "schema": "flyby/mission-control-compiler-control/16",
        "mission_id": spec["mission_id"],
        "dispatch_law": "ready -> compiled -> dependency-safe -> conflict-safe -> admitted",
        "capacity_authority": "EXTERNAL_ORCHESTRATOR",
        "mutation_gate": "BASELINE_ACCEPTED",
        "worker_report_is_candidate_evidence": True,
        "independent_adjudication_required": True,
        "preassigned_custody_required": True,
        "aggregate_normalization": "FORBIDDEN",
        "compiler_parity": "PURE_PACKET_RECONSTRUCTION",
        "context_receipt_required": True,
        "session_residency_required": True,
        "parallelism": {"conflict_class_required": True, "resource_claims_required": True},
        "commands": ["doctor", "status", "sources load", "provenance load", "corpus load", "workspace register", "workspace load", "baseline compile", "baseline accept", "barrier accept", "retry", "dispatch", "settle", "compile", "integrate", "qualify", "close", "test"],
    }
    write_json(root / "control" / "CURRENT_AUTHORITY.json", current)
    write_json(root / "control" / "EXECUTION_DAG.json", dag)
    write_json(root / "control" / "EXECUTION_STATE.json", state)
    write_json(root / "control" / "COMPILER_CONTROL.json", compiler)
    write_json(root / "control" / "SESSION_RESIDENCY.json", {"schema": "flyby/mission-control-session-residency-registry/1", "frontier_id": "ALL", "records": []})
    write_json(root / "control" / "WORKSPACE_LEDGER.json", {
        "schema": "flyby/mission-control-workspace-ledger/16",
        "mission_id": spec["mission_id"],
        "entries": [{
            "workspace_id": "control-authority",
            "kind": "CONTROL",
            "repository": spec["control_repository"],
            "branch": spec["authoritative_working_branch"],
            "base_sha": None,
            "registered_cell": None,
            "worktree_path": str(root),
            "head_sha": None,
            "dirty": None,
            "semantic_status_sha256": None,
            "remote_url": None,
        }],
    })
    write_json(root / "corpus" / "TARGET_MUTATIONS.json", {"schema": "flyby/mission-control-target-corpus/16", "mission_id": spec["mission_id"], "provenance_materialization": {"mode": "TARGET_HAS_NO_LINEAGE_MANIFEST", "target_refs": [], "coverage_requirement_id": None, "validation_schema_ref": None, "authority": "LINEAGE_ONLY", "acceptance": ["Mission author must explicitly confirm or replace this default before source-driven mutation compilation."]}, "requirements": []})
    source_entries = [{
        "id": "owner-intent",
        "kind": "OWNER_INTENT",
        "locator": "MISSION.json#owner_intent",
        "role": "Owner intent declared by the mission author",
    }]
    if spec.get("previous_mission_handoff"):
        handoff_pin = spec.get("previous_mission_handoff_sha256")
        if not handoff_pin:
            loc = str(spec["previous_mission_handoff"])
            try:
                loc_path = resolve_ref(root, loc)
                if loc_path.is_file():
                    handoff_pin = sha256(loc_path)
            except Exception:
                pass
        source_entries.append({
            "id": "previous-mission-handoff",
            "kind": "PREVIOUS_MISSION",
            "locator": spec["previous_mission_handoff"],
            "role": "Explicit previous-mission provenance handoff",
            "pin": handoff_pin,
            "disposition": "SYNTHESIS_REQUIRED",
            "inspection_scope": ["accepted prior-mission handoff claims, invariants, unresolved findings and reusable mechanisms"],
            "copyright": {"usage_mode": "AUTHORITY_ONLY", "rights_status": "NOT_APPLICABLE", "rights_basis": "previous mission authority", "code_copy_allowed": False, "text_copy_allowed": False, "structure_reuse_allowed": False, "obligations": [], "evidence_ref": spec["previous_mission_handoff"], "notes": "Previous mission output is provenance authority, but current target behavior must still be re-derived and re-verified."},
        })
    write_json(root / "corpus" / "SOURCES.json", {"schema": "flyby/mission-control-source-registry/16", "mission_id": spec["mission_id"], "sources": source_entries})
    write_json(root / "corpus" / "PROVENANCE_SYNTHESIS.json", {"schema": "flyby/mission-control-provenance-synthesis/17", "mission_id": spec["mission_id"], "methodology": {"source_handling": "RIGHTS_AWARE_FULL_POTENTIAL_SYNTHESIS", "implementation_rule": "FLYBY_OWNED_DERIVATION", "replacement_rule": "PRESERVE_EXTEND_COMBINE_BEFORE_REPLACE"}, "source_assessments": [], "mechanisms": [], "cross_source_synthesis": {"state": "PENDING", "evidence_ref": None, "mechanism_graph_sha256": None, "intercept_matrix_sha256": None, "combination_hypotheses_sha256": None, "evidence_sha256": None, "rationale": "No source-local synthesis has been admitted yet.", "intercept_matrix": [], "combination_hypotheses": []}})
    write_json(root / "frontiers" / "F000" / "FRONTIER.json", {"schema": FRONTIER_SCHEMA, "frontier_id": "F000", "cells": cells})
    assets = {rel: sha256(root / rel) for rel in sorted(copied)}
    write_json(root / "TEMPLATE_LOCK.json", {
        "schema": "flyby/mission-control-template-lock/16",
        "template_schema": TEMPLATE_SCHEMA,
        **_template_provenance(template_root),
        "source_template_root": "mission-control-template",
        "assets": assets,
    })
    problems = collect_mission_issues(root)
    if problems:
        current["status"] = "BOOTSTRAP_INVALID"
        write_json(root / "control" / "CURRENT_AUTHORITY.json", current)
        write_json(root / "control" / "BOOTSTRAP_INVALID.json", {"issues": problems})
        print(json.dumps({"state": "BOOTSTRAP_INVALID", "issues": problems}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state": "BOOTSTRAPPED", "root": str(root), "template": TEMPLATE_SCHEMA}, indent=2))
    return 0


def _doctor_or_fail(root: Path) -> bool:
    problems = collect_mission_issues(root)
    if problems:
        print(json.dumps({"state": "FAIL", "issues": problems}, indent=2), file=sys.stderr)
        return False
    return True


def _settlement_preflight(root: Path, cell_id: str, attempt: int) -> bool:
    problems = collect_mission_issues(root)
    expected_binding = f"{cell_id}:attempt-{attempt:04d}"
    blocking = [
        problem
        for problem in problems
        if not (problem.get("code") == "MC0220" and expected_binding in problem.get("message", ""))
    ]
    if blocking:
        print(json.dumps({"state": "FAIL", "issues": problems}, indent=2), file=sys.stderr)
        return False
    return True


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    problems = collect_mission_issues(root)
    if problems:
        print(json.dumps({"state": "FAIL", "layout": detect_layout(root), "issues": problems}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state": "PASS", "layout": detect_layout(root), "root": str(root)}, indent=2))
    return 0


def _load_v16(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if detect_layout(root) != "v16":
        raise RuntimeError("this command requires a canonical v16 mission")
    return load_json(root / "control" / "EXECUTION_DAG.json"), load_json(root / "control" / "EXECUTION_STATE.json")


def _save_state(root: Path, state: dict[str, Any]) -> None:
    write_json(root / "control" / "EXECUTION_STATE.json", state)


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    layout = detect_layout(root)
    if layout == "v16":
        dag, state = _load_v16(root)
        counts: dict[str, int] = {}
        for record in state["cells"].values():
            counts[record["state"]] = counts.get(record["state"], 0) + 1
        print(json.dumps({"layout": layout, "lifecycle": state["lifecycle"], "revision": dag["revision"], "cell_states": counts, "frontier": state["frontier"]}, indent=2))
    else:
        state = load_json(root / "control" / "EXECUTION_STATE.json")
        print(json.dumps({"layout": layout, "frontier": state.get("frontier", {}), "next_transition": state.get("next_transition")}, indent=2))
    return 0


def _load_semantic_input(root: Path, source_file: Path, destination: Path, schema_ref: str, label: str) -> int:
    if detect_layout(root) != "v16":
        print(f"{label} load requires a canonical v16 mission", file=sys.stderr)
        return 1
    try:
        _, state = _load_v16(root)
        mission = load_json(root / "MISSION.json")
        candidate = load_json(source_file)
    except Exception as exc:
        print(f"cannot load {label}: {exc}", file=sys.stderr)
        return 1
    if state.get("lifecycle") != "BOOTSTRAPPED":
        print(f"{label} can change only before baseline compilation; lifecycle is {state.get('lifecycle')}", file=sys.stderr)
        return 1
    errors = schema_errors(root, schema_ref, candidate)
    if candidate.get("mission_id") != mission.get("mission_id"):
        errors.append(f"{label} mission_id must equal {mission.get('mission_id')}")
    if label == "target corpus":
        if not candidate.get("requirements"):
            errors.append("target corpus must contain at least one requirement before loading")
        mission_repositories = {
            target.get("repository")
            for target in mission.get("target_repositories", [])
            if isinstance(target, dict) and isinstance(target.get("repository"), str)
        }
        for requirement in candidate.get("requirements", []):
            if not isinstance(requirement, dict):
                continue
            unknown_targets = set(requirement.get("targets", [])) - mission_repositories
            if unknown_targets:
                errors.append(
                    f"requirement {requirement.get('id')} targets repositories outside mission authority: {sorted(unknown_targets)}"
                )
    if label == "source registry":
        source_ids = [item.get("id") for item in candidate.get("sources", []) if isinstance(item, dict)]
        if "owner-intent" not in source_ids:
            errors.append("source registry must retain the built-in owner-intent provenance entry")
    if errors:
        print(json.dumps({"state": "REJECTED", "errors": errors}, indent=2), file=sys.stderr)
        return 1

    original = destination.read_bytes() if destination.is_file() else None
    write_json(destination, candidate)
    problems = collect_mission_issues(root)
    if problems:
        if original is None:
            destination.unlink(missing_ok=True)
        else:
            tmp = destination.with_name(destination.name + ".rollback.tmp")
            tmp.write_bytes(original)
            tmp.replace(destination)
        print(json.dumps({"state": "LOAD_ROLLED_BACK", "label": label, "issues": problems}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state": "LOADED", "label": label, "path": destination.relative_to(root).as_posix()}, indent=2))
    return 0


def cmd_sources_load(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    return _load_semantic_input(
        root,
        Path(args.file).resolve(),
        root / "corpus" / "SOURCES.json",
        "contracts/schemas/SOURCE_REGISTRY_SCHEMA.json",
        "source registry",
    )


def cmd_provenance_load(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    return _load_semantic_input(
        root,
        Path(args.file).resolve(),
        root / "corpus" / "PROVENANCE_SYNTHESIS.json",
        "contracts/schemas/PROVENANCE_SYNTHESIS_SCHEMA.json",
        "provenance synthesis",
    )


def cmd_workspace_register(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    workspace_id = str(args.workspace_id).strip()
    branch = str(args.branch).strip()
    if not workspace_id or not branch:
        print("workspace_id and branch must be non-empty", file=sys.stderr)
        return 1
    # main() serializes every mutating command with mission_control_lock(root).
    # Re-read mutation authority here while that outer inter-process lock is held.
    dag, state = _load_v16(root)
    cell = _find_cell(dag, args.cell)
    if not isinstance(cell, dict):
        print(f"unknown cell: {args.cell}", file=sys.stderr)
        return 1
    target = cell.get("target")
    if not isinstance(target, dict):
        print(f"cell {args.cell} has no target workspace authority", file=sys.stderr)
        return 1
    record = state.get("cells", {}).get(args.cell, {})
    if record.get("state") != "COMPILED":
        print(f"cell {args.cell} must be COMPILED before target workspace registration", file=sys.stderr)
        return 1
    ledger_path = root / "control" / "WORKSPACE_LEDGER.json"
    ledger = load_json(ledger_path)
    entries = ledger.get("entries", [])
    if not isinstance(entries, list):
        print("WORKSPACE_LEDGER entries are malformed", file=sys.stderr)
        return 1
    if any(isinstance(item, dict) and item.get("workspace_id") == workspace_id for item in entries):
        print(f"workspace id already registered: {workspace_id}", file=sys.stderr)
        return 1
    repository = str(target.get("repository"))
    if any(isinstance(item, dict) and item.get("kind") == "TARGET" and item.get("repository") == repository and item.get("branch") == branch for item in entries):
        print(f"target branch already registered: {repository}:{branch}", file=sys.stderr)
        return 1

    base_sha_val = str(target.get("base_sha", "")).lower()
    if args.path:
        wt = Path(args.path).resolve()
        if not wt.is_dir():
            print(f"worktree path does not exist or is not a directory: {args.path}", file=sys.stderr)
            return 1
        def git_probe(*git_args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["git", "-C", str(wt), *git_args], capture_output=True, text=True)
        p_top = git_probe("rev-parse", "--show-toplevel")
        p_head = git_probe("rev-parse", "HEAD")
        p_branch = git_probe("branch", "--show-current")
        p_status = git_probe("status", "--porcelain=v1", "--untracked-files=all")
        p_ancestor = git_probe("merge-base", "--is-ancestor", base_sha_val, "HEAD")
        p_remote = git_probe("remote", "get-url", "origin")
        probes = {"toplevel": p_top, "head": p_head, "branch": p_branch, "status": p_status, "base ancestry": p_ancestor, "origin": p_remote}
        failed = [name for name, proc in probes.items() if proc.returncode != 0]
        if failed:
            detail = "; ".join(f"{name}: {(probes[name].stderr or probes[name].stdout).strip()}" for name in failed)
            print(f"worktree Git custody cannot be verified ({', '.join(failed)}): {detail}", file=sys.stderr)
            return 1
        live_top = str(Path(p_top.stdout.strip()).resolve())
        if live_top != str(wt):
            print(f"workspace path must be the Git worktree root: requested={wt} git={live_top}", file=sys.stderr)
            return 1
        head_sha_val = p_head.stdout.strip().lower()
        live_b = p_branch.stdout.strip()
        if live_b != branch:
            print(f"worktree branch mismatch: live={live_b} requested={branch}", file=sys.stderr)
            return 1
        if head_sha_val != base_sha_val:
            print(f"worktree must register at exact compiled base before mutation: head={head_sha_val} base={base_sha_val}", file=sys.stderr)
            return 1
        lines = sorted(p_status.stdout.splitlines())
        if lines:
            print(f"worktree must be clean at registration: {lines}", file=sys.stderr)
            return 1
        dirty_val = False
        status_sha_val = hashlib.sha256(b"\n").hexdigest()
        worktree_path_val = str(wt)
        remote_url_val = p_remote.stdout.strip()
        if not remote_url_val:
            print("worktree origin remote URL is empty", file=sys.stderr)
            return 1
    else:
        worktree_path_val = None
        head_sha_val = base_sha_val
        dirty_val = False
        status_sha_val = None
        remote_url_val = None

    original = ledger_path.read_bytes()
    entries.append({
        "workspace_id": workspace_id,
        "kind": "TARGET",
        "repository": repository,
        "branch": branch,
        "base_sha": base_sha_val,
        "registered_cell": args.cell,
        "worktree_path": worktree_path_val,
        "head_sha": head_sha_val,
        "dirty": dirty_val,
        "semantic_status_sha256": status_sha_val,
        "remote_url": remote_url_val,
    })
    ledger["entries"] = entries
    write_json(ledger_path, ledger)
    problems = collect_mission_issues(root)
    if problems:
        tmp = ledger_path.with_name(ledger_path.name + ".rollback.tmp")
        tmp.write_bytes(original)
        tmp.replace(ledger_path)
        print(json.dumps({"state":"REGISTER_ROLLED_BACK","issues":problems}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state":"WORKSPACE_REGISTERED","workspace_id":workspace_id,"cell":args.cell,"repository":repository,"branch":branch}, indent=2))
    return 0


def validate_workspace_reconciliation_accounting(root: Path, reconciliation: dict[str, Any], qualification: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(reconciliation, dict):
        return ["workspace reconciliation must be an object"]
    if not isinstance(qualification, dict):
        return ["qualification must be an object"]
    try:
        ledger = load_json(root / "control" / "WORKSPACE_LEDGER.json")
    except Exception as exc:
        return [f"cannot load WORKSPACE_LEDGER.json: {exc}"]
    ledger_entries = ledger.get("entries", []) if isinstance(ledger, dict) else []
    if not isinstance(ledger_entries, list):
        errors.append("WORKSPACE_LEDGER entries must be an array")
        ledger_entries = []
    ledger_controls = {item.get("workspace_id"): item for item in ledger_entries if isinstance(item, dict) and item.get("kind") == "CONTROL"}
    ledger_targets = {item.get("workspace_id"): item for item in ledger_entries if isinstance(item, dict) and item.get("kind") == "TARGET"}
    controls = reconciliation.get("control_workspaces", [])
    if not isinstance(controls, list):
        errors.append("workspace reconciliation control_workspaces must be an array")
        controls = []
    canonical = [item for item in controls if isinstance(item, dict) and item.get("disposition") == "CANONICAL"]
    if len(canonical) != 1:
        errors.append(f"workspace reconciliation requires exactly one CANONICAL control workspace; got {len(canonical)}")
    workspace_ids = [item.get("workspace_id") for item in controls if isinstance(item, dict)]
    if len(workspace_ids) != len(set(workspace_ids)):
        errors.append("workspace reconciliation control workspace ids must be unique")
    if set(workspace_ids) != set(ledger_controls):
        errors.append(f"workspace reconciliation control ids differ from WORKSPACE_LEDGER; reconciliation={sorted(set(workspace_ids))} ledger={sorted(ledger_controls)}")
    def validate_bound_evidence(items: Any, label: str) -> None:
        if not isinstance(items, list) or not items:
            errors.append(f"{label} requires at least one bound evidence object")
            return
        for evidence in items:
            if not isinstance(evidence, dict):
                errors.append(f"{label} evidence entry must be an object")
                continue
            ref = evidence.get("ref")
            expected = evidence.get("sha256")
            try:
                path = resolve_ref(root, str(ref))
            except Exception as exc:
                errors.append(f"{label} evidence ref invalid: {ref}: {exc}")
                continue
            if not path.is_file():
                errors.append(f"{label} evidence ref missing: {ref}")
            elif expected != sha256(path):
                errors.append(f"{label} evidence hash mismatch: {ref}")
    for workspace in controls if isinstance(controls, list) else []:
        if isinstance(workspace, dict):
            validate_bound_evidence(workspace.get("evidence"), f"control workspace {workspace.get('workspace_id')}")
            wt_path = workspace.get("worktree_path")
            if wt_path:
                wp = Path(wt_path)
                if wp.is_dir():
                    try:
                        p_head = subprocess.run(["git", "-C", str(wp), "rev-parse", "HEAD"], capture_output=True, text=True)
                        if p_head.returncode == 0:
                            live_head = p_head.stdout.strip().lower()
                            recorded_head = workspace.get("head_sha")
                            if workspace.get("disposition") == "CANONICAL":
                                if recorded_head:
                                    ancestor = subprocess.run(["git", "-C", str(wp), "merge-base", "--is-ancestor", str(recorded_head), live_head], capture_output=True, text=True)
                                    if ancestor.returncode != 0:
                                        errors.append(f"canonical control workspace {workspace.get('workspace_id')} recorded head is not an ancestor of live HEAD")
                            elif recorded_head and live_head != recorded_head.lower():
                                errors.append(f"control workspace {workspace.get('workspace_id')} HEAD drift: recorded={recorded_head} live={live_head}")
                    except Exception as exc:
                        errors.append(f"cannot inspect control worktree {wt_path}: {exc}")
    repos = reconciliation.get("target_repositories", [])
    if not isinstance(repos, list):
        errors.append("workspace reconciliation target_repositories must be an array")
        repos = []
    repo_ids = [item.get("repository") for item in repos if isinstance(item, dict)]
    if len(repo_ids) != len(set(repo_ids)):
        errors.append("workspace reconciliation target repository identities must be unique")
    qualification_outcomes = qualification.get("target_outcomes", [])
    if not isinstance(qualification_outcomes, list):
        errors.append("qualification target_outcomes must be an array")
        qualification_outcomes = []
    qmap = {item.get("repository"): item.get("accepted_head_sha") for item in qualification_outcomes if isinstance(item, dict)}
    rmap = {item.get("repository"): item.get("accepted_head_sha") for item in repos if isinstance(item, dict)}
    if set(qmap) != set(rmap):
        errors.append(f"workspace reconciliation target repositories differ from qualification; reconciliation={sorted(rmap)} qualification={sorted(qmap)}")
    for repository, accepted_head in qmap.items():
        if rmap.get(repository) != accepted_head:
            errors.append(f"workspace reconciliation accepted head for {repository} differs from qualification")
    reconciliation_branches: dict[str, tuple[str, dict[str, Any]]] = {}
    for repo in repos if isinstance(repos, list) else []:
        if not isinstance(repo, dict) or not isinstance(repo.get("branches"), list):
            continue
        for branch in repo.get("branches", []):
            if isinstance(branch, dict) and isinstance(branch.get("workspace_id"), str):
                wid = branch["workspace_id"]
                if wid in reconciliation_branches:
                    errors.append(f"workspace reconciliation repeats target workspace id {wid}")
                reconciliation_branches[wid] = (str(repo.get("repository")), branch)
    if set(reconciliation_branches) != set(ledger_targets):
        errors.append(f"workspace reconciliation target workspace ids differ from WORKSPACE_LEDGER; reconciliation={sorted(reconciliation_branches)} ledger={sorted(ledger_targets)}")
    for wid, ledger_entry in ledger_targets.items():
        pair = reconciliation_branches.get(wid)
        if pair is None:
            continue
        repository, branch = pair
        if repository != ledger_entry.get("repository") or branch.get("branch") != ledger_entry.get("branch"):
            errors.append(f"workspace reconciliation {wid} repository/branch differs from WORKSPACE_LEDGER")
        if not isinstance(ledger_entry.get("worktree_path"), str) or not ledger_entry.get("worktree_path"):
            errors.append(f"registered target workspace {wid} lacks worktree_path custody")
        if not isinstance(ledger_entry.get("head_sha"), str) or ledger_entry.get("head_sha") != ledger_entry.get("base_sha"):
            errors.append(f"registered target workspace {wid} was not captured at exact compiled base")
        if ledger_entry.get("dirty") is not False or not isinstance(ledger_entry.get("semantic_status_sha256"), str):
            errors.append(f"registered target workspace {wid} lacks clean semantic status custody")
        if not isinstance(ledger_entry.get("remote_url"), str) or not ledger_entry.get("remote_url"):
            errors.append(f"registered target workspace {wid} lacks origin remote identity")
        if isinstance(branch, dict):
            try:
                ledger_path = str(Path(str(ledger_entry.get("worktree_path"))).resolve())
                branch_path = str(Path(str(branch.get("worktree_path"))).resolve())
            except Exception:
                ledger_path = str(ledger_entry.get("worktree_path"))
                branch_path = str(branch.get("worktree_path"))
            if branch_path != ledger_path:
                errors.append(f"workspace reconciliation {wid} worktree path differs from WORKSPACE_LEDGER")
            if branch.get("remote_url") != ledger_entry.get("remote_url"):
                errors.append(f"workspace reconciliation {wid} origin remote differs from WORKSPACE_LEDGER")
            if branch.get("dirty") is not False:
                errors.append(f"workspace reconciliation {wid} claims a dirty target worktree")
    for repo in repos if isinstance(repos, list) else []:
        if not isinstance(repo, dict):
            continue
        accepted_head = repo.get("accepted_head_sha")
        branches = repo.get("branches", [])
        if not isinstance(branches, list):
            errors.append(f"workspace reconciliation branches for {repo.get('repository')} must be an array")
            branches = []
        branch_names = [item.get("branch") for item in branches if isinstance(item, dict)]
        if len(branch_names) != len(set(branch_names)):
            errors.append(f"workspace reconciliation branch identities for {repo.get('repository')} must be unique")
        accepted_branches = [item for item in branches if isinstance(item, dict) and item.get("disposition") == "ACCEPTED_HEAD"]
        if len(accepted_branches) != 1:
            errors.append(f"workspace reconciliation for {repo.get('repository')} requires exactly one ACCEPTED_HEAD branch; got {len(accepted_branches)}")
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            if branch.get("disposition") == "ACCEPTED_HEAD" and branch.get("head_sha") != accepted_head:
                errors.append(f"accepted branch {branch.get('branch')} for {repo.get('repository')} does not equal qualified head")
            validate_bound_evidence(branch.get("evidence"), f"target branch {repo.get('repository')}:{branch.get('branch')}")
            wt_path = branch.get("worktree_path")
            if not isinstance(wt_path, str) or not wt_path:
                errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} lacks worktree_path")
                continue
            wp = Path(wt_path).resolve()
            if not wp.is_dir():
                errors.append(f"target worktree is missing: {wt_path}")
                continue
            try:
                def live_git(*git_args: str) -> subprocess.CompletedProcess[str]:
                    return subprocess.run(["git", "-C", str(wp), *git_args], capture_output=True, text=True)
                p_top = live_git("rev-parse", "--show-toplevel")
                p_head = live_git("rev-parse", "HEAD")
                p_branch = live_git("branch", "--show-current")
                p_status = live_git("status", "--porcelain=v1", "--untracked-files=all")
                p_remote = live_git("remote", "get-url", "origin")
                ledger_entry = ledger_targets.get(branch.get("workspace_id"), {})
                base_sha = ledger_entry.get("base_sha") if isinstance(ledger_entry, dict) else None
                p_ancestor = live_git("merge-base", "--is-ancestor", str(base_sha), "HEAD") if isinstance(base_sha, str) else None
                probe_map = {"toplevel": p_top, "head": p_head, "branch": p_branch, "status": p_status, "origin": p_remote}
                if p_ancestor is not None:
                    probe_map["base ancestry"] = p_ancestor
                failed = [name for name, proc in probe_map.items() if proc.returncode != 0]
                if failed:
                    errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} Git custody probes failed: {failed}")
                    continue
                live_top = str(Path(p_top.stdout.strip()).resolve())
                if live_top != str(wp):
                    errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} worktree root drift: recorded={wp} git={live_top}")
                live_head = p_head.stdout.strip().lower()
                if live_head != str(branch.get("head_sha", "")).lower():
                    errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} HEAD drift: recorded={branch.get('head_sha')} live={live_head}")
                live_b = p_branch.stdout.strip()
                if live_b != branch.get("branch"):
                    errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} branch drift: recorded={branch.get('branch')} live={live_b}")
                lines = sorted(p_status.stdout.splitlines())
                live_dirty = bool(lines)
                live_status = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
                if branch.get("dirty") != live_dirty:
                    errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} dirty-state drift: recorded={branch.get('dirty')} live={live_dirty}")
                if branch.get("semantic_status_sha256") != live_status:
                    errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} status drift: recorded={branch.get('semantic_status_sha256')} live={live_status}")
                live_remote = p_remote.stdout.strip()
                if branch.get("remote_url") != live_remote:
                    errors.append(f"target branch {repo.get('repository')}:{branch.get('branch')} origin remote drift: recorded={branch.get('remote_url')} live={live_remote}")
            except Exception as exc:
                errors.append(f"cannot inspect target worktree {wt_path}: {exc}")
    historical_material = reconciliation.get("historical_material", [])
    if not isinstance(historical_material, list):
        errors.append("workspace reconciliation historical_material must be an array")
        historical_material = []
    for item in historical_material:
        if not isinstance(item, dict):
            continue
        try:
            ref = resolve_ref(root, str(item.get("ref")))
        except Exception as exc:
            errors.append(f"historical reconciliation ref invalid: {item.get('ref')}: {exc}")
            continue
        if not ref.is_file():
            errors.append(f"historical reconciliation ref missing: {item.get('ref')}")
        elif item.get("sha256") != sha256(ref):
            errors.append(f"historical reconciliation hash mismatch: {item.get('ref')}")
        supersession_ref = item.get("supersession_ref")
        supersession_sha = item.get("supersession_sha256")
        if item.get("disposition") == "SUPERSEDED_EVIDENCE":
            if not isinstance(supersession_ref, str) or not supersession_ref:
                errors.append(f"superseded historical evidence lacks supersession_ref: {item.get('ref')}")
            if not isinstance(supersession_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", supersession_sha):
                errors.append(f"superseded historical evidence lacks valid supersession_sha256: {item.get('ref')}")
        elif supersession_ref is not None or supersession_sha is not None:
            errors.append(f"non-superseded historical evidence must not carry supersession authority: {item.get('ref')}")
        if isinstance(supersession_ref, str) and supersession_ref:
            try:
                supersession_path = resolve_ref(root, supersession_ref)
            except Exception as exc:
                errors.append(f"historical supersession ref invalid: {supersession_ref}: {exc}")
            else:
                if not supersession_path.is_file():
                    errors.append(f"historical supersession ref missing: {supersession_ref}")
                elif supersession_sha != sha256(supersession_path):
                    errors.append(f"historical supersession hash mismatch: {supersession_ref}")
                else:
                    try:
                        s_record = load_json(supersession_path)
                        schema_issues = schema_errors(root, "contracts/schemas/SUPERSESSION_RECORD_SCHEMA.json", s_record)
                    except Exception as exc:
                        errors.append(f"historical supersession record cannot be validated: {supersession_ref}: {exc}")
                    else:
                        if schema_issues:
                            errors.append(f"historical supersession record schema errors: {supersession_ref}: {schema_issues}")
                        if s_record.get("superseded_ref") != item.get("ref") or s_record.get("superseded_sha256") != item.get("sha256"):
                            errors.append(f"historical supersession record does not bind exact superseded evidence: {supersession_ref}")
                        successor_ref = s_record.get("successor_ref")
                        try:
                            successor_path = resolve_ref(root, successor_ref)
                        except Exception as exc:
                            errors.append(f"historical supersession successor ref invalid: {successor_ref}: {exc}")
                        else:
                            if not successor_path.is_file():
                                errors.append(f"historical supersession successor ref missing: {successor_ref}")
                            elif sha256(successor_path) != s_record.get("successor_sha256"):
                                errors.append(f"historical supersession successor hash mismatch: {successor_ref}")
    if reconciliation.get("closure_ready") is not True:
        errors.append("workspace reconciliation is not closure_ready")
    return errors


def cmd_workspace_load(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    try:
        _, state = _load_v16(root)
        mission = load_json(root / "MISSION.json")
        candidate = load_json(Path(args.file).resolve())
    except Exception as exc:
        print(f"cannot load workspace reconciliation: {exc}", file=sys.stderr)
        return 1
    errors = schema_errors(root, "contracts/schemas/WORKSPACE_RECONCILIATION_SCHEMA.json", candidate)
    if errors:
        print(json.dumps({"state": "REJECTED", "errors": errors}, indent=2), file=sys.stderr)
        return 1
    if candidate.get("mission_id") != mission.get("mission_id"):
        errors.append(f"workspace reconciliation mission_id must equal {mission.get('mission_id')}")
    if errors:
        print(json.dumps({"state": "REJECTED", "errors": errors}, indent=2), file=sys.stderr)
        return 1
    if state.get("lifecycle") != "ACCEPTED":
        print(f"workspace reconciliation can be loaded only after accepted qualification; lifecycle is {state.get('lifecycle')}", file=sys.stderr)
        return 1
    qualification_path = root / "handoff" / "QUALIFICATION.json"
    if not qualification_path.is_file():
        print(f"cannot load workspace reconciliation: missing qualification artifact {qualification_path}", file=sys.stderr)
        return 1
    qualification = load_json(qualification_path)
    errors.extend(validate_workspace_reconciliation_accounting(root, candidate, qualification))
    if errors:
        print(json.dumps({"state": "REJECTED", "errors": errors}, indent=2), file=sys.stderr)
        return 1
    destination = root / "handoff" / "WORKSPACE_RECONCILIATION.json"
    original = destination.read_bytes() if destination.is_file() else None
    write_json(destination, candidate)
    problems = collect_mission_issues(root)
    if problems:
        if original is None:
            destination.unlink(missing_ok=True)
        else:
            tmp = destination.with_name(destination.name + ".rollback.tmp")
            tmp.write_bytes(original)
            tmp.replace(destination)
        print(json.dumps({"state": "LOAD_ROLLED_BACK", "label": "workspace reconciliation", "issues": problems}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state": "LOADED", "label": "workspace reconciliation", "path": destination.relative_to(root).as_posix()}, indent=2))
    return 0


def cmd_corpus_load(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    return _load_semantic_input(
        root,
        Path(args.file).resolve(),
        root / "corpus" / "TARGET_MUTATIONS.json",
        "contracts/schemas/TARGET_CORPUS_SCHEMA.json",
        "target corpus",
    )


def _build_cell_packet(root: Path, frontier_id: str, cell: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    current = load_json(root / "control" / "CURRENT_AUTHORITY.json")
    target = cell.get("target") if isinstance(cell.get("target"), dict) else None
    if target:
        base_head = str(target["base_sha"]).lower()
    else:
        baselines = current.get("target_baselines", {})
        if not isinstance(baselines, dict) or not baselines:
            raise ValueError("current authority has no target baseline")
        base_head = sha256(root / "control" / "CURRENT_AUTHORITY.json")
    manifest_ref = f"frontiers/{frontier_id}/contexts/{cell['cell_id']}.json"
    manifest = {
        "schema": "flyby/mission-control-context-manifest/1",
        "manifest_id": f"{frontier_id}:{cell['cell_id']}:context",
        "cell_id": cell["cell_id"],
        "base_head": base_head,
        "items": [
            {
                "context_id": "MISSION_SPEC",
                "kind": "STATE_OBJECT",
                "source": "mission-control",
                "locator": "MISSION.json",
                "version": TEMPLATE_SCHEMA,
                "hash": sha256(root / "MISSION.json"),
                "purpose": "Bind exact owner intent, hard boundaries and repository identities.",
                "requirement": "REQUIRED",
                "freshness": "FROZEN_BEFORE_BASELINE_COMPILE",
                "influence_class": "STABLE_AUTHORITY_PREFIX",
                "estimated_size": None,
            },
            {
                "context_id": "CURRENT_AUTHORITY",
                "kind": "STATE_OBJECT",
                "source": "mission-control",
                "locator": "control/CURRENT_AUTHORITY.json",
                "version": TEMPLATE_SCHEMA,
                "hash": sha256(root / "control" / "CURRENT_AUTHORITY.json"),
                "purpose": "Bind exact mission, target and canonical control authority.",
                "requirement": "REQUIRED",
                "freshness": "EXACT_GENERATED_AUTHORITY",
                "influence_class": "STABLE_AUTHORITY_PREFIX",
                "estimated_size": None,
            },
            {
                "context_id": "SOURCE_REGISTRY",
                "kind": "SOURCE_SNAPSHOT",
                "source": "mission-control",
                "locator": "corpus/SOURCES.json",
                "version": TEMPLATE_SCHEMA,
                "hash": sha256(root / "corpus" / "SOURCES.json"),
                "purpose": "Bind admitted provenance used by target requirements and worker decisions.",
                "requirement": "REQUIRED",
                "freshness": "FROZEN_BEFORE_BASELINE_COMPILE",
                "influence_class": "STABLE_AUTHORITY_PREFIX",
                "estimated_size": None,
            },
            {
                "context_id": "PROVENANCE_SYNTHESIS",
                "kind": "SOURCE_SNAPSHOT",
                "source": "mission-control",
                "locator": "corpus/PROVENANCE_SYNTHESIS.json",
                "version": TEMPLATE_SCHEMA,
                "hash": sha256(root / "corpus" / "PROVENANCE_SYNTHESIS.json"),
                "purpose": "Bind rights-aware full-potential source reviews, mechanism dispositions, reuse obligations and FlyBy-owned derivations used by target requirements.",
                "requirement": "REQUIRED",
                "freshness": "FROZEN_BEFORE_BASELINE_COMPILE",
                "influence_class": "STABLE_AUTHORITY_PREFIX",
                "estimated_size": None,
            },
            {
                "context_id": "TARGET_MUTATION_CORPUS",
                "kind": "STATE_OBJECT",
                "source": "mission-control",
                "locator": "corpus/TARGET_MUTATIONS.json",
                "version": TEMPLATE_SCHEMA,
                "hash": sha256(root / "corpus" / "TARGET_MUTATIONS.json"),
                "purpose": "Bind canonical target requirements and acceptance obligations.",
                "requirement": "REQUIRED",
                "freshness": "FROZEN_BEFORE_BASELINE_COMPILE",
                "influence_class": "STABLE_AUTHORITY_PREFIX",
                "estimated_size": None,
            },
            {
                "context_id": "CANONICAL_CELL",
                "kind": "OTHER",
                "source": "canonical-execution-dag",
                "locator": f"control/EXECUTION_DAG.json#{cell['cell_id']}",
                "version": str(cell.get("status", "PENDING")),
                "hash": canonical_json_sha256(cell),
                "purpose": "Bind exact cell objective, dependencies and authority claims.",
                "requirement": "REQUIRED",
                "freshness": "CURRENT_DAG_REVISION_AT_COMPILE",
                "influence_class": "TASK_CONTEXT_PREFIX",
                "estimated_size": None,
            },
        ],
        "manifest_hash_policy": "CANONICAL_JSON_SHA256",
    }
    result_schema_ref = cell.get("result_schema", "contracts/schemas/RESULT_SCHEMA.json")
    receipt_schema_ref = "contracts/schemas/CONTEXT_RECEIPT_SCHEMA.json"
    adjudication_schema_ref = "contracts/schemas/ADJUDICATION_SCHEMA.json"
    packet = {
        "schema": "flyby/mission-control-compiled-workcell/16",
        "frontier_id": frontier_id,
        "cell_id": cell["cell_id"],
        "kind": cell["kind"],
        "base_head": base_head,
        "dependencies": cell.get("dependencies", []),
        "objective": cell["objective"],
        "acceptance": cell["acceptance"],
        "conflict_class": cell["conflict_class"],
        "resource_claims": cell["resource_claims"],
        "requirement_ids": cell.get("requirement_ids", []),
        "target": target,
        "positive_verification": cell.get("positive_verification", []),
        "negative_verification": cell.get("negative_verification", []),
        "rollback": cell.get("rollback"),
        "consumer": cell.get("consumer"),
        "context_manifest_ref": manifest_ref,
        "result_contract": {"schema_ref": result_schema_ref, "schema_sha256": sha256(root / result_schema_ref)},
        "context_receipt_contract": {"schema_ref": receipt_schema_ref, "schema_sha256": sha256(root / receipt_schema_ref)},
        "adjudication_contract": {"schema_ref": adjudication_schema_ref, "schema_sha256": sha256(root / adjudication_schema_ref)},
        "session_reuse_policy": {"mode": "REUSE_IF_RECEIPT_MATCHES", "fresh_only_requires_reason": True},
        "return_contract": ["result.json", "context_receipt.json", "STOP_CELL_NOT_SESSION"],
    }
    return packet, manifest


def _compile_cell_packet(
    root: Path,
    frontier_id: str,
    cell: dict[str, Any],
    built: tuple[dict[str, Any], dict[str, Any]] | None = None,
) -> str:
    path = root / "frontiers" / frontier_id / "workcells" / f"{cell['cell_id']}.json"
    packet, manifest = built if built is not None else _build_cell_packet(root, frontier_id, cell)
    contract_errors = schema_errors(root, "contracts/schemas/WORKCELL_SCHEMA.json", packet)
    contract_errors.extend(schema_errors(root, "contracts/schemas/CONTEXT_MANIFEST_SCHEMA.json", manifest))
    if contract_errors:
        raise ValueError(f"compiled workcell contract invalid for {cell['cell_id']}: {contract_errors}")
    write_immutable_json(root / packet["context_manifest_ref"], manifest)
    write_immutable_json(path, packet)
    return path.relative_to(root).as_posix()


def cmd_baseline_compile(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    dag, state = _load_v16(root)
    if state["lifecycle"] not in {"BOOTSTRAPPED", "BASELINE_READY"}:
        print(f"baseline compile not allowed from {state['lifecycle']}", file=sys.stderr)
        return 1
    if state["lifecycle"] == "BOOTSTRAPPED":
        corpus = load_json(root / "corpus" / "TARGET_MUTATIONS.json")
        if not corpus.get("requirements"):
            print("baseline compile requires a non-empty target corpus loaded through `mc corpus load`", file=sys.stderr)
            return 1
        active_requirements, _ = requirement_dispositions(corpus)
        if not active_requirements:
            print("baseline compile requires at least one active non-waived target requirement", file=sys.stderr)
            return 1
    compiled = set(state["frontier"]["compiled"])
    for cell in dag["cells"]:
        if cell["cell_id"] not in BASELINE_AUDITS:
            continue
        cid = cell["cell_id"]
        record = state["cells"][cid]
        if record["state"] == "PENDING":
            ref = _compile_cell_packet(root, "F000", cell)
            state["cells"][cid] = {"state": "COMPILED", "workcell_ref": ref, "attempt": 1, "attempt_history": []}
            compiled.add(cid)
            continue
        if record["state"] in {"COMPILED", "DISPATCHED", "CANDIDATE", "ACCEPTED"}:
            compiled.add(cid)
            continue
        print(f"baseline cell {cid} is {record['state']}; explicit repair is required before recompilation", file=sys.stderr)
        return 1
    state["frontier"]["compiled"] = sorted(compiled)
    state["lifecycle"] = "BASELINE_READY"
    _save_state(root, state)
    return cmd_doctor(argparse.Namespace(root=str(root)))


def _find_cell(dag: dict[str, Any], cell_id: str) -> dict[str, Any] | None:
    return next((cell for cell in dag.get("cells", []) if cell.get("cell_id") == cell_id), None)


_PHASE_ORDER = {"BASELINE": 0, "MUTATION": 1, "INTEGRATION": 2, "QUALIFICATION": 3}
_PHASE_LIFECYCLES = {
    "BASELINE": {"BASELINE_READY"},
    "MUTATION": {"BASELINE_ACCEPTED", "MUTATION_READY"},
    "INTEGRATION": {"INTEGRATING"},
    "QUALIFICATION": {"QUALIFYING"},
}


def _declared_cell_phase(cell_id: str, cell: dict[str, Any]) -> str:
    if cell_id in BASELINE_AUDITS or cell_id == "G000":
        return "BASELINE"
    return {
        "AUDIT": "MUTATION",
        "MUTATION": "MUTATION",
        "INTEGRATION": "INTEGRATION",
        "QUALIFICATION": "QUALIFICATION",
        "BARRIER": "BASELINE",
    }.get(str(cell.get("kind")), "BASELINE")


def _cell_phase(dag: dict[str, Any], cell_id: str, memo: dict[str, str] | None = None) -> str:
    memo = memo if memo is not None else {}
    if cell_id in memo:
        return memo[cell_id]
    cell = _find_cell(dag, cell_id)
    if not cell:
        raise ValueError(f"unknown cell: {cell_id}")
    phase = _declared_cell_phase(cell_id, cell)
    for dependency in cell.get("dependencies", []):
        dep_phase = _cell_phase(dag, str(dependency), memo)
        if _PHASE_ORDER[dep_phase] > _PHASE_ORDER[phase]:
            phase = dep_phase
    memo[cell_id] = phase
    return phase


def _phase_order_violations(dag: dict[str, Any], cell_ids: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    memo: dict[str, str] = {}
    for cell in dag.get("cells", []):
        cell_id = cell.get("cell_id")
        if not isinstance(cell_id, str) or (cell_ids is not None and cell_id not in cell_ids):
            continue
        if cell.get("kind") == "BARRIER":
            continue
        declared = _declared_cell_phase(cell_id, cell)
        for dependency in cell.get("dependencies", []):
            dependency_phase = _cell_phase(dag, str(dependency), memo)
            if _PHASE_ORDER[dependency_phase] > _PHASE_ORDER[declared]:
                errors.append(
                    f"{cell.get('kind')} {cell_id} in declared {declared} phase depends on later {dependency_phase} authority through {dependency}"
                )
    return errors


def _cells_through_phase(dag: dict[str, Any], maximum_phase: str) -> list[str]:
    limit = _PHASE_ORDER[maximum_phase]
    memo: dict[str, str] = {}
    return [
        cell["cell_id"]
        for cell in dag.get("cells", [])
        if _PHASE_ORDER[_cell_phase(dag, cell["cell_id"], memo)] <= limit
    ]


def cmd_retry(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    dag, state = _load_v16(root)
    cell = _find_cell(dag, args.cell)
    if not cell or cell.get("kind") == "BARRIER":
        print("retry requires an executable cell", file=sys.stderr)
        return 1
    allowed_lifecycles = _PHASE_LIFECYCLES[_cell_phase(dag, args.cell)]
    if state["lifecycle"] not in allowed_lifecycles:
        print(f"retry for {args.cell} blocked from lifecycle {state['lifecycle']}", file=sys.stderr)
        return 1
    record = state["cells"].get(args.cell, {})
    if record.get("state") not in {"CANDIDATE", "REJECTED", "FAILED", "BLOCKED"}:
        print(f"cell {args.cell} is {record.get('state')}; retry requires a settled non-accepted state", file=sys.stderr)
        return 1
    if not isinstance(record.get("workcell_ref"), str):
        print(f"cell {args.cell} has no immutable workcell to retry", file=sys.stderr)
        return 1
    record["attempt"] = int(record.get("attempt", 1)) + 1
    record.setdefault("attempt_history", [])
    record["state"] = "COMPILED"
    for key in (
        "result_ref", "result_sha256", "context_receipt_ref", "context_receipt_sha256",
        "adjudication_ref", "adjudication_sha256", "worker_identity", "verifier_identity",
    ):
        record.pop(key, None)
    state["cells"][args.cell] = record
    state["frontier"]["dispatched"] = sorted(set(state["frontier"]["dispatched"]) - {args.cell})
    state["frontier"]["accepted"] = sorted(set(state["frontier"]["accepted"]) - {args.cell})
    compiled = set(state["frontier"]["compiled"])
    compiled.add(args.cell)
    state["frontier"]["compiled"] = sorted(compiled)
    _save_state(root, state)
    return cmd_doctor(argparse.Namespace(root=str(root)))


def cmd_dispatch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    dag, state = _load_v16(root)
    cell = _find_cell(dag, args.cell)
    if not cell:
        print(f"unknown cell: {args.cell}", file=sys.stderr)
        return 1
    if cell["kind"] == "BARRIER":
        print("barriers are crossed with `mc barrier accept`, not dispatched", file=sys.stderr)
        return 1
    allowed_lifecycles = _PHASE_LIFECYCLES[_cell_phase(dag, args.cell)]
    if state["lifecycle"] not in allowed_lifecycles:
        print(f"cell {args.cell} dispatch blocked from lifecycle {state['lifecycle']}", file=sys.stderr)
        return 1
    record = state["cells"].get(args.cell, {})
    if record.get("state") != "COMPILED":
        print(f"cell {args.cell} is not COMPILED", file=sys.stderr)
        return 1
    attempt = record.get("attempt")
    if not isinstance(attempt, int) or attempt < 1:
        print(f"cell {args.cell} lacks durable attempt identity", file=sys.stderr)
        return 1
    worker_identity = str(args.worker_identity).strip()
    verifier_identity = str(args.verifier_identity).strip()
    if not worker_identity or not verifier_identity:
        print("dispatch custody identities must be non-empty", file=sys.stderr)
        return 1
    if worker_identity == verifier_identity:
        print("dispatch requires distinct worker and verifier identities", file=sys.stderr)
        return 1
    for dep in cell.get("dependencies", []):
        if state["cells"].get(dep, {}).get("state") != "ACCEPTED":
            print(f"dependency {dep} is not ACCEPTED", file=sys.stderr)
            return 1
    target = cell.get("target")
    workspace_id = str(args.workspace_id).strip() if args.workspace_id is not None else ""
    if isinstance(target, dict):
        if not workspace_id:
            print(f"target-bearing cell {args.cell} requires --workspace-id registered before dispatch", file=sys.stderr)
            return 1
        ledger = load_json(root / "control" / "WORKSPACE_LEDGER.json")
        entry = next((item for item in ledger.get("entries", []) if isinstance(item, dict) and item.get("workspace_id") == workspace_id), None)
        if not isinstance(entry, dict) or entry.get("kind") != "TARGET":
            print(f"workspace id is not a registered target workspace: {workspace_id}", file=sys.stderr)
            return 1
        if entry.get("registered_cell") != args.cell or entry.get("repository") != target.get("repository") or entry.get("base_sha") != str(target.get("base_sha", "")).lower():
            print(f"workspace {workspace_id} does not match compiled target authority for {args.cell}", file=sys.stderr)
            return 1
        record["workspace_id"] = workspace_id
    elif workspace_id:
        print(f"non-target cell {args.cell} must not receive --workspace-id", file=sys.stderr)
        return 1
    requested_claims = set(cell.get("resource_claims", []))
    for other_id, other_record in state["cells"].items():
        if other_record.get("state") != "DISPATCHED":
            continue
        other = _find_cell(dag, other_id)
        if not other:
            continue
        if other.get("conflict_class") == cell.get("conflict_class"):
            print(f"cell {args.cell} conflicts with active cell {other_id} by conflict_class", file=sys.stderr)
            return 1
        shared_claims = requested_claims & set(other.get("resource_claims", []))
        if shared_claims:
            print(f"cell {args.cell} conflicts with active cell {other_id} on resources: {sorted(shared_claims)}", file=sys.stderr)
            return 1
    record["state"] = "DISPATCHED"
    record["worker_identity"] = worker_identity
    record["verifier_identity"] = verifier_identity
    state["cells"][args.cell] = record
    dispatched = set(state["frontier"]["dispatched"])
    dispatched.add(args.cell)
    state["frontier"]["dispatched"] = sorted(dispatched)
    _save_state(root, state)
    print(json.dumps({
        "state": "DISPATCHED",
        "cell": args.cell,
        "attempt": attempt,
        "worker_identity": worker_identity,
        "verifier_identity": verifier_identity,
        "workcell_ref": record.get("workcell_ref"),
    }, indent=2))
    return 0


def cmd_settle(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _settlement_preflight(root, args.cell, args.attempt):
        return 1
    dag, state = _load_v16(root)
    cell = _find_cell(dag, args.cell)
    if not cell or cell["kind"] == "BARRIER":
        print("unknown or non-executable cell", file=sys.stderr)
        return 1
    record = state["cells"].get(args.cell, {})
    if record.get("state") != "DISPATCHED":
        print(f"cell {args.cell} must be DISPATCHED before settlement", file=sys.stderr)
        return 1
    current_attempt = record.get("attempt")
    if not isinstance(current_attempt, int) or args.attempt != current_attempt:
        print(f"late/stale settlement rejected for {args.cell}: supplied attempt {args.attempt}, current attempt {current_attempt}", file=sys.stderr)
        return 1
    workcell_ref = record.get("workcell_ref")
    if not isinstance(workcell_ref, str):
        print(f"cell {args.cell} has no compiled workcell_ref", file=sys.stderr)
        return 1
    packet = load_json(resolve_ref(root, workcell_ref))
    result = load_json(Path(args.result).resolve())
    receipt = load_json(Path(args.context_receipt).resolve())
    adjudication = load_json(Path(args.adjudication).resolve())
    errors = validate_result(root, result, args.cell, packet)
    errors.extend(validate_context_receipt(root, receipt, args.cell, packet["context_manifest_ref"], packet["base_head"]))
    errors.extend(validate_context_accounting(root, receipt, packet, str(result.get("outcome"))))
    errors.extend(validate_adjudication(
        root,
        adjudication,
        args.cell,
        current_attempt,
        result,
        receipt,
        packet,
        expected_worker_identity=record.get("worker_identity") if isinstance(record.get("worker_identity"), str) else None,
        expected_verifier_identity=record.get("verifier_identity") if isinstance(record.get("verifier_identity"), str) else None,
    ))
    if errors:
        print(json.dumps({"state": "REJECTED", "errors": errors}, indent=2), file=sys.stderr)
        return 1

    attempt_id = f"attempt-{current_attempt:04d}"
    evidence_root = root / "evidence" / args.cell / attempt_id
    result_path = evidence_root / "result.json"
    receipt_path = evidence_root / "context_receipt.json"
    adjudication_path = evidence_root / "adjudication.json"
    try:
        write_immutable_json(result_path, result)
        write_immutable_json(receipt_path, receipt)
        write_immutable_json(adjudication_path, adjudication)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    state_name = adjudication_state(adjudication.get("decision"))
    if state_name is None:
        print("adjudication did not produce an authoritative state", file=sys.stderr)
        return 1
    record["state"] = state_name
    record["result_ref"] = result_path.relative_to(root).as_posix()
    record["result_sha256"] = sha256(result_path)
    record["context_receipt_ref"] = receipt_path.relative_to(root).as_posix()
    record["context_receipt_sha256"] = sha256(receipt_path)
    record["adjudication_ref"] = adjudication_path.relative_to(root).as_posix()
    record["adjudication_sha256"] = sha256(adjudication_path)
    history = list(record.get("attempt_history", []))
    history.append({
        "attempt": current_attempt,
        "worker_identity": record["worker_identity"],
        "verifier_identity": record["verifier_identity"],
        "state": state_name,
        "result_ref": record["result_ref"],
        "result_sha256": record["result_sha256"],
        "context_receipt_ref": record["context_receipt_ref"],
        "context_receipt_sha256": record["context_receipt_sha256"],
        "adjudication_ref": record["adjudication_ref"],
        "adjudication_sha256": record["adjudication_sha256"],
    })
    record["attempt_history"] = history
    state["cells"][args.cell] = record
    state["frontier"]["dispatched"] = sorted(set(state["frontier"]["dispatched"]) - {args.cell})
    if state_name == "ACCEPTED":
        accepted = set(state["frontier"]["accepted"])
        accepted.add(args.cell)
        state["frontier"]["accepted"] = sorted(accepted)

    residency = load_json(root / "control" / "SESSION_RESIDENCY.json")
    target = packet.get("target") if isinstance(packet.get("target"), dict) else None
    if target:
        target_repository = target["repository"]
    else:
        target_repository = "CONTROL_ONLY"
    worker = receipt["worker"]
    continuation = receipt["continuation"]
    binding = {
        "binding_id": f"{args.cell}:{attempt_id}",
        "worker_identity": worker["identity"],
        "provider": "UNSPECIFIED",
        "native_session_id": worker.get("session_id"),
        "native_session_state": "IDENTIFIED" if worker.get("session_id") else "IDENTITY_UNAVAILABLE",
        "origin_cell": args.cell,
        "origin_attempt": attempt_id,
        "target_repository": target_repository,
        "target_base": packet["base_head"],
        "context_receipt_ref": record["context_receipt_ref"],
        "context_receipt_hash": sha256(receipt_path),
        "continuation_state": "REUSABLE_CANDIDATE" if continuation["session_reusable"] else "NOT_REUSABLE",
        "provider_continuation_supported": None,
        "compaction_state": "NONE_RECORDED",
        "last_bound_cell": args.cell,
        "remaining_context_budget_estimate": None,
        "last_observed_state": "UNKNOWN",
        "non_reuse_reason": None if continuation["session_reusable"] else continuation["reason"],
    }
    records = [r for r in residency.get("records", []) if isinstance(r, dict)]
    existing_binding = next((r for r in records if r.get("binding_id") == binding["binding_id"]), None)
    if existing_binding is not None and existing_binding != binding:
        print(f"settlement binding conflict for {binding['binding_id']}", file=sys.stderr)
        return 1
    if existing_binding is None:
        records.append(binding)
        residency["records"] = records
        write_json(root / "control" / "SESSION_RESIDENCY.json", residency)
    _save_state(root, state)
    print(json.dumps({
        "state": state_name,
        "cell": args.cell,
        "result_ref": record["result_ref"],
        "context_receipt_ref": record["context_receipt_ref"],
        "adjudication_ref": record["adjudication_ref"],
    }, indent=2))
    return 0


def _accept_barrier(root: Path, cell_id: str) -> tuple[bool, str | None]:
    dag, state = _load_v16(root)
    cell = _find_cell(dag, cell_id)
    if not cell or cell.get("kind") != "BARRIER":
        return False, f"unknown or non-barrier cell: {cell_id}"
    record = state["cells"].get(cell_id, {})
    if record.get("state") == "ACCEPTED":
        return True, None
    if record.get("state") != "BLOCKED":
        return False, f"barrier {cell_id} is {record.get('state')}, expected BLOCKED"
    if cell.get("acceptance") != [BARRIER_ACCEPTANCE]:
        return False, f"barrier {cell_id} acceptance is not the canonical dependency-only contract"
    missing = [dep for dep in cell.get("dependencies", []) if state["cells"].get(dep, {}).get("state") != "ACCEPTED"]
    if missing:
        return False, f"barrier {cell_id} blocked; dependencies not ACCEPTED: {missing}"
    state["cells"][cell_id] = {"state": "ACCEPTED"}
    accepted = set(state["frontier"]["accepted"])
    accepted.add(cell_id)
    state["frontier"]["accepted"] = sorted(accepted)
    _save_state(root, state)
    return True, None


def cmd_baseline_accept(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    _, state = _load_v16(root)
    if state["lifecycle"] != "BASELINE_READY":
        print(f"baseline acceptance requires BASELINE_READY, got {state['lifecycle']}", file=sys.stderr)
        return 1
    corpus = load_json(root / "corpus" / "TARGET_MUTATIONS.json")
    if not corpus.get("requirements"):
        print("baseline acceptance requires a non-empty target corpus loaded through `mc corpus load`", file=sys.stderr)
        return 1
    ok, error = _accept_barrier(root, "G000")
    if not ok:
        print(error, file=sys.stderr)
        return 1
    _, state = _load_v16(root)
    state["lifecycle"] = "BASELINE_ACCEPTED"
    _save_state(root, state)
    return cmd_doctor(argparse.Namespace(root=str(root)))


def cmd_barrier_accept(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    if args.cell == "G000":
        print("use `mc baseline accept` for G000", file=sys.stderr)
        return 1
    dag, state = _load_v16(root)
    cell = _find_cell(dag, args.cell)
    if not cell or cell.get("kind") != "BARRIER":
        print(f"unknown or non-barrier cell: {args.cell}", file=sys.stderr)
        return 1
    phase = _cell_phase(dag, args.cell)
    if state["lifecycle"] not in _PHASE_LIFECYCLES[phase]:
        print(f"barrier {args.cell} phase {phase} cannot be accepted from lifecycle {state['lifecycle']}", file=sys.stderr)
        return 1
    ok, error = _accept_barrier(root, args.cell)
    if not ok:
        print(error, file=sys.stderr)
        return 1
    return cmd_doctor(argparse.Namespace(root=str(root)))


def _validate_frontier(frontier: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    root_fields = {"schema", "frontier_id", "cells"}
    extra_root = set(frontier) - root_fields
    if extra_root:
        errors.append(f"unknown frontier fields: {sorted(extra_root)}")
    if frontier.get("schema") != FRONTIER_SCHEMA:
        errors.append(f"frontier schema must be {FRONTIER_SCHEMA}")
    if not valid_control_id(frontier.get("frontier_id")):
        errors.append("frontier_id must match ^[A-Z][A-Z0-9_-]*$")
    cells = frontier.get("cells")
    if not isinstance(cells, list) or not cells:
        errors.append("frontier cells must be non-empty")
        return errors
    for cell in cells:
        if not isinstance(cell, dict):
            errors.append("frontier cells must be objects")
            continue
        allowed = {
            "cell_id", "kind", "dependencies", "objective", "acceptance", "status", "conflict_class",
            "resource_claims", "requirement_ids", "target", "positive_verification", "negative_verification", "rollback",
            "consumer", "result_schema",
        }
        extras = set(cell) - allowed
        if extras:
            errors.append(f"cell has unknown fields: {sorted(extras)}")
        required = {"cell_id", "kind", "dependencies", "objective", "acceptance", "status", "conflict_class", "resource_claims"}
        if not required <= set(cell):
            errors.append(f"cell missing fields: {sorted(required - set(cell))}")
            continue
        if not valid_control_id(cell.get("cell_id")):
            errors.append(f"cell_id must match ^[A-Z][A-Z0-9_-]*$: {cell.get('cell_id')}")
        if cell.get("status") != "PENDING":
            errors.append(f"cell {cell['cell_id']} descriptor status must be PENDING")
        if cell["kind"] not in {"AUDIT", "MUTATION", "INTEGRATION", "QUALIFICATION", "BARRIER"}:
            errors.append(f"invalid kind for {cell['cell_id']}")
        if not isinstance(cell.get("conflict_class"), str) or not cell.get("conflict_class", "").strip():
            errors.append(f"cell {cell['cell_id']} conflict_class must be non-empty")
        claims = cell.get("resource_claims")
        if not isinstance(claims, list) or not all(isinstance(x, str) and x.strip() for x in claims) or len(claims) != len(set(claims)):
            errors.append(f"cell {cell['cell_id']} resource_claims must be a unique string list")
        if cell["kind"] == "AUDIT":
            if not {"consumer", "result_schema"} <= set(cell):
                errors.append(f"AUDIT {cell['cell_id']} requires consumer and result_schema")
            elif cell.get("result_schema") != "contracts/schemas/RESULT_SCHEMA.json":
                errors.append(f"AUDIT {cell['cell_id']} must use canonical RESULT_SCHEMA.json")
            forbidden = {"requirement_ids", "target", "positive_verification", "negative_verification", "rollback"} & set(cell)
            if forbidden:
                errors.append(f"AUDIT {cell['cell_id']} contains mutation-only fields: {sorted(forbidden)}")
        if cell["kind"] == "MUTATION":
            needed = {"requirement_ids", "target", "positive_verification", "negative_verification", "rollback", "result_schema"}
            if not needed <= set(cell):
                errors.append(f"MUTATION {cell['cell_id']} missing {sorted(needed - set(cell))}")
            else:
                requirement_ids = cell.get("requirement_ids")
                if not isinstance(requirement_ids, list) or not requirement_ids or len(requirement_ids) != len(set(requirement_ids)) or not all(valid_control_id(value) for value in requirement_ids):
                    errors.append(f"MUTATION {cell['cell_id']} requirement_ids must be a non-empty unique control-id list")
                target = cell.get("target")
                if not isinstance(target, dict) or set(target) != {"repository", "base_sha", "owned_paths"}:
                    errors.append(f"MUTATION {cell['cell_id']} target must contain only repository, base_sha and owned_paths")
                else:
                    repository = target.get("repository")
                    base_sha = target.get("base_sha")
                    if not isinstance(repository, str) or not repository.strip():
                        errors.append(f"MUTATION {cell['cell_id']} target.repository must be non-empty")
                    if not isinstance(base_sha, str) or len(base_sha) != 40 or any(c not in "0123456789abcdefABCDEF" for c in base_sha):
                        errors.append(f"MUTATION {cell['cell_id']} target.base_sha must be 40-hex")
                    owned_paths = target.get("owned_paths")
                    if not isinstance(owned_paths, list) or not owned_paths or not all(isinstance(path, str) and _safe_scope_path(path) for path in owned_paths):
                        errors.append(f"MUTATION {cell['cell_id']} target.owned_paths must be non-empty safe relative paths")
                if not isinstance(cell.get("positive_verification"), list) or not cell.get("positive_verification"):
                    errors.append(f"MUTATION {cell['cell_id']} positive_verification must be non-empty")
                if not isinstance(cell.get("negative_verification"), list) or not cell.get("negative_verification"):
                    errors.append(f"MUTATION {cell['cell_id']} negative_verification must be non-empty")
                if not isinstance(cell.get("rollback"), str) or not cell.get("rollback", "").strip():
                    errors.append(f"MUTATION {cell['cell_id']} rollback must be non-empty")
                if cell.get("result_schema") != "contracts/schemas/RESULT_SCHEMA.json":
                    errors.append(f"MUTATION {cell['cell_id']} must use canonical RESULT_SCHEMA.json")
                if "consumer" in cell:
                    errors.append(f"MUTATION {cell['cell_id']} contains audit-only field: consumer")
        if cell["kind"] in {"INTEGRATION", "QUALIFICATION"}:
            if cell.get("result_schema") != "contracts/schemas/RESULT_SCHEMA.json":
                errors.append(f"{cell['kind']} {cell['cell_id']} must use canonical RESULT_SCHEMA.json")
            forbidden = {"requirement_ids", "target", "positive_verification", "negative_verification", "rollback", "consumer"} & set(cell)
            if forbidden:
                errors.append(f"{cell['kind']} {cell['cell_id']} contains mutation/audit-only fields: {sorted(forbidden)}")
        if cell["kind"] == "BARRIER":
            forbidden = {"requirement_ids", "target", "positive_verification", "negative_verification", "rollback", "consumer", "result_schema"} & set(cell)
            if forbidden:
                errors.append(f"BARRIER {cell['cell_id']} contains executable-only fields: {sorted(forbidden)}")
            if cell.get("acceptance") != [BARRIER_ACCEPTANCE]:
                errors.append(f"BARRIER {cell['cell_id']} acceptance must be exactly [{BARRIER_ACCEPTANCE!r}]")
    valid_cells = [c for c in cells if isinstance(c, dict) and isinstance(c.get("cell_id"), str)]
    ids = [c["cell_id"] for c in valid_cells]
    if len(ids) != len(set(ids)):
        errors.append("frontier cell ids are not unique")
    known = set(ids)
    projected: list[dict[str, Any]] = []
    for cell in valid_cells:
        deps = cell.get("dependencies", [])
        if not isinstance(deps, list):
            errors.append(f"{cell['cell_id']} dependencies are not a list")
            continue
        invalid_dependencies = [dep for dep in deps if not valid_control_id(dep)]
        if invalid_dependencies:
            errors.append(f"{cell['cell_id']} dependencies contain invalid control ids: {invalid_dependencies}")
        if cell["cell_id"] in deps:
            errors.append(f"{cell['cell_id']} depends on itself")
        projected.append({"cell_id": cell["cell_id"], "dependencies": [d for d in deps if isinstance(d, str) and d in known]})
    cycles = _dag_cycles(projected, "cell_id", "dependencies")
    if cycles:
        errors.append(f"frontier contains cycles: {cycles}")
    return errors


def _compile_preflight(root: Path, frontier: dict[str, Any]) -> bool:
    problems = collect_mission_issues(root)
    if not problems:
        return True

    frontier_id = frontier.get("frontier_id")
    if not isinstance(frontier_id, str) or not valid_control_id(frontier_id):
        return False
    stored_path = root / "frontiers" / frontier_id / "FRONTIER.json"
    if not stored_path.is_file():
        return False
    try:
        if load_json(stored_path) != frontier:
            return False
        dag, state = _load_v16(root)
    except Exception:
        return False

    requested = {cell["cell_id"]: cell for cell in frontier.get("cells", []) if isinstance(cell, dict) and isinstance(cell.get("cell_id"), str)}
    canonical = {cell["cell_id"]: cell for cell in dag.get("cells", []) if isinstance(cell, dict) and isinstance(cell.get("cell_id"), str)}
    requested_ids = set(requested)
    dag_present = requested_ids & set(canonical)
    if dag_present and dag_present != requested_ids:
        return False
    if dag_present and any(canonical[cid] != requested[cid] for cid in requested_ids):
        return False

    state_cells = state.get("cells", {})
    if not isinstance(state_cells, dict):
        return False
    state_present = requested_ids & set(state_cells)
    if state_present and state_present != requested_ids:
        return False
    if state_present and not dag_present:
        return False

    allowed = {"MC0233"} if not dag_present else {"MC0177"} if not state_present else set()
    return bool(allowed) and all(problem.get("code") in allowed for problem in problems)


def cmd_compile(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    frontier = load_json(Path(args.frontier).resolve())
    errors = _validate_frontier(frontier)
    if errors:
        print(json.dumps({"state": "INVALID_FRONTIER", "errors": errors}, indent=2), file=sys.stderr)
        return 1
    if not _compile_preflight(root, frontier):
        problems = collect_mission_issues(root)
        if problems:
            print(json.dumps({"state": "FAIL", "issues": problems}, indent=2), file=sys.stderr)
            return 1

    dag, state = _load_v16(root)
    if state["lifecycle"] not in {"BASELINE_ACCEPTED", "MUTATION_READY"}:
        print(f"frontier compilation blocked from {state['lifecycle']}", file=sys.stderr)
        return 1

    frontier_id = frontier["frontier_id"]
    stored_path = root / "frontiers" / frontier_id / "FRONTIER.json"
    if stored_path.exists():
        try:
            stored = load_json(stored_path)
        except Exception as exc:
            print(f"stored frontier {frontier_id} is unreadable: {exc}", file=sys.stderr)
            return 1
        if stored != frontier:
            print(f"frontier_id {frontier_id} already names a different immutable descriptor", file=sys.stderr)
            return 1

    existing_cells = {c["cell_id"]: c for c in dag["cells"]}
    new_cells = {c["cell_id"]: c for c in frontier["cells"]}
    existing_ids = set(existing_cells)
    new_ids = set(new_cells)
    overlap = existing_ids & new_ids
    exact_existing = bool(overlap) and overlap == new_ids and all(existing_cells[cid] == new_cells[cid] for cid in new_ids)
    if overlap and not exact_existing:
        print(f"frontier redefines existing cells: {sorted(overlap)}", file=sys.stderr)
        return 1

    all_ids = existing_ids | new_ids
    current = load_json(root / "control" / "CURRENT_AUTHORITY.json")
    target_baselines = current.get("target_baselines", {})
    corpus = load_json(root / "corpus" / "TARGET_MUTATIONS.json")
    requirements_by_id = {
        item.get("id"): item
        for item in corpus.get("requirements", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    requirement_ids = set(requirements_by_id)
    active_requirement_ids, frozen_requirement_waivers = requirement_dispositions(corpus)
    for cell in frontier["cells"]:
        unknown = set(cell.get("dependencies", [])) - all_ids
        if unknown:
            print(f"{cell['cell_id']} references unknown dependencies: {sorted(unknown)}", file=sys.stderr)
            return 1
        if cell.get("kind") == "MUTATION":
            cell_requirements = set(cell.get("requirement_ids", []))
            unknown_requirements = cell_requirements - requirement_ids
            if unknown_requirements:
                print(f"{cell['cell_id']} references requirements not present in TARGET_MUTATIONS.json: {sorted(unknown_requirements)}", file=sys.stderr)
                return 1
            waived_requirements = cell_requirements & set(frozen_requirement_waivers)
            if waived_requirements:
                print(f"{cell['cell_id']} references frozen waived requirements: {sorted(waived_requirements)}", file=sys.stderr)
                return 1
            target = cell["target"]
            repository = target["repository"]
            for requirement_id in sorted(cell_requirements):
                allowed_targets = set(requirements_by_id[requirement_id].get("targets", []))
                if repository not in allowed_targets:
                    print(
                        f"{cell['cell_id']} targets {repository} but requirement {requirement_id} is scoped to repositories {sorted(allowed_targets)}",
                        file=sys.stderr,
                    )
                    return 1
            expected = target_baselines.get(repository)
            if expected is None:
                print(f"{cell['cell_id']} targets repository not bound by MISSION.json: {repository}", file=sys.stderr)
                return 1
            if target["base_sha"].lower() != str(expected).lower():
                print(f"{cell['cell_id']} base SHA does not equal current authority for {repository}", file=sys.stderr)
                return 1

    candidate_dag = {
        **dag,
        "cells": list(dag["cells"]) if exact_existing else [*dag["cells"], *frontier["cells"]],
    }
    phase_errors = _phase_order_violations(candidate_dag, new_ids)
    if phase_errors:
        print(json.dumps({"state": "INVALID_PHASE_ORDER", "errors": phase_errors}, indent=2), file=sys.stderr)
        return 1
    for cell in frontier["cells"]:
        if cell.get("kind") == "BARRIER" and cell.get("cell_id") != "G000":
            phase = _cell_phase(candidate_dag, cell["cell_id"])
            if phase == "BASELINE":
                print(
                    f"post-baseline barrier {cell['cell_id']} must depend transitively on a MUTATION, INTEGRATION, or QUALIFICATION cell; inferred phase is BASELINE",
                    file=sys.stderr,
                )
                return 1

    planned_packets: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    try:
        for cell in frontier["cells"]:
            if cell["kind"] != "BARRIER":
                planned_packets[cell["cell_id"]] = _build_cell_packet(root, frontier_id, cell)
    except Exception as exc:
        print(f"frontier {frontier_id} cannot be compiled without mutation: {exc}", file=sys.stderr)
        return 1

    if not stored_path.exists():
        try:
            write_immutable_json(stored_path, frontier)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if not overlap:
        dag["cells"].extend(frontier["cells"])
        dag["revision"] = int(dag.get("revision", 1)) + 1

    compiled = set(state["frontier"]["compiled"])
    state_has_all = new_ids <= set(state["cells"])
    if state_has_all:
        if not exact_existing:
            print(f"frontier state exists without an exact canonical DAG match: {frontier_id}", file=sys.stderr)
            return 1
        return cmd_doctor(argparse.Namespace(root=str(root)))

    for cell in frontier["cells"]:
        cid = cell["cell_id"]
        if cell["kind"] == "BARRIER":
            state["cells"][cid] = {"state": "BLOCKED"}
        else:
            ref = _compile_cell_packet(root, frontier_id, cell, planned_packets[cid])
            state["cells"][cid] = {"state": "COMPILED", "workcell_ref": ref, "attempt": 1, "attempt_history": []}
            compiled.add(cid)
    state["frontier"]["compiled"] = sorted(compiled)
    state["lifecycle"] = "MUTATION_READY"
    write_json(root / "control" / "EXECUTION_DAG.json", dag)
    _save_state(root, state)
    return cmd_doctor(argparse.Namespace(root=str(root)))


def cmd_integrate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    dag, state = _load_v16(root)
    if state["lifecycle"] != "MUTATION_READY":
        print(f"integration requires MUTATION_READY, got {state['lifecycle']}", file=sys.stderr)
        return 1
    mutation_descriptors = [c for c in dag["cells"] if c.get("kind") == "MUTATION"]
    mutation_cells = [c["cell_id"] for c in mutation_descriptors]
    if not mutation_cells:
        print("integration requires at least one mutation cell", file=sys.stderr)
        return 1
    integration_cells = [c["cell_id"] for c in dag["cells"] if c.get("kind") == "INTEGRATION"]
    if not integration_cells:
        print("integration requires at least one typed INTEGRATION cell", file=sys.stderr)
        return 1
    corpus = load_json(root / "corpus" / "TARGET_MUTATIONS.json")
    active_requirement_ids, frozen_requirement_waivers = requirement_dispositions(corpus)
    covered_requirements = {requirement_id for cell in mutation_descriptors for requirement_id in cell.get("requirement_ids", [])}
    illegally_implemented_waivers = covered_requirements & set(frozen_requirement_waivers)
    if illegally_implemented_waivers:
        print(f"integration blocked; waived requirements have mutation-cell bindings: {sorted(illegally_implemented_waivers)}", file=sys.stderr)
        return 1
    missing_requirements = active_requirement_ids - covered_requirements
    if missing_requirements:
        print(f"integration blocked; active target requirements have no mutation-cell binding: {sorted(missing_requirements)}", file=sys.stderr)
        return 1
    criterion_gaps = requirement_acceptance_gaps(corpus, dag["cells"])
    if criterion_gaps:
        print(f"integration blocked; active requirement acceptance criteria are not carried by bound mutation cells: {criterion_gaps}", file=sys.stderr)
        return 1
    target_gaps = requirement_target_gaps(corpus, dag["cells"])
    if target_gaps:
        print(f"integration blocked; active requirement target repositories are not covered by bound mutation cells: {target_gaps}", file=sys.stderr)
        return 1
    target_criterion_gaps = requirement_target_acceptance_gaps(corpus, dag["cells"])
    if target_criterion_gaps:
        print(f"integration blocked; active requirement acceptance criteria are not carried on every targeted repository: {target_criterion_gaps}", file=sys.stderr)
        return 1
    required = _cells_through_phase(dag, "MUTATION")
    unresolved = [cid for cid in required if state["cells"].get(cid, {}).get("state") != "ACCEPTED"]
    if unresolved:
        print(f"integration blocked; mutation-phase cells not ACCEPTED: {unresolved}", file=sys.stderr)
        return 1
    state["lifecycle"] = "INTEGRATING"
    _save_state(root, state)
    print(json.dumps({"state": "INTEGRATING", "accepted_mutations": mutation_cells}, indent=2))
    return 0


def cmd_qualify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    dag, state = _load_v16(root)
    qualification_cells = [c["cell_id"] for c in dag["cells"] if c.get("kind") == "QUALIFICATION"]
    if not qualification_cells:
        print("qualification requires at least one typed QUALIFICATION cell", file=sys.stderr)
        return 1

    if state["lifecycle"] == "INTEGRATING":
        required = _cells_through_phase(dag, "INTEGRATION")
        unresolved = [cid for cid in required if state["cells"].get(cid, {}).get("state") != "ACCEPTED"]
        if unresolved:
            print(f"qualification blocked; integration-phase cells not ACCEPTED: {unresolved}", file=sys.stderr)
            return 1
        if qualification_cells and args.result:
            print("qualification cells exist; enter QUALIFYING first with `mc qualify --root <mission>`", file=sys.stderr)
            return 1
        state["lifecycle"] = "QUALIFYING"
        _save_state(root, state)
        if not args.result:
            return cmd_doctor(argparse.Namespace(root=str(root)))

    elif state["lifecycle"] != "QUALIFYING":
        print(f"qualification requires INTEGRATING or QUALIFYING lifecycle, got {state['lifecycle']}", file=sys.stderr)
        return 1

    required = _cells_through_phase(dag, "QUALIFICATION")
    unresolved = [cid for cid in required if state["cells"].get(cid, {}).get("state") != "ACCEPTED"]
    if unresolved:
        print(f"qualification blocked; qualification-phase cells not ACCEPTED: {unresolved}", file=sys.stderr)
        return 1
    if not args.result:
        print("qualification acceptance requires --result", file=sys.stderr)
        return 1

    result = load_json(Path(args.result).resolve())
    errors = schema_errors(root, "contracts/schemas/QUALIFICATION_SCHEMA.json", result)
    errors.extend(validate_qualification_accounting(root, result))
    if errors:
        print(json.dumps({"state": "REJECTED", "errors": errors}, indent=2), file=sys.stderr)
        return 1
    qualification_path = root / "handoff" / "QUALIFICATION.json"
    try:
        write_immutable_json(qualification_path, result)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    state["qualification_ref"] = qualification_path.relative_to(root).as_posix()
    state["qualification_sha256"] = sha256(qualification_path)
    state["lifecycle"] = "ACCEPTED"
    _save_state(root, state)
    return cmd_doctor(argparse.Namespace(root=str(root)))


def cmd_close(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not _doctor_or_fail(root):
        return 1
    spec = load_json(root / "MISSION.json")
    _, state = _load_v16(root)
    if state["lifecycle"] != "ACCEPTED":
        print("mission can close only from ACCEPTED", file=sys.stderr)
        return 1
    qualification_ref = state.get("qualification_ref")
    qualification_path = resolve_ref(root, str(qualification_ref))
    if qualification_ref != "handoff/QUALIFICATION.json" or not qualification_path.is_file():
        print("mission cannot close without durable qualification evidence", file=sys.stderr)
        return 1
    qualification_hash = sha256(qualification_path)
    if state.get("qualification_sha256") != qualification_hash:
        print("qualification evidence hash drifted before closure", file=sys.stderr)
        return 1
    qualification = load_json(qualification_path)
    workspace_reconciliation_path = root / "handoff" / "WORKSPACE_RECONCILIATION.json"
    if not workspace_reconciliation_path.is_file():
        print("mission cannot close without workspace/candidate reconciliation evidence", file=sys.stderr)
        return 1
    try:
        workspace_reconciliation = load_json(workspace_reconciliation_path)
        workspace_errors = schema_errors(root, "contracts/schemas/WORKSPACE_RECONCILIATION_SCHEMA.json", workspace_reconciliation)
        workspace_errors.extend(validate_workspace_reconciliation_accounting(root, workspace_reconciliation, qualification))
    except Exception as exc:
        print(f"workspace reconciliation cannot be validated before closure: {exc}", file=sys.stderr)
        return 1
    if workspace_errors:
        print(json.dumps({"state":"WORKSPACE_RECONCILIATION_INVALID","errors":workspace_errors}, indent=2), file=sys.stderr)
        return 1
    workspace_reconciliation_hash = sha256(workspace_reconciliation_path)
    closure_path = root / "handoff" / "CLOSURE.json"
    closure = {
        "schema": "flyby/mission-control-closure/16",
        "mission_id": spec["mission_id"],
        "terminal_state": "CLOSED",
        "qualification_ref": "handoff/QUALIFICATION.json",
        "qualification_sha256": qualification_hash,
        "workspace_reconciliation_ref": "handoff/WORKSPACE_RECONCILIATION.json",
        "workspace_reconciliation_sha256": workspace_reconciliation_hash,
        "target_outcomes": qualification["target_outcomes"],
        "requirement_accounting": qualification["requirement_accounting"],
        "verification_accounting": qualification["verification_accounting"],
        "unresolved_defects": qualification["unresolved_defects"],
        "explicit_limitations": qualification["explicit_limitations"],
    }
    closure_errors = schema_errors(root, "contracts/schemas/CLOSURE_SCHEMA.json", closure)
    if closure_errors:
        print(json.dumps({"state": "CLOSURE_INVALID", "errors": closure_errors}, indent=2), file=sys.stderr)
        return 1
    try:
        write_immutable_json(closure_path, closure)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    state["closure_ref"] = closure_path.relative_to(root).as_posix()
    state["closure_sha256"] = sha256(closure_path)
    state["lifecycle"] = "CLOSED"
    _save_state(root, state)
    return cmd_doctor(argparse.Namespace(root=str(root)))


def cmd_test(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    layout = detect_layout(root)
    if layout == "v16":
        test_file = root / "runtime" / "tests" / "test_mission_control.py"
    else:
        template_root = Path(__file__).resolve().parents[1]
        test_file = template_root / "tests" / "test_mission_control.py"
    if not test_file.is_file():
        print(f"test suite missing: {test_file}", file=sys.stderr)
        return 1
    proc = subprocess.run([sys.executable, str(test_file), "--mission-root", str(root)])
    return proc.returncode


def _bootstrap_invalid_recovery_is_pristine(root: Path) -> tuple[bool, str]:
    try:
        current = load_json(root / "control" / "CURRENT_AUTHORITY.json")
        dag = load_json(root / "control" / "EXECUTION_DAG.json")
        state = load_json(root / "control" / "EXECUTION_STATE.json")
        residency = load_json(root / "control" / "SESSION_RESIDENCY.json")
    except Exception as exc:
        return False, f"bootstrap control cannot be read: {exc}"
    if current.get("status") != "BOOTSTRAP_INVALID":
        return False, "bootstrap status is not BOOTSTRAP_INVALID"
    if state.get("lifecycle") != "BOOTSTRAPPED":
        return False, f"execution lifecycle advanced to {state.get('lifecycle')}"
    expected_ids = set(BASELINE_AUDITS) | {"G000"}
    cells = dag.get("cells", [])
    if dag.get("revision") != 1 or {cell.get("cell_id") for cell in cells if isinstance(cell, dict)} != expected_ids:
        return False, "canonical DAG is no longer the untouched bootstrap frontier"
    state_cells = state.get("cells", {})
    if set(state_cells) != expected_ids:
        return False, "execution state no longer matches the untouched bootstrap frontier"
    for cid in BASELINE_AUDITS:
        if state_cells.get(cid) != {"state": "PENDING"}:
            return False, f"baseline cell {cid} is no longer pristine"
    if state_cells.get("G000") != {"state": "BLOCKED"}:
        return False, "baseline barrier G000 is no longer pristine"
    frontier = state.get("frontier", {})
    if any(frontier.get(key) for key in ("compiled", "dispatched", "accepted")):
        return False, "execution frontier already contains compiled/dispatched/accepted work"
    evidence_dir = root / "evidence"
    if evidence_dir.exists():
        for item in evidence_dir.iterdir():
            if item.is_dir() and any(item.glob("attempt-*")):
                return False, "evidence already contains cell execution records"
    if (root / "handoff").exists() and any(path.is_file() for path in (root / "handoff").rglob("*")):
        return False, "handoff already contains durable mission evidence"
    return True, "pristine bootstrap-invalid control"


def cmd_repair_bootstrap(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if detect_layout(root) != "v16" or not (root / "MISSION.json").is_file():
        print("bootstrap repair is only valid for a canonical v16 mission root containing MISSION.json", file=sys.stderr)
        return 1
    try:
        mission = load_json(root / "MISSION.json")
        mission_errors = validate_mission_spec(mission)
    except Exception as exc:
        print(f"cannot repair mission with unreadable MISSION.json: {exc}", file=sys.stderr)
        return 1
    if mission_errors:
        print(json.dumps({"state": "REPAIR_BLOCKED", "errors": mission_errors}, indent=2), file=sys.stderr)
        return 1

    template_root = Path(args.template_root).resolve() if args.template_root else root.parent / "mission-control-template"
    if not (template_root / "TEMPLATE.json").is_file():
        print("template root unavailable; pass --template-root", file=sys.stderr)
        return 1

    asset_pairs = _template_asset_pairs(template_root, root)
    lock_path = root / "TEMPLATE_LOCK.json"
    source_assets = {
        destination.relative_to(root).as_posix(): sha256(source)
        for source, destination in asset_pairs
    }
    if not lock_path.is_file():
        print(json.dumps({
            "state": "REPAIR_BLOCKED",
            "reason": "TEMPLATE_LOCK.json is missing; bootstrap repair cannot prove which template bytes are authoritative",
        }, indent=2), file=sys.stderr)
        return 1
    try:
        existing_lock = load_json(lock_path)
    except Exception as exc:
        print(f"cannot repair bootstrap with unreadable TEMPLATE_LOCK.json: {exc}", file=sys.stderr)
        return 1
    locked_assets = existing_lock.get("assets")
    if existing_lock.get("template_schema") != TEMPLATE_SCHEMA or not isinstance(locked_assets, dict):
        print("bootstrap repair requires a valid existing template lock", file=sys.stderr)
        return 1
    if locked_assets != source_assets:
        print(json.dumps({
            "state": "REPAIR_BLOCKED",
            "reason": "template source bytes differ from the mission's existing TEMPLATE_LOCK; bootstrap repair cannot perform a template upgrade",
        }, indent=2), file=sys.stderr)
        return 1
    current_path = root / "control" / "CURRENT_AUTHORITY.json"
    invalid_marker = root / "control" / "BOOTSTRAP_INVALID.json"
    try:
        current_before = load_json(current_path)
    except Exception as exc:
        print(f"cannot repair bootstrap with unreadable CURRENT_AUTHORITY.json: {exc}", file=sys.stderr)
        return 1
    recover_invalid = current_before.get("status") == "BOOTSTRAP_INVALID"
    if recover_invalid:
        pristine, reason = _bootstrap_invalid_recovery_is_pristine(root)
        if not pristine:
            print(json.dumps({"state": "REPAIR_BLOCKED", "reason": reason}, indent=2), file=sys.stderr)
            return 1
    unlocked_generated = [
        path for rel, path in generated_asset_files(root).items()
        if rel not in locked_assets
    ]
    touched = [destination for _, destination in asset_pairs] + unlocked_generated + [lock_path, current_path, invalid_marker]
    snapshots: dict[Path, bytes | None] = {
        path: path.read_bytes() if path.is_file() else None
        for path in touched
    }
    top_level_dirs = {name: (root / name).exists() for name in ("contracts", "runtime")}

    try:
        copied = _copy_assets(template_root, root)
        for path in unlocked_generated:
            path.unlink(missing_ok=True)
        write_json(lock_path, existing_lock)
        if recover_invalid:
            recovered_current = load_json(current_path)
            recovered_current["status"] = "BOOTSTRAPPED"
            write_json(current_path, recovered_current)
        invalid_marker.unlink(missing_ok=True)
        problems = collect_mission_issues(root)
        if problems:
            raise RuntimeError(json.dumps(problems))
    except Exception as exc:
        for path, original in snapshots.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".repair-rollback.tmp")
                tmp.write_bytes(original)
                tmp.replace(path)
        for name, existed in top_level_dirs.items():
            directory = root / name
            if not existed and directory.exists():
                shutil.rmtree(directory)
        try:
            issues = json.loads(str(exc))
        except Exception:
            issues = [{"code": "MC0240", "message": str(exc), "likely": "bootstrap asset repair failed", "repair": "correct the template source or mission control state before retrying"}]
        print(json.dumps({"state": "REPAIR_ROLLED_BACK", "issues": issues}, indent=2), file=sys.stderr)
        return 1

    scope = "GENERATED_BOOTSTRAP_ASSETS_AND_INVALID_STATUS" if recover_invalid else "GENERATED_BOOTSTRAP_ASSETS_ONLY"
    print(json.dumps({"state": "REPAIRED", "scope": scope, "assets": len(asset_pairs)}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mc", description="Mission Control v16 operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--mission", required=True)
    init.set_defaults(func=cmd_init)
    for name, func in (("doctor", cmd_doctor), ("status", cmd_status), ("integrate", cmd_integrate), ("close", cmd_close), ("test", cmd_test)):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        p.set_defaults(func=func)
    sources = sub.add_parser("sources")
    sources_sub = sources.add_subparsers(dest="sources_command", required=True)
    sources_load = sources_sub.add_parser("load")
    sources_load.add_argument("--root", required=True)
    sources_load.add_argument("--file", required=True)
    sources_load.set_defaults(func=cmd_sources_load)
    provenance = sub.add_parser("provenance")
    provenance_sub = provenance.add_subparsers(dest="provenance_command", required=True)
    provenance_load = provenance_sub.add_parser("load")
    provenance_load.add_argument("--root", required=True)
    provenance_load.add_argument("--file", required=True)
    provenance_load.set_defaults(func=cmd_provenance_load)
    workspace = sub.add_parser("workspace")
    workspace_sub = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_register = workspace_sub.add_parser("register")
    workspace_register.add_argument("--root", required=True)
    workspace_register.add_argument("--cell", required=True)
    workspace_register.add_argument("--workspace-id", required=True)
    workspace_register.add_argument("--branch", required=True)
    workspace_register.add_argument("--path", dest="path", default=None)
    workspace_register.set_defaults(func=cmd_workspace_register)
    workspace_load = workspace_sub.add_parser("load")
    workspace_load.add_argument("--root", required=True)
    workspace_load.add_argument("--file", required=True)
    workspace_load.set_defaults(func=cmd_workspace_load)
    corpus = sub.add_parser("corpus")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)
    corpus_load = corpus_sub.add_parser("load")
    corpus_load.add_argument("--root", required=True)
    corpus_load.add_argument("--file", required=True)
    corpus_load.set_defaults(func=cmd_corpus_load)
    baseline = sub.add_parser("baseline")
    baseline_sub = baseline.add_subparsers(dest="baseline_command", required=True)
    bcompile = baseline_sub.add_parser("compile")
    bcompile.add_argument("--root", required=True)
    bcompile.set_defaults(func=cmd_baseline_compile)
    baccept = baseline_sub.add_parser("accept")
    baccept.add_argument("--root", required=True)
    baccept.set_defaults(func=cmd_baseline_accept)
    barrier = sub.add_parser("barrier")
    barrier_sub = barrier.add_subparsers(dest="barrier_command", required=True)
    barrier_accept = barrier_sub.add_parser("accept")
    barrier_accept.add_argument("--root", required=True)
    barrier_accept.add_argument("--cell", required=True)
    barrier_accept.set_defaults(func=cmd_barrier_accept)
    retry = sub.add_parser("retry")
    retry.add_argument("--root", required=True)
    retry.add_argument("--cell", required=True)
    retry.set_defaults(func=cmd_retry)
    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("--root", required=True)
    dispatch.add_argument("--cell", required=True)
    dispatch.add_argument("--worker-identity", required=True)
    dispatch.add_argument("--verifier-identity", required=True)
    dispatch.add_argument("--workspace-id")
    dispatch.set_defaults(func=cmd_dispatch)
    settle = sub.add_parser("settle")
    settle.add_argument("--root", required=True)
    settle.add_argument("--cell", required=True)
    settle.add_argument("--attempt", required=True, type=int)
    settle.add_argument("--result", required=True)
    settle.add_argument("--context-receipt", required=True)
    settle.add_argument("--adjudication", required=True)
    settle.set_defaults(func=cmd_settle)
    compile_cmd = sub.add_parser("compile")
    compile_cmd.add_argument("--root", required=True)
    compile_cmd.add_argument("--frontier", required=True)
    compile_cmd.set_defaults(func=cmd_compile)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("--root", required=True)
    qualify.add_argument("--result")
    qualify.set_defaults(func=cmd_qualify)
    repair = sub.add_parser("repair")
    repair_sub = repair.add_subparsers(dest="repair_command", required=True)
    bootstrap = repair_sub.add_parser("bootstrap")
    bootstrap.add_argument("--root", required=True)
    bootstrap.add_argument("--template-root")
    bootstrap.set_defaults(func=cmd_repair_bootstrap)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "init":
        root = Path(args.mission).resolve().parent
    elif hasattr(args, "root"):
        root = Path(args.root).resolve()
    else:
        return int(args.func(args))
    try:
        with mission_control_lock(root):
            return int(args.func(args))
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
