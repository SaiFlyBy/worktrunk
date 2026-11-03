# Provenance Synthesis Methodology

This policy defines how a Mission Control mission turns repositories, papers, prior missions, documents, and owner-provided references into target mutations while preserving exact source lineage, verified reuse rights, target authority, and implementation quality.

## Purpose

Provenance is not a bibliography and it is not a reason to underuse a source. An admitted source is complete only when Mission Control has deliberately inspected its material capabilities, challenged its first-pass interpretation, classified every materially useful opportunity, translated the surviving value into target requirements, and retained the exact rights/attribution basis for whatever was reused.

The mandatory pipeline is:

```text
MISSION intent and hard boundaries
  -> immutable source admission
  -> exact ownership/license/rights verification
  -> multi-round source excoriation where warranted
  -> full-potential capability inventory
  -> existing-target assessment
  -> synthesis/disposition and direct-reuse decision
  -> target requirement derivation
  -> target lineage/provenance materialization plan
  -> mutation-cell design
  -> implementation
  -> independent derivation + rights/obligation verification
  -> integration and qualification
  -> provenance/derivation/reuse evidence retained at closure
```

Skipping the synthesis layer is a control failure. Stopping after the first attractive mechanism is also a control failure when the source contains additional materially useful capabilities.

## Rights-aware source handling

Default methodology is `RIGHTS_AWARE_FULL_POTENTIAL_SYNTHESIS`, not blanket clean-room restriction.

Every repository, research artifact, or document that can influence implementation receives one exact use mode:

- `OWNER_AUTHORIZED_REUSE`: the owner has authority to permit reuse. Mission Control may copy, adapt, restructure, combine, or reimplement to the extent explicitly recorded in the permission record.
- `LICENSE_PERMITTED_REUSE`: the exact pinned source is under a verified license that permits the recorded forms of reuse. License obligations remain mandatory even when the license is permissive.
- `CLEAN_ROOM_BEHAVIORAL_SYNTHESIS`: direct code/text/distinctive-structure reuse is not authorized or not desired; only independently expressed mechanisms, behavior, invariants, interfaces, failure modes, and measurable outcomes may influence implementation.
- `REFERENCE_ONLY`, `AUTHORITY_ONLY`, and `AUDIT_EVIDENCE`: the source does not authorize implementation derivation.

A license name or repository badge is not enough. Reuse-capable modes require evidence tied to the exact admitted source revision, a rights basis, explicit code/text/structure permissions, and retained obligations such as attribution, copyright notice, NOTICE propagation, source-offer/copyleft conditions, or other license terms.

Permissive or owner-authorized reuse removes artificial clean-room limits; it does not make wholesale copying automatically desirable. The engineering decision is still evidence-driven. Direct reuse is appropriate when it is the strongest integration, maintenance, correctness, or compatibility choice. Adaptation or target-native recomposition is appropriate when existing FlyBy authority, architecture, performance, or product semantics make a literal transplant worse.

## Phase 1: immutable source admission and rights verification

`corpus/SOURCES.json` is the immutable source registry. For repositories and research:

1. identify the exact repository/paper/document;
2. freeze an immutable commit, tag, DOI/version, arXiv version, or equivalent revision;
3. state why the source was admitted;
4. classify its disposition as `SYNTHESIS_REQUIRED`, `ADJUDICATED_SYNTHESIS`, `REFERENCE_ONLY`, `REJECTED`, or `AUTHORITY_ONLY`;
5. record the intended inspection scope, which may be broadened by deep review when useful material is discovered;
6. record the exact use mode and reuse permissions;
7. for owner/license reuse, record verified rights evidence and all obligations before direct reuse is proposed.

A moving default branch, mutable web page, unversioned research locator, or unverified license claim is not sufficient provenance for a source that can influence mutation. A previous-mission handoff is also immutable source authority: `MISSION.json` must bind its exact SHA-256, the generated `PREVIOUS_MISSION` source record must carry the same digest as its pin, and doctor must reject later byte drift.

## Phase 2: multi-round source excoriation and full-potential coverage

`corpus/PROVENANCE_SYNTHESIS.json` is the required bridge between source admission and target requirements.

