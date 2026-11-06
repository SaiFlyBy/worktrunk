#!/usr/bin/env python3
"""Bridge Worktrunk worktrees to Mission Control v16.

Mission Control remains authoritative for workcell compilation, resource claims,
independent adjudication and closure. This adapter creates a worktree without
running hooks before registering its exact compiled base. It never cleans up a
worktree or changes history as a side effect.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


class BridgeError(Exception):
    pass


def child_environment(source: dict[str, str]) -> dict[str, str]:
    env = dict(source)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "WORKTRUNK_DIRECTIVE_CD_FILE"):
        env.pop(key, None)
    return env


def run(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, cwd=cwd, env=child_environment(os.environ) if env is None else env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
    except OSError as exc:
        raise BridgeError(f"Cannot start {argv[0]}: {exc}") from exc


def require_success(proc: subprocess.CompletedProcess[str], action: str) -> str:
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise BridgeError(f"{action} failed (exit {proc.returncode}): {detail}")
    return proc.stdout


def git(repo: Path, *args: str) -> str:
    return require_success(run(["git", "-C", str(repo), *args]), "Git " + args[0]).strip()


def read_json(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            raw = stream.read(8_000_001)
        if len(raw) > 8_000_000:
            raise BridgeError(f"Mission artifact exceeds the 8 MB projection limit: {path}")
        value = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise BridgeError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BridgeError(f"Expected an object in {path}")
    return value


def safe_ref(root: Path, ref: str) -> Path:
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute():
        raise BridgeError("Invalid mission artifact reference")
    result = (root / ref).resolve()
    if not result.is_relative_to(root):
        raise BridgeError("Mission artifact reference escapes the mission")
    return result


def mc(root: Path, *args: str) -> str:
    runtime = root / "runtime" / "tools" / "mc.py"
    if not runtime.is_file():
        raise BridgeError(f"Mission runtime is missing: {runtime}")
    return require_success(run([sys.executable, str(runtime), *args, "--root", str(root)]),
                           "Mission Control " + " ".join(args[:2]))



# This child process imports the mission's own sealed runtime in isolation.
# Its lock gives one coherent observation; it does not reserve a queue claim or
# authenticate an external provider. The actual settlement remains mc's job.
_SETTLEMENT_SNAPSHOT = r'''
import importlib.util
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
cell = sys.argv[2]
attempt = int(sys.argv[3])
inputs = [Path(value) for value in sys.argv[4:7]]
generation, token = sys.argv[7:9]
lineage_input = sys.argv[9] if len(sys.argv) > 9 else ""
binding_digest = sys.argv[10] if len(sys.argv) > 10 else ""
runtime = root / "runtime" / "tools" / "mc.py"
sys.path.insert(0, str(runtime.parent))
spec = importlib.util.spec_from_file_location("_frozen_mission_runtime", runtime)
if spec is None or spec.loader is None:
    raise RuntimeError("Frozen Mission Control runtime cannot be loaded")
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)
required = ("mission_control_lock", "_doctor_or_fail", "_load_v16",
            "resolve_ref", "sha256", "load_json")
missing = [name for name in required if not callable(getattr(mc, name, None))]
if missing:
    print("unsupported frozen mission runtime: missing " + ", ".join(missing), file=sys.stderr)
    sys.exit(2)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

with mc.mission_control_lock(root):
    if not mc._doctor_or_fail(root):
        raise RuntimeError("Mission Control cannot validate recorded evidence")
    _, state = mc._load_v16(root)
    record = state.get("cells", {}).get(cell)
    if not isinstance(record, dict) or record.get("attempt") != attempt:
        raise RuntimeError("Settlement attempt is stale or missing")
    if record.get("state") not in {"ACCEPTED", "REJECTED", "FAILED", "BLOCKED", "CANDIDATE"}:
        raise RuntimeError("Settlement has not been recorded")
    coordination = record.get("coordination")
    if coordination and (str(coordination.get("generation")) != generation or coordination.get("token") != token):
        raise RuntimeError("Settlement generation is stale or missing")
    reservation = record.get("execution_reservation")
    if reservation and reservation.get("binding_digest") != binding_digest:
        raise RuntimeError("Settlement reservation binding digest is stale or missing")
    history = [item for item in record.get("attempt_history", [])
               if isinstance(item, dict) and item.get("attempt") == attempt]
    if len(history) != 1 or history[0].get("state") != record["state"]:
        raise RuntimeError("Settlement history is missing or ambiguous")
    item = history[0]
    for identity in ("worker_identity", "verifier_identity"):
        if not record.get(identity) or record.get(identity) != item.get(identity):
            raise RuntimeError("Settlement custody differs from attempt history")
    for prefix, supplied in zip(("result", "context_receipt", "adjudication"), inputs):
        ref, digest = record.get(prefix + "_ref"), record.get(prefix + "_sha256")
        if (not isinstance(ref, str) or not isinstance(digest, str)
                or item.get(prefix + "_ref") != ref or item.get(prefix + "_sha256") != digest):
            raise RuntimeError("Settlement evidence differs from attempt history")
        recorded = mc.resolve_ref(root, ref)
        if (mc.sha256(recorded) != digest
                or canonical(mc.load_json(recorded)) != canonical(mc.load_json(supplied))):
            raise RuntimeError("Settlement evidence is different or has changed")
    if lineage_input or record.get("lineage_review_ref"):
        if not lineage_input or not callable(getattr(mc, "load_lineage_review", None)):
            raise RuntimeError("Settlement requires its exact lineage review and capable frozen runtime")
        ref, digest = record.get("lineage_review_ref"), record.get("lineage_review_sha256")
        if not ref or not digest or item.get("lineage_review_ref") != ref or item.get("lineage_review_sha256") != digest:
            raise RuntimeError("Settlement lineage review differs from attempt history")
        recorded = mc.resolve_ref(root, ref)
        if (mc.sha256(recorded) != digest
                or canonical(mc.load_lineage_review(recorded)) != canonical(mc.load_lineage_review(Path(lineage_input)))):
            raise RuntimeError("Settlement lineage review is different or has changed")
    print(json.dumps({
        "state": record["state"], "cell": cell, "attempt": attempt,
        "result_ref": record["result_ref"],
        "context_receipt_ref": record["context_receipt_ref"],
        "adjudication_ref": record["adjudication_ref"],
        "reconciled": True,
    }))
'''


def settle_reconciled(args: argparse.Namespace) -> dict:
    """Submit once and reconcile an identical recorded attempt after an uncertain reply.

    The snapshot is an observation under the frozen Mission Control lock, not
    authority to complete an ADE task or launch another provider.
    """
    root = Path(args.root).resolve()
    if not re.fullmatch(r"[1-9][0-9]*", str(args.attempt)):
        raise BridgeError("Settlement attempt must be a positive integer")
    runtime = root / "runtime" / "tools" / "mc.py"
    if not runtime.is_file():
        raise BridgeError(f"Mission runtime is missing: {runtime}")
    values = [read_json(Path(value).resolve()) for value in
              (args.result, args.context_receipt, args.adjudication)]
    # Keep each submitted object stable even if the caller edits its source file
    # while the mission runtime is validating and recording the evidence.
    with tempfile.TemporaryDirectory(prefix="wt-mission-settle-") as temp:
        paths = [Path(temp) / name for name in ("result.json", "receipt.json", "adjudication.json")]
        for path, value in zip(paths, values):
            path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        fence = (["--generation", str(args.generation), "--token", args.token]
                 if args.generation is not None and args.token is not None else [])
        lineage_path = None
        if getattr(args, "lineage_review", None):
            lineage_path = Path(temp) / "lineage-review.json"
            # Keep the submitted review bytes stable; the frozen runtime owns
            # strict parsing and the candidate/source binding checks.
            lineage_path.write_bytes(Path(args.lineage_review).resolve().read_bytes())
        lineage = ["--lineage-review", str(lineage_path)] if lineage_path else []
        binding = ["--binding-digest", args.binding_digest] if getattr(args, "binding_digest", None) else []
        proc = run([sys.executable, str(runtime), "settle", "--root", str(root),
                    "--cell", args.cell, "--attempt", str(args.attempt),
                    "--result", str(paths[0]), "--context-receipt", str(paths[1]),
                    "--adjudication", str(paths[2]), *fence, *lineage, *binding])
        if proc.returncode == 0:
            try:
                result = json.loads(proc.stdout)
            except ValueError as exc:
                raise BridgeError("Settlement succeeded but its response was unreadable; reconcile before continuing") from exc
            if (not isinstance(result, dict) or result.get("cell") != args.cell
                    or result.get("state") not in {"ACCEPTED", "REJECTED", "FAILED", "BLOCKED", "CANDIDATE"}):
                raise BridgeError("Settlement response did not identify the expected cell; reconcile before continuing")
            result["attempt"] = int(args.attempt)
            result["reconciled"] = False
            return result
        snapshot = run([sys.executable, "-I", "-c", _SETTLEMENT_SNAPSHOT,
                        str(root), args.cell, str(args.attempt), *map(str, paths), str(args.generation or ""), str(args.token or ""),
                        str(lineage_path or ""), str(getattr(args, "binding_digest", None) or "")])
        if snapshot.returncode:
            detail = (proc.stderr or proc.stdout).strip()
            check = (snapshot.stderr or snapshot.stdout).strip()
            reason = check.splitlines()[-1][:500] if check else ""
            raise BridgeError("Settlement did not succeed and identical current evidence could not be reconciled"
                              + (f": {detail}" if detail else "")
                              + (f"; reconciliation check: {reason}" if reason else ""))
        try:
            result = json.loads(snapshot.stdout)
        except ValueError as exc:
            raise BridgeError("Settlement reconciliation returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise BridgeError("Settlement reconciliation returned an invalid result")
        return result


def cell_info(root: Path, cell_id: str) -> tuple[dict, dict, dict]:
    mc(root, "doctor")
    dag = read_json(root / "control" / "EXECUTION_DAG.json")
    state = read_json(root / "control" / "EXECUTION_STATE.json")
    matches = [item for item in dag.get("cells", []) if isinstance(item, dict)
               and item.get("cell_id") == cell_id]
    record = state.get("cells", {}).get(cell_id)
    if len(matches) != 1 or not isinstance(record, dict):
        raise BridgeError(f"Unknown or ambiguous cell: {cell_id}")
    packet = read_json(safe_ref(root, record.get("workcell_ref")))
    if packet.get("cell_id") != cell_id or packet.get("target") != matches[0].get("target"):
        raise BridgeError("Compiled workcell and execution DAG disagree")
    return matches[0], record, packet


def origin_matches(origin: str, repository: str) -> bool:
    if "://" in origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
            return False
        path = parsed.path
    elif ":" in origin and not re.match(r"^[A-Za-z]:", origin):
        _, path = origin.split(":", 1)
    else:
        return False
    normalized = path.strip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.casefold() == repository.strip("/").casefold()


def ledger_entry(root: Path, cell_id: str) -> dict:
    ledger = read_json(root / "control" / "WORKSPACE_LEDGER.json")
    entries = [item for item in ledger.get("entries", []) if isinstance(item, dict)
               and item.get("kind") == "TARGET" and item.get("registered_cell") == cell_id]
    if len(entries) != 1 or not entries[0].get("worktree_path"):
        raise BridgeError(f"Cell {cell_id} needs exactly one registered live workspace")
    return entries[0]


def prepare(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    if ((args.worker or args.verifier)
            and "contracts/capabilities/execution-reservation-v1.json" in read_json(root / "TEMPLATE_LOCK.json").get("assets", {})):
        raise BridgeError("For an execution-reservation mission, prepare without worker/verifier flags, then use execution reserve with the exact binding and launch intent")
    repo = Path(args.repo).resolve()
    cell, record, packet = cell_info(root, args.cell)
    target = packet.get("target")
    if record.get("state") != "COMPILED" or not isinstance(target, dict):
        raise BridgeError("Prepare requires a COMPILED target-bearing cell")
    repository, base = target.get("repository"), str(target.get("base_sha", "")).lower()
    if not isinstance(repository, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
        raise BridgeError("Compiled target repository or base is invalid")
    if not args.workspace_id.strip() or not args.branch.strip() or args.branch.startswith("-"):
        raise BridgeError("Workspace ID and branch must be non-empty")
    if bool(args.worker) != bool(args.verifier) or (args.worker and
            (not args.worker.strip() or not args.verifier.strip() or args.worker.strip() == args.verifier.strip())):
        raise BridgeError("Supply distinct worker and verifier identities together")
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise BridgeError("--repo must identify the Git worktree root")
    origin = git(repo, "remote", "get-url", "origin")
    if args.expected_origin:
        if origin != args.expected_origin:
            raise BridgeError("Origin does not match --expected-origin")
    elif not origin_matches(origin, repository):
        raise BridgeError("Origin does not identify the compiled repository; supply --expected-origin only after verifying it")
    if git(repo, "rev-parse", f"{base}^{{commit}}").lower() != base:
        raise BridgeError("Compiled base is not an exact local commit")
    ledger = read_json(root / "control" / "WORKSPACE_LEDGER.json")
    if any(item.get("workspace_id") == args.workspace_id or
           (item.get("kind") == "TARGET" and item.get("repository") == repository
            and item.get("branch") == args.branch)
           for item in ledger.get("entries", []) if isinstance(item, dict)):
        raise BridgeError("Workspace ID or repository branch is already registered")
    if args.path and Path(args.path).exists():
        raise BridgeError("Requested worktree path already exists")

    command = [args.wt, "switch", args.branch, "--create", "--base", base,
               "--no-hooks", "--no-cd", "--format=json"]
    if args.path:
        command += ["--path", str(Path(args.path).resolve())]
    env = child_environment(os.environ)
    for key in list(env):
        if key == "GIT_CONFIG_PARAMETERS" or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            env.pop(key, None)
    # Git's own post-checkout hook can mutate a fresh worktree, independently
    # of Worktrunk hooks. Override only this child process's hook path.
    with tempfile.TemporaryDirectory(prefix="wt-mission-no-hooks-") as empty_hooks:
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                    "GIT_CONFIG_VALUE_0": empty_hooks})
        proc = run(command, cwd=repo, env=env)
    if proc.returncode:
        raise BridgeError("Worktrunk switch failed; any created worktree was preserved. "
                          + (proc.stderr or proc.stdout).strip())
    try:
        result = json.loads(proc.stdout)
    except ValueError as exc:
        raise BridgeError("Worktrunk returned invalid JSON; any created worktree was preserved") from exc
    if result.get("action") != "created" or result.get("created_branch") is not True:
        raise BridgeError("Worktrunk did not report a newly created branch; workspace preserved")
    workspace = Path(result["path"]).resolve()
    try:
        mc(root, "workspace", "register", "--cell", args.cell, "--workspace-id",
           args.workspace_id, "--branch", args.branch, "--path", str(workspace))
    except BridgeError as exc:
        raise BridgeError(f"{exc}; created workspace was preserved at {workspace}") from exc
    output = {"state": "WORKSPACE_REGISTERED", "cell": args.cell,
              "workspace_id": args.workspace_id, "branch": args.branch,
              "path": str(workspace), "base_sha": base}
    if args.worker:
        try:
            assignment = json.loads(mc(root, "dispatch", "--cell", args.cell, "--workspace-id", args.workspace_id,
               "--worker-identity", args.worker, "--verifier-identity", args.verifier))
        except BridgeError as exc:
            raise BridgeError(f"{exc}; registered workspace was preserved at {workspace}") from exc
        output["state"] = assignment["state"]
        if "phase" in assignment:
            output["coordination"] = assignment
    print(json.dumps(output, indent=2))


def scope_report(root: Path, cell_id: str) -> dict:
    cell, record, packet = cell_info(root, cell_id)
    report = {
        "cell": cell_id, "state": record.get("state"),
        "kind": packet.get("kind"), "target": packet.get("target"),
        "requirements": packet.get("requirement_ids", []),
        "dependencies": packet.get("dependencies", []),
        "conflict_class": packet.get("conflict_class"),
        "resource_claims": packet.get("resource_claims", []),
        "acceptance": packet.get("acceptance", []),
        "positive_verification": packet.get("positive_verification", []),
        "negative_verification": packet.get("negative_verification", []),
        "workcell_ref": record.get("workcell_ref"),
        "workcell_sha256": hashlib.sha256(safe_ref(root, record["workcell_ref"]).read_bytes()).hexdigest(),
        "attempt": record.get("attempt"),
        "coordination": record.get("coordination"),
        "execution_reservation": reservation_selector(record),
        "worker_identity": record.get("worker_identity"),
        "verifier_identity": record.get("verifier_identity"),
        "note": "Read-only projection of Mission Control records; not an additional decision or proof of unrecorded checks.",
    }
    for key in ("result_ref", "result_sha256", "context_receipt_ref", "context_receipt_sha256",
                "adjudication_ref", "adjudication_sha256", "lineage_review_ref", "lineage_review_sha256"):
        if record.get(key):
            report[key] = record[key]
    if record.get("result_ref"):
        report["result"] = read_json(safe_ref(root, record["result_ref"]))
    if record.get("adjudication_ref"):
        report["adjudication"] = read_json(safe_ref(root, record["adjudication_ref"]))
    if record.get("workspace_id"):
        entry = ledger_entry(root, cell_id)
        path = Path(entry["worktree_path"]).resolve()
        if Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path:
            raise BridgeError("Registered path is no longer the Git worktree root")
        report["workspace"] = {
            "id": entry["workspace_id"], "path": str(path),
            "branch": git(path, "branch", "--show-current"),
            "head_sha": git(path, "rev-parse", "HEAD").lower(),
            "clean": not bool(git(path, "status", "--porcelain=v1", "--untracked-files=all")),
            "origin": git(path, "remote", "get-url", "origin"),
        }
    return report


def remote_head(repo: Path, ref: str) -> str | None:
    text = git(repo, "ls-remote", "--refs", "origin", ref)
    rows = [line.split() for line in text.splitlines() if line.strip()]
    if not rows:
        return None
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref or not re.fullmatch(r"[0-9a-fA-F]{40}", rows[0][0]):
        raise BridgeError(f"Unexpected remote response for {ref}")
    return rows[0][0].lower()


def github_origin(origin: str, repository: str) -> bool:
    # A GitHub repository identity has exactly two literal path components.
    # Reject encoded or path-normalizing forms before comparing destinations.
    if not isinstance(repository, str):
        return False
    parts = repository.split("/")
    if (len(parts) != 2 or any(part in {"", ".", ".."} or
            any(ch in "\\%?#" or ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in part)
            for part in parts)):
        return False
    try:
        if origin.startswith(("https://", "ssh://")):
            parsed = urlsplit(origin)
            if parsed.query or parsed.fragment:
                return False
            host = parsed.hostname
        elif ":" in origin and not re.match(r"^[A-Za-z]:", origin):
            host = origin.split(":", 1)[0].rsplit("@", 1)[-1]
        else:
            return False
        return bool(host and host.casefold() == "github.com" and origin_matches(origin, repository))
    except ValueError:
        return False


HANDOFF_MARKER = "\nWORKTRUNK_HANDOFF_V1="
HANDOFF_ACCEPTANCE = [
    "Incorporate the accepted source head and the observed base without rewriting either; independently verify their combination and resolve conflicts.",
    "Reassess each reused evidence item against the candidate, base, inputs, dependencies, test selection and toolchain; rerun affected or unknown checks or explicitly account for them.",
]


def changed_paths(repo: Path, old: str, new: str) -> list[str]:
    # A bounded projection of the changed paths is advisory context, not proof
    # that other test premises are unchanged. Keep stderr out of the pipe so a
    # noisy Git process cannot block while stdout is being bounded.
    argv = ["git", "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", old, new, "--"]
    try:
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errors,
                                    env=child_environment(os.environ))
            assert proc.stdout is not None
            data = proc.stdout.read(1_000_001)
            proc.stdout.close()
            if len(data) > 1_000_000:
                proc.kill()
                proc.wait()
                raise BridgeError("Base change list exceeds the 1 MB handoff limit")
            code = proc.wait()
            if code:
                errors.seek(0)
                detail = errors.read(4096).decode("utf-8", errors="replace")
                raise BridgeError(f"Git diff failed (exit {code}): {detail.strip()}")
    except OSError as exc:
        raise BridgeError(f"Cannot inspect base changes: {exc}") from exc
    try:
        paths = data.decode("utf-8").split("\0")
    except UnicodeError as exc:
        raise BridgeError("Base changes contain paths that cannot be represented as UTF-8") from exc
    if paths and paths[-1] == "":
        paths.pop()
    return paths



def _dependency_ancestor(repo: Path, older: str, newer: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{40}", older) or not re.fullmatch(r"[0-9a-f]{40}", newer):
        raise BridgeError("Dependency ancestry requires exact commit IDs")
    proc = run(["git", "--no-replace-objects", "-C", str(repo), "merge-base", "--is-ancestor", older, newer])
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise BridgeError(f"Cannot determine dependency ancestry (Git exit {proc.returncode}); fetch and reconcile")


def _accepted_dependency(root: Path, cell: dict, record: dict) -> tuple[str, dict]:
    cell_id = str(cell.get("cell_id", ""))
    target = cell.get("target")
    if record.get("state") != "ACCEPTED" or not isinstance(target, dict):
        raise BridgeError(f"Dependency {cell_id} is not an independently accepted target")
    evidence = {}
    values = {}
    for kind in ("result", "context_receipt", "adjudication", *(
            ["lineage_review"] if record.get("lineage_review_ref") or record.get("lineage_review_sha256") else [])):
        ref, digest = record.get(kind + "_ref"), record.get(kind + "_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BridgeError(f"Dependency {cell_id} has no valid {kind} digest")
        try:
            path = safe_ref(root, ref)
            with path.open("rb") as stream:
                raw = stream.read(8_000_001)
            if len(raw) > 8_000_000:
                raise BridgeError("Dependency evidence exceeds the 8 MB limit")
            if hashlib.sha256(raw).hexdigest() != digest:
                raise BridgeError("Dependency evidence digest changed")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise BridgeError("Dependency evidence is not an object")
            values[kind] = value
        except (OSError, ValueError, UnicodeError, BridgeError) as exc:
            raise BridgeError(f"Cannot validate dependency {cell_id} {kind} evidence") from exc
        evidence[kind] = {"ref": ref, "sha256": digest}
    if values["adjudication"].get("decision") != "ACCEPTED":
        raise BridgeError(f"Dependency {cell_id} lacks an accepted adjudication")
    outcomes = values["result"].get("target_outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 1 or not isinstance(outcomes[0], dict):
        raise BridgeError(f"Dependency {cell_id} lacks one accepted target outcome")
    outcome = outcomes[0]
    head, base = str(outcome.get("head_sha", "")).lower(), str(target.get("base_sha", "")).lower()
    if (outcome.get("repository") != target.get("repository") or outcome.get("baseline_sha") != base
            or not re.fullmatch(r"[0-9a-f]{40}", head)):
        raise BridgeError(f"Dependency {cell_id} outcome does not bind its target")
    return head, evidence


def _dependency_custody(root: Path, cell_id: str, record: dict) -> dict:
    request = record.get("coordination")
    if request is None:
        lock = root / "TEMPLATE_LOCK.json"
        if ((root / "contracts/capabilities/cell-coordination-v1.json").exists()
                or lock.is_file() and "contracts/capabilities/cell-coordination-v1.json" in read_json(lock).get("assets", {})):
            raise BridgeError(f"Dependency {cell_id} is missing required coordinated writer custody")
        return {}
    if (not isinstance(request, dict) or request.get("phase") != "RELEASED"
            or type(request.get("generation")) is not int or request["generation"] < 1
            or not isinstance(request.get("token"), str) or not request["token"]):
        raise BridgeError(f"Dependency {cell_id} retains writer ownership; confirm and release its exact generation")
    evidence = {}
    for kind in ("scope_proof", *(["stop_observation"] if request.get("executor_identity") else [])):
        ref, digest = request.get(kind + "_ref"), request.get(kind + "_sha256")
        try:
            actual = hashlib.sha256(safe_ref(root, ref).read_bytes()).hexdigest()
        except (OSError, BridgeError) as exc:
            raise BridgeError(f"Dependency {cell_id} {kind} evidence is missing or changed") from exc
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or actual != digest:
            raise BridgeError(f"Dependency {cell_id} {kind} evidence is missing or changed")
        evidence[kind] = {"ref": ref, "sha256": digest}
    return {"generation": request["generation"], "token": request["token"],
            "binding_digest": request.get("binding_digest"), "phase": request["phase"], "evidence": evidence}


def reservation_selector(record: dict) -> dict | None:
    reservation = record.get("execution_reservation")
    if not isinstance(reservation, dict):
        return None
    return {"reservation_id": reservation.get("token"), "fence": reservation.get("generation"),
            "binding_digest": reservation.get("binding_digest"), "launch_intent_id": reservation.get("launch_intent_id")}


def _handoff_lineage(root: Path, cells: dict[str, dict], records: dict, current: str,
                     repo: Path, candidate: str, observed_base: str) -> set[str]:
    """Recognize only a fully evidence-bound, structurally consistent continuation."""
    lineage: set[str] = set()
    visited: set[str] = set()
    while current not in visited:
        visited.add(current)
        child = cells[current]
        objective = child.get("objective")
        if not isinstance(objective, str) or HANDOFF_MARKER not in objective:
            break
        prefix, encoded = objective.split(HANDOFF_MARKER, 1)
        try:
            payload = json.loads(encoded)
        except ValueError:
            break
        if not isinstance(payload, dict):
            break
        predecessor = payload.get("source_cell")
        if not isinstance(predecessor, str) or predecessor not in cells or predecessor == current:
            break
        parent = cells[predecessor]
        record = records.get(predecessor)
        if not isinstance(record, dict) or parent.get("kind") != "MUTATION":
            break
        head, evidence = _accepted_dependency(root, parent, record)
        custody = _dependency_custody(root, predecessor, record)
        if reservation_selector(record) is not None and payload.get("execution_reservation") != reservation_selector(record):
            break
        target = parent.get("target")
        preserved = set(parent) | set(child)
        preserved -= {"cell_id", "dependencies", "objective", "acceptance"}
        expected_deps = list(dict.fromkeys([*parent.get("dependencies", []), predecessor]))
        expected_acceptance = list(dict.fromkeys([*parent.get("acceptance", []), *HANDOFF_ACCEPTANCE]))
        old_objective = str(parent.get("objective", "")).split(HANDOFF_MARKER, 1)[0]
        prior_base = str(payload.get("observed_base", "")).lower()
        if (any(json.dumps(parent.get(key), sort_keys=True, ensure_ascii=False)
                != json.dumps(child.get(key), sort_keys=True, ensure_ascii=False) for key in preserved)
                or child.get("dependencies") != expected_deps
                or child.get("acceptance") != expected_acceptance or prefix != old_objective
                or type(payload.get("source_attempt")) is not int
                or type(record.get("attempt")) is not int
                or payload.get("source_attempt") != record.get("attempt")
                or payload.get("source_head") != head
                or payload.get("repository") != target.get("repository")
                or payload.get("compiled_base") != str(target.get("base_sha", "")).lower()
                or payload.get("accepted_evidence") != evidence
                or not re.fullmatch(r"[0-9a-f]{40}", prior_base)):
            break
        if (not _dependency_ancestor(repo, head, candidate)
                or not _dependency_ancestor(repo, prior_base, observed_base)
                or not _dependency_ancestor(repo, prior_base, candidate)):
            break
        if custody:
            request = record["coordination"]
            expected_observation = {
                "schema": "flyby/mission-control-accepted-base-observation/1",
                "ref": "refs/heads/main", "sha": prior_base,
                "origin": request["binding"]["workspace"]["origin"],
                "source_scope_proof_sha256": request["scope_proof_sha256"],
                "source_generation": request["generation"], "source_token": request["token"],
            }
            if payload.get("scope_base_observation") != expected_observation:
                break
        merge_base = git(repo, "merge-base", head, prior_base).lower()
        if (payload.get("merge_base") != merge_base
                or payload.get("base_changed_paths") != changed_paths(repo, merge_base, prior_base)):
            break
        lineage.add(predecessor)
        current = predecessor
    return lineage


def _merged_dependency_pr(repo: Path, gh: str, repository: str, branch: str,
                          cell_id: str, head: str, observed_base: str, number: str) -> dict:
    proc = run([gh, "pr", "view", number, "--repo", repository, "--json",
                "number,url,state,mergedAt,headRefOid,baseRefName,mergeCommit"], cwd=repo)
    try:
        value = json.loads(require_success(proc, f"Dependency {cell_id} PR lookup"))
    except ValueError as exc:
        raise BridgeError(f"Dependency {cell_id} PR lookup returned invalid JSON") from exc
    merge = value.get("mergeCommit") if isinstance(value, dict) else None
    merge_sha = str(merge.get("oid", "")).lower() if isinstance(merge, dict) else ""
    expected_url = f"https://github.com/{repository}/pull/{number}"
    if (not isinstance(value, dict) or type(value.get("number")) is not int
            or value.get("number") != int(number)
            or str(value.get("url", "")).casefold() != expected_url.casefold()
            or value.get("state") != "MERGED" or not isinstance(value.get("mergedAt"), str)
            or not value["mergedAt"].strip() or value.get("baseRefName") != branch
            or str(value.get("headRefOid", "")).lower() != head
            or not re.fullmatch(r"[0-9a-f]{40}", merge_sha)
            or not _dependency_ancestor(repo, merge_sha, observed_base)):
        raise BridgeError(f"Dependency {cell_id} PR does not establish delivery into the observed base")
    return {"cell": cell_id, "state": "MERGED_PR", "head_sha": head,
            "evidence_kind": "OPERATOR_SELECTED_PR_AND_CURRENT_FORGE_OBSERVATION",
            "pr": expected_url, "merge_sha": merge_sha, "merged_at": value["mergedAt"]}


def _repository_key(value: object) -> str:
    if not isinstance(value, str) or not github_origin("https://github.com/" + value, value):
        raise BridgeError("Dependency repository is not an unambiguous GitHub identity")
    return value.casefold()


def check_dependency_delivery(root: Path, cell_id: str, repo: Path, repository: str,
                              candidate: str, observed_base: str, branch: str, gh: str,
                              dependency_prs: dict[str, str]) -> list[dict]:
    """Check same-repository mutation ancestors against the exact publication base.

    A GitHub merged-PR result is a current delivery-history observation, not a
    proof of CI success, merge-time head immutability, or unchanged behavior.
    """
    root, repo = root.resolve(), repo.resolve()
    dag = read_json(root / "control" / "EXECUTION_DAG.json")
    state = read_json(root / "control" / "EXECUTION_STATE.json")
    items = dag.get("cells")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise BridgeError("Mission dependency DAG is invalid")
    cells = {item.get("cell_id"): item for item in items if isinstance(item.get("cell_id"), str)}
    if len(cells) != len(items) or cell_id not in cells:
        raise BridgeError("Mission dependency DAG has missing or ambiguous cells")
    records = state.get("cells")
    if not isinstance(records, dict):
        raise BridgeError("Mission dependency state is invalid")
    lineage = _handoff_lineage(root, cells, records, cell_id, repo, candidate, observed_base)
    pending = list(cells[cell_id].get("dependencies", []))
    visited: set[str] = set()
    used_prs: set[str] = set()
    observations = []
    while pending:
        dependency = pending.pop()
        if not isinstance(dependency, str) or dependency not in cells:
            raise BridgeError("Mission dependency is missing from the DAG")
        if dependency in visited:
            continue
        visited.add(dependency)
        descriptor = cells[dependency]
        deps = descriptor.get("dependencies", [])
        if not isinstance(deps, list):
            raise BridgeError(f"Dependency {dependency} has invalid predecessors")
        pending.extend(deps)
        if descriptor.get("kind") != "MUTATION":
            continue
        target = descriptor.get("target")
        if not isinstance(target, dict):
            raise BridgeError(f"Dependency {dependency} has no target")
        if _repository_key(target.get("repository")) != _repository_key(repository):
            observations.append({"cell": dependency, "state": "OTHER_REPOSITORY_UNASSESSED",
                                 "repository": target.get("repository")})
            continue
        record = records.get(dependency)
        if not isinstance(record, dict):
            raise BridgeError(f"Dependency {dependency} has no authoritative state")
        head, evidence = _accepted_dependency(root, descriptor, record)
        attempt = record.get("attempt")
        if type(attempt) is not int or attempt < 1:
            raise BridgeError(f"Dependency {dependency} has no valid attempt identity")
        identity = {"attempt": attempt, "evidence": evidence}
        custody = _dependency_custody(root, dependency, record)
        if custody:
            identity["coordination"] = custody
        if reservation_selector(record) is not None:
            identity["execution_reservation"] = reservation_selector(record)
        if dependency in lineage:
            observations.append({"cell": dependency, "state": "SAME_SCOPE_HANDOFF",
                                 "head_sha": head, **identity})
        elif dependency in dependency_prs:
            observation = _merged_dependency_pr(repo, gh, repository, branch, dependency,
                                                head, observed_base, dependency_prs[dependency])
            observations.append({**observation, **identity})
            used_prs.add(dependency)
        elif _dependency_ancestor(repo, head, observed_base):
            observations.append({"cell": dependency, "state": "IN_BASE", "head_sha": head, **identity})
        else:
            raise BridgeError(f"Dependency {dependency} is not established in the selected PR base; land it first or supply its merged PR")
    if set(dependency_prs) != used_prs:
        raise BridgeError("Dependency PR mappings must identify distinct same-repository mutation dependencies")
    return sorted(observations, key=lambda item: item["cell"])


def parse_dependency_prs(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        match = re.fullmatch(r"([A-Z][A-Z0-9_-]{0,63})=([1-9][0-9]*)", value)
        if not match or match.group(1) in result:
            raise BridgeError("Use each dependency PR once as CELL=NUMBER")
        result[match.group(1)] = match.group(2)
    return result


def handoff(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    if any(not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,63}", value)
           for value in (args.cell, args.successor, args.frontier)):
        raise BridgeError("Cell and frontier IDs must be uppercase control IDs")
    if args.cell == args.successor or not re.fullmatch(r"[0-9a-fA-F]{40}", args.base_sha):
        raise BridgeError("A distinct successor and an exact 40-digit base SHA are required")
    old_cell, record, packet = cell_info(root, args.cell)
    report = scope_report(root, args.cell)
    if record.get("state") != "ACCEPTED" or packet.get("kind") != "MUTATION":
        raise BridgeError("Handoff requires an independently accepted mutation")
    target, result, workspace = report.get("target"), report.get("result"), report.get("workspace")
    if not all(isinstance(value, dict) for value in (target, result, workspace)):
        raise BridgeError("Accepted target, result or workspace is missing")
    outcomes = result.get("target_outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 1 or not isinstance(outcomes[0], dict):
        raise BridgeError("Accepted mutation must have one target outcome")
    outcome = outcomes[0]
    baseline = str(target.get("base_sha", "")).lower()
    source = str(outcome.get("head_sha", "")).lower()
    observed = args.base_sha.lower()
    repository = target.get("repository")
    if (outcome.get("repository") != repository or outcome.get("baseline_sha") != baseline
            or not re.fullmatch(r"[0-9a-f]{40}", source)):
        raise BridgeError("Accepted outcome does not bind the compiled target")
    entry = ledger_entry(root, args.cell)
    if (not workspace.get("clean") or workspace.get("head_sha") != source
            or workspace.get("branch") != entry.get("branch")
            or workspace.get("origin") != entry.get("remote_url")
            or entry.get("repository") != repository or entry.get("base_sha") != baseline):
        raise BridgeError("Accepted workspace custody or HEAD has changed")
    repo = Path(workspace["path"])
    if git(repo, "rev-parse", f"{observed}^{{commit}}").lower() != observed:
        raise BridgeError("Observed base must be an exact local commit")
    for head in (source, observed):
        require_success(run(["git", "-C", str(repo), "merge-base", "--is-ancestor", baseline, head]),
                        "Compiled baseline ancestry check")
    if run(["git", "-C", str(repo), "merge-base", "--is-ancestor", observed, source]).returncode == 0:
        raise BridgeError("Accepted head already contains this base; use publish directly")
    if run(["git", "-C", str(repo), "merge-base", "--is-ancestor", source, observed]).returncode == 0:
        raise BridgeError("The accepted head is already contained in this base; reconcile its publication")
    merge_base = git(repo, "merge-base", source, observed).lower()
    changes = changed_paths(repo, merge_base, observed)
    evidence = {}
    for kind in ("result", "context_receipt", "adjudication", *(
            ["lineage_review"] if record.get("lineage_review_ref") else [])):
        ref, digest = record.get(kind + "_ref"), record.get(kind + "_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BridgeError(f"Accepted {kind} hash is missing or invalid")
        try:
            with safe_ref(root, ref).open("rb") as stream:
                hasher = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
                actual = hasher.hexdigest()
        except OSError as exc:
            raise BridgeError(f"Cannot read accepted {kind} evidence: {exc}") from exc
        if actual != digest:
            raise BridgeError(f"Accepted {kind} evidence changed")
        evidence[kind] = {"ref": ref, "sha256": digest}
    payload = {"source_cell": args.cell, "source_attempt": record.get("attempt"),
               "source_head": source, "repository": repository,
               "compiled_base": baseline, "observed_base": observed,
               "merge_base": merge_base, "base_changed_paths": changes,
               "accepted_evidence": evidence}
    if reservation_selector(record) is not None:
        payload["execution_reservation"] = reservation_selector(record)
    if "contracts/capabilities/cell-coordination-v1.json" in read_json(root / "TEMPLATE_LOCK.json").get("assets", {}):
        coordination = record.get("coordination", {})
        scope_base = coordination.get("binding", {}).get("scope_base", baseline)
        verify_coordination_for_publication(root, args.cell, source, scope_base)
        if remote_head(repo, "refs/heads/main") != observed:
            raise BridgeError("Handoff base is not the observed accepted main ref; fetch and reassess")
        payload["scope_base_observation"] = {
            "schema": "flyby/mission-control-accepted-base-observation/1",
            "ref": "refs/heads/main", "sha": observed, "origin": entry["remote_url"],
            "source_scope_proof_sha256": coordination["scope_proof_sha256"],
            "source_generation": coordination["generation"], "source_token": coordination["token"],
        }
    successor = copy.deepcopy(old_cell)
    successor["cell_id"] = args.successor
    successor["dependencies"] = list(dict.fromkeys([*old_cell.get("dependencies", []), args.cell]))
    successor["objective"] = old_cell["objective"].split(HANDOFF_MARKER, 1)[0] + HANDOFF_MARKER + json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    successor["acceptance"] = list(dict.fromkeys([*old_cell["acceptance"], *HANDOFF_ACCEPTANCE]))
    frontier = {"schema": "flyby/mission-control-frontier/16", "frontier_id": args.frontier,
                "cells": [successor]}
    # Mission Control compiles and binds the descriptor into its authoritative
    # DAG/context. It remains responsible for claims and independent settlement.
    with tempfile.TemporaryDirectory(prefix="wt-mission-handoff-") as tmp:
        descriptor = Path(tmp) / "frontier.json"
        descriptor.write_text(json.dumps(frontier, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            mc(root, "compile", "--frontier", str(descriptor))
        except BridgeError as exc:
            raise BridgeError(f"{exc}; inspect the mission frontier before retrying") from exc
    print(json.dumps({"state": "SUCCESSOR_COMPILED", "cell": args.successor,
                      "frontier": args.frontier, **payload,
                      "next": "Prepare and dispatch the successor, then incorporate both heads and independently verify the evidence."},
                     indent=2, ensure_ascii=False))


def validate_push_destinations(repo: Path, repository: str) -> list[str]:
    # Git may use one or more push URLs distinct from the fetch URL; get-url
    # expands pushInsteadOf/insteadOf using Git's effective configuration.
    proc = run(["git", "-C", str(repo), "remote", "get-url", "--push", "--all", "origin"])
    if proc.returncode:
        raise BridgeError("Cannot resolve every effective origin push destination")
    destinations = proc.stdout.splitlines()
    if not destinations or any(not url or url != url.strip() or not github_origin(url, repository)
                               for url in destinations):
        # Do not echo URLs: they may contain credentials.
        raise BridgeError("Every effective origin push destination must identify the compiled GitHub repository")
    return destinations


def config_quote(value: str) -> str:
    # Git config supports these escapes in quoted subsection names and values.
    if any(ch in value for ch in "\x00\r\n"):
        raise BridgeError("Cannot bind a Git configuration value containing a line break")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\b", "\\b") + '"'


def system_config_origin(repo: Path, env: dict[str, str]) -> str | None:
    # Retain the user's effective system configuration when inserting a
    # process-only URL binding before all existing rewrite rules.
    proc = run(["git", "-C", str(repo), "config", "--show-scope", "--show-origin",
                "--null", "--list", "--includes"], env=env)
    fields = proc.stdout.split("\x00")
    if fields and fields[-1] == "":
        fields.pop()
    if proc.returncode or len(fields) % 3:
        raise BridgeError("Cannot inspect Git configuration for the verified push")
    for i in range(0, len(fields), 3):
        if fields[i] == "system":
            origin = fields[i + 1]
            if not origin.startswith("file:") or not origin[5:]:
                raise BridgeError("Cannot preserve Git system configuration for the verified push")
            return origin[5:]
    return None


def push_to_verified_destination(repo: Path, destination: str, candidate: str,
                                 branch_ref: str) -> subprocess.CompletedProcess[str]:
    env = child_environment(os.environ)
    system_origin = system_config_origin(repo, env)
    # An exact-match self-rewrite comes first in Git's system scope. It prevents
    # the already-resolved URL from being rewritten a second time while leaving
    # the original system, global, and local configuration in effect.
    quoted = config_quote(destination)
    config = f"[url {quoted}]\n\tinsteadOf = {quoted}\n\tpushInsteadOf = {quoted}\n"
    if system_origin:
        config += f"[include]\n\tpath = {config_quote(system_origin)}\n"
    with tempfile.TemporaryDirectory(prefix="wt-mission-push-config-") as tmp:
        system_config = Path(tmp) / "config"
        system_config.write_text(config, encoding="utf-8")
        env["GIT_CONFIG_SYSTEM"] = str(system_config)
        env["GIT_CONFIG_NOSYSTEM"] = "0"
        env["WT_MISSION_PUSH_URL"] = destination
        # Git treats an empty pushurl as clearing the preceding list. These
        # process-only options then add exactly the verified URL, while keeping
        # the origin name for hooks and origin-specific transport settings.
        # The URL stays out of the process command line if it has credentials.
        binding = ["-c", "remote.origin.pushurl=",
                   "--config-env=remote.origin.pushurl=WT_MISSION_PUSH_URL"]
        # Older Git versions append empty push URLs rather than clearing the
        # list. Test this exact behavior with a sentinel before any upload.
        probe = run(["git", "-C", str(repo), "-c", "remote.origin.pushurl=wt-mission-binding-probe",
                     *binding, "remote", "get-url", "--push", "--all", "origin"], env=env)
        if probe.returncode or probe.stdout.splitlines() != [destination]:
            raise BridgeError("This Git cannot safely bind the verified push URL; use a Git version that supports clearing push URLs")
        return run(["git", "-C", str(repo), *binding,
                    "-c", "remote.origin.mirror=false", "push",
                    "--no-follow-tags", "--recurse-submodules=no",
                    f"--force-with-lease={branch_ref}:", "origin", f"{candidate}:{branch_ref}"], env=env)


def verify_publication(repo: Path, gh: str, repository: str, url: str,
                       branch: str, base: str, candidate: str, observed_base: str,
                       *, require_draft: bool) -> dict:
    """Observe the published PR and refs, without claiming a cross-service transaction.

    Git's lease protects the branch write, not a later forge operation. Reconcile
    after that operation before issuing a success receipt. Other writers remain
    free to advance refs after these observations; acceptance must still bind OIDs.
    """
    pending = "Publication could not be verified; branch and any PR were preserved; reconcile before retrying"
    if not isinstance(url, str) or not re.fullmatch(
            r"https://github\.com/" + re.escape(repository) + r"/pull/[1-9][0-9]*", url, re.IGNORECASE):
        raise BridgeError(pending + ": unexpected PR URL")
    try:
        view = run([gh, "pr", "view", url, "--repo", repository, "--json",
                    "url,headRefOid,baseRefOid,headRefName,baseRefName,state,isDraft,isCrossRepository"], cwd=repo)
    except BridgeError as exc:
        raise BridgeError(pending + ": PR lookup could not start") from exc
    if view.returncode:
        raise BridgeError(pending + ": PR lookup failed")
    try:
        pr = json.loads(view.stdout)
    except ValueError as exc:
        raise BridgeError(pending + ": invalid PR response") from exc
    if (not isinstance(pr, dict) or not isinstance(pr.get("url"), str)
            or pr["url"].casefold() != url.casefold()
            or pr.get("headRefOid") != candidate or pr.get("baseRefOid") != observed_base
            or pr.get("headRefName") != branch or pr.get("baseRefName") != base
            or pr.get("state") != "OPEN" or pr.get("isCrossRepository") is not False
            or (require_draft and pr.get("isDraft") is not True)):
        raise BridgeError(pending + ": PR no longer matches the accepted candidate and observed base")
    try:
        head_now = remote_head(repo, f"refs/heads/{branch}")
        base_now = remote_head(repo, f"refs/heads/{base}")
    except BridgeError as exc:
        raise BridgeError(pending + ": remote refs could not be read") from exc
    if head_now != candidate or base_now != observed_base:
        raise BridgeError(pending + ": remote refs changed during publication")
    return pr


def verify_coordination_for_publication(root: Path, cell: str, candidate: str, base: str) -> None:
    if "contracts/capabilities/cell-coordination-v1.json" in read_json(root / "TEMPLATE_LOCK.json").get("assets", {}):
        mc(root, "coordination", "verify", "--cell", cell, "--candidate", candidate, "--publication-base", base)


def verify_lineage_for_publication(root: Path, cell_id: str, repository: str,
                                   candidate: str, publication_base: str, base_ref: str) -> None:
    corpus = read_json(root / "corpus" / "TARGET_MUTATIONS.json")
    materialization = corpus.get("provenance_materialization", {})
    if not isinstance(materialization, dict) or materialization.get("mode") != "SAME_REPOSITORY_NO_NEW_HARVEST":
        return
    if base_ref != "refs/heads/main":
        raise BridgeError("Lineage preservation profile requires the accepted main branch")
    preservation = materialization.get("preservation", {})
    if not isinstance(preservation, dict) or preservation.get("repository") != repository:
        raise BridgeError("Lineage preservation contract does not bind this target repository")
    mc(root, "lineage", "verify", "--cell", cell_id, "--candidate", candidate,
       "--publication-base", publication_base)


def publish(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    report = scope_report(root, args.cell)
    target = report.get("target")
    result = report.get("result")
    workspace = report.get("workspace")
    if report["state"] != "ACCEPTED" or report["kind"] != "MUTATION":
        raise BridgeError("Publishing requires an independently accepted mutation cell")
    if not isinstance(target, dict) or not isinstance(result, dict) or not isinstance(workspace, dict):
        raise BridgeError("Accepted target, result, or live workspace is missing")
    outcomes = result.get("target_outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 1:
        raise BridgeError("Accepted mutation must have one target outcome")
    outcome = outcomes[0]
    repository = target["repository"]
    base_sha = target["base_sha"].lower()
    candidate = outcome.get("head_sha")
    if (outcome.get("repository") != repository or outcome.get("baseline_sha") != base_sha
            or not re.fullmatch(r"[0-9a-f]{40}", str(candidate))):
        raise BridgeError("Accepted outcome does not bind the compiled target")
    repo = Path(workspace["path"])
    entry = ledger_entry(root, args.cell)
    if (workspace["branch"] != entry.get("branch") or not workspace["clean"]
            or workspace["head_sha"] != candidate
            or workspace["origin"] != entry.get("remote_url")
            or entry.get("repository") != repository or entry.get("base_sha") != base_sha):
        raise BridgeError("Workspace custody or HEAD differs from the accepted result")
    if not github_origin(workspace["origin"], repository):
        raise BridgeError("Publishing requires origin to identify the compiled GitHub repository")
    validate_push_destinations(repo, repository)
    require_success(run(["git", "-C", str(repo), "check-ref-format", "--branch", args.base]), "Base branch validation")
    require_success(run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base_sha, candidate]), "Base ancestry check")
    base_ref, branch_ref = f"refs/heads/{args.base}", f"refs/heads/{workspace['branch']}"
    observed_base = remote_head(repo, base_ref)
    if observed_base is None:
        raise BridgeError("Remote base branch is missing")
    ancestry = run(["git", "-C", str(repo), "merge-base", "--is-ancestor", observed_base, candidate])
    if ancestry.returncode:
        raise BridgeError("Cannot verify the current remote base is contained in the accepted head; fetch and reassess the candidate and its evidence")
    verify_coordination_for_publication(root, args.cell, candidate, observed_base)
    verify_lineage_for_publication(root, args.cell, repository, candidate, observed_base, base_ref)
    dependency_prs = parse_dependency_prs(getattr(args, "dependency_pr", []))
    dependencies = check_dependency_delivery(root, args.cell, repo, repository, candidate,
                                             observed_base, args.base, args.gh, dependency_prs)
    for dependency in dependencies:
        if dependency["state"] == "OTHER_REPOSITORY_UNASSESSED":
            print(f"wt-mission: Dependency {dependency['cell']} targets another repository and was not checked",
                  file=sys.stderr)

    def recheck_dependencies(*, published: bool = False) -> None:
        mc(root, "doctor")
        current = check_dependency_delivery(root, args.cell, repo, repository, candidate,
                                            observed_base, args.base, args.gh, dependency_prs)
        if current != dependencies or remote_head(repo, base_ref) != observed_base:
            raise BridgeError("Dependencies or remote base changed; publication requires reconciliation")
        if published and remote_head(repo, branch_ref) != candidate:
            raise BridgeError("Published branch changed during dependency verification; reconcile before retrying")

    existing = remote_head(repo, branch_ref)
    if existing is not None and existing != candidate:
        raise BridgeError("Remote branch already exists at a different commit; it was not changed")
    # Check forge access and reconcile any existing PR before changing the remote branch.
    query = run([args.gh, "pr", "list", "--repo", repository, "--base", args.base,
                 "--head", workspace["branch"], "--state", "open",
                 "--json", "number,url,headRefOid"], cwd=repo)
    try:
        existing_prs = json.loads(require_success(query, "PR lookup"))
    except ValueError as exc:
        raise BridgeError("PR lookup returned invalid JSON; no branch was pushed") from exc
    if not isinstance(existing_prs, list) or len(existing_prs) > 1:
        raise BridgeError("PR lookup is ambiguous; no branch was pushed")
    if existing_prs:
        pr = existing_prs[0]
        if existing != candidate or str(pr.get("headRefOid", "")).lower() != candidate:
            raise BridgeError("Existing PR or remote branch differs from accepted head")
        verified = verify_publication(repo, args.gh, repository, pr.get("url", ""),
                                      workspace["branch"], args.base, candidate, observed_base,
                                      require_draft=False)
        verify_coordination_for_publication(root, args.cell, candidate, observed_base)
        verify_lineage_for_publication(root, args.cell, repository, candidate, observed_base, base_ref)
        recheck_dependencies(published=True)
        print(json.dumps({"state": "EXISTING_PR", "pr": pr, "head_sha": candidate,
                          "base_sha": observed_base, "verified_pr": verified,
                          "dependencies": dependencies}, indent=2))
        return
    verify_lineage_for_publication(root, args.cell, repository, candidate, observed_base, base_ref)
    if existing is None:
        recheck_dependencies()
        # Re-read immediately before upload. The empty expected value is an
        # atomic create-only lease: Git refuses the update if the ref exists,
        # even when a concurrent creator chose an ancestor of the candidate.
        verify_coordination_for_publication(root, args.cell, candidate, observed_base)
        destination = validate_push_destinations(repo, repository)[0]
        push = push_to_verified_destination(repo, destination, candidate, branch_ref)
        if push.returncode:
            # Git may include a credential-bearing URL in its diagnostics.
            raise BridgeError(f"Push did not confirm success (exit {push.returncode}); reconcile the remote branch before retrying")
    if remote_head(repo, branch_ref) != candidate:
        raise BridgeError("Remote branch does not match the accepted head; reconcile before retrying")
    if remote_head(repo, base_ref) != observed_base:
        raise BridgeError("Remote base changed after push; branch preserved, no PR created")
    verify_coordination_for_publication(root, args.cell, candidate, observed_base)
    verify_lineage_for_publication(root, args.cell, repository, candidate, observed_base, base_ref)
    recheck_dependencies(published=True)
    create = run([args.gh, "pr", "create", "--repo", repository, "--base", args.base,
                  "--head", workspace["branch"], "--title", args.title,
                  "--body", args.body, "--draft"], cwd=repo)
    if create.returncode:
        raise BridgeError("PR creation did not confirm success; reconcile the remote PR before retrying. "
                          + (create.stderr or create.stdout).strip())
    verified = verify_publication(repo, args.gh, repository, create.stdout.strip(),
                                  workspace["branch"], args.base, candidate, observed_base,
                                  require_draft=True)
    verify_coordination_for_publication(root, args.cell, candidate, observed_base)
    verify_lineage_for_publication(root, args.cell, repository, candidate, observed_base, base_ref)
    recheck_dependencies(published=True)
    print(json.dumps({"state": "DRAFT_PR_CREATED", "url": verified["url"],
                      "head_sha": candidate, "base_sha": observed_base, "compiled_base_sha": base_sha,
                      "dependencies": dependencies}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Worktrunk and Mission Control v16 bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Create and register one clean target worktree")
    for flag in ("root", "repo", "cell", "branch", "workspace-id"):
        prep.add_argument("--" + flag, required=True)
    prep.add_argument("--path")
    prep.add_argument("--expected-origin")
    prep.add_argument("--wt", default="wt")
    prep.add_argument("--worker")
    prep.add_argument("--verifier")
    show = sub.add_parser("report", help="Show the recorded evidence for one scope")
    show.add_argument("--root", required=True)
    show.add_argument("--cell", required=True)
    transfer = sub.add_parser("handoff", help="Compile a successor for an accepted scope after the base advances")
    for flag in ("root", "cell", "successor", "frontier", "base-sha"):
        transfer.add_argument("--" + flag, required=True)
    pr = sub.add_parser("publish", help="Publish one accepted scope as a draft PR")
    for flag in ("root", "cell", "base", "title", "body"):
        pr.add_argument("--" + flag, required=True)
    pr.add_argument("--gh", default="gh")
    pr.add_argument("--dependency-pr", action="append", default=[], metavar="CELL=NUMBER",
                    help="Verify a merged same-repository dependency PR (repeatable)")
    settle = sub.add_parser("settle", help="Submit worker and independent verifier evidence")
    for flag in ("root", "cell", "attempt", "result", "context-receipt", "adjudication"):
        settle.add_argument("--" + flag, required=True)
    settle.add_argument("--generation", type=int)
    settle.add_argument("--token")
    settle.add_argument("--binding-digest")
    settle.add_argument("--reconcile", action="store_true", help="Reconcile an identical previously settled attempt")
    settle.add_argument("--lineage-review")
    close = sub.add_parser("reconcile", help="Load workspace reconciliation, optionally close")
    close.add_argument("--root", required=True)
    close.add_argument("--file", required=True)
    close.add_argument("--close", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "report":
            print(json.dumps(scope_report(Path(args.root).resolve(), args.cell), indent=2))
        elif args.command == "handoff":
            handoff(args)
        elif args.command == "publish":
            publish(args)
        elif args.command == "settle":
            lineage = ["--lineage-review", args.lineage_review] if args.lineage_review else []
            binding = ["--binding-digest", args.binding_digest] if args.binding_digest else []
            if args.reconcile:
                print(json.dumps(settle_reconciled(args), indent=2))
            else:
                print(mc(Path(args.root).resolve(), "settle", "--cell", args.cell, "--attempt", args.attempt,
                         "--result", args.result, "--context-receipt", args.context_receipt,
                         "--adjudication", args.adjudication, *(["--generation", str(args.generation), "--token", args.token]
                     if args.generation is not None and args.token is not None else []), *lineage, *binding).strip())
        else:
            root = Path(args.root).resolve()
            print(mc(root, "workspace", "load", "--file", args.file).strip())
            if args.close:
                print(mc(root, "close").strip())
    except BridgeError as exc:
        print(f"wt-mission: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
