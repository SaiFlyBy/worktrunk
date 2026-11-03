# Mission Control Template v16

For the Worktrunk bridge and one-scope draft PR workflow, see [WORKTRUNK.md](WORKTRUNK.md).


Mission Control v16 turns the reusable control methodology into an executable bootstrap contract. A mission author supplies one `MISSION.json`; the template generates the canonical control layout, locks the exact template/runtime inputs, validates the mission, and exposes one operator CLI.

The author should not need to know internal filenames beyond `MISSION.json`.

## Operator path

```text
python mission-control-template/tools/mc.py init --mission mission-control-v7/MISSION.json
python mission-control-v7/runtime/tools/mc.py doctor --root mission-control-v7
python mission-control-v7/runtime/tools/mc.py status --root mission-control-v7
python mission-control-v7/runtime/tools/mc.py sources load --root mission-control-v7 --file sources.json
python mission-control-v7/runtime/tools/mc.py provenance load --root mission-control-v7 --file provenance-synthesis.json
python mission-control-v7/runtime/tools/mc.py corpus load --root mission-control-v7 --file target-corpus.json
python mission-control-v7/runtime/tools/mc.py baseline compile --root mission-control-v7
```

After baseline workers return typed results:

```text
python mission-control-v7/runtime/tools/mc.py dispatch --root mission-control-v7 --cell A000 --worker-identity worker-A000 --verifier-identity verifier-A000
python mission-control-v7/runtime/tools/mc.py settle --root mission-control-v7 --cell A000 --attempt 1 --result result.json --context-receipt context_receipt.json --adjudication adjudication.json
python mission-control-v7/runtime/tools/mc.py baseline accept --root mission-control-v7
```

A mission-specific mutation frontier is then compiled through the same path:

```text
python mission-control-v7/runtime/tools/mc.py compile --root mission-control-v7 --frontier mutation-frontier.json
python mission-control-v7/runtime/tools/mc.py dispatch --root mission-control-v7 --cell M000 --worker-identity worker-M000 --verifier-identity verifier-M000
python mission-control-v7/runtime/tools/mc.py settle --root mission-control-v7 --cell M000 --attempt 1 --result result.json --context-receipt context_receipt.json --adjudication adjudication.json
python mission-control-v7/runtime/tools/mc.py barrier accept --root mission-control-v7 --cell G100
python mission-control-v7/runtime/tools/mc.py integrate --root mission-control-v7
python mission-control-v7/runtime/tools/mc.py dispatch --root mission-control-v7 --cell I000 --worker-identity worker-I000 --verifier-identity verifier-I000
python mission-control-v7/runtime/tools/mc.py settle --root mission-control-v7 --cell I000 --attempt 1 --result integration-result.json --context-receipt integration-receipt.json --adjudication integration-adjudication.json
python mission-control-v7/runtime/tools/mc.py qualify --root mission-control-v7
python mission-control-v7/runtime/tools/mc.py dispatch --root mission-control-v7 --cell Q000 --worker-identity worker-Q000 --verifier-identity verifier-Q000
python mission-control-v7/runtime/tools/mc.py settle --root mission-control-v7 --cell Q000 --attempt 1 --result qualification-cell-result.json --context-receipt qualification-cell-receipt.json --adjudication qualification-cell-adjudication.json
python mission-control-v7/runtime/tools/mc.py qualify --root mission-control-v7 --result qualification-result.json
python mission-control-v7/runtime/tools/mc.py workspace register --root mission-control-v7 --cell M000 --workspace-id ws-M000 --branch mcv6/m000 --path /abs/path/to/target-worktree
python mission-control-v7/runtime/tools/mc.py workspace load --root mission-control-v7 --file workspace-reconciliation.json
python mission-control-v7/runtime/tools/mc.py close --root mission-control-v7
```

`mc doctor` is the fail-closed entrypoint before authoritative transitions. `dispatch` freezes distinct worker and verifier custody identities before execution. `settle --attempt N` requires the ContextReceipt worker and adjudication verifier to match those preassigned identities, then binds worker result/ContextReceipt evidence plus the separate control-side adjudication to that attempt. Authoritative state is derived from the adjudication decision, never directly from the worker result claim. Use `mc retry --cell <id>` only after an adjudicated non-accepted attempt; the retry returns to `COMPILED` and requires fresh custody assignment on redispatch. Late evidence from older attempts is rejected.