A source assessment must not confuse one useful idea with source coverage. The normal `SYNTHESIS_REQUIRED` path uses `deep_review` to record how the source was challenged. Review depth is independent of reuse rights: clean-room sources can contain valuable behaviors and invariants even when their copyrighted expression cannot be copied. `ADAPTIVE_MULTI_ROUND_EXCORIATION` starts with at least three deliberate passes:

1. **exhaustive discovery** — inspect architecture, runtime behavior, data models, algorithms, UX/workflows, tests, failure recovery, operational tooling, evaluation, performance, extension seams, and documented limitations; enumerate all capabilities that could materially benefit the target;
2. **omission/adversarial challenge** — revisit unread or weakly understood areas, attack the first summary, identify hidden dependencies and second-order capabilities, distinguish core mechanisms from accidental implementation, and search specifically for high-value features omitted in round one;
3. **target-integration deepening** — compare the surviving capabilities against the current target, identify direct reuse versus adaptation versus combination opportunities, discover cross-source combinations, and challenge any rejection that was based merely on minimizing change.

Three turns are a floor, never a stopping rule. Round 1 must partition the source into critical subsystems/sections and record any uninspected critical partitions. Further same-thread turns are mandatory while material omissions, unresolved high-value questions, or uninspected critical partitions remain. There is no fixed maximum turn count. Rights mode governs direct/adapted reuse; it never authorizes skipping deep capability review.

### Bounded Reading Tranches & Durable Incremental Checkpoints

Deep source analysis must survive context compaction and process restart. Reviewers must **not** use an unbounded "read the whole source, then write the report" workflow.

Every source review uses the following resumable cycle:

1. resolve the exact source identity, immutable version, and license/rights evidence;
2. select one bounded tranche (subsystem, file set, section, page range, commit range, or equivalent);
3. inspect that tranche;
4. persist a durable checkpoint conforming to `SOURCE_REVIEW_CHECKPOINT_SCHEMA.json` (`flyby/source-review-checkpoint/1`);
5. validate that checkpoint before reading the next tranche;
6. on compaction/restart, load the latest validated checkpoint and resume at its exact next cursor.

A checkpoint binds `source_id`, `source_identity`, immutable `source_version`, derived `source_ref`, owning thread, turn number, and monotonically contiguous `checkpoint_sequence`. Sequence one has no predecessor; every later checkpoint carries `previous_checkpoint_sha256` matching the exact preceding checkpoint bytes. The next checkpoint's inspected partition/path/range must match the predecessor's `next_read_cursor`. A reviewer may not silently restart, skip forward, jump backward, cross to a different source/version, or rewrite historical findings without a new lineage node.

Checkpoint content must preserve, at minimum:

- exact `license_and_rights_evidence` plus its locator;
- `coverage_cursor` with inspected partition, paths, immutable version/commit, optional line/page/range locator, completed partitions, and remaining partitions;
- `mechanism_candidates` whose `finding_class` is `SOURCE_FACT` and which carry exact evidence locators;
- `mc_reinterpretation_hypotheses` whose `finding_class` is `ENGINEERING_INFERENCE`, keeping target adaptation hypotheses mechanically distinct from source facts;
- `rejected_or_non_adoptable` mechanisms with evidence locator and rationale;
- `failure_and_adversarial_notes` with kind, locator, observation, and downstream impact;
- confidence, uninspected gaps, open questions, unresolved rights issues, and the exact `next_read_cursor`;
- `completion_flag`, which may not be true while source partitions, questions/gaps, or rights issues remain.

Working checkpoints are always `authority_status: "NON_AUTHORITATIVE_SCRATCH"`. They cannot satisfy convergence, replace an adjudicated source review, or be promoted directly into campaign authority. Source-review convergence remains controlled by the final validated turn/envelope and independent/adjudication gates.

### Source payload cleanup and evidence retention

Downloaded archives, extracted source trees, and source clones are temporary working payloads, not campaign authority. After a final durable review exists and adjudication is complete, cleanup is governed by `SOURCE_REVIEW_CLEANUP_SCHEMA.json` (`flyby/source-review-cleanup/1`) and `tools/validate_source_review_cleanup.py` (which validates the final-review bytes and delegates lifecycle invariants to `validate_cleanup_manifest`).

