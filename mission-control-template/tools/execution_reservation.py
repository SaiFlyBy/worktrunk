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
OBSERVATIONS = {"session_observation": "PROVIDER_SESSION_OBSERVATION_SCHEMA_V1.json",
                "terminal_observation": "PROVIDER_TERMINAL_OBSERVATION_SCHEMA_V1.json",
                "no_launch": "NO_LAUNCH_OBSERVATION_SCHEMA_V1.json",
                "session_mapping": "PROVIDER_SESSION_MAPPING_SCHEMA_V1.json"}


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
                "runtime/tools/execution_reservation.py",
                *("contracts/schemas/" + name for name in OBSERVATIONS.values()))
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
        requests = ([request] if request else []) + [item for item in history if item.get("binding", {}).get("cell") == cell_id]
        for selected in requests:
            matches = [value for value, _ in declarations if value and value.get("token") == selected.get("token")
                       and value.get("generation") == selected.get("generation")]
            if "execution_binding_digest" in selected.get("binding", {}) and len(matches) != 1:
                errors.append(f"{cell_id}: reservation and coordinated generation history are not one-to-one")
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
                _validate_retained_observations(api, root, reservation, selected)
                if selected.get("scope_proof_ref"):
                    settlements = [item for item in record.get("attempt_history", []) if item.get("attempt") == reservation["attempt"]]
                    if len(settlements) != 1:
                        raise ValueError("executed reservation lacks one exact independent settlement")
                    settled = settlements[0]
                    validate_settlement(scope, root, {"execution_reservation": reservation, "coordination": selected},
                                        api.load_json(api.resolve_ref(root, settled["result_ref"])),
                                        api.load_json(api.resolve_ref(root, settled["context_receipt_ref"])),
                                        SimpleNamespace(binding_digest=reservation["binding_digest"]))
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
    hashes = {key: settlement[key] for key in ("result_sha256", "context_receipt_sha256", "adjudication_sha256")
              if key in settlement}
    no_launch = reservation.get("no_launch_ref") or reservation.get("prelaunch_release_ref")
    phase = ("RELEASED_NO_LAUNCH" if no_launch else "SETTLED" if settlement else
             "TERMINAL" if reservation.get("terminal_observation_ref") else
             {"ADMITTED": "RESERVED", "LAUNCH_UNCERTAIN": "LAUNCHING"}.get(request["phase"], request["phase"]))
    return {"schema": "flyby/mission-control-execution-reservation-view/2",
            "reservation_id": reservation["token"], "fence": reservation["generation"],
            "binding": reservation["binding"], "binding_digest": reservation["binding_digest"],
            "launch_intent_id": reservation["launch_intent_id"], "attempt": attempt, "current": current,
            "cell_state": record["state"] if current else settlement.get("state", "COMPILED"),
            "phase": phase, "coordination_phase": request["phase"], "executor_identity": request["executor_identity"],
            "ownership_released": request["phase"] == "RELEASED",
            "released_without_launch": request["phase"] == "RELEASED" and bool(no_launch),
            "session_ref": reservation.get("session_ref"), "terminal_outcome": reservation.get("terminal_outcome"),
            "terminal_ref": reservation.get("terminal_observation_ref"),
            "terminal_sha256": reservation.get("terminal_observation_sha256"),
            "release_receipt_ref": no_launch,
            "release_receipt_sha256": reservation.get("no_launch_sha256", reservation.get("prelaunch_release_sha256")),
            "released_fence": reservation["generation"] if no_launch else None,
            "settlement_ref": settlement.get("adjudication_ref"), "evidence_hashes": hashes,
            "evidence_digest": digest(hashes) if hashes else None,
            "lineage_review_ref": settlement.get("lineage_review_ref"),
            "lineage_review_sha256": settlement.get("lineage_review_sha256"),
            "stop_observation_ref": request["stop_observation_ref"],
            "stop_observation_sha256": request["stop_observation_sha256"],
            "provider_launch_performed_by_runtime": False, "termination_supported": False}


def _selectors(value: dict) -> dict:
    return {"cell": value["cell_id"], "reservation_id": value["reservation_id"], "fence": value["fence"],
            "binding_digest": value["binding_digest"]}


