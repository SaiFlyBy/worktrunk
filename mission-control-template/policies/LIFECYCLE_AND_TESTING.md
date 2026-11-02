# Lifecycle and Testing

Mission Control v16 has one explicit lifecycle:

`BOOTSTRAPPED -> BASELINE_READY -> BASELINE_ACCEPTED -> MUTATION_READY -> INTEGRATING -> QUALIFYING -> ACCEPTED -> CLOSED`.

Authoritative transitions run `doctor` first and fail closed on structural incoherence.

## Baseline gate

Every mission receives the generic A000-A004 audit frontier and G000 barrier. Before baseline compilation, the operator must load a non-empty `TARGET_MUTATIONS.json` through `mc corpus load`; requirement source IDs must resolve through the transactionally loaded `SOURCES.json`. Baseline compilation freezes both semantic inputs and hashes them into every compiled ContextManifest. Mutation dispatch is forbidden until all baseline audit results are accepted and G000 is crossed. Executable dependencies must be phase-monotonic: mutation/audit work cannot depend on integration or qualification authority, and integration work cannot depend on qualification authority. G000 is the only baseline-phase barrier; every barrier compiled afterward must depend transitively on a `MUTATION`, `INTEGRATION`, or `QUALIFICATION` cell so its inferred phase has a reachable lifecycle in which it can be accepted. Barrier acceptance is purely topological and must be exactly `all dependencies are ACCEPTED`; any additional condition belongs in an executable workcell whose result is independently adjudicated.

The generic A000-A004 frontier remains intentionally small because it is universal. Large/high-risk missions add explicit audit cells for the engineering contracts below rather than pretending every project has the same language, platform, or deployment topology.

## Engineering design gate

A mission that mutates a target must complete a specification/provenance/structure design gate before the first ordinary mutation is authoritative.

The canonical high-assurance artifacts are:

- `control/SPECIFICATION.json` validated by `SPECIFICATION_CONTRACT_SCHEMA.json`;
- `corpus/ENGINEERING_LEDGER.json` validated by `ENGINEERING_LEDGER_SCHEMA.json`;
- frozen dynamic collection snapshots under `corpus/source-collections/` when owner intent names collections rather than a closed source list, validated by `SOURCE_COLLECTION_SNAPSHOT_SCHEMA.json`;
- one source map per admitted repository-scale source under `corpus/source-surfaces/`, validated by `SOURCE_SURFACE_MAP_SCHEMA.json`;
- structural mutation plans under `control/structural-mutation-plans/` for nontrivial code/config mutation surfaces, validated by `STRUCTURAL_MUTATION_PLAN_SCHEMA.json`;
- `control/CI_QUALIFICATION_MATRIX.json`, which may begin with `PENDING` gates during design but must enumerate the release evidence expected from the exact candidate.

Run both validators before ordinary mutation dispatch in missions that opt into the high-assurance engineering contract:

```text
runtime/tools/validate_source_collections.py --root <mission-root> --phase pre-mutation
runtime/tools/validate_engineering_contracts.py --root <mission-root> --phase pre-mutation
```

The source-collection validator is a no-op when the mission has no dynamic collections. When collections exist, it freezes exact membership, reconciles every member to `SOURCES.json`, and requires terminal adjudication plus exhausted source-surface coverage before mutation.

Any validation failure is a design blocker, not a reason to weaken the contract. The mission's cells/acceptance criteria must bind these gates so they cannot be bypassed by an orchestration path that does not call the validators automatically.

Specification is upstream authority. A meaning-bearing specification amendment after cells have been compiled makes affected packets/evidence stale and requires re-planning/re-compilation for the changed behavior. An amended specification is re-frozen before mutation resumes. Implementation must converge back to the specification; tests may not be rewritten merely to bless accidental behavior.

Full mission scope remains mandatory. Cell decomposition is execution structure, not permission to reduce accepted owner intent to an MVP/POC/subset. Every frozen collection member, admitted source mechanism, and active target requirement must have durable terminal accounting before candidate readiness.

## Compiled dispatch and settlement

A compiled executable cell always materializes two artifacts from one pure construction path:

- `CompiledWorkCell`, carrying exact base, conflict/resource claims, acceptance and output contracts;
- `ContextManifest`, carrying exact authority/cell context and base identity.