Cleanup manifests distinguish `SOURCE_DOWNLOAD` and `SOURCE_CLONE` payloads from retained evidence/results. A delete candidate is permitted only when it is explicitly declared as one of those temporary source payloads. Retained artifacts require a justification. `AUTHORITY_EVIDENCE` and `AGENT_AUTHORED_REVIEW` artifacts are protected and may not be deleted merely because their source payload has been removed. Checkpoint evidence or other justified results may likewise be retained when required for lineage, auditability, rights adjudication, or reproducibility. Cleanup before final adjudication is rejected.

Source-local review custody is exclusive. Each source has one owning review thread/context. That thread may inspect tools/files/network evidence, but it may not forward or delegate source adjudication to a different source's review thread. Any cross-source-forwarded result is invalid source-local evidence and must be re-issued by the owning thread. Cross-source composition happens only after source-local convergence.

Each source assessment inventories materially relevant capabilities as:

- `BOUND_TO_MECHANISM`;
- `ALREADY_SATISFIED` by the target and therefore requiring verification rather than a new component;
- `REJECTED_NON_GOAL` with an evidence-based rationale.

For the normal `SYNTHESIS_REQUIRED` path, coverage is `COMPLETE` only when open questions are empty, every critical partition is inspected, the final same-thread round explicitly converges, `deep_review.convergence.material_omissions_remaining` is false, all extracted mechanisms are bidirectionally accounted, and independent review binds both the exact coverage/deep-review trajectory and source-local mechanism contributions. A `VERIFIED` independent review is not a metadata label: it requires a mission-local typed receipt whose SHA-256 is bound in the assessment, whose reviewer identity is distinct from the source/deep-review extractor custody, and whose source-record, coverage, and source-local contribution digests exactly match current authority.

`ADJUDICATED_SYNTHESIS` is the alternate authorizing path for a source that already completed a stronger independent multi-stage adjudication outside the ordinary deep-review shape. It does not waive provenance or engineering closure. Its source assessment must be `COMPLETE`, have no open material questions, preserve an immutable terminal adjudication receipt and exact adjudicated candidate snapshot with SHA-256 bindings, and mark that adjudication `VERIFIED` and `READY_FOR_AUTHORITY_ADMISSION`. The adjudicated source still requires rights-aware source registration, exhaustive mechanism contributions, concrete target requirements, hostile verification, and bidirectional source -> mechanism -> requirement accounting. A citation, summary, model verdict, or unbound transcript is never enough.

Shared cross-source mechanisms are synthesized and digest-bound separately so one source change does not invalidate unrelated source review custody.

## Phase 3: mechanism extraction

A mechanism is the smallest useful source-derived capability that can be assessed independently. It may describe an algorithm, state transition discipline, architecture contract, data structure, UI/operator workflow, test strategy, failure-recovery mechanism, performance technique, extension model, evaluation design, or other concrete capability.

Mechanism extraction must answer:

- what problem does it solve?
- what observable behavior or invariant makes it valuable?
- what exact source locators support the interpretation?
- what parts are essential, optional, or source-specific?
- what failure mode does it prevent?
- is direct reuse permitted and useful, or is adaptation/synthesis stronger?
- if implementation material is reused, which exact source IDs authorize it and what obligations follow?

Clean-room mechanisms remain paraphrased. Rights-verified mechanisms may record `ADAPTED_IMPLEMENTATION`, `DIRECT_REUSE`, or `MIXED` and must bind `reuse_source_ids` plus obligations.

## Phase 4: existing-target assessment

Before proposing new code, inspect the target system. Every mechanism records:

- existing target capabilities that already solve part of the problem;
- exact target locations inspected;
- gaps or failure modes that remain;
- mature target behavior that must be preserved;
- neighboring capabilities that can be composed with the source mechanism;
- whether current target code has advanced enough that an earlier mutation design is stale.

This prevents replacement-by-convenience without preventing high-value reuse. Existing target authority is not sacred when evidence supports replacement, but replacement must be a deliberate migration with compatibility and rollback consequences.

## Phase 5: synthesis and disposition

Every mechanism receives exactly one disposition:

- `NEW_MUTATION`;
- `EXTEND_EXISTING`;
- `COMBINE_EXISTING`;
- `ALREADY_SATISFIED`;
- `REJECTED`.

The preferred engineering question is not “what is the smallest diff?” It is “what combination preserves mature target strengths while extracting the greatest justified value from the sources?” Preserve/extend/combine is usually safer than replacement, but useful capabilities must not be discarded merely to reduce implementation effort.

