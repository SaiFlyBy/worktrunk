# Control Laws

These are the detailed reusable control laws carried forward from template v15. The v16 operator surface is simpler; these laws remain normative unless a newer policy explicitly supersedes one.

# Reusable Mission Control Template

This template captures the reusable control-plane methodology learned through MCv5. It is intended for MCv6+ or any later external Mission Control campaign until FlyByMaestro can self-host equivalent engineering safely.

It is a **methodology template**, not a copy of MCv5's target architecture.

## 0. Instantiate, do not improvise

For v16, the author binds only the durable owner decisions in `MISSION.json`: mission identity, control repository/branch, exact target repository baselines, previous-mission handoff, owner intent, and hard boundaries. `mc init` derives the control root, canonical authority paths, baseline DAG, runtime and schemas; authors do not manually bind those internal filenames.

Before G000 can cross, admit provenance through `mc sources load` and load the machine-readable target requirements through `mc corpus load`. Those semantic inputs become frozen baseline authority at `BASELINE_ACCEPTED`.

Do not begin target mutation until these identities and semantic inputs are durable.

## 1. Three-layer separation

Every Mission Control must separate:

```text
CONTROL SYSTEM
  how this Mission Control operates

TARGET MUTATION CORPUS
  what the target product/system must become

REUSABLE TEMPLATE
  what operating methodology should survive into the next Mission Control
```

Every new useful mechanism receives one transfer class:

```text
MISSION_CONTROL_ONLY
TARGET_ONLY
BOTH
```

A `TARGET_ONLY` or `BOTH` mechanism must become a target-corpus requirement with implementation and acceptance binding. A `BOTH` or reusable control improvement must also update this template before mission closure.

## 2. Authority model

Default external-author workflow:

```text
owner
  Γåô
Mission Control overseer/author
  Γåô
authoritative working branch
  Γåô
compiled workcells
  Γåô
scoped local/remote executors
  Γåô
candidate branches/worktrees/realms
  Γåô
oversee/adjudicate/reconcile
  Γåô
authoritative working branch
```

Laws:

- main/default target branch remains untouched during authoring unless explicitly authorized;
- overseer/author is the primary author, not a delegation router;
- executor is scoped execution/repair, not broad architecture authority;
- executor mutation begins from exact author branch/head;
- executor cannot claim the next workcell;
- executor cannot weaken acceptance or broaden semantic authority;
- changes outside owned scope require recompile/amendment, not improvisation.

Provider/model identity is not architectural authority.

## 3. Previous-mission handoff

Create a machine-readable handoff binding:

```text
previous mission terminal status
control-plane closure commit
accepted target head/baseline
tests/evals actually run
tests/evals waived/not run
remaining/terminated work
known limitations
owner decisions
```

Never infer coverage from work that was terminated, waived, skipped or merely planned.

## 4. Canonical target corpus

Create one machine-readable target mutation corpus before wide execution.

Every v16 target requirement carries an immutable id, name, admitted source/provenance ids, target scope, and hostile/measurable acceptance. Mutable execution state does not live in the corpus: mutation cells bind `requirement_ids`, while final accepted/waived disposition and waiver authority live in qualification/closure accounting.

A design conclusion present only in prose is not safely ingested.

## 5. One canonical execution graph

Use one canonical machine DAG/frontier authority.

Side analyses/overlays may exist as provenance but cannot become a second scheduler authority.

A DAG node/topic is **not** an executable prompt.

## 6. Workcell compiler bootstrap

v16 supersedes manual bootstrap composition with the built-in A000-A004/G000 baseline frontier and one deterministic compiler. Mission-specific frontier descriptors enter the same final schemas only after G000 is accepted.

```text
intent/requirement
ΓåÆ DAG cell
ΓåÆ CompiledWorkCell
ΓåÆ ContextManifest
ΓåÆ bounded execution
ΓåÆ ContextReceipt
ΓåÆ typed result
ΓåÆ adjudication
ΓåÆ next-frontier update
```

No ordinary cell may bypass compiled dispatch.

## 7. CompiledWorkCell contract

Every executable cell declares at minimum:

```text
cell id
source requirement/DAG cell
exact base repository/branch/head
objective
why ready
semantic authority
owned scope
prohibited scope
conflict/resource claims
dependencies + accepted receipts
context manifest
acceptance
negative tests
local verification
mutation policy
failure policy
return contract
stop condition
session/context reuse decision
```

