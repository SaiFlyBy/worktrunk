# CI/CD Qualification

CI/CD is release evidence, not ceremony. A workflow name, green badge, or historical success is not authority unless the exact candidate and required production path were exercised.

## Exact-candidate law

Every required release gate binds:

- repository identity;
- exact candidate commit/tree;
- workflow/job or local authoritative command identity;
- runner/environment identity;
- toolchain/dependency identity where relevant;
- start/end time and terminal result;
- raw evidence/artifact references;
- the specification behaviors/invariants/requirements it proves.

Evidence from an older commit is stale after a meaning-bearing mutation.

If a required proof intentionally validates historical commits, migration ancestry, or hash-bound prior artifacts, CI must fetch enough repository history for those exact historical objects to exist. A shallow checkout that makes a required historical proof impossible is a blocked/failed qualification, not evidence that the historical contract is absent.

Reusable runners must also materialize hash-bound tracked text through the exact candidate's current Git attributes before byte-level proof. A prior checkout can retain stale working-tree line endings when a later commit changes `.gitattributes` without changing the referenced blobs. Rehydrate the hash-bound root from `HEAD`, then require a content-clean worktree and validate the resulting bytes; do not silently normalize evidence inside the verifier. Cleanliness must be decided from tracked content/index differences plus untracked paths, not from stat-cache-only porcelain noise when the worktree bytes already equal the candidate blobs. Line-ending policy belongs to each evidence authority: the current golden reference mission is sealed as LF, while the archived MCV6 compatibility fixture preserves its original CRLF text authority and leaves byte-preserved binary evidence outside text conversion.

## Required proof classes

A mission explicitly classifies which of the following are required for its risk surface:

- formatting/lint/static checks;
- CI/workflow-definition semantic validation;
- schema/contract validation;
- type checking;
- unit/regression tests;
- integration tests;
- end-to-end/user-path tests;
- property/model-based tests;
- fuzz/adversarial/hostile-input tests;
- mutation testing or equivalent test-effectiveness evidence for high-risk logic;
- concurrency/race/deadlock tests;
- deterministic replay/idempotency/order-invariance tests when behavior claims determinism or resumability;
- fault-injection/chaos/recovery tests for failure-sensitive distributed, persistent, external-service, or orchestration paths;
- migration/upgrade/downgrade/rollback tests;
- backup/restore/data-integrity tests when persistent state is release-critical;
- security and secret/supply-chain checks;
- reproducibility/hermeticity checks;
- compatibility/API/ABI/schema-breaking checks;
- performance/load/soak/resource tests;
- installation/package/distribution tests;
- executable documentation/example/conformance checks when documented workflows are part of the supported product surface;
- real external-service/provider/hardware/OS tests;
- deployment/reconciliation/smoke tests;
- observability/diagnostic assertions;
- provenance/license/SBOM/attestation checks when artifacts are distributed.

Not every project needs every class, but every omitted class that is relevant to the mission risk model must have an explicit rationale. Absence by default is not a decision. The mission must be able to explain why each class is required, equivalent to another gate for the specific risk surface, or genuinely inapplicable.

## Test effectiveness

A large passing test count is not evidence that the suite can detect regressions. High-risk logic should use one or more independent test-effectiveness mechanisms when practical:

- mutation testing;
- seeded known-bad fixtures;
- differential oracles;
- independently generated protocol vectors;
- property/model checks;
- historical regression corpus replay;
- fault injection that proves recovery assertions actually fire.

Mission Control must not optimize a mutation score, coverage percentage, or benchmark number in isolation. These are evidence signals tied back to specification behavior, not release goals by themselves.

## Platform and environment matrix

Portable claims require a platform matrix. If the supported product claims Windows, Linux, macOS, multiple runtimes, databases, architectures, accelerators, browsers, deployment substrates, or provider backends, qualification must identify which combinations are release-critical and which are sampled.

A matrix may reduce redundant combinations using evidence-based equivalence classes, but it may not call one environment representative of another without an explicit equivalence argument and hostile boundary coverage.

## No green-through-skipping

A required behavior that is skipped, xfailed, filtered, mocked away, replaced by a weaker backend, disabled by environment detection, or hidden behind an unavailable dependency is not a pass.

Required skips remain blocking until the exact candidate is exercised in an authoritative capable environment. Optional skips require classification showing they do not cover release-critical behavior.

Expected failures are defects or deliberately accepted limitations, not invisible successes. Their release impact must be explicit.

## Test independence

Tests must derive from specification/invariants and known failure modes, not merely mirror the implementation that was just written. High-risk changes require negative/failure-path tests that would fail if the implementation were subtly wrong.

Where practical, use independent or differential oracles: prior compatible behavior, reference protocol vectors, independently generated expected values, model/property checks, alternate implementations, external conformance suites, or deliberately corrupted/faulted executions.

## Stateful-system qualification

When the product owns durable state, qualification should cover the state transitions that can lose or corrupt it, not merely fresh-install behavior. Depending on the product, this includes migration forward/backward, interrupted migration recovery, backup creation, restore into a clean environment, partial write/crash recovery, replay/idempotency, schema compatibility, and degraded dependency behavior.

A backup that was never restored is not proven recovery. A migration tested only on an empty database is not representative evidence for a populated production-shaped state when the mission changes migration behavior.

## Workflow-definition validation

CI definitions must be validated independently of the workflow being changed. A malformed workflow can be rejected before any job exists, so a workflow cannot be the sole validator of its own parseability or expression/context semantics.

For GitHub Actions, use `actionlint` or an authoritative equivalent from a separate stable workflow/pre-merge gate. Bind the validator version and integrity material in provenance, validate exact candidate workflow bytes, and retain the validator result as qualification evidence. Equivalent CI systems require the same property: definition validation must still execute when the candidate workflow itself cannot start.

Workflow-definition validation complements, rather than replaces, executing the actual workflow on the supported runner matrix.

## CI security and reproducibility

CI definitions are production code. Missions should:

- grant least-privilege workflow permissions;
- pin external actions/tools to immutable versions/digests when feasible;
- isolate untrusted pull-request code from secrets and privileged credentials;
- prevent cache/artifact poisoning across trust boundaries;
- verify checksums/signatures for downloaded toolchains where supported;
- retain provenance for release artifacts;
- produce SBOM/license/NOTICE material when distribution obligations require it;
- protect deployment environments with explicit authorization and rollback paths.

## CD and deployment proof

Deployment is not proven by producing an artifact. Where the mission changes deployment/runtime behavior, qualification must cover the actual deployment/reconciliation path, post-deploy health, rollback/recovery behavior, and persistent-state compatibility.

Canary, staged, blue/green, or progressive rollout strategies may reduce blast radius but never substitute for correctness evidence. Where rollback is contractually required, rehearse the rollback or prove an authoritative equivalent rather than relying on an unexecuted document.

## Qualification matrix

Before final qualification, every required behavior maps to at least one exact release gate. Every required gate maps back to the behaviors it proves. The matrix records `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN`, or an explicitly authorized waiver; it never silently drops a gate.

Final acceptance requires all required non-waived gates to be `PASS` on the exact accepted candidate and all artifacts/evidence to remain addressable.
