# Reusable Mission Control Executor Protocol

## Authority split

The Mission Control/control repository owns design, topology, compiled work authority, durable execution state and adjudication. Target repositories own product mutation candidates.

For every mutating cell:

```text
TARGET_BASE = CompiledWorkCell.base.repository + branch + head
```

Create the isolated target branch/worktree from that exact target base. The control/overseer branch is not a target mutation base when control and target are different repositories. Never infer the mutation base across repository custody boundaries.

The executor is scoped execution/repair only. It does not broadly inspect the project, select its next workcell, mutate canonical refs, or integrate sibling candidates.

## Required packet

Product mutation requires:

- exact CoreMutationContract;
- CompiledWorkCell;
- exact ContextManifest;
- every applicable target-transfer requirement;
- accepted dependency evidence;
- exact result schema/hash/template/validator;
- SessionReuseAdjudication when immutable prior receipt evidence is reused beyond its original routing scope.

A DAG topic or transfer-requirement name alone is not executable authority.

## Context

Workers consume only compiled context. Missing context produces an amendment/recompile request rather than open-ended orientation.

Accepted ContextReceipts are immutable. Cell completion ends cell authority, not necessarily the underlying model/provider session. Compatible hot sessions may be rebound by the orchestrator under a new compiled packet; fresh-session selection requires a safety, independence, availability or critical-path/economic reason when compatible hot context exists.

## Mutation custody

Each mutating cell gets one isolated target branch/worktree or equivalent realm with exact base identity and owned/prohibited scope. Workers never push directly to target `main`/canonical state.

Frontier evidence may be aggregated separately in the control repository under a scoped evidence branch. Control evidence aggregation does not integrate target code.

## Settlement

Structured output is strict at the worker boundary:

```text
write from compiled template
→ validate before commit/PASS
→ orchestrator independently revalidates committed child
→ adjudicate/integrate
```

Malformed output remains the same active attempt when repair is possible. Aggregate normalization is forbidden. Before dispatch, the control/orchestrator assigns distinct worker and verifier custody identities and freezes them into the attempt. Worker result and ContextReceipt remain candidate evidence. The control/orchestrator must obtain a separate adjudication from the preassigned verifier custody before authoritative state changes; the ContextReceipt worker and adjudication verifier must match those assignments, and the adjudication binds the exact result, receipt, CompiledWorkCell and ContextManifest.

## Diff-validation phase law

Precommit validation must inspect the uncommitted working tree/index, not a committed range:

```text
git diff --check
git diff --cached --check   # when staged/index changes exist
```

Run both when changes may exist in both locations. `git diff --check BASE..HEAD` compares committed objects only and cannot validate an uncommitted repair.

After commit, validate the committed candidate/range with:

```text
git diff --check BASE..HEAD
```

A precommit committed-range gate is invalid evidence for uncommitted changes and must not override later exact-head postcommit evidence.

## Parallelism and integration

No arbitrary static concurrency cap. Admit dependency-ready work according to semantic/resource conflicts, useful value, session/context economics and downstream capacity.

Independent conflict components may execute/qualify concurrently. Serialize only true conflicting transitions and the smallest canonical advancement critical section.

## Stop

`STOP_CELL_NOT_SESSION`: the worker cannot self-select more work. The session may remain parked for orchestrator-controlled rebinding.