Workers execute this contract. They do not orient themselves globally.

## 8. Context compilation

A ContextManifest selects exact required knowledge using addressable locators and source/version identity.

Invalid primary context instructions:

```text
read the repo
understand the system
inspect whatever seems relevant
research the architecture
```

If discovery is necessary, compile a bounded discovery cell with a typed downstream consumer.

Context should distinguish:

```text
STABLE_AUTHORITY_PREFIX
TASK_CONTEXT_PREFIX
VOLATILE_RUNTIME_TAIL
```

A ContextReceipt records what was actually consumed and what remains outside the worker's proven coverage.

## 9. Hot-session/context reuse

Warmth is an optimization, not authority.

Reuse only when an accepted receipt proves compatibility:

```text
base/version compatible
required semantic coverage matched
freshness valid
safe_reuse_scope includes new cell
remaining context/runtime budget adequate
contamination/staleness acceptable
```

Compiler outputs:

```text
REUSE_SESSION
ALREADY_COVERED
INGEST_DELTA
INVALIDATE_FROM_PRIOR_CONTEXT
```

Otherwise use a fresh resource.

## 10. Read-only work law

A read-only/research/archaeology cell must name:

- a typed output artifact consumed by named downstream cells; or
- an explicit acceptance/evaluation purpose.

Do not spawn agents merely to understand the project.

## 11. Dynamic parallelism

Never hard-code concurrency merely because a prior mission used a particular agent count.

Track:

```text
ready_width
safe_width
useful_width
admitted_width
```

`safe_width` accounts for dependency, authority, semantic/write/resource conflicts, provider/session capacity, host/workspace/realm capacity and hard operator constraints.

`useful_width` accounts for critical-path gain minus context, coordination, verification/integration, quota, correlated-failure and rework costs.

No static policy ceiling is required unless imposed by the operator/resource/platform.

## 12. Conflict graph and integration tranches

Build dynamic conflict components from:

```text
paths/writes
semantic authority
shared mutable resources
external services
schema/migrations
credentials/permissions
environment mutation
integration target
verification/test leases
```

One isolated branch/worktree/realm per mutating cell.

Use semantic tranche/component integration branches where useful:

```text
canonical author branch
  Γåô
component/tranche integration branches
  Γåô
cell branches/worktrees
```

Parallelize independent sets both across and, when safe, within connected conflict components.

Serialize only the true conflicting transitions and smallest canonical-ref/state advancement critical section.

Independent repository/component merge queues may operate concurrently.

## 13. Continuous reconciliation

Do not wait for an arbitrary wave boundary when a cell is accepted and useful downstream work can unlock.

Continuously:

```text
adjudicate
reconcile
refresh conflict graph
refresh base/staleness
recompute frontier
admit new work
```

Wave labels are organizational unless a real global barrier exists.

## 14. Downstream backpressure

Mutation generation cannot outrun verification, integration, evaluation or ingestion indefinitely.

Observe queue depth/age and service rates.

When pressure rises:

1. preserve critical-path work;
2. reduce/defer low-value mutation;
3. redirect capacity to bottleneck services where safe;
4. scale bottleneck capacity where possible;
5. reduce mutation width;
6. never weaken acceptance to drain a queue.

## 15. Deterministic vs cognitive work

Do not allocate LLM cognition to work with no semantic decision requirement.

Use deterministic lanes for deterministic projection, validation, reconciliation, indexing, backfills, identity checks or other mechanically defined work when feasible.

The task record/workcell says what the work is. The lane says whether cognition is required.

## 16. Failure semantics

Terminal states are typed. At minimum distinguish:

```text
COMPLETED
ACCEPTED
REJECTED
FAILED
BLOCKED
PENDING_APPROVAL
TIMEOUT
HALTED
PARTIAL
STALE
SUPERSEDED
CANCELLED
```

Fluent partial output must never look like completion.

Durable attempt identity, leases/idempotency, recovery and late-result rejection are required where side effects exist.

## 17. Evidence and adjudication

Model self-report/confidence is never primary truth.

Separate:

```text
observation
claim
evidence
evaluation
state transition
```