Apply `PROVENANCE_INGESTION_WORKFLOW.md` whenever provenance is intended to improve a target. Source identity is custody; material mechanisms are the ingestion units. Representative sampling, one-headline-feature harvesting, wrapper/stub-only implementation, false equivalence based on names, and convenience-driven rejection are nonterminal defects. Accepted mechanisms must produce implementation-grade target after-states and qualification rather than conceptual advice that forces the mutation stage to rediscover the donor.

## Phase 6: FlyBy derivation and reuse decision

For every non-rejected mechanism, define the target result before implementation:

- owned abstraction or capability;
- target-native behavior and authority owner;
- existing capabilities it combines with;
- integration points;
- invariants to preserve;
- source-specific features deliberately excluded;
- implementation reuse class (`PARAPHRASED_SYNTHESIS`, `ADAPTED_IMPLEMENTATION`, `DIRECT_REUSE`, or `MIXED`);
- exact reused source IDs and license/ownership obligations when applicable;
- verification that distinguishes real incorporation from nominal metadata.

“FlyBy-owned” means FlyBy owns the integrated authority and product behavior. It does not prohibit using legally/owner-authorized implementation material inside that authority.

## Phase 7: target corpus binding

A source-driven target requirement must:

- list exact source IDs and mechanism IDs;
- define the target-owned abstraction and composition strategy;
- state what existing behavior is preserved or deliberately migrated;
- define meaningful non-goals rather than blanket anti-copy restrictions;
- define observable acceptance and hostile cases;
- declare the actual rights posture used by the requirement.

Bidirectional accounting remains mandatory: source -> mechanism -> requirement and requirement -> mechanism -> source must agree. Every `SYNTHESIS_REQUIRED` source carried by a bound mechanism must also appear explicitly in that requirement's `sources`; a requirement may not hide research lineage by listing only owner intent while retaining a research-derived mechanism. `source_driven` is therefore derived from the union of requirement sources and bound mechanism sources. A `REJECTED` mechanism has zero target requirements and may not be named by a target requirement; rejected evidence remains preserved only as evidence.

The target corpus also declares `provenance_materialization`. If the target already has a lineage/provenance manifest, Mission Control must create a requirement that updates it during execution. That update records exact source revisions, rights basis, review evidence, adopted/rejected mechanisms, implementation locations, and obligations. Provenance remains lineage evidence unless a separate architecture decision grants runtime authority.

## Phase 8: mutation-cell design

Cells implement target requirements, not repositories. Their write scopes come from current target ownership after baseline/current-state audits.

For rights-verified reusable sources, an executor may receive and inspect the admitted source tree when the cell requires it. The cell still must:

- bind the exact source revision and rights record;
- say whether it may copy, adapt, or only inspect;
- preserve attribution/notice obligations;
- integrate into the existing target owner rather than create a shadow runtime;
- include positive, negative, compatibility, and rollback verification.

For clean-room sources, donor implementation remains excluded from implementation context beyond the permitted evidence/mechanism summary.

## Phase 9: independent derivation and rights review

Before acceptance, the verifier checks:

1. target behavior satisfies acceptance;
2. implementation fits or deliberately migrates target authority;
3. mature adjacent behavior was not removed merely for convenience;
4. source-derived capability is materially present;
5. direct/adapted reuse is authorized by exact source rights evidence;
6. copied/adapted material is bound to the correct `reuse_source_ids` and all obligations are satisfied;
7. clean-room sources did not leak code/text/distinctive structure;
8. provenance pins, deep-review receipts, mechanisms, requirements, and implementation locations remain exact;
9. rejected/non-goal features did not leak into scope without a new reviewed decision.

## Phase 10: integration, qualification, closure

Integration evaluates synthesized behavior, not donor demos. Qualification covers source-derived invariants that affect user-visible behavior, correctness, performance, safety, recovery, truth, authority, or cost.

Closure preserves:

- immutable source registry and rights evidence;
- multi-round source review/excoriation receipts;
- provenance synthesis matrix;
- target corpus and provenance-materialization contract;
- direct/adapted reuse locations and obligations;
- accepted derivation/verification evidence;
- explicit rejections/non-goals;
- target-native lineage/provenance updates;
- reusable methodology discoveries that should update this template.

