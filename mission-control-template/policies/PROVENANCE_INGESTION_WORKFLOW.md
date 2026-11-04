# Provenance Ingestion Workflow

This policy is the reusable Mission Control workflow for turning admitted provenance into implementation-grade target improvements. It composes `SOURCE_EXHAUSTION_AND_ENGINEERING_LEDGER.md`, `PROVENANCE_SYNTHESIS.md`, `SCOPE_COMPLETENESS_AND_NO_MINIMALIZATION.md`, `MCV_ENGINEERING_AUDIT_AND_ADJUDICATION.md`, and `NATIVE_TASK_PIPELINE.md`.

It is intentionally target-generic. A mission may specialize capability lanes, owner-pinned runtime obligations, rights rules, GUI/domain requirements, or phase topology, but it must not weaken the ingestion-depth laws below without explicit owner authority.

## Objective

Use provenance to materially improve the target system, not merely to cite, summarize, wrap, minimally imitate, or sample donors.

The material mechanism is the unit of ingestion. Repository, paper, document, package, service, asset, or prior-mission identity establishes provenance custody; it does not justify one repository-level disposition when the source contains multiple materially distinct mechanisms.

A source is not consumed merely because:

- its README or architecture was summarized;
- one headline feature was mapped;
- a dependency, registry row, provenance note, schema field, configuration flag, TODO, wrapper, adapter shell, or stub was added;
- an existing target feature has a similar name;
- the easiest donor subset was selected;
- the source was marked reviewed without complete mechanism accounting.

## Minimality boundary

Closed-loop audit methodology deliberately prefers the smallest correct intervention for closing one material finding and avoiding gratuitous refactors.

That rule applies to the correction used to close the current finding. It does **not** authorize:

- reducing the set of materially valuable mechanisms that must be assessed;
- shrinking an accepted mechanism to an MVP or surface-only form;
- omitting failure, recovery, persistence, migration, diagnostics, authority, security, performance, resource, UX, or real-environment behavior that is material to the mechanism;
- choosing a lower-value integration solely because it is easier;
- treating implementation effort, novelty, unfamiliarity, schedule pressure, model context, or worker capacity as a source disposition.

Execution may be decomposed. Accepted capability scope may not be silently minimized.

## Source exhaustion and mechanism inventory

Review sources in bounded, checkpointed tranches. Do not use an unbounded "read everything, then summarize" pass.

For the reviewed source boundary:

1. Freeze exact source identity, revision/version, integrity evidence, and rights/reuse boundaries.
2. Build or verify the source surface map so omitted subsystems can be detected.
3. Inspect every critical partition and either inspect or explicitly exclude every noncritical partition with evidence-backed rationale.
4. Inventory every materially distinct mechanism, invariant, representation, workflow, operator, algorithm, policy, extension point, lifecycle, recovery behavior, diagnostic strategy, performance/resource technique, test/qualification technique, reusable asset, and reusable capability discovered in the covered source.
5. Record exact evidence locators and limitations/failure modes for every material mechanism.
6. Do not claim source exhaustion while any material mechanism is unenumerated, undispositioned, or represented only by a generic summary.

Representative sampling is not source completion.

## Mandatory per-mechanism ingestion record

Every material mechanism must produce enough durable evidence to answer all of the following.

### Source evidence

- exact source ID/version and evidence locator;
- mechanism/invariant and observable value;
- internal state, data/control flow, algorithm/process, lifecycle, failure modes, and assumptions;
- rights/reuse boundary and retained obligations;
- source-specific strengths that would be lost by flattening or shallow wrapping.

### Current target state

Independently inspect the actual current target owners/files/symbols or equivalent concrete target surfaces. Classify the relationship as one of:

- true semantic equivalence;
- partial/inferior overlap;
- complementary mechanism;
- no implementation/gap;
- incompatible/nonportable;
- out of owner-authorized product scope.

Similar names or broad categories are not proof of equivalence. Compare invariants, state/authority, failure/recovery, diagnostics, performance/resource characteristics, security/trust, migration/compatibility, and specialized semantics.

### Disposition

Use the mission's canonical disposition vocabulary. At minimum, the outcome must distinguish implementation/extension/combination, already satisfied behavior, evidence-backed rejection, owner-authorized deferral, and concrete blocking dependencies.

For accepted mechanisms, record the exact reuse/custody mode. For rejected or deferred mechanisms, preserve the reason, residual gap, consequence, and re-entry condition. Difficulty alone is not a disposition.

### Improvement value

State what materially becomes better in the target: capability, correctness, reliability, recoverability, performance, resource efficiency, security, maintainability, UX, observability, composability, reuse, portability, qualification quality, or reduced future model reasoning.

When evidence supports it, explicitly search for amelioration, enhancement, hardening, simplification, generalization, acceleration, cross-verification, or reuse opportunities beyond literal donor parity.

### Implementation depth