`mc sources load`, `mc provenance load`, and `mc corpus load` are transactional semantic-input gates. They are allowed only before baseline compilation, validate provenance/requirement schemas, and roll back on incoherence. Baseline compilation seals those semantic inputs into every compiled ContextManifest; G000 cannot be accepted with an empty target corpus.

## One input

`MISSION.json` contains only owner/author decisions:

```json
{
  "schema": "flyby/mission-control-mission/16",
  "mission_id": "MCV7",
  "control_repository": "SaiFlyBy/flybyrefactor",
  "authoritative_working_branch": "mcv7/mission-control",
  "target_repositories": [
    {
      "repository": "SaiFlyBy/flybymaestro",
      "baseline_sha": "0123456789abcdef0123456789abcdef01234567"
    }
  ],
  "previous_mission_handoff": "archive/mission-control-v6/handoff/CLOSURE.json",
  "previous_mission_handoff_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "owner_intent": ["..."],
  "hard_boundaries": ["..."]
}
```

The mission root is the directory containing this file. `control_root` is derived, not manually duplicated.

## Canonical generated layout

```text
MISSION.json
TEMPLATE_LOCK.json
control/
  CURRENT_AUTHORITY.json
  EXECUTION_DAG.json
  EXECUTION_STATE.json
  COMPILER_CONTROL.json
  SESSION_RESIDENCY.json
corpus/
  TARGET_MUTATIONS.json
  SOURCES.json
  PROVENANCE_SYNTHESIS.json
contracts/
  schemas/
  policies/
runtime/
  tools/
frontiers/
evidence/
handoff/
```

There is one canonical authority path for each concept. Root-level compatibility mirrors such as `00_CURRENT_AUTHORITY.json`, `CANONICAL_EXECUTION_DAG.json`, or `EXECUTION_STATE.json` are forbidden in a v16 mission.

The generated `TEMPLATE_LOCK.json` records the template version, source commit when available, and SHA-256 of every copied runtime/contract asset. Git history is the historical template snapshot; missions do not embed a second template copy.

## Lifecycle

The canonical mission lifecycle is:

```text
UNINITIALIZED
  -> BOOTSTRAPPED
  -> BASELINE_READY
  -> BASELINE_ACCEPTED
  -> MUTATION_READY
  -> INTEGRATING
  -> QUALIFYING
  -> ACCEPTED
  -> CLOSED
```

Baseline acceptance is structural. Mutation cells cannot be dispatched before `BASELINE_ACCEPTED`.

## Built-in baseline

Every mission receives one generic baseline frontier definition with these audit responsibilities:

- `A000` existing tests and verification inventory;
- `A001` performance and resource baseline;
- `A002` architecture and authority inventory;
- `A003` provenance/source inventory;
- `A004` environment and execution-capability inventory;
- `G000` baseline barrier depending on all five audits.

`baseline compile` materializes the audit workcells. `baseline accept` only crosses G000 after all baseline audits have accepted typed evidence.

Mission-specific audit cells may be added, but the generic baseline cannot be silently removed.

## Typed cells

v16 exposes four executable cell kinds plus barriers:

- `AUDIT`: read-only discovery with a typed downstream result;
- `MUTATION`: one or more canonical `requirement_ids`, exact target base, owned write scope, positive/negative verification, rollback/evidence requirements;
- `INTEGRATION`: bounded reconciliation of accepted mutation evidence;
- `QUALIFICATION`: full-system/no-regression evidence;
- `BARRIER`: non-executable dependency gate.

Every cell also declares a `conflict_class` and explicit `resource_claims`. Dispatch refuses concurrent cells with the same conflict class or overlapping resource claims.

A cell descriptor is not a worker prompt. `mc compile` expands a frontier descriptor through one pure construction path into a schema-validated `CompiledWorkCell` and exact `ContextManifest`. `mc doctor` validates both schemas, reconstructs both artifacts, and fails if materialization has drifted from compiler output.

