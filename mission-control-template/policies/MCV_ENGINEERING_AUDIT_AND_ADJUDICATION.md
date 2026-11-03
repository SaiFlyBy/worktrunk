# MCV Engineering Audit and Adjudication Methodology

This policy carries forward the source-review, independent evidence assessment, serial adjudication, and durable-closure methodology proven during MCV6. It is reusable Mission Control methodology, not mission-specific authority. It sits inside the provenance-to-mutation chain and does not replace the top-level Mission Control lifecycle, schemas, or explicit owner admission decisions.

The method is provider-agnostic. A mission may use different models, providers, or human reviewers for the roles below, but it must preserve the evidence, independence, custody, seriality, and authority boundaries defined here. For durable multi-item assignment, successor append, automatic mailbox refill, and different-seat phase scheduling, use `NATIVE_TASK_PIPELINE.md`; that scheduler never weakens the Stage-A/B/C authority rules in this policy.

## 1. Core separation

Keep these states distinct at all times:

1. **source evidence** — what the exact source/version actually supports;
2. **engineering inference** — what may be useful or compatible in the target;
3. **review quality** — whether the source package has been independently assessed against evidence appropriate to its assigned scope;
4. **readiness/preflight** — whether current evidence is packaged for adjudication;
5. **Stage C adjudication** — source-by-source disposition against current target authority;
6. **authority admission** — the owner/coordinator decision that changes shared control authority;
7. **implementation and runtime qualification** — later target mutation and executable proof.

No earlier state silently grants a later one. In particular:

- a source fact is not an engineering decision;
- a candidate is not admission;
- A/B closure is not Stage C completion;
- Stage-C readiness is not Stage C;
- a Stage-C disposition is not shared-authority admission unless the mission explicitly defines and validates that transition;
- static/source/contract evidence is not candidate-native runtime or end-to-end qualification;
- provider availability is not proof that the canonical adjudicator session is runnable;
- a green packet or manifest is not permission to mutate the target.

## 2. Closed-loop engineering audit law

Deep source review, remediation, provenance reconciliation, and material control reconciliation use one closed-loop engineering investigation:

1. establish the exact boundary and baseline;
2. inspect one bounded coherent tranche;
3. stop broad discovery when the first material finding is confirmed;
4. prove evidence, impact, severity, confidence, root cause, and blast radius;
5. define the smallest correct intervention;
6. create a reproducer or protection check when practical;
7. make the smallest coherent correction;
8. validate in widening rings;
9. inspect changed state and explicitly close the finding;
10. resume from the durable next cursor.

**One material finding at a time** is the default. A nested blocking finding may be opened only when required to close its parent. Do not batch ten findings for later repair. Do not perform broad rewrites merely because nearby material could also be improved.

Audit completeness is scoped. A Stage A or Stage B review must be comprehensive inside the exact assigned source/package/cluster, not across the whole mission unless the assignment explicitly says so. Every relevant audit domain inside that boundary must be inspected or marked not applicable before terminal completion.

The smallest-correct-intervention rule is local to closing one material finding. It does not authorize minimal provenance consumption, representative sampling, wrapper/stub-only adoption, convenience rejection, lowest-common-denominator capability loss, or an MVP substitute for an evidence-backed target requirement. When the mission is ingesting provenance to improve a target, apply `PROVENANCE_INGESTION_WORKFLOW.md`: every material mechanism in the assigned source boundary must be accounted, and every accepted mechanism must leave an implementation-grade target consequence before source review can terminalize.

## 3. Immutable custody and additive correction

Historical evidence is custody, not editable memory.

- Never rewrite a prior terminal artifact merely to make it look compliant with a newer schema or methodology.
- Preserve exact prior bytes and hashes whenever they are still available.
- Correct drift with an additive successor, overlay, selector update, supersession record, or migration record.
- The successor must state exactly what it changes, what it preserves, and what authority effect it does **not** have.
- A failed or superseded generation remains historical noncontrolling custody; it does not disappear.
- A hard-gate failure cannot be bypassed by an ad hoc manual waiver. A mission-owner policy change must itself be explicit, durable, independently validated when required, and must not falsify prior evidence.
- When a correction is intended to be additive-only, prove the delta. When practical, removing the additive block should reconstruct the exact predecessor hash or semantics.

Legacy evidence must never be backfilled with fabricated lineage, fabricated hashes, fabricated review turns, or invented modern-stage markers.