`doctor` validates both against their executable schemas, reconstructs both from canonical authority, and compares them to the materialized files. Check-mode, schema enforcement, and materialization therefore cannot silently diverge.

Dispatch freezes distinct worker and verifier custody identities before execution. Settlement requires `--attempt`, worker-owned `result.json` and `context_receipt.json`, plus control-owned `adjudication.json`. The ContextReceipt worker and adjudication verifier must match those preassigned identities; the worker result is a claim, not authority. The adjudication is produced under separate verifier custody, must identify a verifier identity/session distinct from the worker, and binds canonical SHA-256 values for the exact worker result, ContextReceipt, CompiledWorkCell and ContextManifest. An `ACCEPTED` adjudication must additionally set `verified_acceptance` to the exact compiled acceptance criteria. Authoritative cell state is derived only from the adjudication decision. Attempt identity is monotonic; all three artifacts are stored under immutable per-attempt paths, and stale/late evidence cannot settle a newer attempt. A non-accepted adjudicated attempt may be reopened only through `mc retry`, which preserves prior attempt history. An accepted executable cell must retain durable result/receipt/adjudication references. Its ContextReceipt is immutable evidence of consumed context, coverage, unknowns and safe/unsafe continuation scope. The receipt must bind the exact ContextManifest SHA-256, may name only manifest context ids, and an `ACCEPTED` worker claim requires every `REQUIRED` manifest item to be consumed.

Every settlement also records provider/native continuation identity in `control/SESSION_RESIDENCY.json`. Absence of a provider session handle is represented as `IDENTITY_UNAVAILABLE`; worker identity is never substituted for a native session id.

Aggregate normalization is forbidden. Malformed structured evidence is repaired within the attempt or rejected before settlement.

## Structural mutation gate

Cells that change source/configuration structure must declare a mutation strategy proportionate to the surface. Parser/AST/language-server/schema-aware/generator-owned transformations are preferred when the intended edit depends on syntax, symbols, scopes, schemas, imports, call relationships, or generated ownership.

Blind regex/string rewriting is not an acceptable substitute merely because it is faster to author. `TEXT_ONLY_WITH_JUSTIFICATION` requires an explicit rationale and hostile checks for overmatch, undermatch, comments/strings, generated/vendor regions, formatting, and idempotency. Parse failure is evidence and must not trigger an unrecorded fallback.

Structural analysis can be implemented with Tree-sitter, compiler ASTs, language servers, OpenRewrite-like engines, queryable IRs, or target-native generators; the mission chooses the strongest mechanism for the language/surface and records exact tool provenance/version when it materially affects mutation.

## Parallel admission

Every cell declares a `conflict_class` and explicit `resource_claims`. A dispatch is rejected while another active cell has the same conflict class or an overlapping resource claim. This conservative executable boundary may later be refined by a richer conflict graph, but it cannot be bypassed by omitting safety metadata.

The local CLI does not claim to know provider, host, verifier, or downstream service capacity. `COMPILER_CONTROL.capacity_authority` is `EXTERNAL_ORCHESTRATOR`; that orchestrator is responsible for dynamic safe/useful width and backpressure before calling local dispatch. The local executable admission law therefore proves dependency and conflict/resource safety only, rather than falsely labeling an unobserved capacity decision as `capacity-safe`.

For large source corpora, parallel source-review seats are a throughput mechanism only. The frozen source-collection snapshot and source registry remain the coverage authority. Queue width, model availability, or context limits never remove source members from the mission.

## Requirement and closure accounting

