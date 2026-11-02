# Scope Completeness and No-Minimalization

Mission Control executes the owner-authorized mission, not an unsolicited prototype of it.

## Core law

Decomposition is permitted. Silent scope reduction is not.

For provenance-ingestion missions, apply `PROVENANCE_INGESTION_WORKFLOW.md`: source review and later implementation account for material mechanisms rather than source names alone. Minimal correction size never authorizes a minimal capability surface.

A mission may be split into audits, mutation cells, integration tranches, qualification cells, and closure work for safety and reviewability. That execution decomposition never changes the promised end state. Terms such as `minimal`, `MVP`, `proof of concept`, `simplified`, `representative subset`, `good enough`, or `phase one` do not authorize dropping accepted scope unless the owner explicitly chose that reduction or a real blocker is recorded.

## Complete accounting

Before mutation dispatch, every owner requirement, admitted source-derived mechanism, accepted architecture decision, and required migration/compatibility obligation must have exactly one durable disposition:

- `IMPLEMENT` — new target behavior is required;
- `EXTEND` — an existing target owner is strengthened;
- `COMBINE` — multiple existing/source mechanisms are composed under one target owner;
- `ALREADY_SATISFIED` — current target behavior is independently verified to satisfy the contract;
- `REJECTED` — evidence shows the mechanism is inferior, incompatible, unsafe, redundant, out of scope, or otherwise should not enter the target;
- `DEFERRED_BY_OWNER` — the owner explicitly removed the item from the current mission;
- `BLOCKED` — a concrete dependency prevents safe implementation and the blocker has an owner and exact next action.

`DEFERRED_BY_OWNER` may not be inferred from cost, model context, schedule pressure, implementation difficulty, source size, or reviewer preference. `BLOCKED` is nonterminal and does not make a mission complete.

## Full-corpus missions

When owner intent says to ingest or assess an entire corpus, the mission must not select a few attractive sources or mechanisms and call the corpus reviewed. Every admitted source must reach the source-exhaustion contract or an explicit source-level rejection. Every surviving mechanism must reach disposition and target accounting.

Parallelism changes throughput, not coverage. Source reviews may run concurrently when custody is disjoint, but no source disappears because the available worker pool was smaller than the corpus.

## Existing-target judgment

Mission Control must not replace target behavior merely because a source is popular, newer, faster in a donor benchmark, or aesthetically cleaner.

For each proposed replacement or major migration:

1. inspect the current target owner and its surrounding contracts;
2. identify mature behavior, integrations, failure handling, observability, and compatibility that must survive;
3. compare source and target mechanisms on the target's actual requirements;
4. prefer preserve/extend/combine when that produces the stronger whole;
5. replace only when the resulting target contract is demonstrably better and migration/rollback consequences are explicit.

The burden is symmetric: existing code is not sacred, and donor code is not automatically superior.

## Mission completion

A mission cannot reach candidate readiness while any accepted scope item lacks a terminal disposition, any `IMPLEMENT`/`EXTEND`/`COMBINE` item lacks mutation-cell coverage, any active requirement lacks acceptance coverage on every target, or any required verification lacks authoritative evidence.

A green subset is not a green mission.