## 4. Stage A — source-local construction

Stage A builds or normalizes one source-local package.

Before mechanism interpretation:

- resolve canonical source identity;
- pin the exact revision/version/date/capture;
- verify source integrity where possible;
- establish source rights and separately classify linked code, datasets, prompts, models, services, marks, and assets;
- bind the exact target baseline used for owner/compatibility interpretation;
- record pre-existing source-review custody and any legacy/superseded generations.

Then review bounded source tranches with exact locators and a durable next-read cursor. For each tranche:

- distinguish `SOURCE_FACT`, `ENGINEERING_INFERENCE`, and authority/admission statements;
- inspect relevant omissions, nonportable assumptions, target conflicts, failure semantics, observability, security boundaries, rights, and deterministic verification needs;
- stop and close the first material finding before continuing;
- immediately update the authorized source-local checkpoint and candidate/mutation-plan artifact;
- persist coverage, unresolved questions, confidence, validation evidence, and the exact next cursor.

A Stage-A terminal package normally contains or points to:

- exact source identity/version/integrity evidence;
- rights and reuse boundaries;
- bounded audit ledger/checkpoint chain;
- candidate/mechanism objects with evidence locators;
- validation evidence;
- terminal handoff/cleanup state;
- a current selector or lane index that identifies the controlling generation without deleting historical custody.

Stage A may stage candidates. It does not admit them to shared authority.

## 5. Stage B — independent evidence review

Stage B is an independent audit of Stage A and its source package. The Stage-A author/session must not self-certify Stage B for the same generation.

Stage B is not a hash-only preflight. It must independently assess material source/package claims against the underlying evidence, investigating or verifying further where the scope and risks justify it, using the same one-finding-at-a-time audit loop. Inside the assigned package it must cover, as applicable:

- canonical identity/version and source custody;
- rights/reuse boundaries, including linked artifacts;
- bounded source/code coverage with exact locators or explicit not-applicable reasoning;
- every candidate/mechanism disposition;
- source fact versus engineering inference separation;
- target-owner, durable-state-owner, authority-owner, and activation mappings;
- collision/duplication/supersession relationships;
- failure, recovery, rollback, unknown-effect, and idempotency semantics;
- security/trust boundaries;
- proportional negative, hostile, or falsification-oriented validation;
- static/specification evidence versus actually executed target-native evidence;
- terminal lineage, validation, current-selector precedence, and cleanup state.

A Stage-B terminal receipt is not sufficient merely because it exists. If later quality review proves missing bounded coverage, candidates without necessary review, false lineage, stale selector precedence, or unsupported validation claims, that Stage-B generation becomes historical custody for closure purposes until an additive remediation generation plus independent QA proves closure.

## 6. Independent QA and remediation generations

Quality review may be separate from Stage B when the mission needs a corpus-wide or risk-based closure gate.

A QA reviewer:

- is read-only over the source package unless separately authorized to remediate;
- must be independent of the current author/remediator when the result is used as a hard closure gate;
- verifies durable coverage, candidate evidence, rights/owner analysis, applicable negative validation, and terminal lineage rather than trusting summary prose;
- fails closed when the evidence does not prove the claimed completeness.

A QA `FAIL` does not erase the reviewed bytes. It blocks their use as current quality authority and routes the smallest evidence-backed remediation. Remediation creates a new additive generation, preserves the failed generation, closes findings serially, and receives a different-seat/session QA before becoming current when independence is required.

Same-author rechecks are useful diagnostics but do not substitute for a different-author integrity gate when the artifact controls downstream authority.

## 7. Corpus-wide A/B closure

Do not declare source-program A/B closure from a collection of terminal receipts. Build an exact canonical universe and prove it.

The closure process must:

1. enumerate the exact canonical source keys in scope;
2. maintain an alias/canonical-key fence so display-name drift cannot create duplicate or missing rows;
3. classify every source package under one explicit quality state;
4. preserve truthful legacy gaps instead of fabricating modern lineage;
5. bind exact qualifying evidence for every modern-quality PASS row;
6. produce a closure ledger over the exact universe;
7. receive independent integrity validation of that ledger before formal closure.

Recommended closure classes, adapted from MCV6, are:

- `MODERN_AB_QUALITY_PROVEN`;
- `MODERN_B_REMEDIATION_REQUIRED`;
- `LEGACY_TERMINAL_NORMALIZED_WITH_GAPS`;
- `REFERENCE_OR_NONPORTABLE_TERMINAL`;
- `UNRESOLVED_OR_INCOMPLETE`;
- `SELF_CONFLICT_REASSIGN` when the assigned reviewer cannot independently certify the controlling evidence.

The exact labels may be mission-specific, but their semantics must remain fail-closed.

A/B closure is scoped to the exact declared corpus. It does **not** imply Stage C completion, runtime qualification, owner resolution, rights clearance for implementation, live activation, authority admission, promotion, or production readiness.

## 8. Current selectors and precedence

Every source package needs one discoverable current interpretation without destroying prior generations.

A current selector/lane index should bind:

- the controlling candidate/review generation;
- the controlling validation and independent QA when required;
- any additive correction or precedence overlay;
- current A/B classification;
- current Stage-C/readiness state;
- explicit historical/superseded custody.

Selector or metadata drift should normally be corrected additively. A selector defect does not automatically reopen A/B quality unless it exposes a real semantic, evidence, or lineage defect. Conversely, a later QA failure cannot be hidden behind an older selector that still says `PASS`.

## 9. Stage-C readiness is packaging, not adjudication

Readiness/preflight is intentionally lighter than Stage A/B. It packages already-terminal evidence for adjudication and should be fast when the underlying source review is already complete.

A readiness artifact binds current:

- source selector and controlling A/B evidence;
- candidate objects and exact dispositions/contracts;
- rights/reuse boundary;
- target-owner/activation/runtime/evidence blockers;
- source dependencies and no-duplicate/reference prerequisites;
- target baseline/current-authority identity needed for later reread.

Readiness must preserve unresolved blockers and evidence ceilings. It may not upgrade static tests to runtime qualification, convert measurement-only evidence into policy, invent owners, or imply admission.

When a readiness artifact becomes stale, prefer an additive current-readiness overlay. Historical readiness remains custody.

## 10. Canonical serial Stage-C queue

Actual Stage C is serial even when readiness/preflight work is parallel.

Compile one canonical queue over the exact corpus with explicit classes such as:

- fresh Stage C required;
- current Stage C already terminal/no-duplicate;
- reference/nonportable/no-runtime-adjudication;
- source-level blocked, only when the whole source truly cannot be adjudicated.

Candidate-level defers do not automatically make a whole source `blocked`.

For every fresh row bind:

- unique serial position;
- canonical source key;
- exact current readiness/evidence pointer;
- immediate serial predecessor;
- explicit `depends_on`, `priority_after`, or terminal prerequisites where needed;
- source-specific guards;
- no-duplicate/reference semantics.

The queue must receive independent integrity validation before becoming a hard dispatch input. Later support corrections do not require a queue rewrite unless they actually change a row pointer, guard, class, order, or dependency. If a queue successor is necessary, preserve the parent and prove the exact authorized delta.

Only the lowest nonterminal eligible fresh source may enter Stage C. No forward scan, leapfrog, or batch dispatch is allowed.

## 11. Stage-C hardening gates

Before the first fresh dispatch, establish fail-closed program-level gates. The exact artifact names are mission-specific, but the following responsibilities are required when applicable:

1. **canonical queue + independent integrity** — exact corpus, classes, positions, dependencies, hashes;
2. **current-readiness completion** — no accidental stale/absent row used for dispatch;
3. **rights/reuse fence + independent integrity** — evidence usefulness never broadens code/data/prompt/text/figure/asset/model/dependency/service rights;
4. **owner/activation/runtime/blocker matrix + independent integrity** — no owner invention, no silent live activation, no static-to-runtime widening;
5. **current dispatch packet + different-author integrity** — exact source/candidate/contracts/guards bound to the current queue and readiness;
6. **serial recompute contract + independent integrity** — exact advancement semantics after each terminal;
7. **forward terminal-receipt contract + independent integrity** — exact machine-checkable receipt and validation requirements;
8. **provider/session recovery runbook + independent integrity** when an external persistent adjudicator is used;
9. **execution-time current-state rereads** — current authority, live activation, source selector/candidate/validation/readiness, rights, blockers, and no-existing-terminal state;
10. **canonical adjudicator session recovery proof** — the exact intended persistent context is runnable.

A catalog entry, adapter `available=true`, quota availability, or language-server presence is not enough to satisfy item 10.