Verification strength is risk-sensitive. Deterministic claims prefer deterministic checks.

Worker result/ContextReceipt artifacts are candidate evidence. Worker and verifier custody identities are assigned distinctly by the control plane before dispatch and frozen for the attempt. Authoritative settlement requires a separate control-side adjudication whose verifier identity matches that preassignment and whose ContextReceipt worker matches the assigned worker. The adjudication must bind the exact result, ContextReceipt, CompiledWorkCell and ContextManifest. Only the adjudication decision may change authoritative cell state.

Only independently adjudicated, evidence-backed accepted results unlock dependent authority.

## 18. Diagnostic recovery and learning

Do not learn directly from failure appearance.

```text
expectation
ΓåÆ observation
ΓåÆ gap
ΓåÆ competing cause hypotheses
ΓåÆ discriminating evidence
ΓåÆ cause assessment
ΓåÆ minimal recovery candidate
ΓåÆ bounded trial
ΓåÆ independent evaluation
ΓåÆ keep/revise/reject/promote/rollback
```

`gap != cause`.

Worker self-diagnosis is a hypothesis.

`UNKNOWN` is a valid cause assessment.

Investigate unexpectedly good outcomes too.

## 19. Independent improvement governance

The proposer cannot silently define the evaluation bar that promotes its own change.

Use versioned baseline/eval contracts, held-out/canary evidence where appropriate, scope-limited rollout, attribution and rollback lineage.

Prefer policy/state adaptation before source self-modification.

## 20. Selective metacognition

Critic/reviewer/reflection machinery is conditional.

Activate it when consequence, uncertainty, missing-context value or probability of changing a decision warrants the cost.

If deterministic evidence already settles a low-risk question, do not create critic loops for ceremony.

## 21. Predictive resource/workflow control

Forecasting is optional and must be evaluated against reactive/static baselines.

Potential signals:

```text
provider latency/quota
work arrival
task duration
verification/integration backlog
repair rate
context hydration cost
session churn
host resource pressure
```

Forecasts are advisory control inputs, not evidence or authority.

## 22. Donor/research ingestion

Every external source is provenance, not runtime authority.

Use:

```text
donor capability
ΓåÆ underlying problem
ΓåÆ existing target capability inventory
ΓåÆ useful semantic principle
ΓåÆ deterministic authority/enforcement boundary
ΓåÆ measurable target requirement
```

Do not copy vendor agent hierarchies, retry counts, file formats or product surfaces without demonstrating why their semantics are required.

## 23. New organ/primitive promotion

A new organ may emerge. Do not suppress it to preserve a prior architecture count.

Promote when it owns independent state, lifecycle, failures, semantic/authority boundary, acceptance and cross-system consumers.

Otherwise extend existing physiology.

## 24. Materialization law

If a conclusion changes mission execution, target requirements, acceptance, inheritance or future work, materialize it during the same design turn.

Chat-only conclusions are non-durable and must not be relied upon.

## 25. Anti-theater tests

Reject or flag:

- read-only work with no consumer;
- managers with no owned decision frontier;
- verification that cannot change acceptance;
- context packets that only duplicate prose;
- parallel branches that do not improve useful progress;
- control objects that never affect runtime behavior;
- repeated retries without causal strategy change;
- ornamental logs not consumed by decisions/recovery/evidence;
- wave barriers with no real global dependency;
- global serialization where conflict-local serialization suffices.

## 26. Current-state drift control

Before dispatch, compile from the current accepted author head.

After any accepted author/control change:

- invalidate stale pending packets whose exact base changed;
- recompile only affected cells;
- preserve previously accepted evidence when its source identities remain valid;
- do not force whole-campaign rereads/restarts without need.

## 27. Closure contract

A Mission Control closes only after:

```text
target requirements terminally accounted for
accepted target head bound
required hostile/behavioral gates adjudicated
waivers explicit
unresolved defects explicit
control-template improvements promoted
next-mission handoff materialized
archives/provenance distinguish historical from live authority
```

The closure artifact must state what was **not** run/proven.

## 28. Template self-update

Before mission closure ask, for every material control discovery:

```text
Was this campaign-local?
Should future Mission Controls inherit it?
Should the target product internalize it?
Both?
```

Update the template and/or target corpus immediately. Do not leave the answer in chat.
