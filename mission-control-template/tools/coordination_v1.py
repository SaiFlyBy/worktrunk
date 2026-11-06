"""Mission Control's opt-in target-cell coordination capability.

The execution-state ledger remains the admission authority. One short transaction
orders requests, checks declared conflicts and records permission to start a
launch protocol. No provider is launched here. A per-Git-common-directory marker
prevents two capable Mission Controls from independently governing the same
worktrees; it is an authority registration, not another scheduler.

Results and writer liveness are independent. This runtime has no qualified
provider-tree termination API. After launch intent, only an explicit, independent
operator fence observation can establish the missing safety premise. Timeouts,
heartbeats, result receipts and process IDs never establish it automatically.
The operator and the control directory are trusted; arbitrary external writers
and other clones governed by another control directory are outside this boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

CAPABILITY = "contracts/capabilities/cell-coordination-v1.json"
STATE_SCHEMA = "flyby/mission-control-execution-state/19"
SCHEMA_REF = "contracts/schemas/EXECUTION_STATE_SCHEMA_V19.json"
REGISTRATION = "mission-control-coordination-authority-v1.json"
PHASES = {"QUEUED", "ADMITTED", "LAUNCH_UNCERTAIN", "RUNNING", "STOP_REQUESTED",
          "UNKNOWN", "STOP_CONFIRMED", "RELEASED"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


def enabled(root: Path) -> bool:
    try:
        return CAPABILITY in json.loads((root / "TEMPLATE_LOCK.json").read_text(encoding="utf-8"))["assets"]
    except (OSError, ValueError, KeyError, TypeError):
        return False


def stable_lock_required(root: Path) -> bool:
    if (root / CAPABILITY).exists() or enabled(root):
        return True
    try:
        return json.loads((root / "control/EXECUTION_STATE.json").read_text(encoding="utf-8")).get("schema") == STATE_SCHEMA
    except (OSError, ValueError, TypeError):
        return False


def git(repo: Path, *args: str) -> bytes:
    # These probes must inspect the registered checkout, not an inherited index,
    # replacement object, worktree, fsmonitor program or external diff driver.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    proc = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                           "-C", str(repo), *args], capture_output=True, env=env)
    if proc.returncode:
        raise ValueError(f"Git {args[0]} could not verify registered custody (exit {proc.returncode})")
    return proc.stdout


def text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode("utf-8", "surrogateescape").rstrip("\r\n")


def path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _safe_relative(value: str) -> tuple[str, bool]:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("scope must be a nonempty literal relative path")
    value = value.replace("\\", "/")
    directory = value.endswith("/")
    value = value[:-1] if directory else value
    parts = value.split("/")
    if (any(part in {"", ".", ".."} for part in parts) or value.startswith("/")
            or any(char in value for char in ":*?[]{}")):
        raise ValueError(f"unsafe or unsupported scope syntax: {value!r}")
    for part in parts:
        folded = part.casefold().rstrip(" .")
        if folded == ".git" or folded.startswith((".git~", "git~")):
            raise ValueError(f"Git metadata is outside cell ownership: {value!r}")
        if os.name == "nt" and (part.endswith((" ", ".")) or
                part.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}):
            raise ValueError(f"unsupported Windows path alias: {value!r}")
    return value, directory


def _resolved_relative(repo: Path, value: str) -> str:
    prefix = repo
    for part in value.split("/")[:-1]:
        prefix = prefix / part
        if prefix.exists() and not prefix.is_dir():
            raise ValueError(f"scope traverses a file: {value!r}")
    result = (repo / value).resolve()
    if not result.is_relative_to(repo):
        raise ValueError(f"scope escapes registered workspace through a link: {value!r}")
    relative = result.relative_to(repo).as_posix()
    _safe_relative(relative)
    return relative


def scopes(repo: Path, owned: list[str], insensitive: bool) -> list[dict]:
    result = []
    for value in owned:
        relative, directory = _safe_relative(value)
        resolved = _resolved_relative(repo, relative)
        # Existing directories and an explicit trailing slash are directories;
        # nonexistent unsuffixed paths are exact files. Pin this interpretation.
        directory = directory or (repo / relative).is_dir()
        if directory and (repo / relative).exists() and not (repo / relative).is_dir():
            raise ValueError(f"directory scope names a file: {value!r}")
        fold = str.casefold if insensitive else lambda value: value
        result.append({"path": fold(relative), "resolved": fold(resolved), "directory": directory})
    if not result:
        raise ValueError("target cell has no owned paths")
    return sorted(result, key=lambda item: (item["path"], item["resolved"], item["directory"]))


def contains(scope: dict, path: str) -> bool:
    return path == scope["path"] or (scope["directory"] and path.startswith(scope["path"] + "/"))


def overlaps(left: dict, right: dict) -> bool:
    for lpath in {left["path"], left["resolved"]}:
        for rpath in {right["path"], right["resolved"]}:
            # An exact file does not own descendants, but Git cannot represent
            # that file and a descendant simultaneously in one accepted tree.
            if lpath == rpath or rpath.startswith(lpath + "/") or lpath.startswith(rpath + "/"):
                return True
    return False


def _entry(api, root: Path, cell_id: str, workspace_id: str) -> dict:
    entries = api.load_json(root / "control/WORKSPACE_LEDGER.json").get("entries", [])
    matches = [entry for entry in entries if entry.get("workspace_id") == workspace_id
               and entry.get("registered_cell") == cell_id and entry.get("kind") == "TARGET"]
    if len(matches) != 1 or not isinstance(matches[0].get("worktree_path"), str):
        raise ValueError("coordination requires one registered physical target workspace")
    return matches[0]


def custody(entry: dict) -> dict:
    repo = Path(entry["worktree_path"]).resolve()
    if str(repo) != entry["worktree_path"] or not repo.is_dir():
        raise ValueError("registered workspace path changed or disappeared")
    if Path(text(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("registered path is not the Git worktree root")
    if text(repo, "branch", "--show-current") != entry["branch"]:
        raise ValueError("registered workspace branch changed")
    if text(repo, "remote", "get-url", "origin") != entry["remote_url"]:
        raise ValueError("registered workspace origin changed")
    flags = git(repo, "ls-files", "-v", "-z").split(b"\0")
    if any(item and (97 <= item[0] <= 122 or item[:1] == b"S") for item in flags):
        raise ValueError("index has assume-unchanged or skip-worktree entries")
    common = Path(text(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    # Windows's supported contract is conservative, case-insensitive matching.
    # Elsewhere Git's core.ignorecase repository contract is respected.
    ignorecase = text(repo, "config", "--local", "--bool", "--default", "false", "--get", "core.ignorecase") == "true"
    return {"workspace_path": str(repo), "git_common_dir": path_key(common),
            "branch": entry["branch"], "origin": entry["remote_url"],
            "base_sha": entry["base_sha"], "case_insensitive": os.name == "nt" or ignorecase}


def _registration(api, root: Path, state: dict, entry: dict, *, create: bool = False) -> dict:
    bound = custody(entry)
    common = Path(bound["git_common_dir"])
    marker = common / REGISTRATION
    expected = {"schema": "flyby/mission-control-repository-authority/1",
                "authority_root": str(root), "instance_id": state["coordination"]["instance_id"],
                "git_common_dir": bound["git_common_dir"]}
    with api.mission_control_lock(common, stable=True):
        if marker.exists():
            if api.load_json(marker) != expected:
                raise ValueError("Git common directory belongs to another coordination authority; reconcile its claims before an explicit relinquishment")
        elif create:
            api.write_immutable_json(marker, expected)
        else:
            raise ValueError("repository coordination authority registration is missing")
    return bound


def register(scope: dict, root: Path, state: dict, entry: dict) -> None:
    _registration(SimpleNamespace(**scope), root, state, entry, create=True)


def binding(api, root: Path, dag: dict, state: dict, cell_id: str, workspace_id: str,
            worker: str, verifier: str) -> dict:
    cell = api._find_cell(dag, cell_id)
    record = state["cells"][cell_id]
    if not cell or cell.get("kind") != "MUTATION" or not isinstance(cell.get("target"), dict):
        raise ValueError("coordination v1 requires a target MUTATION cell")
    entry = _entry(api, root, cell_id, workspace_id)
    target = cell["target"]
    if entry["repository"] != target["repository"] or entry["base_sha"] != target["base_sha"].lower():
        raise ValueError("workspace differs from compiled target base or repository")
    live = _registration(api, root, state, entry)
    repository = target["repository"]
    # Owner/repository slugs are case-insensitive. Filesystem paths are not
    # lowercased on case-sensitive repository contracts.
    key = repository.casefold() if re.fullmatch(r"[\w.-]+/[\w.-]+", repository) else repository
    scope_base, inherited_head = live["base_sha"], None
    marker = "\nWORKTRUNK_HANDOFF_V1="
    if marker in cell.get("objective", ""):
        payload = json.loads(cell["objective"].rsplit(marker, 1)[1])
        observation = payload.get("scope_base_observation", {})
        source = state["cells"].get(payload.get("source_cell"), {})
        source_request = source.get("coordination", {})
        if (source.get("state") != "ACCEPTED" or source_request.get("phase") != "RELEASED"
                or payload.get("source_cell") not in cell.get("dependencies", [])
                or source.get("attempt") != payload.get("source_attempt")
                or observation.get("schema") != "flyby/mission-control-accepted-base-observation/1"
                or observation.get("ref") != "refs/heads/main" or observation.get("sha") != payload.get("observed_base")
                or observation.get("origin") != live["origin"]
                or observation.get("source_scope_proof_sha256") != source_request.get("scope_proof_sha256")
                or observation.get("source_token") != source_request.get("token")
                or observation.get("source_generation") != source_request.get("generation")):
            raise ValueError("handoff lacks verified accepted-base observation and safely released source custody")
        for kind in ("result", "context_receipt", "adjudication"):
            if payload.get("accepted_evidence", {}).get(kind) != {"ref": source.get(kind + "_ref"), "sha256": source.get(kind + "_sha256")}:
                raise ValueError("handoff source evidence no longer matches accepted custody")
        source_result = api.load_json(api.resolve_ref(root, source["result_ref"]))
        if source_result["target_outcomes"][0]["head_sha"] != payload.get("source_head"):
            raise ValueError("handoff source candidate changed")
        scope_base, inherited_head = payload["observed_base"], payload["source_head"]
        if not re.fullmatch(r"[0-9a-f]{40}", scope_base):
            raise ValueError("handoff scope base is not an immutable commit")
        git(Path(live["workspace_path"]), "merge-base", "--is-ancestor", live["base_sha"], scope_base)
    return {"instance_id": state["coordination"]["instance_id"], "authority_root": str(root),
            "cell": cell_id, "attempt": record["attempt"], "workspace_id": workspace_id,
            "worker_identity": worker, "verifier_identity": verifier,
            "workcell_ref": record["workcell_ref"], "workcell_sha256": api.sha256(root / record["workcell_ref"]),
            "target": target, "repository_key": key, "workspace": live,
            "scope_base": scope_base, "inherited_head": inherited_head,
            "scopes": scopes(Path(live["workspace_path"]), target["owned_paths"], live["case_insensitive"]),
            "dependencies": cell.get("dependencies", []), "claims": sorted(cell.get("resource_claims", [])),
            "conflict_class": cell["conflict_class"]}


def conflict(left: dict, right: dict) -> list[str]:
    reasons = []
    if left["conflict_class"] == right["conflict_class"]:
        reasons.append("conflict_class")
    reasons.extend("resource:" + value for value in sorted(set(left["claims"]) & set(right["claims"])))
    same_repository = (left["repository_key"] == right["repository_key"] or
                       left["workspace"]["git_common_dir"] == right["workspace"]["git_common_dir"])
    if same_repository:
        if os.path.normcase(left["workspace"]["workspace_path"]) == os.path.normcase(right["workspace"]["workspace_path"]):
            reasons.append("physical_workspace")
        if any(overlaps(a, b) for a in left["scopes"] for b in right["scopes"]):
            reasons.append("owned_paths")
    # Also account for nested repositories/submodules whose physical write
    # scopes intersect despite having different logical repository identities.
    def physical(bound):
        repo = Path(bound["workspace"]["workspace_path"])
        return [{"path": os.path.normcase(str(repo / item["resolved"])).replace("\\", "/"),
                 "resolved": os.path.normcase(str(repo / item["resolved"])).replace("\\", "/"), "directory": item["directory"]}
                for item in bound["scopes"]]
    if any(overlaps(a, b) for a in physical(left) for b in physical(right)):
        reasons.append("physical_paths")
    return reasons


def snapshot(bound: dict, candidate: str, base: str, *, clean: bool, admission: bool = False) -> dict:
    repo = Path(bound["workspace"]["workspace_path"])
    live = custody({"worktree_path": str(repo), "branch": bound["workspace"]["branch"],
                    "remote_url": bound["workspace"]["origin"], "base_sha": bound["workspace"]["base_sha"]})
    if live != bound["workspace"]:
        raise ValueError("workspace identity or filesystem contract changed")
    current_scopes = scopes(repo, bound["target"]["owned_paths"], live["case_insensitive"])
    if current_scopes != bound["scopes"]:
        raise ValueError("scope resolution changed; explicit reassessment and reacquisition required")
    if text(repo, "rev-parse", "HEAD") != candidate or not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise ValueError("candidate differs from live registered HEAD")
    git(repo, "merge-base", "--is-ancestor", base, candidate)
    if not admission and bound.get("inherited_head"):
        git(repo, "merge-base", "--is-ancestor", bound["inherited_head"], candidate)
        git(repo, "merge-base", "--is-ancestor", bound["scope_base"], candidate)
    commands = {"committed": (base, candidate), "staged": ("--cached", "HEAD"), "unstaged": ()}
    paths = {}
    for name, revision in commands.items():
        raw = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--ignore-submodules=none",
                  "--name-only", "-z", *revision, "--")
        paths[name] = sorted(set(part.decode("utf-8", "surrogateescape") for part in raw.split(b"\0") if part))
    paths["untracked"] = sorted(set(part.decode("utf-8", "surrogateescape") for part in
                                     git(repo, "ls-files", "--others", "-z").split(b"\0") if part))
    offending = []
    for path in sorted(set(value for group in paths.values() for value in group)):
        relative, _ = _safe_relative(path)
        resolved = _resolved_relative(repo, relative)
        if live["case_insensitive"]:
            relative, resolved = relative.casefold(), resolved.casefold()
        if not any(contains(item, relative) and
                   (resolved == item["resolved"] or (item["directory"] and resolved.startswith(item["resolved"] + "/")))
                   for item in bound["scopes"]):
            offending.append(path)
    status = git(repo, "status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=none")
    dirty = sorted(set(paths["staged"] + paths["unstaged"] + paths["untracked"]))
    if offending:
        raise ValueError(json.dumps({"authority_mismatch": "changed files outside admitted ownership", "offending_paths": offending}, ensure_ascii=True))
    if clean and (status or dirty):
        raise ValueError(json.dumps({"authority_mismatch": "candidate workspace is dirty", "dirty_paths": dirty}, ensure_ascii=True))
    dirty_content = []
    for path in dirty:
        item = repo / path
        if item.is_symlink():
            value = {"link": os.readlink(item)}
        elif item.is_file():
            h = hashlib.sha256()
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            value = {"sha256": h.hexdigest(), "mode": stat.S_IMODE(item.stat().st_mode)}
        else:
            value = {"directory_or_missing": True}
        dirty_content.append([path, value])
    return {"binding_digest": digest(bound), "candidate": candidate,
            "tree": text(repo, "rev-parse", candidate + "^{tree}"), "base": base,
            "paths": paths, "index_sha256": hashlib.sha256(git(repo, "ls-files", "--stage", "-z")).hexdigest(),
            "status_sha256": hashlib.sha256(status).hexdigest(), "dirty_content": dirty_content}


def _ready(api, root: Path, dag: dict, state: dict, cell_id: str, request: dict) -> list[str]:
    bound = request["binding"]
    blockers = ["dependency:" + dep for dep in bound["dependencies"] if state["cells"].get(dep, {}).get("state") != "ACCEPTED"]
    blockers.extend("dependency_release:" + dep for dep in bound["dependencies"]
                    if state["cells"].get(dep, {}).get("coordination", {}).get("phase") not in {None, "RELEASED"})
    if state["lifecycle"] not in api._PHASE_LIFECYCLES[api._cell_phase(dag, cell_id)]:
        blockers.append("lifecycle:" + state["lifecycle"])
    try:
        current = binding(api, root, dag, state, cell_id, bound["workspace_id"], bound["worker_identity"], bound["verifier_identity"])
        if current != bound:
            raise ValueError("scope/base/dependency/custody premise changed; explicit reassessment required")
        snapshot(bound, bound["workspace"]["base_sha"], bound["workspace"]["base_sha"], clean=True, admission=True)
    except (ValueError, OSError) as exc:
        blockers.append("reassessment:" + str(exc))
    return blockers


def _view(cell_id: str, record: dict) -> dict:
    request = record["coordination"]
    return {"cell": cell_id, "attempt": record["attempt"], "state": record["state"],
            "phase": request["phase"], "request_id": request["request_id"], "order": request["order"],
            "generation": request["generation"], "token": request["token"], "blockers": request["blockers"],
            "workcell_ref": record.get("workcell_ref"), "workspace_id": request["binding"]["workspace_id"],
            "worker_identity": request["binding"]["worker_identity"], "verifier_identity": request["binding"]["verifier_identity"],
            "capability": "cell-coordination/v1", "launch_protocol_required": True,
            "provider_launch_performed": False, "termination_supported": False}


def _sweep(api, root: Path, dag: dict, state: dict) -> None:
    requests = [(cid, rec) for cid, rec in state["cells"].items() if isinstance(rec.get("coordination"), dict)]
    eligible = {}
    for cid, record in requests:
        request = record["coordination"]
        if request["phase"] == "QUEUED":
            request["blockers"] = _ready(api, root, dag, state, cid, request)
            eligible[cid] = not request["blockers"]
    # FIFO among currently eligible conflicting requests, then cell identity.
    # Ineligible requests do not reserve paths or cause head-of-line blocking.
    for cid, record in sorted(requests, key=lambda item: (item[1]["coordination"]["order"], item[0])):
        request = record["coordination"]
        if not eligible.get(cid):
            continue
        blockers = []
        for oid, other in requests:
            if oid == cid:
                continue
            peer = other["coordination"]
            if peer["phase"] not in {"QUEUED", "RELEASED"}:
                blockers.extend(f"active:{oid}:{reason}" for reason in conflict(request["binding"], peer["binding"]))
            elif peer["phase"] == "QUEUED" and eligible.get(oid) and (peer["order"], oid) < (request["order"], cid):
                blockers.extend(f"earlier:{oid}:{reason}" for reason in conflict(request["binding"], peer["binding"]))
        # Retain existing explicit claim/class behavior for control-only cells.
        for oid, other in state["cells"].items():
            if oid == cid or other.get("coordination") or other.get("state") != "DISPATCHED":
                continue
            peer = api._find_cell(dag, oid)
            if peer and (peer.get("conflict_class") == request["binding"]["conflict_class"] or
                         set(peer.get("resource_claims", [])) & set(request["binding"]["claims"])):
                blockers.append("active_control_claim:" + oid)
        request["blockers"] = blockers
        if not blockers:
            request["phase"] = "ADMITTED"
            record.update({"state": "DISPATCHED", "workspace_id": request["binding"]["workspace_id"],
                           "worker_identity": request["binding"]["worker_identity"],
                           "verifier_identity": request["binding"]["verifier_identity"]})
            state["frontier"]["dispatched"] = sorted(set(state["frontier"]["dispatched"]) | {cid})


def dispatch(scope: dict, args) -> int:
    api = SimpleNamespace(**scope)
    root = Path(args.root).resolve()
    if not api._doctor_or_fail(root):
        return 1
    dag, state = api._load_v16(root)
    record = state["cells"][args.cell]
    worker, verifier = str(args.worker_identity).strip(), str(args.verifier_identity).strip()
    if not worker or not verifier or worker == verifier:
        raise ValueError("dispatch requires distinct nonempty custody identities")
    _enqueue(api, root, dag, state, args, worker, verifier)
    _sweep(api, root, dag, state)
    api._save_state(root, state)
    print(json.dumps(_view(args.cell, record), indent=2))
    return 0


def _enqueue(api, root: Path, dag: dict, state: dict, args, worker: str, verifier: str) -> None:
    record = state["cells"][args.cell]
    bound = binding(api, root, dag, state, args.cell, str(args.workspace_id or ""), worker, verifier)
    request_id = str(getattr(args, "request_id", None) or f"{args.cell}:{record['attempt']}")
    if not request_id.strip() or len(request_id) > 256:
        raise ValueError("request identity must be nonempty and at most 256 characters")
    previous = record.get("coordination")
    if previous:
        if previous["request_id"] != request_id or previous["binding"] != bound:
            raise ValueError("request identity or authority differs; explicit reassessment required")
    else:
        if record.get("state") != "COMPILED":
            raise ValueError("new admission requires a COMPILED current attempt")
        all_requests = [rec["coordination"] for rec in state["cells"].values() if rec.get("coordination")]
        all_requests += state["coordination"]["history"]
        if any(req["request_id"] == request_id for req in all_requests):
            raise ValueError("request identity already belongs to another cell or generation")
        state["coordination"]["next_order"] += 1
        generations = [req["generation"] for req in all_requests if req["binding"]["cell"] == args.cell]
        record["coordination"] = {"request_id": request_id, "order": state["coordination"]["next_order"],
                                  "generation": max(generations, default=0) + 1, "token": str(uuid.uuid4()),
                                  "binding": bound, "binding_digest": digest(bound), "phase": "QUEUED",
                                  "blockers": [], "executor_identity": None, "stop_observation_ref": None,
                                  "stop_observation_sha256": None, "scope_proof_ref": None, "scope_proof_sha256": None}


def retry(scope: dict, root: Path, state: dict, cell_id: str) -> None:
    record = state["cells"][cell_id]
    request = record.get("coordination")
    if request:
        if request["phase"] != "RELEASED":
            raise ValueError("retry requires confirmed safe ownership release; result outcome is not writer liveness")
        state["coordination"]["history"].append(request)
        del record["coordination"]


def settlement(scope: dict, root: Path, state: dict, cell_id: str, result: dict, args) -> dict | None:
    api = SimpleNamespace(**scope)
    record = state["cells"][cell_id]
    request = record.get("coordination")
    if not request:
        return None
    _current(state, args)
    if request["executor_identity"] is None:
        raise ValueError("settlement requires the current generation's recorded launch intent")
    bound = request["binding"]
    dag, _ = api._load_v16(root)
    if binding(api, root, dag, state, cell_id, bound["workspace_id"], bound["worker_identity"], bound["verifier_identity"]) != bound:
        raise ValueError("settlement authority changed after admission")
    outcomes = result.get("target_outcomes", [])
    candidate = text(Path(bound["workspace"]["workspace_path"]), "rev-parse", "HEAD")
    if result.get("outcome") == "ACCEPTED":
        if len(outcomes) != 1 or outcomes[0].get("head_sha") != candidate:
            raise ValueError("accepted result differs from the exact live candidate")
    try:
        proof = snapshot(bound, candidate, bound["scope_base"], clean=result.get("outcome") == "ACCEPTED")
    except (ValueError, OSError) as exc:
        denial = {"binding": bound, "generation": request["generation"], "token": request["token"],
                  "result_digest": digest(result), "reason": str(exc)}
        api.write_immutable_json(root / f"evidence/{cell_id}/attempt-{record['attempt']:04d}/scope-denials/{digest(denial)}.json", denial)
        raise
    return {"schema": "flyby/mission-control-scope-proof/1", "generation": request["generation"],
            "token": request["token"], "binding": bound, "snapshot": proof}


def record_settlement(scope: dict, root: Path, state: dict, cell_id: str, proof: dict | None) -> None:
    if proof is None:
        return
    api = SimpleNamespace(**scope)
    record = state["cells"][cell_id]
    request = record["coordination"]
    previous = proof["snapshot"]
    current = snapshot(proof["binding"], previous["candidate"], previous["base"], clean=record["state"] == "ACCEPTED")
    if current != previous:
        raise ValueError("candidate or dirty state changed while settlement evidence was being recorded")
    ref = f"evidence/{cell_id}/attempt-{record['attempt']:04d}/scope_proof.json"
    api.write_immutable_json(root / ref, proof)
    request["scope_proof_ref"], request["scope_proof_sha256"] = ref, api.sha256(root / ref)


def _evidence_errors(api, root: Path, request: dict, label: str) -> list[str]:
    errors = []
    bound = request["binding"]
    for prefix in ("stop_observation", "scope_proof"):
        ref = request[prefix + "_ref"]
        checksum = request[prefix + "_sha256"]
        if ref is None:
            if checksum is not None:
                errors.append(f"{label}: {prefix} digest exists without evidence")
            continue
        path = api.resolve_ref(root, ref)
        if not path.is_file() or api.sha256(path) != checksum:
            errors.append(f"{label}: {prefix} evidence changed or disappeared")
            continue
        value = api.load_json(path)
        if prefix == "scope_proof":
            if (value.get("schema") != "flyby/mission-control-scope-proof/1" or value.get("binding") != bound
                    or value.get("generation") != request["generation"] or value.get("token") != request["token"]
                    or value.get("snapshot", {}).get("binding_digest") != request["binding_digest"]
                    or value.get("snapshot", {}).get("base") != bound["scope_base"]):
                errors.append(f"{label}: scope proof no longer identifies the admitted generation/base")
        else:
            expected = {"cell": bound["cell"], "attempt": bound["attempt"], "generation": request["generation"],
                        "token": request["token"], "executor_identity": request["executor_identity"],
                        "observer_identity": bound["verifier_identity"]}
            invalid = api.schema_errors(root, "contracts/schemas/FENCE_OBSERVATION_SCHEMA_V1.json", value)
            if invalid or any(value.get(key) != item for key, item in expected.items()):
                errors.append(f"{label}: fence observation no longer identifies exact independent custody")
                continue
            for item in value["evidence"]:
                source = api.resolve_ref(root, item["ref"])
                if not source.is_file() or api.sha256(source) != item["sha256"]:
                    errors.append(f"{label}: underlying fence evidence changed or disappeared: {item['ref']}")
    return errors


def issues(scope: dict, root: Path, state: dict, dag: dict) -> list[str]:
    api = SimpleNamespace(**scope)
    errors = []
    authority = state.get("coordination", {})
    if authority.get("authority_root") != str(root):
        errors.append("coordination mission was moved or copied; original authority root required")
    orders, tokens, requests = set(), set(), set()
    for request in authority.get("history", []):
        try:
            bound = request["binding"]
            if (request["phase"] not in {"QUEUED", "RELEASED"} or bound["instance_id"] != authority["instance_id"]
                    or bound["authority_root"] != str(root) or request["binding_digest"] != digest(bound)
                    or (request["executor_identity"] is not None and
                        (request["phase"] != "RELEASED" or not request["stop_observation_ref"]))):
                errors.append("historical coordination generation lacks safe-release custody")
            for field, seen in (("order", orders), ("token", tokens), ("request_id", requests)):
                if request[field] in seen:
                    errors.append(f"duplicate historical coordination {field}")
                seen.add(request[field])
            if request["order"] > authority["next_order"]:
                errors.append("historical coordination order exceeds durable sequence")
            errors.extend(_evidence_errors(api, root, request, "historical " + bound["cell"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"invalid historical coordination custody: {exc}")
    active = []
    for cell_id, record in state.get("cells", {}).items():
        request = record.get("coordination")
        cell = api._find_cell(dag, cell_id)
        if enabled(root) and cell and isinstance(cell.get("target"), dict) and record.get("state") == "DISPATCHED" and not request:
            errors.append(f"{cell_id}: target dispatch lacks an admission")
        if not request:
            continue
        try:
            bound = request["binding"]
            if (bound["instance_id"] != authority["instance_id"] or bound["authority_root"] != str(root)
                    or bound["cell"] != cell_id or bound["attempt"] != record["attempt"]
                    or bound["workcell_ref"] != record.get("workcell_ref")
                    or api.sha256(root / bound["workcell_ref"]) != bound["workcell_sha256"]
                    or request["binding_digest"] != digest(bound) or cell["target"] != bound["target"]
                    or cell.get("dependencies", []) != bound["dependencies"]
                    or sorted(cell.get("resource_claims", [])) != bound["claims"]
                    or cell["conflict_class"] != bound["conflict_class"]):
                errors.append(f"{cell_id}: admission no longer matches immutable attempt/scope/custody authority")
            for field, seen in (("order", orders), ("token", tokens), ("request_id", requests)):
                if request[field] in seen:
                    errors.append(f"{cell_id}: duplicate admission {field}")
                seen.add(request[field])
            if request["order"] > authority["next_order"]:
                errors.append(f"{cell_id}: admission order exceeds durable sequence")
            if request["phase"] == "QUEUED" and record["state"] != "COMPILED":
                errors.append(f"{cell_id}: queued declaration granted execution state")
            if request["phase"] not in {"QUEUED", "RELEASED"} and any(
                    record.get(key) != value for key, value in
                    (("workspace_id", bound["workspace_id"]), ("worker_identity", bound["worker_identity"]),
                     ("verifier_identity", bound["verifier_identity"]))):
                errors.append(f"{cell_id}: admission custody differs from current assignment")
            if request["phase"] not in {"QUEUED", "RELEASED"}:
                active.append((cell_id, request))
            if request["phase"] in {"STOP_CONFIRMED", "RELEASED"} and request["executor_identity"] is not None and not request["stop_observation_ref"]:
                errors.append(f"{cell_id}: ownership release lacks an independent fence observation")
            errors.extend(_evidence_errors(api, root, request, cell_id))
            if record.get("result_ref") and not request["scope_proof_ref"]:
                errors.append(f"{cell_id}: settled target lacks authoritative Git scope evidence")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{cell_id}: invalid coordination state: {exc}")
    for i, (cell_id, request) in enumerate(active):
        for peer_id, peer in active[i + 1:]:
            if conflict(request["binding"], peer["binding"]):
                errors.append(f"{cell_id}/{peer_id}: simultaneous conflicting exclusive admission")
    return errors


def _current(state: dict, args) -> tuple[dict, dict]:
    record = state["cells"].get(args.cell, {})
    request = record.get("coordination")
    if (not request or request["generation"] != args.generation or request["token"] != args.token):
        raise ValueError("stale generation/token does not identify the current admitted attempt")
    return record, request


def command(scope: dict, args) -> int:
    api = SimpleNamespace(**scope)
    root = Path(args.root).resolve()
    if not enabled(root):
        raise ValueError("frozen runtime lacks cell-coordination/v1; initialize a new capable mission")
    if not api._doctor_or_fail(root):
        return 1
    dag, state = api._load_v16(root)
    action = args.coordination_command
    if action in {"status", "recover"}:
        if action == "recover":
            _sweep(api, root, dag, state)
            api._save_state(root, state)
        print(json.dumps({"cells": [_view(cid, rec) for cid, rec in state["cells"].items() if rec.get("coordination")],
                          "provider_launch_performed": False, "termination_supported": False}, indent=2))
        return 0
    if action == "relinquish":
        entry = _entry(api, root, args.cell, args.workspace_id)
        live = _registration(api, root, state, entry)
        if any(rec.get("coordination", {}).get("phase") not in {None, "RELEASED"}
               and rec["coordination"]["binding"]["workspace"]["git_common_dir"] == live["git_common_dir"]
               for rec in state["cells"].values()):
            raise ValueError("repository authority still has queued or unreleased claims")
        with api.mission_control_lock(Path(live["git_common_dir"]), stable=True):
            marker = Path(live["git_common_dir"]) / REGISTRATION
            if api.load_json(marker).get("instance_id") != state["coordination"]["instance_id"]:
                raise ValueError("authority registration changed before relinquishment")
            marker.unlink()
        print(json.dumps({"state": "RELINQUISHED", "git_common_dir": live["git_common_dir"]}))
        return 0
    if action == "verify":
        record = state["cells"].get(args.cell, {})
        request = record.get("coordination")
        if record.get("state") != "ACCEPTED" or not request or request["phase"] not in {"STOP_CONFIRMED", "RELEASED"}:
            raise ValueError("publication requires accepted scope evidence and confirmed writer termination")
        proof = api.load_json(api.resolve_ref(root, request["scope_proof_ref"]))
        bound = binding(api, root, dag, state, args.cell, request["binding"]["workspace_id"],
                        record["worker_identity"], record["verifier_identity"])
        if bound != proof["binding"] or proof["token"] != request["token"] or proof["generation"] != request["generation"]:
            raise ValueError("publication scope/evidence no longer matches accepted custody")
        original = proof["snapshot"]
        if args.candidate != original["candidate"] or snapshot(bound, args.candidate, original["base"], clean=True) != original:
            raise ValueError("publication candidate changed after acceptance")
        snapshot(bound, args.candidate, args.publication_base, clean=True)
        print(json.dumps({"state": "VERIFIED", "candidate": args.candidate, "publication_base": args.publication_base}))
        return 0
    record, request = _current(state, args)
    phase = request["phase"]
    changed = False
    if action == "launching":
        if phase == "ADMITTED":
            if not args.executor_identity.strip():
                raise ValueError("launch intent requires an actual durable executor/session identity, not a PID")
            bound = request["binding"]
            snapshot(bound, bound["workspace"]["base_sha"], bound["workspace"]["base_sha"], clean=True, admission=True)
            request["executor_identity"] = args.executor_identity
            request["phase"] = "LAUNCH_UNCERTAIN"
            changed = True
        elif request["executor_identity"] != args.executor_identity:
            raise ValueError("launch identity differs from the recorded intent")
    elif action in {"running", "unknown", "stop"}:
        if phase not in {"LAUNCH_UNCERTAIN", "RUNNING", "UNKNOWN", "STOP_REQUESTED"}:
            raise ValueError("no launched execution is eligible for this observation")
        request["phase"] = {"running": "RUNNING", "unknown": "UNKNOWN", "stop": "STOP_REQUESTED"}[action]
    elif action == "confirm-stop":
        observation = api.load_json(Path(args.observation).resolve())
        for error in api.schema_errors(root, "contracts/schemas/FENCE_OBSERVATION_SCHEMA_V1.json", observation):
            raise ValueError("invalid fence observation: " + error)
        expected = {"cell": args.cell, "attempt": record["attempt"], "generation": request["generation"],
                    "token": request["token"], "executor_identity": request["executor_identity"],
                    "observer_identity": request["binding"]["verifier_identity"]}
        if phase in {"QUEUED", "ADMITTED"} or any(observation.get(key) != value for key, value in expected.items()):
            raise ValueError("fence observation does not identify the exact launched attempt and independent observer")
        for item in observation["evidence"]:
            path = api.resolve_ref(root, item["ref"])
            if not path.is_file() or api.sha256(path) != item["sha256"]:
                raise ValueError("operator fence evidence is missing or changed")
        ref = f"evidence/{args.cell}/attempt-{record['attempt']:04d}/fence-{request['generation']:04d}.json"
        api.write_immutable_json(root / ref, observation)
        request["stop_observation_ref"], request["stop_observation_sha256"] = ref, api.sha256(root / ref)
        if phase != "RELEASED":
            request["phase"] = "STOP_CONFIRMED"
    elif action == "release":
        if phase not in {"QUEUED", "ADMITTED", "STOP_CONFIRMED", "RELEASED"}:
            raise ValueError("writer liveness is unknown; cancellation/result/timeout cannot release ownership")
        if phase in {"QUEUED", "ADMITTED"}:
            # Under the capable protocol these states never authorize a writer.
            # Revoke their launch permission atomically with the claim release.
            record["state"] = "COMPILED"
            state["frontier"]["dispatched"] = sorted(set(state["frontier"]["dispatched"]) - {args.cell})
        request["phase"] = "RELEASED"
    elif action == "reassess":
        if phase not in {"QUEUED", "RELEASED"} or record.get("state") != "COMPILED":
            raise ValueError("reassessment requires an unlaunched COMPILED declaration and released custody")
        state["coordination"]["history"].append(request)
        del record["coordination"]
        args.worker_identity, args.verifier_identity = request["binding"]["worker_identity"], request["binding"]["verifier_identity"]
        args.workspace_id = request["binding"]["workspace_id"]
        args.request_id = args.request_id or f"{args.cell}:{record['attempt']}:reassess:{uuid.uuid4()}"
        _enqueue(api, root, dag, state, args, args.worker_identity, args.verifier_identity)
        _sweep(api, root, dag, state)
    else:
        raise ValueError("unsupported coordination transition")
    api._save_state(root, state)
    print(json.dumps({**_view(args.cell, record), "launch_authorized": changed}, indent=2))
    return 0


def add_parser(sub, handler) -> None:
    parser = sub.add_parser("coordination", help="Inspect and recover capable target-cell ownership")
    actions = parser.add_subparsers(dest="coordination_command", required=True)
    for action in ("status", "recover", "launching", "running", "unknown", "stop", "confirm-stop", "release", "reassess", "verify", "relinquish"):
        command = actions.add_parser(action)
        command.add_argument("--root", required=True)
        if action not in {"status", "recover"}:
            command.add_argument("--cell", required=True)
        if action not in {"status", "recover", "verify", "relinquish"}:
            command.add_argument("--generation", required=True, type=int)
            command.add_argument("--token", required=True)
        if action == "launching":
            command.add_argument("--executor-identity", required=True)
        if action == "confirm-stop":
            command.add_argument("--observation", required=True)
        if action == "reassess":
            command.add_argument("--request-id")
        if action == "relinquish":
            command.add_argument("--workspace-id", required=True)
        if action == "verify":
            command.add_argument("--candidate", required=True)
            command.add_argument("--publication-base", required=True)
        command.set_defaults(func=handler)