Settlement requires `--attempt`, worker-owned `result.json` and `context_receipt.json`, plus control-owned `adjudication.json`. The adjudication binds canonical hashes of the exact result, ContextReceipt, CompiledWorkCell, and ContextManifest; its verifier identity/session must differ from the worker. An `ACCEPTED` adjudication must also attest the exact compiled acceptance criteria through `verified_acceptance`. Only the adjudication decision can change authoritative cell state. Accepted executable cells retain all three immutable per-attempt artifacts, and `control/SESSION_RESIDENCY.json` records provider/native worker continuation identity or explicit `IDENTITY_UNAVAILABLE`. Aggregate normalization remains forbidden.

Target provenance is executable, not decorative: every target requirement cites admitted source IDs; repository sources require immutable pins; each requirement `targets` field names exact repositories already frozen in `MISSION.json`; mutation cells may bind active `requirement_ids` only on repositories listed by those requirements, and every active requirement must have mutation coverage for every listed target repository. Every active requirement acceptance clause must also be carried by bound mutation-cell acceptance contracts on every repository targeted by that requirement before integration. A requirement may be waived only in the frozen pre-baseline target corpus with explicit reason/authority; waived requirements must not receive mutation authority. Final qualification must accept every active requirement and reproduce every frozen waiver exactly. Each accepted `INTEGRATION` result must enumerate every accepted mutation cell in `integrated_mutations` and bind its exact immutable mutation result head. Accepted integration cells must then converge on one head per mission target; accepted `QUALIFICATION` results must prove those same integrated heads at settlement time, and terminal target outcomes must match them. `verification_accounting.run` must equal the acceptance criteria independently adjudicated on accepted `QUALIFICATION` workcells, so closure cannot invent verification claims. The accepted qualification also records target baseline/accepted-head pairs, verification waivers/not-run accounting, unresolved defects, and limitations. `close` deterministically copies that accounting into the immutable closure artifact.

## Provenance-to-mutation synthesis

Repository, paper, document, and prior-mission provenance must pass through an explicit synthesis layer before it can authorize target mutation. The canonical chain is:

```text
SOURCES.json
  -> PROVENANCE_SYNTHESIS.json
  -> TARGET_MUTATIONS.json
  -> mutation/integration/qualification cells
```

`SOURCES.json` freezes source identity and revision and records a rights-aware implementation boundary. `OWNER_AUTHORIZED_REUSE` and `LICENSE_PERMITTED_REUSE` permit direct/adapted implementation reuse only when the exact admitted revision has verified rights evidence and retained obligations. `CLEAN_ROOM_BEHAVIORAL_SYNTHESIS` remains available when direct code/text/structure reuse is not authorized or not desired. A permissive license removes artificial clean-room restrictions; it does not make blind copying an engineering default.

`PROVENANCE_SYNTHESIS.json` decomposes admitted sources into mechanisms and records how deeply each source was reviewed. Every synthesis source uses rights-independent `ADAPTIVE_MULTI_ROUND_EXCORIATION`: exhaustive discovery, omission/adversarial challenge, and target-integration deepening are the minimum three turns; the same thread continues without a fixed maximum while material omissions or uninspected critical partitions remain. Source-local custody is exclusive: a source's reviewer cannot delegate its adjudication to another source's review thread; such outputs are invalid until reproduced by the owning thread. Mechanisms record target capabilities already inspected, gaps/preservation, disposition (`NEW_MUTATION`, `EXTEND_EXISTING`, `COMBINE_EXISTING`, `ALREADY_SATISFIED`, or `REJECTED`), reuse class, exact reuse source IDs/obligations when implementation material is reused, target-native derivation, and verification intent.

Each authorizing source has a `source_assessment` and source-local `mechanism_contributions` that are independently digest-bound; cross-source synthesis separately binds the final shared mechanism graph. `SYNTHESIS_REQUIRED` uses the adaptive `deep_review` + independent-review path. `ADJUDICATED_SYNTHESIS` is allowed only when an already-completed independent adjudication is preserved as immutable mission-local receipt and candidate bytes with exact SHA-256 bindings and a `READY_FOR_AUTHORITY_ADMISSION` disposition. Neither path permits citation-only admission. Baseline compilation is blocked when rights are unverified for claimed reuse, required review/adjudication evidence is incomplete, known material omissions remain, questions are unresolved, or source/mechanism accounting is not bidirectional.