No failed hardening generation may remain accidentally hardcoded as a permanent prerequisite after an authorized additive successor closes it. Successor semantics must be explicit and independently checked.

## 12. Persistent adjudicator session law

When Stage C uses an external conversational/provider adjudicator, use one canonical persistent session/context for the serial lane unless the mission owner explicitly changes the topology.

- Do not create a substitute session because the canonical session is temporarily unavailable.
- Do not switch provider/model/context merely to keep throughput high.
- Provider return alone does not authorize dispatch; all hard gates and fresh rereads still apply.
- If provider loss occurs mid-source, keep the same serial position in flight and preserve the adjudication cursor.
- Resume only the same canonical session after recovery and after repeating the required current-state rereads.
- A diagnostic provider turn must not consume or perturb the authoritative serial adjudication stream. Prefer testing recovery through the real next authorized dispatch once hard gates are closed.

Session identity is continuation evidence, not authority by itself.

## 13. Stage-C dispatch packet

A dispatch packet should be dormant until its serial turn and should bind, at minimum:

- canonical queue generation and independent queue PASS;
- source position/key/class and predecessor guards;
- current source selector/readiness/candidate/validation/handoff artifacts;
- exact candidate objects and authoritative contract/disposition strings;
- rights/reuse classification and retained obligations;
- target/current-authority bindings required for execution-time reread;
- owner/activation/runtime/evidence blockers;
- cross-source dependencies and no-duplicate prerequisites;
- explicit statement that packet preparation is not Stage C, runtime qualification, live activation, implementation, or admission.

Derived summaries must be labeled as derived/non-authoritative. Do not place paraphrases in fields that claim to contain authoritative source/candidate contracts.

Packets may be prepared in parallel for future rows, but that never creates permission to adjudicate those rows early.

## 14. Full-source Stage-C terminal receipt

A Stage-C source advances the scheduler only through a valid durable **full-source terminal receipt** plus independent receipt validation.

The forward receipt contract should machine-bind:

- exact queue generation and serial position;
- exact source/current-selector/candidate/validation/readiness inputs;
- current-authority and target baseline reread evidence;
- rights/reuse state;
- owner/activation/runtime/evidence-level findings;
- per-candidate dispositions and residual blockers;
- executed-versus-static/specification/source-only evidence distinctions;
- source-level terminal disposition;
- explicit authority/admission effect, normally `NONE` unless a separate authority artifact says otherwise;
- scheduler-recompute inputs;
- external post-write receipt hash and completion sequence/receipt identity.

Do not embed a self-hash inside the receipt and then pretend it proves the final bytes. The filesystem/collaboration completion record supplies the external final hash.

A separate independent validator must bind:

- terminal receipt reference and external hash;
- validator contract reference/hash;
- the exact configured check cardinality and results;
- `PASS` only when every required check passes;
- validator receipt reference, external hash, and completion sequence.

The check count is mission-specific; what matters is that the configured set is exact, hash-bound, complete, and independently executed. Missing, stale, mismatched, partial, self-authored, or non-PASS validation is nonterminal for scheduler advancement.

Historical receipts that predate the forward contract remain immutable grandfathered custody unless the mission explicitly requires a new current-generation adjudication. Do not retrofit fabricated fields.

## 15. Terminal and nonterminal Stage-C outcomes

A full-source `PASS`, `DEFER`, or `REJECT` may be terminal when the receipt exhaustively accounts for all candidates and residuals under the mission contract.

- Candidate `DEFER` does not automatically prevent a full-source terminal receipt.
- A full-source `DEFER` is terminal only if it is the explicit adjudicated outcome with complete accounting.
- `PROVIDER_BLOCKED`, interrupted execution, invalid receipt, or incomplete independent validation is nonterminal.
- `UNKNOWN` external effects remain fail-closed. Do not treat inability to observe an effect as proof of absence, empty output, or zero-byte state.

## 16. Scheduler recompute

After each independently validated full-source terminal receipt:

1. reread the canonical queue/recompute contract;
2. mark only the exact source terminal under its validated outcome;
3. re-evaluate immediate predecessor and nonserial dependency guards;
4. preserve no-duplicate/reference semantics;
5. select the new lowest eligible nonterminal fresh row;
6. perform fresh execution-time authority/source/rights/blocker/no-terminal rereads before dispatch.