def _validate_observation(api, root: Path, value: dict, kind: str, reservation: dict) -> None:
    errors = api.schema_errors(root, "contracts/schemas/" + OBSERVATIONS[kind], value)
    expected = {"cell_id": reservation["cell"], "attempt": reservation["attempt"],
                "reservation_id": reservation["token"], "fence": reservation["generation"],
                "binding_digest": reservation["binding_digest"], "launch_intent_id": reservation["launch_intent_id"]}
    errors.extend(key + " differs from exact reservation" for key, target in expected.items() if value.get(key) != target)
    if errors:
        raise ValueError("invalid execution observation: " + "; ".join(errors))
    source = value.get("source_evidence")
    if source:
        path = api.resolve_ref(root, source["record_ref"])
        if not path.is_file() or api.sha256(path) != source["record_sha256"]:
            raise ValueError("retained adapter source evidence is missing or changed")
    if kind == "session_mapping":
        if value["reviewer_identity"] != reservation["binding"]["verifier_identity"]:
            raise ValueError("provider session mapping requires the independent assigned verifier")
        for item in value["evidence"]:
            if api.sha256(api.resolve_ref(root, item["ref"])) != item["sha256"]:
                raise ValueError("independent session mapping evidence changed")


def _validate_retained_observations(api, root: Path, reservation: dict, request: dict) -> None:
    records = [(kind, reservation.get(kind + "_ref"), reservation.get(kind + "_sha256"))
               for kind in OBSERVATIONS if reservation.get(kind + "_ref") or reservation.get(kind + "_sha256")]
    records += [(item["kind"], item["ref"], item["sha256"]) for item in reservation.get("observation_history", [])]
    for kind, ref, expected in records:
        path = api.resolve_ref(root, ref)
        if api.sha256(path) != expected:
            raise ValueError("retained " + kind + " digest changed")
        value = load_binding(path)
        _validate_observation(api, root, value, kind, reservation)
        if kind in {"session_observation", "terminal_observation", "session_mapping"} and value["session_ref"] != reservation.get("session_ref"):
            raise ValueError("retained observation session differs from reservation")
        if kind == "terminal_observation" and value["outcome"] != reservation.get("terminal_outcome"):
            raise ValueError("retained terminal outcome differs from reservation")
        if kind in {"terminal_observation", "no_launch"}:
            _require_independent_fence(request)
    if reservation.get("no_launch_ref") and (request.get("scope_proof_ref") or reservation.get("session_ref")):
        raise ValueError("no-launch reservation contradicts execution evidence")
    if reservation.get("prelaunch_release_ref"):
        path = api.resolve_ref(root, reservation["prelaunch_release_ref"])
        if (api.sha256(path) != reservation.get("prelaunch_release_sha256")
                or load_binding(path) != _prelaunch_receipt(reservation)
                or request["executor_identity"] is not None or request["phase"] != "RELEASED"
                or reservation.get("session_ref")):
            raise ValueError("prelaunch release receipt or unlaunched custody changed")


def _prelaunch_receipt(reservation: dict) -> dict:
    return {"schema": "flyby/mission-control-prelaunch-release/1",
            "cell": reservation["cell"], "attempt": reservation["attempt"], "reservation_id": reservation["token"],
            "fence": reservation["generation"], "binding_digest": reservation["binding_digest"],
            "launch_intent_id": reservation["launch_intent_id"], "reason": "LAUNCH_PERMISSION_NEVER_GRANTED"}


def _require_independent_fence(request: dict) -> None:
    if request["phase"] not in {"STOP_CONFIRMED", "RELEASED"} or not request["stop_observation_ref"]:
        raise ValueError("observation requires independent confirmation that the exact writer domain is stopped or fenced")


def _store_observation(api, root: Path, reservation: dict, kind: str, value: dict) -> bool:
    ref = f"evidence/{reservation['cell']}/attempt-{reservation['attempt']:04d}/reservation-{reservation['generation']}/{kind}-{digest(value)}.json"
    api.write_immutable_json(root / ref, value)
    if reservation.get(kind + "_ref") == ref:
        return False
    if reservation.get(kind + "_ref"):
        reservation.setdefault("observation_history", []).append({"kind": kind, "ref": reservation[kind + "_ref"],
                                                                  "sha256": reservation[kind + "_sha256"]})
    reservation[kind + "_ref"], reservation[kind + "_sha256"] = ref, api.sha256(root / ref)
    return True


