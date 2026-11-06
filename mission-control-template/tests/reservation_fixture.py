"""Controlled adapter/independent-observer evidence for reservation tests."""
from __future__ import annotations

import json
from pathlib import Path
import test_runtime_state_machine as lifecycle


class ReservationProtocol:
    def __init__(self, fixture):
        self.fixture, self.root = fixture, fixture.root

    def current(self, cell):
        return self.fixture.state()["cells"][cell]["execution_reservation"]

    def selectors(self, reservation):
        return ["--reservation-id", reservation["token"], "--fence", reservation["generation"],
                "--binding-digest", reservation["binding_digest"]]

    def action(self, action, cell, *more, ok=True):
        return self.fixture.mc("execution", action, "--root", self.root, "--cell", cell,
                               *self.selectors(self.current(cell)), *more, ok=ok)

    def observation(self, cell, kind, *, outcome="COMPLETED", session=None):
        reservation = self.current(cell)
        session = session or "fixture-provider:" + cell
        schema = {"session": "provider-session", "terminal": "provider-terminal", "no-launch": "no-launch"}[kind]
        source = self.root / "evidence" / f"adapter-{cell}-{reservation['generation']}-{kind}.json"
        lifecycle.write_json(source, {"fixture": "controlled adapter authenticated and correlated this inert test source",
                                      "binding_digest": reservation["binding_digest"], "outcome": outcome,
                                      "session": None if kind == "no-launch" else session,
                                      "launch_authority_revoked": kind == "no-launch"})
        value = {"schema": f"flyby/mission-control-{schema}-observation/1", "cell_id": cell,
                 "reservation_id": reservation["token"], "fence": reservation["generation"],
                 "binding_digest": reservation["binding_digest"], "attempt": reservation["attempt"],
                 "launch_intent_id": reservation["launch_intent_id"], "observation_id": kind + ":" + cell,
                 "session_ref": None if kind == "no-launch" else session,
                 "source_evidence": {"authority": "controlled-fixture-adapter",
                     "record_ref": source.relative_to(self.root).as_posix(), "record_sha256": lifecycle.sha256(source)}}
        if kind == "terminal":
            value.update(outcome=outcome, writer_domain_stopped_or_fenced=True)
        elif kind == "no-launch":
            value.update(outcome="NO_LAUNCH", start_not_occurred=True, launch_authority_revoked=True)
        path = self.root / f"{cell}-{kind}-observation.json"
        lifecycle.write_json(path, value)
        return path, value

    def running(self, cell, *, context_session=None):
        path, value = self.observation(cell, "session")
        more = []
        if context_session:
            reservation = self.current(cell)
            source = value["source_evidence"]
            mapping = {key: value[key] for key in ("cell_id", "attempt", "reservation_id", "fence", "binding_digest", "launch_intent_id", "session_ref")}
            mapping.update(schema="flyby/mission-control-provider-session-mapping/1", context_session_ref=context_session,
                           reviewer_identity=reservation["binding"]["verifier_identity"],
                           evidence=[{"ref": source["record_ref"], "sha256": source["record_sha256"]}])
            mapping_path = self.root / (cell + "-session-mapping.json")
            lifecycle.write_json(mapping_path, mapping)
            more = ["--session-mapping", mapping_path]
        return self.fixture.mc("execution", "running", "--root", self.root, "--observation", path, *more)

    def fence(self, cell, source):
        record = self.fixture.state()["cells"][cell]
        request = record["coordination"]
        evidence = self.root / "evidence" / f"operator-{cell}-{request['generation']}.json"
        lifecycle.write_json(evidence, {"fixture": "independent observer owns and has fenced every possible test writer and future launch authority",
                                        "executor_identity": request["executor_identity"]})
        observation = {"schema": "flyby/mission-control-fence-observation/1", "kind": "INDEPENDENT_OPERATOR_CONFIRMATION",
                       "cell": cell, "attempt": record["attempt"], "generation": request["generation"], "token": request["token"],
                       "executor_identity": request["executor_identity"], "observer_identity": request["binding"]["verifier_identity"],
                       "termination_confirmed": True, "descendants_fenced": True,
                       "rationale": "Controlled fixture: writer domain and old launch authority are fenced; retained adapter evidence independently inspected.",
                       "evidence": [{"ref": evidence.relative_to(self.root).as_posix(), "sha256": lifecycle.sha256(evidence)},
                                    {"ref": source["record_ref"], "sha256": source["record_sha256"]}]}
        path = self.root / f"{cell}-{request['generation']}-fence.json"
        lifecycle.write_json(path, observation)
        return self.action("confirm-stop", cell, "--observation", path)

    def terminal(self, cell, *, outcome="COMPLETED"):
        path, value = self.observation(cell, "terminal", outcome=outcome)
        self.fence(cell, value["source_evidence"])
        return self.fixture.mc("execution", "terminal", "--root", self.root, "--observation", path)

    def receipt_session(self, path: Path, cell: str):
        reservation = self.current(cell)
        value = json.loads(path.read_text(encoding="utf-8"))
        session = reservation.get("session_ref")
        if reservation.get("session_mapping_ref"):
            session = json.loads((self.root / reservation["session_mapping_ref"]).read_text(encoding="utf-8"))["context_session_ref"]
        value["worker"]["session_id"] = session
        lifecycle.write_json(path, value)
        return path