Never pre-authorize a later row merely because its dormant packet is complete. Never leapfrog a provider-blocked or receipt-invalid current row.

## 17. Rights and reuse fence

Evidence eligibility and implementation reuse are separate questions.

For every source, classify exact reuse boundaries across code, text, prompts, datasets, figures, models, services, dependencies, marks/assets, and linked repositories. Typical reusable categories include:

- direct/adapted reuse allowed for a proven exact surface;
- clean-room behavioral/architectural synthesis only;
- behavioral reference only;
- linked-artifact rights separate;
- mixed/conditional by path or asset class.

A permissive root license does not automatically clear nested or linked surfaces. A paper license does not automatically license linked implementation code. Provider/service behavior can inform engineering without granting source-expression reuse rights.

Stage C may narrow or defer reuse but must not silently broaden rights.

## 18. Owner, authority, activation, and runtime blockers

Do not invent missing owners merely to make a source actionable.

For every candidate/mechanism distinguish:

- durable state owner;
- authority owner;
- execution/effect owner;
- activation conditions;
- grant/lease/authorization custody;
- qualification/runtime owner;
- observability/evidence owner.

Unresolved placement may yield `DEFER_OWNER_UNRESOLVED` or an equivalent fail-closed state.

Static target inspection, owner-regression tests, specification cases, source runtime tests, and substrate smoke tests must remain below candidate-native target integration/E2E qualification unless such execution actually occurred.

## 19. Cross-source collision and convergence

Before authority admission, fingerprint each proposed mechanism by:

- invariant/problem;
- inputs/outputs;
- durable state owner;
- authority owner;
- activation conditions;
- qualification/evidence contract;
- failure/recovery/rollback;
- security boundary;
- observability;
- rights boundary.

Classify the relationship to existing and other proposed mechanisms using a small explicit set such as:

- `REUSE_EXISTING`;
- `EXTEND_EXISTING`;
- `FUSE_COMPLEMENTARY`;
- `NEW_OWNER_REQUIRED`;
- `REJECT_DUPLICATE`;
- `REJECT_NONPORTABLE`;
- `DEFER_OWNER_UNRESOLVED`.

`NEW_OWNER_REQUIRED` needs positive proof that no existing owner can carry the invariant without violating state/authority boundaries. Newer sources do not supersede older mechanisms merely because they are newer. Replacement requires equivalence/supersession proof, retained-capability accounting, state migration, evidence/authority compatibility, and recovery/rollback reasoning.

Source-local reviewers may propose relationships. Cross-source authority resolution belongs to the designated coordinator/owner and must remain separate from source-local facts.

## 20. Parallel executor coordination

Parallelism is allowed for disjoint source-local work and read-only/preflight work; conflicting authority surfaces serialize.

- Claim the smallest conflicting source-local or shared-control resource before mutation.
- Different source directories may be mutated concurrently when their claims are disjoint.
- Shared control ledgers, closure declarations, canonical queues, and other single-authority files are single-writer surfaces.
- One worker should hold at most one conflicting mutation claim at a time unless the mission explicitly proves otherwise.
- `claims + recent durable receipts` are the live coordination authority. Participant/task summary fields may be stale.
- A mailbox delivery does not prove the worker woke, claimed, or executed the task.
- Before rerouting allegedly idle work, resnapshot live claims and recent results. Do not create duplicate work because a delivered task has not yet started.
- After terminal completion/release, reread the mailbox and take the next concrete eligible nonconflicting task.
- The collaboration bus and durable artifacts are machine-to-machine handoff authority. Human-facing chat finals are not the inter-seat control plane.
- Persist artifacts first, then publish the durable completion receipt, then release claims, then produce the user-facing final.

Work-conserving refill should give idle executors concrete bounded tasks, not vague reserve work that requires them to rediscover the queue.

## 21. Frozen-target source phase

During source ingestion/audit/synthesis, the target should normally remain frozen read-only evidence unless the mission explicitly authorizes an implementation phase.

This separation prevents source reviewers from validating their own speculative target changes and keeps owner/compatibility evidence comparable across sources.

Target mutation requires, as applicable:

- intended source scope complete enough for the mission decision;
- A/B quality closure for the declared corpus;
- required Stage C adjudication and cross-source convergence;
- current rights/owner/activation/runtime blockers reconciled;
- final synthesis/validation green to the practical limit;
- explicit owner authorization for implementation.