def observation(scope: dict, args, kind: str) -> int:
    api = SimpleNamespace(**scope)
    root = Path(args.root).resolve()
    value = load_binding(Path(args.observation).resolve())
    errors = api.schema_errors(root, "contracts/schemas/" + OBSERVATIONS[kind], value)
    if errors:
        raise ValueError("invalid execution observation: " + "; ".join(errors))
    _, state = api._load_v16(root)
    selector = SimpleNamespace(**_selectors(value))
    record, reservation, request, current = _select(state, selector, historical=kind == "no_launch")
    _validate_observation(api, root, value, kind, reservation)
    if kind == "no_launch" and not current:
        if not reservation.get("no_launch_ref") or load_binding(api.resolve_ref(root, reservation["no_launch_ref"])) != value:
            raise ValueError("historical no-launch replay conflicts with its immutable receipt")
        print(json.dumps(_view(api, root, state, record, reservation, request, current=False), indent=2))
        return 0
    if request["executor_identity"] is None:
        raise ValueError("provider observation requires the recorded launch intent")
    if kind == "session_observation":
        if reservation.get("session_ref") not in {None, value["session_ref"]}:
            raise ValueError("provider session conflicts with its recorded reservation")
        reservation["session_ref"] = value["session_ref"]
        frozen = reservation.get("terminal_observation_ref") or request.get("scope_proof_ref")
        if frozen and (not reservation.get("session_observation_ref") or
                       load_binding(api.resolve_ref(root, reservation["session_observation_ref"])) != value):
            raise ValueError("terminal or settled provider session evidence is immutable")
        mapping_changed = False
        if args.session_mapping:
            mapping = load_binding(Path(args.session_mapping).resolve())
            _validate_observation(api, root, mapping, "session_mapping", reservation)
            if mapping["session_ref"] != value["session_ref"]:
                raise ValueError("provider session mapping names a different session")
            if reservation.get("session_mapping_ref") and load_binding(api.resolve_ref(root, reservation["session_mapping_ref"])) != mapping:
                raise ValueError("independent provider session mapping is immutable")
            if frozen and not reservation.get("session_mapping_ref"):
                raise ValueError("terminal or settled provider session mapping is immutable")
            mapping_changed = _store_observation(api, root, reservation, "session_mapping", mapping)
        changed = _store_observation(api, root, reservation, kind, value) or mapping_changed
        if not reservation.get("terminal_observation_ref") and request["phase"] in {"LAUNCH_UNCERTAIN", "UNKNOWN", "RUNNING"}:
            request["phase"] = "RUNNING"
    elif kind == "terminal_observation":
        if reservation.get("session_ref") != value["session_ref"]:
            raise ValueError("terminal observation must identify the recorded provider session")
        if reservation.get("terminal_outcome") not in {None, value["outcome"]}:
            raise ValueError("terminal outcome conflicts with its recorded observation")
        if reservation.get("terminal_observation_ref") and load_binding(api.resolve_ref(root, reservation["terminal_observation_ref"])) != value:
            raise ValueError("retained provider terminal evidence is immutable")
        _require_independent_fence(request)
        reservation["terminal_outcome"] = value["outcome"]
        changed = _store_observation(api, root, reservation, kind, value)
    else:
        if reservation.get("session_ref") or record.get("result_ref") or request.get("scope_proof_ref"):
            raise ValueError("no-launch recovery contradicts recorded provider execution or settlement")
        _require_independent_fence(request)
        bound = request["binding"]
        api._coordination().snapshot(bound, bound["workspace"]["base_sha"], bound["workspace"]["base_sha"], clean=True, admission=True)
        _store_observation(api, root, reservation, kind, value)
        api._coordination().release_unlaunched(state, reservation["cell"], confirmed_no_launch=True)
        state["coordination"]["history"].append(record.pop("coordination"))
        archive(record)
        changed, current = True, False
    api._save_state(root, state)
    print(json.dumps({**_view(api, root, state, record, reservation, request, current=current), "transitioned": changed}, indent=2))
    return 0


