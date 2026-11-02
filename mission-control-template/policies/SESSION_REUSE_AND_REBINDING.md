# Session Reuse and Rebinding

Future Mission Controls must treat workcell authority and model/provider session lifetime as separate things.

```text
CELL STOP != SESSION DESTRUCTION
```

A worker may not self-select another task when a cell ends. The orchestrator may keep the underlying session alive and later bind it to a new separately compiled workcell.

## Default

```text
REUSE_IF_RECEIPT_MATCHES
```

`FRESH_ONLY` is an explicit reason-bearing exception.

## Session residency registry

Context overlap is not enough to reuse a session: the orchestrator needs an addressable provider/native continuation identity.

Every cognitive dispatch/settlement therefore updates a registry conforming to `SESSION_RESIDENCY_REGISTRY_SCHEMA.json` with the provider, native session identity when exposed, worker/cell/attempt identity, target base, ContextReceipt ref/hash, continuation support, compaction state and last observed residency.

If no durable native identity is exposed, record `IDENTITY_UNAVAILABLE`; never infer a reusable session from a worker label or historical receipt alone.

Authored affinity hints may name a source cell, but actual `candidate_session` selection is runtime-resolved from the registry plus accepted receipt evidence. Accepted workcells/receipts remain immutable.

## Reuse decision

For pending cell `C` and addressable live session `S`:

```text
required(C) = exact context required by C
proven(S)   = still-fresh accepted ContextReceipt coverage

ALREADY_COVERED = required(C) ∩ proven(S)
INGEST_DELTA     = required(C) - proven(S)
INVALIDATE       = prior context no longer safe/fresh
```

Reuse requires addressable residency, compatible versions, freshness, safe/unsafe scope, remaining context/runtime budget and acceptable contamination risk.

## Hot-before-cold law

Before creating a fresh cognitive session, evaluate compatible live sessions from the residency registry. Prefer reuse when reuse + delta has lower total accepted-progress cost.

Cold spawn remains valid when no safe/addressable match exists or a recorded marginal critical-path/parallelism benefit exceeds re-ingestion savings.

If a compatible hot session exists and a fresh one is still selected, record why.

## Wide frontiers

Ready width is not fresh-session width. A useful scheduler may open several sessions, keep them hot, and feed related compiled cells to them as they finish. This preserves parallelism without repeatedly hydrating the same project context.

A deterministic frontier compiler should emit affinity hints from exact context overlap/subsystem locality/downstream consumers. Runtime ContextReceipt + session-residency evidence outrank those hints.

## Acceptance

Prove:

- provider/native session identity is captured whenever available and remains addressable after cell STOP;
- identity-unavailable sessions are explicitly typed and are never falsely reused;
- related cells can reuse a session and ingest only a delta;
- unrelated/stale sessions are rejected;
- STOP blocks worker self-selection but does not force session destruction;
- `FRESH_ONLY` without a reason is invalid;
- the scheduler can still expand fresh parallel width when its marginal value is higher.
