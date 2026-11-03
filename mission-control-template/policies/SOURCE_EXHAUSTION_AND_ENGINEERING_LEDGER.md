# Source Exhaustion and Engineering Ledger

This policy supplements `PROVENANCE_SYNTHESIS.md`. Provenance synthesis explains how evidence becomes target requirements; this policy makes source coverage and downstream engineering accountability mechanically inspectable.

## Source collection intake

When owner intent names a dynamic collection rather than a closed source list — for example a GitHub star list, topic, search result, registry query, package collection, or generated manifest — Mission Control freezes the collection before source-review scheduling.

The snapshot records:

- collection identity and locator;
- observation time;
- retrieval mechanism;
- every pagination page/cursor or equivalent completeness witness;
- provider-reported total when available;
- immutable raw enumeration evidence;
- every discovered source identity and observed revision;
- exact item count;
- a canonical membership digest;
- a completeness assertion explaining why no additional page/member is expected.

Every captured repository becomes an explicit `SOURCES.json` entry before source-review work is scheduled. A collection item cannot disappear because a reviewer decided it looked uninteresting. It may later be rejected through the normal evidence-backed disposition path.

A frozen collection is mission intake authority. If the live collection changes while the mission runs, do not rewrite the historical snapshot or silently widen/shrink the active corpus. Record the delta and create an explicitly admitted follow-on wave/amendment when owner intent requires the new members.

For a full-corpus mission, queue coverage must reconcile against the frozen collection item-for-item. Worker capacity changes parallelism, not membership.

## Source surface map

Every repository-scale source admitted for synthesis receives a durable surface map before it can be called exhausted.

The map must inventory, when present:

- root packages/modules/components;
- architecture and design documents;
- public APIs/contracts/schemas;
- runtime/execution paths;
- storage/state models and migrations;
- tests, fixtures, fuzzers, conformance suites, benchmarks and evals;
- CI/CD, packaging, deployment and release machinery;
- examples/tutorials/reference applications;
- extension/plugin/provider interfaces;
- security/trust boundaries and threat-model material;
- observability, diagnostics and failure recovery;
- performance/caching/concurrency/resource-control mechanisms;
- license, NOTICE, dependency and generated/vendor boundaries;
- release notes/changelogs and material design discussions when they explain behavior not visible from current code.

The reviewer may partition a source by subsystem, directory, language, runtime, documentation section, or other stable boundary. Every discovered partition ends in one of:

- `INSPECTED`;
- `EXCLUDED_GENERATED`;
- `EXCLUDED_VENDOR`;
- `EXCLUDED_BINARY`;
- `EXCLUDED_IRRELEVANT_WITH_RATIONALE`;
- `BLOCKED`.

An exclusion is not omission. It carries a reason and enough evidence to show why inspecting that payload would not add target-relevant understanding. Critical partitions are inspected rather than excluded as irrelevant.

## Exhaustion standard

A repository is not exhausted because its README, architecture document, or main package was read. Exhaustion requires:

1. immutable source revision and rights record;
2. root inventory/surface map complete enough to detect omitted subsystems;
3. every critical partition inspected;
4. every noncritical partition inspected or explicitly excluded;
5. tests/CI/benchmarks/examples/release machinery reviewed for mechanisms not obvious in production code;
6. unresolved high-value questions closed or represented as blockers;
7. all discovered mechanisms accounted by the engineering ledger;
8. independent review challenges coverage and omissions;
9. source-local terminal receipt binds exact surface-map and mechanism-ledger digests.

Large repositories use bounded tranches and durable checkpoints; exhaustion is accumulated, never inferred from context-window confidence.

## Engineering ledger

The engineering ledger is not a bibliography. It is the mission's normalized accountability graph.

Every mechanism entry records at least:

- exact source identities and evidence locators;
- problem and observable value;
- mechanism internals: state, data flow, control flow, algorithm/process and lifecycle;
- role and authority boundary;
- dependencies, consumers, conflicts and composition relationships;
- current-target owner and inspected locations;
- target disposition and implementation/reuse mode;
- proposed/landed implementation locations;
- positive, negative, hostile and compatibility verification;
- failure modes and recovery/rollback;
- observability/diagnostics;
- security/privacy/trust-boundary impact;
- performance/resource impact and calibration needs;
- portability/environment constraints;
- license/rights obligations and required NOTICE/attribution/source-offer material;
- rejected alternatives and nonportable source-specific behavior;
- unresolved questions and confidence;
- final disposition and admission authority.

The ledger explicitly distinguishes `SOURCE_FACT`, `ENGINEERING_INFERENCE`, and `ADMITTED_TARGET_AUTHORITY`. No model summary may silently promote inference into authority.

## Cross-source synthesis

Duplicate or overlapping mechanisms from different sources are not independently implemented by default. The synthesis stage must identify equivalence, complementarity, conflict, and opportunities to combine mechanisms with mature target behavior.

A source may contribute only one small feature and still be worth retaining. Another source may contribute dozens. Review quota or source popularity does not determine engineering weight.

The material mechanism is the unit of ingestion. Repository-level labels do not substitute for mechanism-by-mechanism accounting when a source contains multiple materially distinct mechanisms. For every accepted mechanism, the engineering ledger must contain an implementation-grade target after-state: exact target owner/locations, preserved semantics, relevant end-to-end wiring, migration/operations consequences, qualification, and rights/reuse mode. A wrapper, stub, config flag, schema field, dependency declaration, provenance note, or other surface marker is not sufficient unless it genuinely realizes the mechanism's material behavior. See `PROVENANCE_INGESTION_WORKFLOW.md`.

## Target accountability

Every non-rejected admitted mechanism must map to one or more target requirements or be independently proved `ALREADY_SATISFIED`. Every active target requirement maps back to its source/owner mechanisms. Mutation cells, tests, qualification gates and landed implementation locations complete the chain.

Any orphan in this graph is a mission defect:

- collection member with no source-registry identity;
- repository source with no source-surface map;
- source mechanism with no disposition;
- admitted mechanism with no requirement;
- requirement with no implementing cell;
- cell with no requirement/spec behavior;
- behavior with no verification;
- release gate with no behavior claim;
- landed reuse with no rights/obligation record.

## Historical durability

Source payloads may be cleaned after adjudication, but collection snapshots, surface maps, mechanism findings, rights evidence, review receipts, engineering-ledger entries, and target lineage remain durable. Future missions may supersede conclusions but do not rewrite the historical evidence that produced them.