`TARGET_MUTATIONS.json` binds requirements to exact mechanism IDs and records the target-native abstraction, composition strategy, preserved/migrated behavior, non-goals, verification strategy, actual rights posture, and mission-level `provenance_materialization`. If the target already has a lineage manifest, Mission Control creates a requirement that updates it with every materially used source, exact revision, rights basis, review evidence, implementation location, and retained obligations. Provenance remains lineage-only unless a separate architecture decision grants runtime authority.

The preferred engineering question is not “what is the smallest diff?” but “what combination preserves mature target strengths while extracting the greatest justified value from the sources?” Useful source capabilities cannot be silently discarded merely to minimize change, and multiple source mechanisms should be combined when one coherent target abstraction can carry them.

See `policies/PROVENANCE_SYNTHESIS.md` for the full rights verification, multi-round excoriation, synthesis, reuse, target-lineage, verification and closure methodology.

## Reusable provenance-ingestion workflow

`policies/PROVENANCE_INGESTION_WORKFLOW.md` is the reusable mission-level workflow for turning provenance into implementation-grade target improvements. It makes the material mechanism—not the repository/paper/document name—the unit of ingestion; requires exhaustive bounded source coverage, independent current-target comparison, per-mechanism disposition, preserved specialization, cross-source fusion, and exact qualification consequences; and fails closed on representative sampling, wrapper/stub-only adoption, false equivalence, convenience rejection, or MVP/minimal-surface substitution.

The closed-loop audit rule to make the smallest correct intervention remains valid for closing one finding. It must never be interpreted as permission to minimize accepted capability scope. A later mutation stage may optimize implementation shape, but it may not silently reduce the admitted mechanism set or required end-to-end behavior without a new evidence-backed adjudication.

Future missions receive this workflow automatically because template initialization copies all policy files into `contracts/policies/`. Missions may add domain-specific obligations, capability lanes, rights rules, or adjudication topology, but those specializations do not weaken the generic ingestion-depth contract unless owner authority explicitly changes scope.

## MCV engineering-audit and serial adjudication methodology

The reusable template now also carries the closed-loop methodology proven during MCV6 in `policies/MCV_ENGINEERING_AUDIT_AND_ADJUDICATION.md`. It is a source-evidence maturation pipeline nested inside provenance synthesis; it does not replace the top-level Mission Control lifecycle.

The reusable flow is:

```text
Stage A source-local construction/normalization
  -> independent Stage B adversarial audit
  -> optional independent QA/remediation generations
  -> exact corpus A/B closure ledger + different-author integrity
  -> current Stage-C readiness/preflight
  -> canonical serial Stage-C queue + hardening gates
  -> one-source-at-a-time persistent adjudication
  -> durable full-source terminal receipt + independent validation
  -> scheduler recompute
  -> cross-source convergence / owner resolution
  -> explicit authority admission
  -> separately authorized implementation + qualification
```

The central laws are intentionally fail-closed: exact source identity/version/rights precede interpretation; deep audits use bounded tranches and close one material finding at a time; historical bytes remain immutable custody and corrections are additive; Stage-A authors do not self-certify Stage B; readiness is packaging rather than adjudication; only one fresh Stage-C source may be in flight; provider/catalog availability alone is not session-recovery proof; scheduler advancement requires a durable full-source terminal receipt plus independent validation; and no source candidate, readiness packet, Stage-C result, or provider response silently grants shared-authority admission or target-mutation authority.

Parallel workers may audit disjoint source-local resources and prepare dormant future packets, but canonical queues/shared ledgers remain single-writer surfaces and actual Stage C remains serial. Live coordination authority comes from current claims plus durable receipts rather than stale task-summary fields. When the source/audit phase uses a frozen target, target mutation stays read-only until the mission's explicit implementation gate is satisfied.

## Native multi-phase task queue

`policies/NATIVE_TASK_PIPELINE.md` and `schemas/TASK_PIPELINE_SCHEMA.json` make the staged MCV review pattern directly schedulable across independent chat seats. The initial queue contains every Phase-A item. A later phase is created only after its predecessor terminalizes, and is appended at the queue tail; it does not jump ahead of already queued Phase-A work. Completion may immediately refill the worker's durable collaboration inbox with its earliest eligible task.