Each `MUTATION` binds one or more active canonical target `requirement_ids`. Every requirement `targets` entry is an exact repository already frozen in `MISSION.json`; a mutation may bind a requirement only on one of those repositories, and integration requires bound mutation coverage for every target repository listed by every active requirement. Every acceptance clause of every active requirement must also appear in bound mutation-cell acceptance contracts on every repository targeted by that requirement before integration, and accepted adjudications attest those compiled criteria explicitly. A requirement may be waived only in `TARGET_MUTATIONS.json` before baseline compilation, with immutable reason/authority; waived requirements must not receive mutation-cell authority. Integration is forbidden until every active requirement has complete target-repository mutation coverage, all active requirement acceptance clauses are carried into those cells, and all mutation-phase cells/barriers are accepted. Final qualification must accept exactly the active requirements and reproduce every frozen waiver exactly. Each accepted `INTEGRATION` result must enumerate every accepted mutation cell and bind its exact immutable result head through `integrated_mutations`. Accepted integration cells must then converge on exactly one head per mission target; accepted `QUALIFICATION` results must prove those same heads at settlement time, and terminal `target_outcomes` must match them. Its `verification_accounting.run` must equal the acceptance criteria independently adjudicated on accepted `QUALIFICATION` workcells; terminal accounting cannot invent a verification that no qualification workcell proved. It also records target baseline/accepted-head pairs plus verification waivers/not-run accounting. Frozen requirement waivers, verification waivers, not-run verification, or unresolved defects require explicit limitations. `close` is deterministic: it binds the immutable qualification hash and copies this accounting rather than inventing a cleaner terminal story.

The engineering ledger adds another accounting dimension for high-assurance missions: source/owner intent -> mechanism -> specification behavior -> requirement -> mutation cell -> verification -> qualification gate -> landed location. Any orphan in that graph is a defect, not harmless documentation drift.

## CI/CD qualification gate

Qualification is evidence for the exact integrated candidate, not an aggregation of historical green runs.

`control/CI_QUALIFICATION_MATRIX.json` enumerates required proof classes, supported environment/platform combinations, exact candidate SHAs, workflow/command identities, real-path status, behavior/requirement coverage, evidence/artifacts, and skip/waiver classification.

Before final acceptance run:

```text
runtime/tools/validate_source_collections.py --root <mission-root> --phase qualification
runtime/tools/validate_engineering_contracts.py --root <mission-root> --phase qualification
```

For required gates, `FAIL`, `BLOCKED`, and `NOT_RUN` are release blockers. A required skip/xfail/environment fallback is not a pass. A waiver is visible authority with rationale, not an automatic conversion of missing evidence into green status.

CI definitions are production code: use least privilege, immutable action/tool revisions where practical, secret-safe trust boundaries, reproducible inputs, and retained release/provenance artifacts. Deployment-changing missions additionally qualify the actual deployment/reconciliation path and rollback/recovery behavior.

## Tests

The canonical proof taxonomy has four ordered layers:

1. `unit_regression`: static template/schema/CLI coherence, test-classification contracts, dynamic source-collection intake, engineering-contract schema/semantic checks, policy/index integrity and CI workflow pinning;
2. `e2e`: the hostile runtime state-machine suite and generated-mission golden lifecycle, including semantic-input loading, compiler parity, retries/crash recovery, conflict-safe admission, typed integration/qualification, accounting rejection and deterministic closure;
3. `performance_load`: external-observer integrity, bounded observer overhead, doctor scaling and soak/no-drift characterization;
4. `environment_integration`: the arbitrary-mission structural suite, including canonical v16 and the v15-derived MCV6 compatibility adapter against an explicit environment mission root.

All four layers are required for FlyByRefactor's reusable-template qualification because `archive/mission-control-v6` is a repository-tracked compatibility fixture. Downstream missions may classify environment integration as optional only when their machine catalog explicitly does so, no compatible live/fixture mission exists, and the omission has an explicit risk rationale. A required layer that cannot obtain its environment is blocking rather than green. `tests/TEST_LAYERS.json` is the machine authority for layer order, requiredness, proof ownership and commands; `tools/run_template_suite.py` executes that catalog and preserves raw evidence.

The FlyByRefactor repository additionally runs the complete template suite through GitHub Actions across Linux, Windows and macOS on multiple supported Python versions, plus a trusted same-repository self-hosted Windows matrix. Untrusted fork pull requests do not receive the self-hosted runner. A separate pinned Actionlint workflow validates Mission Control workflow definitions so a malformed candidate workflow cannot be its own only validator. External Actions are bound to immutable commit SHAs and the workflows use read-only repository permissions. CI checks out and asserts the exact pull-request head rather than relying on GitHub's synthetic merge ref. CI cannot replace the local/runtime proofs; it independently exercises them on clean runners.

Legacy compatibility checks are explicit; a legacy mission is not allowed to masquerade as canonical v16.

A future template revision must add its own adapter or migrate its mission layout before dropping an older adapter that is still required by a live Mission Control.