def validate_settlement(scope: dict, root: Path, record: dict, result: dict, receipt: dict, args) -> None:
    api = SimpleNamespace(**scope)
    reservation = record.get("execution_reservation")
    if not reservation:
        return
    if getattr(args, "binding_digest", None) != reservation["binding_digest"]:
        raise ValueError("settlement requires the exact reservation binding digest")
    if not reservation.get("terminal_observation_ref") or not reservation.get("session_observation_ref"):
        raise ValueError("execution reservation requires retained provider session and trusted terminal observations before settlement")
    _validate_retained_observations(api, root, reservation, record["coordination"])
    expected_session = reservation["session_ref"]
    if reservation.get("session_mapping_ref"):
        expected_session = load_binding(api.resolve_ref(root, reservation["session_mapping_ref"]))["context_session_ref"]
    if receipt.get("worker", {}).get("session_id") != expected_session:
        raise ValueError("worker ContextReceipt session does not match the provider observation or independent mapping")
    if reservation["terminal_outcome"] in {"FAILED", "CANCELLED"} and result.get("outcome") == "ACCEPTED":
        raise ValueError("provider failure or cancellation cannot establish an accepted worker result")


def command(scope: dict, args) -> int:
    api = SimpleNamespace(**scope)
    root = Path(args.root).resolve()
    if args.execution_command == "reserve":
        return reserve(scope, args)
    if not enabled(root):
        raise ValueError("frozen mission lacks execution-reservation/v1; initialize a new capable mission")
    if not api._doctor_or_fail(root):
        return 1
    kinds = {"running": "session_observation", "terminal": "terminal_observation", "release-no-launch": "no_launch"}
    if args.execution_command in kinds:
        return observation(scope, args, kinds[args.execution_command])
    _, state = api._load_v16(root)
    record, reservation, request, current = _select(state, args, historical=args.execution_command in {"inspect", "release"})
    transition = {}
    if args.execution_command == "release" and not current:
        if request["phase"] != "RELEASED":
            raise ValueError("historical release replay requires an already released exact generation")
        print(json.dumps(_view(api, root, state, record, reservation, request, current=False), indent=2))
        return 0
    if args.execution_command == "release" and request["phase"] in {"QUEUED", "ADMITTED"}:
        ref = f"evidence/{args.cell}/attempt-{reservation['attempt']:04d}/reservation-{reservation['generation']}/prelaunch-release.json"
        api.write_immutable_json(root / ref, _prelaunch_receipt(reservation))
        reservation["prelaunch_release_ref"], reservation["prelaunch_release_sha256"] = ref, api.sha256(root / ref)
        api._coordination().release_unlaunched(state, args.cell)
        state["coordination"]["history"].append(record.pop("coordination"))
        archive(record)
        api._save_state(root, state)
        print(json.dumps(_view(api, root, state, record, reservation, request, current=False), indent=2))
        return 0
    if args.execution_command == "retry":
        with contextlib.redirect_stdout(io.StringIO()):
            code = api.cmd_retry(SimpleNamespace(root=str(root), cell=args.cell, _execution_selected=True))
        if code:
            return code
        _, state = api._load_v16(root)
        record, reservation, request, current = _select(state, args, historical=True)
        print(json.dumps({**_view(api, root, state, record, reservation, request, current=False),
                          "retry_prepared": True, "next_attempt": record["attempt"]}, indent=2))
        return 0
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
        value["transitioned"] = transition["launch_authorized"]
    print(json.dumps(value, indent=2))
    return 0


def add_parser(sub, handler) -> None:
    parser = sub.add_parser("execution", help="Bind transport reservations to coordinated target ownership")
    actions = parser.add_subparsers(dest="execution_command", required=True)
    for action in ("reserve", "inspect", "launching", "running", "terminal", "release-no-launch", "unknown", "stop", "confirm-stop", "release", "retry"):
        command = actions.add_parser(action)
        command.add_argument("--root", required=True)
        if action == "reserve":
            command.add_argument("--binding", required=True)
            command.add_argument("--launch-intent-id", required=True)
        elif action in {"running", "terminal", "release-no-launch"}:
            command.add_argument("--observation", required=True)
            if action == "running":
                command.add_argument("--session-mapping")
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