The phase contract carries independence explicitly: Phase B can require a different seat from Phase A, and a later final-review phase can require a seat not used anywhere earlier in that item's lineage. The reference pipeline demonstrates `A -> B(independent adversarial review) -> C(distinct lineage seat)`. Mission-specific authority still wins: MCV6 source Stage C remains its canonical serial adjudicator lane, while the implementation program uses per-cell ChatGPT A/B followed by convergence and the top-level final Astra barrier rather than pretending every workflow has the same Phase C.

The queue is execution plumbing, not authority. Green worker receipts do not authorize convergence, admission, implementation, promotion or release. See `examples/reference-mission/TASK_PIPELINE.json`.

## Workspace ledger

Final reconciliation is checked against execution-time and live Git authority, not against its own self-declared inventory. `control/WORKSPACE_LEDGER.json` is created at bootstrap with the canonical control repository/branch. Every compiled target-bearing cell must register one mission-owned target workspace/branch before dispatch using `mc workspace register --path ...`; registration proves the exact Git worktree root, requested branch, compiled base HEAD, clean status, base ancestry, and `origin` URL, then records their custody data. Dispatch requires and durably records that workspace ID. Duplicate workspace IDs and duplicate repository/branch registrations fail closed.

At closure, `handoff/WORKSPACE_RECONCILIATION.json` must account for the ledger exactly. This lets a mission reconcile only the workspaces it created or explicitly registered, without scanning or mutating unrelated repositories under the same parent directory.

## Workspace and candidate reconciliation

A mission is not closable merely because qualification passed. `control/WORKSPACE_LEDGER.json` records canonical control identity and every mission-authorized target workspace/branch plus its live worktree path, registered HEAD, clean-status digest, and origin URL. A target-bearing cell must be registered with `mc workspace register --path ...` before dispatch and then dispatched with the exact `--workspace-id`. Before closure, classify every ledger entry plus any historical temporary control workspace, preserve unique historical evidence only under typed hash-bound supersession to exact successor authority, and load `handoff/WORKSPACE_RECONCILIATION.json`. Reconciliation must match the ledger and re-prove live Git path/branch/HEAD/status/base ancestry/origin; `mc close` refuses terminal authority without it, and `doctor` hash-binds it after closure.

This prevents an older worktree or branch from retaining a contradictory `ACCEPTED` result after canonical authority has superseded it. It also prevents cleanup from sweeping unrelated repositories merely because they share a parent directory. See `contracts/policies/WORKSPACE_RECONCILIATION.md`.

## Three-layer separation

Every mission still separates:

```text
CONTROL SYSTEM        how Mission Control operates
TARGET CORPUS         what the target must become
REUSABLE TEMPLATE     what methodology survives to later missions
```

Every reusable discovery is classified `MISSION_CONTROL_ONLY`, `TARGET_ONLY`, or `BOTH`. Target discoveries become machine-readable target requirements. Reusable control discoveries update this template before mission closure.

## Authority laws retained from v15

v16 simplifies the operator surface; it does not remove the hard-won control laws:

- target and control repository custody remain separate;
- target mutations bind exact repository/branch/head and never inherit a control branch by accident;
- topology is versioned/static authority while mutable progress lives in execution state;
- compiled workcells and exact context/evidence contracts precede dispatch;
- worker self-report is candidate evidence, not acceptance;
- structured outputs are validated before settlement/integration;
- context/session reuse is evidence-bound and does not transfer prior authority;
- independent work may execute concurrently; true conflicts and canonical state transitions serialize minimally;
- failure is localized and repaired through bounded evidence-bearing attempts;
- closure states what was proven, skipped, waived, or unresolved.

Detailed policies live under `policies/` and are copied into `contracts/policies/` for each mission.

## Prescriptive diagnostics

`mc doctor` emits stable error codes with expected location, likely cause, and repair action. Example:

```text
MC0163 runtime tool missing: runtime/tools/mc.py
  likely: mission was manually assembled or generated bootstrap assets drifted
  repair: python mission-control-template/tools/mc.py repair bootstrap --root <mission-root> --template-root mission-control-template
```

