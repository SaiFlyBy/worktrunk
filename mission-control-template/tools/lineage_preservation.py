#!/usr/bin/env python3
"""Verify exact same-repository lineage objects for an opt-in mission.

This module compares committed Git blobs, not checkout text. It cannot prove that
an undisclosed donor was never used: a separate independent review must make that
bounded finding against the exact sources, target policy and candidate.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class LineageProofError(ValueError):
    pass


# This v1 profile is established from the target's accepted operating contract
# and validator. A policy or validator change requires a separately reviewed
# profile revision; role labels supplied by the caller cannot replace it.
PROFILE_REPOSITORY = "saiflyby/flybymaestro"
PROFILE_POLICY_BLOB = "02c210f2dfb91f49790429dd205d955aef7d8e83"
PROFILE_VALIDATOR_BLOB = "79ab372d4217bf21598cbeb743ae6fc460df4d42"
PROFILE_PATHS = {
    "LINEAGE": "sources_provenance.yaml",
    "HARVEST": "external_harvest_manifest.yaml",
    "POLICY": "PROJECT_OPERATING_CONTRACT.md",
    "VALIDATOR": "scripts/ci/verify_sources_provenance.py",
}


def validate_target_profile(repository: Any, items: Any) -> list[str]:
    if not isinstance(repository, str) or repository.casefold() != PROFILE_REPOSITORY:
        return ["no independently established lineage profile for this repository"]
    if not isinstance(items, list) or len(items) != len(PROFILE_PATHS):
        return ["the target profile requires exactly its four protected files"]
    if not all(isinstance(item, dict) for item in items):
        return ["the target profile contains a malformed protected file"]
    if any(not isinstance(item.get("role"), str) or not isinstance(item.get("path"), str) for item in items):
        return ["the target profile contains a malformed protected role or path"]
    if len({item.get("role") for item in items}) != len(PROFILE_PATHS):
        return ["the target profile requires each protected role exactly once"]
    by_role = {item.get("role"): item for item in items}
    if set(by_role) != set(PROFILE_PATHS) or any(
            by_role[role].get("path") != path for role, path in PROFILE_PATHS.items()):
        return ["protected role paths differ from the independently established target profile"]
    for role, blob in (("POLICY", PROFILE_POLICY_BLOB), ("VALIDATOR", PROFILE_VALIDATOR_BLOB)):
        if by_role[role].get("mode") != "100644" or by_role[role].get("git_blob") != blob:
            return [f"{role.lower()} changed; an independently reviewed target profile is required"]
    return []


def _git_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_PREFIX", "GIT_IMPLICIT_WORK_TREE", "GIT_NAMESPACE",
        "GIT_SHALLOW_FILE", "GIT_REPLACE_REF_BASE",
    ):
        env.pop(key, None)
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_LITERAL_PATHSPECS"] = "1"
    return env


def _git(repo: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], env=_git_environment(),
                              capture_output=True, check=False)
    except OSError as exc:
        raise LineageProofError(f"Git could not start: {exc}") from exc
    if proc.returncode:
        raise LineageProofError(f"Git {args[0]} failed with exit {proc.returncode}")
    return proc.stdout


def _canonical_repository(origin: str) -> str | None:
    try:
        if origin.startswith(("https://", "ssh://")):
            parsed = urlsplit(origin)
            if (parsed.hostname or "").casefold() != "github.com" or parsed.query or parsed.fragment or parsed.port:
                return None
            path = parsed.path
        else:
            match = re.fullmatch(r"(?:[^@/:]+@)?github\.com:(.+)", origin, re.IGNORECASE)
            if not match:
                return None
            path = match.group(1)
        path = path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = path.split("/")
        if len(parts) != 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."} for part in parts):
            return None
        return "/".join(parts).casefold()
    except ValueError:
        return None


def _safe_git_path(path: Any) -> bool:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return False
    if any(ord(c) < 32 or ord(c) == 127 or c in ":*?[]" for c in path):
        return False
    return all(part not in {"", ".", ".."} for part in path.split("/"))


def _exact_commit(repo: Path, commit: Any) -> str:
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise LineageProofError("commit must be a full lowercase SHA-1 object id")
    resolved = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").decode("ascii").strip()
    if resolved != commit:
        raise LineageProofError("commit does not resolve to its exact object id")
    return commit


def _blob_digest(repo: Path, oid: str) -> str:
    try:
        proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "blob", oid],
                                env=_git_environment(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise LineageProofError(f"Git cat-file could not start: {exc}") from exc
    digest = hashlib.sha256()
    assert proc.stdout is not None
    with proc.stdout:
        for chunk in iter(lambda: proc.stdout.read(1024 * 1024), b""):
            digest.update(chunk)
    if proc.wait() != 0:
        raise LineageProofError("Git cat-file could not read the committed blob")
    return digest.hexdigest()


def _tree_entry(repo: Path, commit: str, path: str) -> tuple[str, str, str]:
    raw = _git(repo, "ls-tree", "-z", "--full-tree", commit, "--", path)
    entries = [entry for entry in raw.split(b"\0") if entry]
    if len(entries) != 1:
        raise LineageProofError(f"{path}: expected one committed file, found {len(entries)}")
    try:
        header, found_path = entries[0].split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split(" ")
        if found_path.decode("utf-8") != path:
            raise ValueError("path mismatch")
    except (ValueError, UnicodeError) as exc:
        raise LineageProofError(f"{path}: ambiguous Git tree entry") from exc
    if mode not in {"100644", "100755"} or kind != "blob" or not re.fullmatch(r"[0-9a-f]{40}", oid):
        raise LineageProofError(f"{path}: expected a regular committed file")
    return mode, oid, _blob_digest(repo, oid)


def verify_target_trees(repo: Path, contract: dict[str, Any], candidate: str,
                        publication_base: str, *, reviewed_base: str | None = None) -> list[str]:
    """Compare the accepted policy base and candidate against pinned raw blobs.

    The caller must separately authenticate the repository, source reviews, and
    independent no-new-harvest finding. This function performs no network call.
    """
    errors: list[str] = []
    try:
        repo = Path(repo).resolve()
        if not repo.is_dir() or Path(_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve() != repo:
            raise LineageProofError("registered path is not the Git worktree root")
        repository = contract.get("repository")
        if not isinstance(repository, str) or _canonical_repository(
                _git(repo, "remote", "get-url", "origin").decode("utf-8").strip()) != repository.casefold():
            raise LineageProofError("origin does not identify the declared GitHub repository")
        policy_base = _exact_commit(repo, contract.get("policy_base_sha"))
        _exact_commit(repo, candidate)
        _exact_commit(repo, publication_base)
        reviewed_base = _exact_commit(repo, reviewed_base if reviewed_base is not None else policy_base)
        if publication_base != reviewed_base:
            raise LineageProofError("publication base changed; renew the preservation review")
        _git(repo, "merge-base", "--is-ancestor", policy_base, reviewed_base)
        _git(repo, "merge-base", "--is-ancestor", reviewed_base, candidate)
        items = contract.get("protected_files")
        profile_errors = validate_target_profile(repository, items)
        if profile_errors:
            raise LineageProofError("; ".join(profile_errors))
        if not isinstance(items, list) or not items:
            raise LineageProofError("protected file evidence is missing")
        roles = [item.get("role") for item in items if isinstance(item, dict)]
        if not {"LINEAGE", "HARVEST", "POLICY", "VALIDATOR"}.issubset(roles):
            raise LineageProofError("lineage, harvest, policy and validator files must all be bound")
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {"role", "path", "mode", "git_blob", "sha256"}:
                errors.append("protected file record is malformed")
                continue
            path = item["path"]
            if not _safe_git_path(path) or path in seen:
                errors.append(f"unsafe or duplicate protected path: {path!r}")
                continue
            seen.add(path)
            if item["role"] not in {"LINEAGE", "HARVEST", "POLICY", "VALIDATOR"}:
                errors.append(f"{path}: unsupported protected file role")
                continue
            if (item["mode"] not in {"100644", "100755"}
                    or not isinstance(item["git_blob"], str)
                    or not re.fullmatch(r"[0-9a-f]{40}", item["git_blob"])
                    or not isinstance(item["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
                errors.append(f"{path}: malformed mode or digest")
                continue
            expected = (item["mode"], item["git_blob"], item["sha256"])
            for label, commit in (("policy base", policy_base), ("reviewed base", reviewed_base), ("candidate", candidate)):
                try:
                    if _tree_entry(repo, commit, path) != expected:
                        errors.append(f"{path}: {label} file mode, blob or raw-byte digest changed")
                except LineageProofError as exc:
                    errors.append(f"{label} {exc}")
    except (LineageProofError, OSError, UnicodeError, TypeError) as exc:
        errors.append(str(exc))
    return errors

def _source_repository(locator: Any) -> str | None:
    if not isinstance(locator, str):
        return None
    try:
        parsed = urlsplit(locator)
        if (parsed.scheme != "https" or (parsed.hostname or "").casefold() != "github.com"
                or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment):
            return None
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in {".", ".."} for p in parts[:2]):
            return None
        return "/".join(parts[:2]).removesuffix(".git").casefold()
    except ValueError:
        return None


def _canonical_digest(value: Any) -> str:
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _evidence_path(root: Path, ref: Any) -> Path:
    if not _safe_git_path(ref):
        raise LineageProofError("source review evidence ref is unsafe")
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise LineageProofError("source review evidence is missing or outside the mission")
    return path


def _reviewed_source_ids(requirements: list[dict[str, Any]],
                         mechanisms: list[dict[str, Any]],
                         sources: dict[str, Any]) -> set[str]:
    used = {sid for requirement in requirements for sid in requirement.get("sources", [])}
    used.update(sid for mechanism in mechanisms for sid in mechanism.get("source_ids", []))
    used.update(source.get("id") for source in sources.get("sources", [])
                if isinstance(source, dict)
                and source.get("disposition") in {"SYNTHESIS_REQUIRED", "ADJUDICATED_SYNTHESIS"})
    return used


def verify_source_scope(root: Path, repo: Path, repository: str, corpus: dict[str, Any],
                        sources: dict[str, Any], synthesis: dict[str, Any], candidate: str,
                        *, check_git: bool = True) -> list[str]:
    """Check admitted source identity and retained review bindings.

    The caller must also run Mission Control doctor for the full existing
    source/requirement/mechanism and rights checks, and obtain an independent
    candidate-specific no-new-harvest review.
    """
    errors: list[str] = []
    try:
        if check_git:
            _exact_commit(repo, candidate)
        elif not isinstance(candidate, str) or not re.fullmatch(r"[0-9a-f]{40}", candidate):
            return ["candidate must be a full lowercase SHA-1 object id"]
        requirements = [r for r in corpus.get("requirements", [])
                        if isinstance(r, dict) and repository in r.get("targets", [])]
        req_ids = {r.get("id") for r in requirements}
        if not req_ids:
            return ["preservation target has no bound requirements"]
        mechanisms = [m for m in synthesis.get("mechanisms", [])
                      if isinstance(m, dict) and m.get("disposition") != "REJECTED"
                      and set(m.get("target_requirements", [])) & req_ids]
        mechanism_sources = {sid for m in mechanisms for sid in m.get("source_ids", [])}
        used_ids = _reviewed_source_ids(requirements, mechanisms, sources)
        records = {s.get("id"): s for s in sources.get("sources", []) if isinstance(s, dict)}
        assessments = {a.get("source_id"): a for a in synthesis.get("source_assessments", []) if isinstance(a, dict)}
        if not mechanisms or synthesis.get("cross_source_synthesis", {}).get("state") != "VERIFIED":
            errors.append("verified source mechanism synthesis is required")
        if not used_ids or not used_ids.issubset(records):
            errors.append("source identities are missing from the admitted registry")
        material_count = 0
        for source_id in sorted(used_ids & records.keys()):
            source = records[source_id]
            kind = source.get("kind")
            if kind == "OWNER_INTENT" and source_id == "owner-intent" and source.get("locator") == "MISSION.json#owner_intent":
                if source_id in mechanism_sources:
                    errors.append("owner intent cannot impersonate a repository implementation source")
                continue
            if kind == "AUDIT" and source.get("disposition") == "REFERENCE_ONLY" and source_id not in mechanism_sources:
                continue
            if kind != "REPOSITORY":
                errors.append(f"{source_id}: non-repository or unknown material source is not eligible")
                continue
            material_count += 1
            if _source_repository(source.get("locator")) != repository.casefold():
                errors.append(f"{source_id}: source locator is not the same GitHub repository")
            rights = source.get("copyright")
            if (not isinstance(rights, dict) or rights.get("usage_mode") != "OWNER_AUTHORIZED_REUSE"
                    or rights.get("rights_status") != "VERIFIED" or rights.get("code_copy_allowed") is not True
                    or rights.get("obligations") != []):
                errors.append(f"{source_id}: verified owner rights without new obligations are required")
            try:
                pin = source.get("pin")
                if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{40}", pin):
                    raise LineageProofError("source pin is not a full lowercase commit id")
                if check_git:
                    _exact_commit(repo, pin)
                    _git(repo, "merge-base", "--is-ancestor", pin, candidate)
            except LineageProofError as exc:
                errors.append(f"{source_id}: source pin is not an ancestor of the exact candidate ({exc})")
            assessment = assessments.get(source_id)
            review = assessment.get("independent_review") if isinstance(assessment, dict) else None
            if (not isinstance(assessment, dict) or assessment.get("coverage_status") != "COMPLETE"
                    or assessment.get("open_questions") or not isinstance(review, dict)
                    or review.get("state") != "VERIFIED"
                    or not review.get("reviewer_identity") or not review.get("extractor_identity")
                    or review.get("reviewer_identity") == review.get("extractor_identity")
                    or review.get("source_record_sha256") != _canonical_digest(source)):
                errors.append(f"{source_id}: exact independent source review is missing or stale")
                continue
            try:
                review_path = _evidence_path(root, review.get("review_ref"))
                if hashlib.sha256(review_path.read_bytes()).hexdigest() != review.get("review_sha256"):
                    errors.append(f"{source_id}: independent source review hash changed")
            except (LineageProofError, OSError) as exc:
                errors.append(f"{source_id}: {exc}")
        if not material_count:
            errors.append("at least one same-repository implementation source is required")
        for mechanism in mechanisms:
            posture = mechanism.get("copyright_posture")
            if isinstance(posture, dict) and posture.get("obligations"):
                errors.append(f"{mechanism.get('id')}: new obligations cannot use preservation mode")
    except (LineageProofError, OSError, UnicodeError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors

def verify_preservation_review(root: Path, repo: Path, corpus: dict[str, Any],
                               sources: dict[str, Any], synthesis: dict[str, Any],
                               state: dict[str, Any], cell_id: str, record: dict[str, Any],
                               candidate: str, publication_base: str,
                               review: dict[str, Any], *, check_git: bool = True) -> list[str]:
    """Validate exact candidate, source and independent-review custody.

    This verifies structured evidence and Git objects. It does not authenticate
    the reviewer or prove that undisclosed external material does not exist.
    """
    errors: list[str] = []
    try:
        materialization = corpus.get("provenance_materialization", {})
        contract = materialization.get("preservation") if isinstance(materialization, dict) else None
        if materialization.get("mode") != "SAME_REPOSITORY_NO_NEW_HARVEST" or not isinstance(contract, dict):
            return ["same-repository preservation contract is missing"]
        repository = contract.get("repository")
        if not isinstance(repository, str) or not repository:
            return ["preservation repository is missing"]
        expected = {
            "schema": "flyby/mission-control-lineage-preservation-review/1",
            "mission_id": state.get("mission_id"),
            "mission_instance_id": state.get("mission_instance_id"),
            "cell_id": cell_id,
            "attempt": record.get("attempt"),
            "repository": repository,
            "policy_base_sha": contract.get("policy_base_sha"),
            "candidate_sha": candidate,
            "author_identity": record.get("worker_identity"),
            "reviewer_identity": record.get("verifier_identity"),
            "decision": "VERIFIED_SAME_REPOSITORY_NO_NEW_HARVEST",
        }
        for key, value in expected.items():
            if review.get(key) != value:
                errors.append(f"candidate review {key} differs from the exact mission or attempt")
        if (not isinstance(record.get("worker_identity"), str) or not record.get("worker_identity")
                or not isinstance(record.get("verifier_identity"), str) or not record.get("verifier_identity")
                or record["worker_identity"] == record["verifier_identity"]):
            errors.append("candidate review requires distinct preassigned author and verifier identities")
        if review.get("workspace_id") is not None and review.get("workspace_id") != record.get("workspace_id"):
            errors.append("candidate review workspace_id differs from the registered workspace")
        if review.get("no_new_external_contribution") is not True or review.get("no_new_obligations") is not True:
            errors.append("candidate review must explicitly verify no new external contribution or obligation")
        for field, filename in (("corpus_sha256", "TARGET_MUTATIONS.json"),
                                ("sources_sha256", "SOURCES.json"),
                                ("synthesis_sha256", "PROVENANCE_SYNTHESIS.json")):
            path = root / "corpus" / filename
            if not path.is_file() or review.get(field) != hashlib.sha256(path.read_bytes()).hexdigest():
                errors.append(f"candidate review {field} does not bind the current artifact bytes")
        requirements = [r for r in corpus.get("requirements", [])
                        if isinstance(r, dict) and repository in r.get("targets", [])]
        req_ids = {r.get("id") for r in requirements}
        mechanisms = [m for m in synthesis.get("mechanisms", [])
                      if isinstance(m, dict) and m.get("disposition") != "REJECTED"
                      and set(m.get("target_requirements", [])) & req_ids]
        expected_sources = _reviewed_source_ids(requirements, mechanisms, sources)
        reviewed = review.get("reviewed_source_ids")
        if not isinstance(reviewed, list) or len(reviewed) != len(set(reviewed)) or set(reviewed) != expected_sources:
            errors.append("candidate review must name every exact relevant source")
        evidence = review.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("candidate review requires retained independent evidence")
        else:
            for item in evidence:
                try:
                    if not isinstance(item, dict):
                        raise LineageProofError("candidate review evidence entry is malformed")
                    path = _evidence_path(root, item.get("ref"))
                    if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
                        raise LineageProofError("candidate review evidence hash changed")
                except (LineageProofError, OSError) as exc:
                    errors.append(str(exc))
        errors.extend(verify_source_scope(root, repo, repository, corpus, sources, synthesis, candidate,
                                          check_git=check_git))
        reviewed_base = review.get("publication_base_sha", review.get("policy_base_sha"))
        if publication_base != reviewed_base:
            errors.append("publication base changed; renew the preservation review")
        if check_git:
            errors.extend(verify_target_trees(repo, contract, candidate, publication_base,
                                               reviewed_base=reviewed_base))
    except (OSError, TypeError, ValueError, LineageProofError) as exc:
        errors.append(f"candidate review could not be validated: {exc}")
    return errors