A source candidate, readiness packet, Stage-C result, or provider response alone never authorizes implementation.

## 22. Implementation-cell convergence after authorization

When implementation is later authorized, do not bulk-merge independently green branches/cells.

Each implementation cell should be freshly compiled against the exact current accepted target base with:

- exact read/write sets;
- authority and semantic-owner sets;
- contract/schema surfaces;
- state/migration surfaces;
- dependency identities;
- semantic mechanism fingerprints;
- verification and rollback requirements.

Parallel implementation is allowed only when write/write, write/read, authority, semantic-owner, contract-version, and migration conflicts are compatible.

Every completed cell needs an integration receipt with an explicit disposition such as merge-as-is, fuse/refactor, recompile-on-new-base, hold-conflict, reject-duplicate, reject-regression, or reject-rights/provenance. After one overlapping cell is admitted, remaining overlapping cells must be recompiled against the new integration base.

Git merge cleanliness is necessary but not sufficient. Semantic cohesion and one canonical owner per invariant are the actual convergence gates.

## 23. Failure interpretation rules

Preserve fail-closed but precise classifications:

- provider/runtime unavailability is an environmental dispatch blocker, not automatically a source-quality blocker;
- a stale readiness pointer is a packaging defect unless it exposes semantic/source lineage drift;
- a stale selector is a precedence/discoverability defect unless it reveals that the controlling evidence itself is invalid;
- a packet contract mismatch blocks that packet/source turn but does not automatically rewrite the canonical queue;
- a candidate-level owner defer is not automatically a source-level blocked state;
- a blocked or unavailable test is not a PASS;
- a static hostile case is not an executed integration test;
- failure to observe an external effect is not proof that the effect is absent.

Correct only the layer where the defect actually exists.

## 24. Closure and reporting semantics

Every closure statement must name its exact scope and non-effects.

Examples:

- A/B corpus closure: exact source universe and quality classes only;
- readiness completion: current packaging only;
- queue integrity: scheduling metadata only;
- Stage-C source terminality: source adjudication only;
- authority admission: only the explicitly admitted shared-control delta;
- qualification: only the executed target/evidence boundaries actually proven.

Do not use terms such as `fully hardened`, `runtime-qualified`, `production-ready`, or `admitted` merely because upstream evidence is green.

At each terminal boundary report:

- exact scope;
- controlling artifact references and hashes;
- findings closed;
- validation executed and results;
- unresolved blockers/residual risks;
- exact next executable action or stop reason;
- explicit authority/runtime/admission effect.

## 25. Recommended durable artifact families

The exact filenames are mission-specific, but a robust mission usually needs equivalents of the following.

### Source-local

- source identity/version/integrity record;
- rights/reuse record;
- bounded audit ledger/checkpoint chain;
- candidate/mechanism artifact;
- validation receipt;
- terminal handoff/cleanup receipt;
- current selector/lane index;
- additive correction/supersession overlays when needed;
- independent Stage-B/QA result and remediation generations.

### Program-level

- canonical source-key/alias fence;
- A/B quality closure ledger + independent integrity;
- current Stage-C readiness completion ledger;
- canonical serial Stage-C queue + independent integrity;
- rights/reuse fence + independent integrity;
- owner/activation/runtime/blocker matrix + independent integrity;
- dormant/current dispatch packets + different-author integrity for hard-gated packets;
- serial recompute contract + independent integrity;
- forward terminal-receipt contract + independent integrity;
- provider/session recovery runbook + independent integrity when applicable;
- per-source terminal receipts + independent receipt validation;
- cross-source collision/owner convergence artifacts;
- final synthesis/admission/qualification/closure records.

## 26. Relationship to existing Mission Control policies

This policy complements, rather than replaces:

- `PROVENANCE_SYNTHESIS.md` for rights-aware source synthesis and mechanism attribution;
- `EXECUTOR_PROTOCOL.md` for compiled execution custody and target-base binding;
- `CONTROL_LAWS.md` for authority, evidence, conflict, and independent adjudication laws;
- `LIFECYCLE_AND_TESTING.md` for mission lifecycle and qualification semantics;
- `WORKSPACE_RECONCILIATION.md` for live workspace/branch reconciliation before closure.

When a rule conflicts, the stricter current mission authority or schema wins. A mission-specific relaxation must be explicit and durable; silence never weakens these fail-closed defaults.