## Required control laws

1. Rights are verified before direct/adapted reuse; license labels alone are not authority.
2. A permissive/owner-authorized source is not artificially constrained to clean-room synthesis.
3. Permission to copy does not make copying the default engineering choice.
4. A source review is incomplete while material high-value capabilities remain unassessed.
5. Large/high-value sources use repeated deepening, not one surface summary.
6. Provenance without mechanism disposition is incomplete.
7. Mechanism disposition without current-target assessment is incomplete.
8. Source-driven requirements without mechanism IDs and rights posture are invalid.
9. Existing target authority is preserved or migrated deliberately; convenience is not migration evidence.
10. Useful source features are not silently discarded to minimize change.
11. More mechanisms do not imply more components; cross-source composition is encouraged when one coherent target abstraction can carry them.
12. Rejection and already-satisfied findings are evidence-bearing outcomes.
13. Direct reuse records exact source IDs, locations, obligations, and attribution/notice requirements.
14. Every materially used source is materialized into the target's existing lineage manifest when one exists.
15. Provenance records lineage; they do not silently create runtime authority.
16. Qualification proves the integrated target behavior and obligations, not visual similarity to a source.
17. A bound mechanism cannot hide an authorizing synthesis source from the target requirement that consumes it.
18. Rejected mechanisms carry no target requirement authority.
19. `VERIFIED` independent source review requires a typed, mission-local, hash-bound receipt and distinct reviewer custody.
20. Previous-mission handoff authority is admitted only by exact immutable content digest.

### Cross-source semantic compression and intercept custody

After every source-local review converges, cross-source synthesis must compress overlapping findings into the smallest target-native mechanism graph that preserves behavior. `intercept_matrix` maps every final mechanism to an execution/control phase, deterministic order, input/output state keys, and composition mode. Two mechanisms with an identical `(phase, composition_mode, state_in, state_out)` signature are not independently admissible; unify them and retain source-specific derivations in `mechanism_contributions`. Mechanisms that write overlapping state at the same phase must have deterministic non-exclusive ordering or one must be rejected/unified. `combination_hypotheses` records high-value multi-source compositions and must be explicitly ADOPTED or REJECTED before seal.

Reviewer custody is also evidence. Retired or contaminated source-review threads must be tombstoned and cannot later satisfy source-local review. A replacement owner must independently derive its review from admitted primary evidence; discarded forwarded outputs remain invalid.

### Linked source discovery

A source review may discover a linked repository, paper, dataset, implementation, or supplement. That linked material does not inherit the parent source's pin, license, review, or reuse permissions. If it is materially additive, admit it as a separate immutable source, verify its exact rights, assign a distinct source-local review owner, and only then incorporate its mechanisms or copyrighted implementation. If it is not material or rights are insufficient, record a reference-only/rejected disposition. This prevents a permissively licensed paper from laundering unlicensed code, and prevents a curated catalog from silently authorizing hundreds of linked projects.
### Mechanism versus evidence classification

Deep source review must not inflate executable mechanism counts with complexity properties, benchmark/evaluation results, limitations, scope boundaries, rights metadata, or negative/falsifying evidence. Preserve those findings at full fidelity as `EVIDENCE_ONLY` coverage (or source-review evidence fields) with exact locators and downstream qualification/test implications. A source mechanism is counted only when it contributes a distinct executable/behavioral state transition, control invariant, typed transformation, routing decision, or other independently falsifiable operational behavior. Folding a row out of the mechanism count must never delete its evidence.
### Behavior-specific source attribution

A source listed on a composite FlyBy requirement does not automatically support every acceptance clause in that requirement. Source-local `mechanism_contributions` and coverage rationale must state the exact behavior each source supports. Working-state selection, replay, independent verification, safety, provenance, or other adjacent target behavior must not be credited to a source merely because its mechanism is composed into the same subsystem. Target-owned extensions and cross-source composition remain explicit.
Reviewed source rows may outnumber executable mechanisms. Rejected or negative rows remain full-fidelity evidence with their locators and hostile-test implications; they are not deleted merely to reduce the mechanism count.
### Final source-artifact and cross-source seal binding

A `COMPLETE` deep review is sealable only when its final source-review artifact is bound by mission-relative reference, SHA-256, exact immutable source identity/version, owning source-review thread, review-round count, and final executable-mechanism count. Completed round numbers are unique and contiguous. Round evidence is hash-bound; prospective turn-chain hashes must be captured at execution time and must never be fabricated retroactively.