For every accepted mechanism, produce an implementation-grade target after-state precise enough that the later mutation stage should not need to rediscover the donor merely to understand what must be built.

Cover every relevant layer:

- target authority owner and exact planned locations;
- state/data/schema and serialization contracts;
- APIs/CLI/protocol surfaces;
- orchestration/workflow and compiler/lowering paths;
- runtime/backend/provider/tool integration;
- persistence/cache/invalidation;
- transactions/effects/idempotency;
- failure/recovery/rollback;
- observability/diagnostics;
- security/privacy/trust;
- UX/editor/operator surfaces;
- compatibility/state/schema migration;
- deployment/operations;
- performance/resource calibration;
- provenance/SBOM/license/attribution;
- positive, negative, hostile, failure-path, integration, native-environment, and end-to-end qualification.

Code or configuration presence alone is not proof of ingestion.

### Fusion and specialization

For each mechanism, compare relevant current-target and cross-source capabilities. Evaluate as applicable:

- `COMPOSE` — keep distinct mechanisms behind one higher-level capability;
- `BRIDGE` — create typed translation between representations/state models;
- `LOWER` — use one representation as a higher-level form and another as execution substrate;
- `WRAP` — preserve a specialized backend behind target authority/contracts;
- `CROSS_VERIFY` — use independent mechanisms to detect disagreement or bugs;
- `HYBRIDIZE` — combine complementary strengths into a new mechanism;
- `PROMOTE` — generalize a successful composition into reusable target capability.

Normalization must preserve valuable specialized semantics. Lowest-common-denominator unification is a defect when it erases behavior that materially improves the target.

## Phase A — source-local construction

The source-owning reviewer must:

- exhaust the assigned source boundary in bounded tranches;
- build the complete material-mechanism inventory;
- inspect relevant current target owners independently;
- distinguish `SOURCE_FACT`, `ENGINEERING_INFERENCE`, and admission/authority;
- produce per-mechanism target comparison, disposition candidate, improvement value, implementation-grade target delta, fusion analysis, qualification, rights posture, and rejected/deferred reasoning;
- preserve exact coverage/next cursor and immutable handoff evidence.

Phase A fails if it only summarizes the source, samples representative features, or proposes shallow wrapper/stub integration.

## Phase B — independent evidence review

A different author/seat/session independently assesses the canonical source and immutable Phase-A evidence. Inspect or verify further where the scope, material claims, and risks justify it.

Phase B assesses whether the evidence supports the claimed scope and disposition. As applicable, it examines:

- skipped or collapsed mechanisms;
- false target equivalence;
- convenience-driven rejection or deferral;
- lowest-common-denominator normalization;
- wrapper-only or surface-level integration;
- missing failure/recovery, migration, observability, security, performance, or real-environment behavior;
- weak qualification or self-fulfilling tests;
- missed fusion/composite opportunities;
- rights/custody errors;
- target-owner or authority miswiring.

A terminal Phase-B package preserves immutable incoming/outgoing evidence and does not grant shared authority by itself.

## Phase C or mission-defined adjudication

When the mission defines a third independent phase, serial adjudicator, convergence barrier, or owner-review step, it must require a terminal disposition for every material mechanism.

Accepted mechanisms may not survive adjudication with a plan that is:

- surface-level;
- wrapper/stub-only;
- under-qualified;
- vague enough to require donor rediscovery during implementation;
- missing preserved specialized semantics;
- silently reduced relative to the evidence-backed improvement.

Non-runtime or rejected outcomes are valid when evidence supports them, but no material mechanism may disappear through convenience.

Mission-specific authority topology wins over this generic label: do not invent a generic Phase C where the mission defines another adjudication barrier.

## Cross-source convergence

A source is not fully consumed until its mechanisms are compared with the relevant target capability lanes and overlapping terminal findings.

Wave/corpus convergence must:

- map accepted mechanisms, not merely source identities;
- resolve equivalence, complementarity, conflicts, owner collisions, and duplicate authority;
- preserve source-specific strengths;
- identify superior composite designs;
- retain rejected/deferred mechanism reasons and re-entry conditions;
- ensure every accepted mechanism maps to target requirements/cells/verification or is independently proved already satisfied;
- ensure every materially used source remains traceable through target provenance/lineage.

No source island and no mechanism orphan may remain at mutation admission.

## Completion and later mutation law

A source-review phase is complete only when exact source coverage, mechanism inventory, per-mechanism dispositions, current-target comparison, implementation-grade target deltas for accepted mechanisms, preserved semantics, fusion analysis, rights, qualification implications, rejected/deferred reasons and re-entry conditions, validation, unresolved questions, and durable receipts are recorded.

The later mutation stage may optimize implementation shape, reuse native external assets, reorganize owners, or choose a better target-native design. It may not silently reduce the admitted mechanism set or required end-to-end behavior. A reduction requires a new evidence-backed adjudication under the mission's authority rules.