A mission with doctor errors cannot perform authoritative lifecycle transitions. `repair bootstrap` is restorative, not an upgrade command: it requires the mission's existing `TEMPLATE_LOCK.json`, requires the supplied template bytes to match that lock exactly, restores only locked generated assets, removes stale unlocked files from generated runtime/contract directories, and rolls back if coherence is not restored. A missing lock must be recovered from version control or another trusted provenance source rather than reconstructed from an arbitrary template checkout.

## Template acceptance

The template owns an end-to-end golden test:

```text
empty temporary directory
  -> initialize reference mission
  -> doctor
  -> load admitted sources, provenance synthesis, and target requirements transactionally
  -> compile baseline and prove packet/context parity
  -> reject malformed result and ContextReceipt evidence
  -> dispatch/settle all baseline audits with attempt/session-residency records
  -> accept baseline barrier only with a non-empty target corpus
  -> reject a stale target base
  -> compile requirement-bound mutation frontier
  -> prove conflicting mutations cannot run concurrently
  -> dispatch/settle serialized mutations
  -> cross mutation barrier and settle typed integration work
  -> enter qualification and settle typed qualification work
  -> reject incomplete requirement accounting
  -> accept target-head/verification/limitation qualification evidence
  -> deterministic closure
```

Run it with:

```text
python mission-control-template/tools/test_template_v16.py
```

The test uses only the Python standard library. If the template cannot bootstrap and close its own reference mission, v16 is not releasable.

## Internal files

`TEMPLATE.json` is intentionally small and operational. Schemas live in `schemas/`; durable control laws live in `policies/`; operators normally use only `tools/mc.py`.

Do not manually compose a new mission from template internals. Use `mc init`.

Cross-source synthesis is not a concatenation step: it must disposition multi-source combination hypotheses, build a deterministic runtime/control intercept matrix, merge identical semantic signatures, and resolve same-state collisions before baseline seal. Retired reviewer contexts are tombstoned evidence and cannot be reused as valid source-review custody.
## Source-review turn custody and mechanical birth evidence

New source-review generations created after turn-contract enforcement use `SOURCE_REVIEW_TURN_CONTRACT_SCHEMA.json` v2 plus `SOURCE_REVIEW_TURN_CHAIN_INDEX_SCHEMA.json` and `DIRECT_LAUNCH_RECEIPT_SCHEMA.json`. Every review generation is a direct top-level provider session: the review session may not create or delegate child review threads, forks, or subagents. A canonical source owner cannot be admitted from self-declared `DIRECT_TOP_LEVEL` metadata alone.

Admission requires:
1. `DIRECT_LAUNCH_RECEIPT_SCHEMA.json` with `approval_policy="never"`, `sandbox_policy="danger-full-access"`, `child_thread_created=false`, and `delegation_used=false`.
2. Mechanical provider session birth evidence artifact (`session_birth_evidence_ref` and `session_birth_evidence_sha256`) parsed and validated to ensure no `create_thread`/`fork_thread` tool calls or forbidden policies occurred.
3. Turn 1 has no predecessor; each later turn binds the exact previous turn self-hash. Each envelope also binds the adoption revision, phase contract and prompt, exact source revision, critical-partition manifest, source-pinned locator content hashes, evidence artifact, rights mode, contributions, and convergence state.

Older source-review generations are not rewritten to look compliant. They remain explicitly indexed as legacy pre-enforcement evidence and retain their original mailbox/final-artifact custody. Mission Control never fabricates retroactive turn hashes. Child-created review results are tombstoned from canonical authority. A replacement generation must tombstone the same source's prior owner and receives a new generation number. Replacement-required state clears active thread/turn count while preserving retired custody evidence.

### Resumable source review

Source reviews use durable non-authoritative checkpoints rather than an unbounded read-then-report pass. `schemas/SOURCE_REVIEW_CHECKPOINT_SCHEMA.json` and `tools/source_review_turn_chain.py` bind each checkpoint to the exact source/version and predecessor digest and require exact next-cursor resumption. `schemas/SOURCE_REVIEW_CLEANUP_SCHEMA.json` defines post-adjudication cleanup: only declared temporary source payloads may be deleted; protected authority evidence and agent-authored durable review artifacts remain retained.
