"""Exact transport bindings over the existing coordinated admission authority.

Reservations add the retained transport/claim identity contract to one durable
coordination request. They do not create another scheduler or launch a provider.
Admission, uncertainty, stop confirmation and release keep coordination/v1's
meaning. Every mutation selects the exact current reservation; historical lookup
is read-only. An accepted result and a stopped writer remain separate facts.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

CAPABILITY = "contracts/capabilities/execution-reservation-v1.json"
STATE_SCHEMA = "flyby/mission-control-execution-state/21"
BINDING_SCHEMA = "contracts/schemas/EXECUTION_BINDING_SCHEMA_V1.json"


def enabled(root: Path) -> bool:
    try:
        return CAPABILITY in json.loads((root / "TEMPLATE_LOCK.json").read_text(encoding="utf-8"))["assets"]
    except (OSError, ValueError, KeyError, TypeError):
        return False


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def load_binding(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("reservation binding has duplicate JSON keys")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("reservation binding contains a non-finite number")
    with path.open("rb") as stream:
        raw = stream.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("reservation binding exceeds the 8 MB input limit")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("reservation binding must be an object")
    return value


def _binding_errors(api, root: Path, state: dict, binding: dict, cell_id: str, bound: dict) -> list[str]:
    errors = api.schema_errors(root, BINDING_SCHEMA, binding)
    expected = {"mission_id": state["mission_id"], "mission_instance_id": state["coordination"]["instance_id"],
                "cell_id": cell_id, "attempt": bound["attempt"], "workspace_id": bound["workspace_id"],
                "workspace_path": bound["workspace"]["workspace_path"], "repository": bound["target"]["repository"],
                "base_sha": bound["workspace"]["base_sha"], "worker_identity": bound["worker_identity"],
                "verifier_identity": bound["verifier_identity"]}
    for key, value in expected.items():
        if binding.get(key) != value:
            errors.append(f"reservation {key} differs from the exact mission, attempt or workspace custody")
    if "workspace_origin" in binding and binding["workspace_origin"] != bound["workspace"]["origin"]:
        errors.append("reservation workspace_origin differs from the registered effective origin")
    for key, value in binding.items():
        if isinstance(value, str) and (not value.strip() or value != value.strip()):
            errors.append(f"reservation {key} must be nonempty with no surrounding whitespace")
    if binding.get("worker_identity") == binding.get("verifier_identity"):
        errors.append("reservation worker and verifier must be independent")
    return errors


def issues(scope: dict, root: Path, state: dict) -> list[str]:
    api = SimpleNamespace(**scope)
    errors = []
    if state.get("mission_root") != str(root.resolve()) or state.get("mission_instance_id") != state.get("coordination", {}).get("instance_id"):
        errors.append("reservation authority root or mission instance changed")
    required = (CAPABILITY, BINDING_SCHEMA, "contracts/schemas/EXECUTION_STATE_SCHEMA_V21.json",
                "runtime/tools/execution_reservation.py")
    lock = api.load_json(root / "TEMPLATE_LOCK.json")
    if any(ref not in lock.get("assets", {}) for ref in required):
        errors.append("reservation capability assets are not fully sealed")
    for cell_id, record in state.get("cells", {}).items():
        request = record.get("coordination")
        current = record.get("execution_reservation")
        if bool(request) != bool(current):
            errors.append(f"{cell_id}: coordinated target lacks its exact execution reservation")
        declarations = [(current, request)] if current else []
        history = state.get("coordination", {}).get("history", [])
        for old in record.get("execution_reservation_history", []):
            matches = [item for item in history if item.get("token") == old.get("token")]
            declarations.append((old, matches[0] if len(matches) == 1 else None))
        for reservation, selected in declarations:
            try:
                if not selected or any(reservation.get(key) != value for key, value in (
                        ("cell", cell_id), ("attempt", selected["binding"]["attempt"]),
                        ("generation", selected["generation"]), ("token", selected["token"]),
                        ("launch_intent_id", selected["request_id"]))):
                    raise ValueError("reservation no longer selects its exact coordinated generation")
                binding = reservation["binding"]
                if reservation["binding_digest"] != digest(binding):
                    raise ValueError("reservation binding digest changed")
                if selected["binding"].get("execution_binding_digest") != reservation["binding_digest"]:
                    raise ValueError("reservation transport binding differs from the admitted scope proof")
                errors.extend(f"{cell_id}: {error}" for error in
                              _binding_errors(api, root, state, binding, cell_id, selected["binding"]))
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{cell_id}: {exc}")
    return errors


def archive(record: dict) -> None:
    current = record.pop("execution_reservation", None)
    if current is not None:
        record.setdefault("execution_reservation_history", []).append(current)


def reserve(scope: dict, args) -> int:
    api = SimpleNamespace(**scope)
    root = Path(args.root).resolve()
    if not enabled(root):
        raise ValueError("frozen mission lacks execution-reservation/v1; initialize a new capable mission")
    if not api._doctor_or_fail(root):
        return 1
    dag, state = api._load_v16(root)
    binding = load_binding(Path(args.binding).resolve())
    errors = api.schema_errors(root, BINDING_SCHEMA, binding)
    if errors:
        raise ValueError("invalid reservation binding: " + "; ".join(errors))
    cell_id = binding["cell_id"]
    if cell_id not in state["cells"]:
        raise ValueError("reservation cell is absent from the authoritative DAG")
    record = state["cells"][cell_id]
    intent = args.launch_intent_id
    if not intent.strip() or intent != intent.strip() or len(intent) > 256:
        raise ValueError("launch intent must be nonempty, at most 256 characters and have no surrounding whitespace")
    bound = api._coordination().binding(api, root, dag, state, cell_id, binding["workspace_id"],
                                       binding["worker_identity"], binding["verifier_identity"])
    errors = _binding_errors(api, root, state, binding, cell_id, bound)
    if errors:
        raise ValueError("invalid reservation binding: " + "; ".join(errors))
    previous = record.get("execution_reservation")
    if previous:
        if previous["binding"] == binding and previous["launch_intent_id"] == intent:
            print(json.dumps(_view(api, root, state, record, previous, record["coordination"], current=True), indent=2))
            return 0
        if record["coordination"]["phase"] != "RELEASED" or record["state"] != "COMPILED":
            raise ValueError("current attempt already has a different reservation; preserve and release its writer custody")
        state["coordination"]["history"].append(record.pop("coordination"))
        archive(record)
    request_args = SimpleNamespace(cell=cell_id, workspace_id=binding["workspace_id"], request_id=intent)
    coord = api._coordination()
    # This provisional in-memory value lets the existing authority bind the
    # transport digest before allocating a generation; it is never saved alone.
    record["execution_reservation"] = {"binding_digest": digest(binding)}
    coord._enqueue(api, root, dag, state, request_args, binding["worker_identity"], binding["verifier_identity"])
    request = record["coordination"]
    reservation = {"cell": cell_id, "attempt": record["attempt"], "generation": request["generation"],
                   "token": request["token"], "binding": binding, "binding_digest": digest(binding),
                   "launch_intent_id": intent}
    record["execution_reservation"] = reservation
    coord._sweep(api, root, dag, state)
    # Admission, claims, intent and transport binding share the one state write.
    api._save_state(root, state)
    print(json.dumps(_view(api, root, state, record, reservation, request, current=True), indent=2))
    return 0


def _select(state: dict, args, *, historical: bool) -> tuple[dict, dict, dict, bool]:
    record = state.get("cells", {}).get(args.cell, {})
    declarations = [(record.get("execution_reservation"), record.get("coordination"), True)]
    if historical:
        for old in record.get("execution_reservation_history", []):
            requests = [item for item in state["coordination"]["history"] if item["token"] == old["token"]]
            if len(requests) == 1:
                declarations.append((old, requests[0], False))
    matches = [(record, reservation, request, current) for reservation, request, current in declarations
               if reservation and request and reservation["token"] == args.reservation_id
               and type(args.fence) is int and reservation["generation"] == args.fence
               and reservation["binding_digest"] == args.binding_digest]
    if len(matches) != 1:
        raise ValueError("reservation ID, fence and binding digest do not identify one exact permitted generation")
    return matches[0]


def _view(api, root: Path, state: dict, record: dict, reservation: dict, request: dict, *, current: bool) -> dict:
    attempt = reservation["attempt"]
    settled = [item for item in record.get("attempt_history", [])
               if item.get("attempt") == attempt and request.get("scope_proof_ref")]
    settlement = settled[0] if len(settled) == 1 else {}
    hashes = {key: settlement[key] for key in ("result_sha256", "context_receipt_sha256", "adjudication_sha256",
                                               "lineage_review_sha256") if key in settlement}
    return {"reservation_id": reservation["token"], "fence": reservation["generation"],
            "binding": reservation["binding"], "binding_digest": reservation["binding_digest"],
            "launch_intent_id": reservation["launch_intent_id"], "attempt": attempt, "current": current,
            "cell_state": record["state"] if current else settlement.get("state", "COMPILED"),
            "phase": request["phase"], "executor_identity": request["executor_identity"],
            "ownership_released": request["phase"] == "RELEASED",
            "released_without_launch": request["phase"] == "RELEASED" and request["executor_identity"] is None,
            "settlement_ref": settlement.get("adjudication_ref"), "evidence_hashes": hashes,
            "evidence_digest": digest(hashes) if hashes else None,
            "lineage_review_ref": settlement.get("lineage_review_ref"),
            "stop_observation_ref": request["stop_observation_ref"],
            "stop_observation_sha256": request["stop_observation_sha256"],
            "provider_launch_performed": False, "termination_supported": False}


def command(scope: dict, args) -> int:
    api = SimpleNamespace(**scope)
    root = Path(args.root).resolve()
    if args.execution_command == "reserve":
        return reserve(scope, args)
    if not enabled(root):
        raise ValueError("frozen mission lacks execution-reservation/v1; initialize a new capable mission")
    if not api._doctor_or_fail(root):
        return 1
    _, state = api._load_v16(root)
    record, reservation, request, current = _select(state, args, historical=args.execution_command == "inspect")
    transition = {}
    if args.execution_command != "inspect":
        delegated = SimpleNamespace(**vars(args), coordination_command=args.execution_command,
                                    generation=args.fence, token=args.reservation_id)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = api._coordination().command(scope, delegated)
        if code:
            return code
        transition = json.loads(output.getvalue())
        _, state = api._load_v16(root)
        record, reservation, request, current = _select(state, args, historical=False)
    value = _view(api, root, state, record, reservation, request, current=current)
    if "launch_authorized" in transition:
        value["launch_authorized"] = transition["launch_authorized"]
    print(json.dumps(value, indent=2))
    return 0


def add_parser(sub, handler) -> None:
    parser = sub.add_parser("execution", help="Bind transport reservations to coordinated target ownership")
    actions = parser.add_subparsers(dest="execution_command", required=True)
    for action in ("reserve", "inspect", "launching", "running", "unknown", "stop", "confirm-stop", "release"):
        command = actions.add_parser(action)
        command.add_argument("--root", required=True)
        if action == "reserve":
            command.add_argument("--binding", required=True)
            command.add_argument("--launch-intent-id", required=True)
        else:
            command.add_argument("--cell", required=True)
            command.add_argument("--reservation-id", required=True)
            command.add_argument("--fence", required=True, type=int)
            command.add_argument("--binding-digest", required=True)
        if action == "launching":
            command.add_argument("--executor-identity", required=True)
        if action == "confirm-stop":
            command.add_argument("--observation", required=True)
        command.set_defaults(func=handler)
