# Native multi-phase task pipeline

This policy turns the MCV6 staged-review discipline into a reusable execution queue for independent chat seats. It is a scheduling contract, not model authorization: the user must still authorize any downstream provider or worker delegation required by the mission.

## 1. Overseer authority

One overseer/coordinator owns pipeline definition and queue management. The overseer may create a list of items, define ordered phases, inspect queue state, dispatch idle seats, pause/resume a pipeline, and cancel work that has not been assigned.

Assigned work is never silently revoked. A worker remains responsible for its assigned task until it produces a durable terminal receipt or the mission explicitly resolves the assignment.

The queue is durable coordination state. Worker UI summaries are not the handoff authority.

## 2. Queue construction law

For a pipeline with items `I1..In` and phases `A..N`:

1. initially materialize **only Phase A** for every item;
2. preserve deterministic queue order for those initial rows;
3. when `Ix/A` terminalizes successfully, materialize `Ix/B` and append it at the **tail** of the current queue;
4. repeat that rule for every later phase;
5. never pre-create a later phase merely because its predecessor is expected to pass.

Therefore a corpus of 100 papers starts as 100 Phase-A rows. If the first paper finishes while the other 99 Phase-A rows remain queued, that paper's Phase-B row is appended behind the existing Phase-A tail rather than jumping the line.

A successor is created only from a valid durable predecessor completion. A blocker, cancelled task, ambiguous terminal state, or invalid receipt does not silently advance the lineage.

## 3. Automatic mailbox handoff

A worker should not need an overseer prompt after every successful task.

The scheduler contract names this handoff `AUTO_ASSIGN_NEXT_TO_COMPLETING_SEAT`.

After a worker completes an assigned queue task, the scheduler atomically:

1. records the completion receipt;
2. appends the next phase for that item when one exists;
3. releases task-scoped claims;
4. selects the earliest queued task for which that same worker is eligible;
5. places that assignment in the worker's durable collaboration inbox.

If no eligible task exists, the worker becomes idle. The overseer can later dispatch new eligible work, or the worker can request the next eligible row.

This is queue assignment, not provider delegation. Launching a model/provider for the assigned work still follows the mission's user-authorization boundary.

## 4. Independent-seat laws

Each phase declares its independence requirements.

- `different_from_previous=true`: the phase cannot be assigned to the agent/seat that executed the immediately preceding phase for that item.
- `distinct_lineage_seat=true`: the phase cannot be assigned to any agent/seat already used by an earlier phase of the same item.
- `required_role`: the phase is eligible only for participants holding that role.

The scheduler skips ineligible rows for that participant without changing their queue position or weakening the requirement.

Stage-B self-certification is forbidden when MCV methodology requires independence. A clean diff, matching hash, or same-seat recheck is not a substitute for a different-seat substantive audit.

## 5. MCV source-review mapping

For source/research ingestion, the reusable MCV chain is:

```text
Phase A: source-local construction / ingestion
  -> Phase B: independent evidence review under the mission-defined project workflow
  -> Phase C: adjudication / final disposition topology chosen by mission policy
```

Phase B must be different from Phase A. The substantive review method is defined by the mission's versioned project workflow and active engineering contracts; the queue must not introduce an external methodology dependency.

Phase C is not universally "another ChatGPT pass." The mission must preserve the topology required by its authority model. For the MCV6 source-adjudication lane, actual Stage C remains the canonical serial adjudicator flow described in `MCV_ENGINEERING_AUDIT_AND_ADJUDICATION.md`; the queue may prepare and hand off its eligible input, but it must not parallelize or replace that serial authority. A different mission may define Phase C as a third independent chat seat and set `distinct_lineage_seat=true`.

## 6. MCV implementation-audit mapping

For the implementation phase captured by the latest MCV6 execution program, the per-cell queue is:

```text
Cell Phase A: ChatGPT project-defined audit over the implemented cell
  -> Cell Phase B: different-seat ChatGPT project-defined audit
  -> convergence/integration authority
```

The final Astra full-system pass in MCV6 is **not** a generic per-cell Phase C. It occurs after stable cell heads converge and remains a top-level final audit barrier. The queue must not flatten that barrier into ordinary cell work.

Additional cell-local remediation cycles preserve lineage:

```text
A1 -> B1 -> A2 -> B2 -> ...
```

A new remediation generation is appended; prior generations remain custody.

## 7. Queue and convergence separation

A green queued task proves only its own phase receipt. It does not authorize convergence, shared-authority admission, target promotion, or production release.

The overseer/convergence authority must still resolve:

- overlapping write or semantic-owner boundaries;
- duplicate state/registry/router/scheduler owners;
- dependency and migration conflicts;
- stale generations after integration;
- required re-audit against a newer integrated base.

Do not bulk-merge results merely because every worker reported success.

## 8. Durable evidence

Every assignment and terminal receipt must preserve enough machine-readable state to reconstruct:

- pipeline, item, phase, and queue position;
- assigned participant/agent;
- predecessor lineage and independence constraint;
- requested skill/methodology;
- resource boundary when applicable;
- terminal result and supporting artifacts;
- successor creation and subsequent assignment.

Project-visible coordination state should be inspectable outside source checkouts. Runtime queue state must never be committed as source code or mixed into the target repository's Git history.

## 9. Home_Tunnel mapping

When Home_Tunnel provides the collaboration transport, the intended mapping is:

- `collab.queue.enqueue` — overseer creates item list + ordered phases;
- `collab.queue.dispatch` — overseer fills idle eligible seats;
- `collab.queue.next` — one idle worker requests its earliest eligible task;
- `collab.inbox` — durable assignment delivery;
- `collab.complete` — terminal receipt, successor append, claim release, automatic next assignment;
- `collab.queue.list` — queue/pipeline inspection;
- `collab.queue.manage` — pause/resume/cancel unassigned work.

The Home_Tunnel queue is transport/scheduling infrastructure. This MCV policy remains the methodology and authority contract.