Independent final review binds the current finalized source artifact as well as the source-local coverage/contribution/mechanism digests, and the independent reviewer identity must differ from the source-owner thread. A later source-artifact change therefore returns the source to review rather than inheriting an old VERIFIED receipt.

`VERIFIED` cross-source synthesis separately binds the exact final mechanism graph, intercept matrix, combination-hypothesis set, and review evidence artifact. Hypothesis ids are unique. An adopted cross-source result must preserve all contributing source identities in its result mechanism lineage; an existing single-source mechanism cannot be relabeled as a multi-source synthesis result.
### Direct review-session custody and birth evidence

Post-enforcement source review is performed only in a direct top-level review session. The review session itself must not spawn, delegate, or forward source-review work to child threads, subagents, or forks. A canonical source owner cannot be admitted from self-declared custody metadata alone; it requires a hash-bound direct launch receipt backed by mechanical provider session birth evidence.

Direct launch receipt invariants:
1. `approval_policy`: strictly `never`.
2. `sandbox_policy`: strictly `danger-full-access` (or template-allowed read-only direct-top-level policy if distinguished).
3. `child_thread_created`: `false`.
4. `delegation_used`: `false`.
5. `session_birth_evidence_ref` & `session_birth_evidence_sha256`: mission-local normalized JSON or JSONL provider session birth record capturing the top-level session initialization events.
6. The validator mechanically parses the birth evidence and rejects any function call or output naming `create_thread` or `fork_thread`, any non-conforming approval/sandbox policy, any thread ID mismatch, or any evidence hash drift.

Its append-only v2 turn envelopes bind self/predecessor hashes, current phase/prompt digests, the exact immutable source identity, source-pinned locator content hashes, evidence receipts, rights mode, and critical-partition accounting. `CONVERGED` is valid only in a convergence-permitted phase after all critical partitions are accounted and material omissions are false.

Pre-enforcement generations remain explicitly `LEGACY_PRE_ENFORCEMENT`; they are not upgraded by inventing predecessor or turn hashes. Child-created results may be retained only as corroborative/historical evidence and must be tombstoned from canonical authority. Replacement custody is source-specific: one active source/generation owner, exact same-source tombstones for retired owners, and no tombstoned thread may re-enter current source or independent-review authority. Replacement-required state must clear active thread/turn count and preserve retired custody evidence.

## Resumable source-review checkpoints and cleanup lifecycle

Long source reviews are tranche-based and resumable. The required operating loop is: resolve the exact source identity/version and license evidence; select one bounded tranche; inspect it; persist a durable checkpoint; validate the checkpoint; only then advance. After context compaction or process restart, the reviewer reloads the latest validated checkpoint and resumes from its exact `next_read_cursor`. A workflow that instead reads an unbounded source first and writes findings only at the end is non-conforming.

Every checkpoint is non-authoritative scratch and is bound to the exact source identity, pinned source version, source reference, thread, checkpoint sequence, and predecessor digest. Sequence numbers are contiguous. For every checkpoint after the first, `previous_checkpoint_sha256` must equal the exact digest of the prior checkpoint, and the new coverage cursor must begin at the predecessor's exact next partition/paths/range. This prevents silent restart, skipped coverage, cursor jumps, history rewriting, cross-source lineage, and stale-version continuation. `completion_flag` may not be asserted by an incomplete checkpoint; final authority still requires the normal adjudicated review/convergence path.

Checkpoint findings preserve provenance granularity: source facts/mechanisms require evidence locators, engineering reinterpretations remain explicitly hypotheses, rejected mechanisms retain their locator and rationale, and unresolved rights questions/open questions survive every checkpoint. Checkpoints may inform a final review but are never promoted directly into authority.

Downloaded archives, working clones, extracted source payloads, and similar source material are temporary lifecycle objects. A cleanup manifest may delete only payloads explicitly declared temporary and only after adjudication completes. Final/authoritative evidence, reviewer-authored reports, checkpoint lineage needed to substantiate the final result, rights evidence, and other protected retained evidence are never deletion candidates merely because temporary source payloads are removed. Cleanup that targets a protected evidence reference fails closed.
