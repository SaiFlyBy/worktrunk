# Workspace and Candidate Reconciliation

Mission closure is not complete while branch, worktree, candidate, temporary compiler, or evidence authority remains ambiguous outside the canonical mission state.

## Execution-time workspace ledger

`control/WORKSPACE_LEDGER.json` is canonical execution authority, not a cleanup convenience. Bootstrap registers exactly one control workspace. Before any target-bearing compiled cell may dispatch, the orchestrator must run `mc workspace register` with the exact cell, workspace id, target branch, and live worktree path. Registration derives repository and frozen base from the compiled cell; callers do not get to restate them. The live worktree must be the Git toplevel, be on the exact requested branch at the exact compiled base, be clean, prove the compiled base is an ancestor, and expose a nonempty `origin` remote. The ledger stores the resolved path, registered HEAD, clean-status digest, dirty flag, and origin URL. Failed or partial Git probes are rejection, never nullable evidence. Duplicate workspace ids and duplicate repository/branch identities fail closed.

Dispatch of a target-bearing cell requires `--workspace-id` and proves that the ledger record was registered for that exact cell/repository/base. Non-target cells may not claim a target workspace. This makes every mission-authorized target branch/workspace discoverable before mutation begins.

Final `WORKSPACE_RECONCILIATION.json` must account for the ledger exactly: the canonical control workspace id set and all registered target workspace ids must match one-for-one, and each target record must preserve its registered repository/branch/path/origin identity. Reconciliation re-runs Git against every target path and binds the live branch, HEAD, clean-status digest, base ancestry, and origin URL; caller-authored summaries cannot substitute for those probes. A self-consistent but incomplete closure inventory therefore cannot omit a mission-authorized target branch. Workspaces or branches created outside this registration law never acquire Mission Control authority.

## Closure law

Before `mc close`, enumerate every mission-created control workspace and every surviving target branch/worktree that the mission created or used. Do not scan or mutate unrelated repositories. The reconciliation scope is the mission's own workspaces plus target branches/worktrees explicitly created by this mission.

Every item receives a terminal disposition. Control workspaces are canonical, superseded, temporary-and-reconciled, or archived. Target branches are accepted, unmutated historical, superseded-and-preserved, or rejected-and-preserved. There is no silent `unknown` or `probably unused` state at closure.

Useful historical facts may be archived, but stale adjudication has zero authority. If an older workspace says a candidate was accepted and later canonical authority superseded that decision, preserve the old bytes only under an explicit supersession record. `SUPERSEDED_EVIDENCE` requires a typed, hash-bound supersession artifact that identifies the exact old evidence ref/hash and the exact successor authority ref/hash; the existence of some unrelated file is never enough. Never rewrite the historical evidence to make it look as though it always agreed with current authority.

## Procedure

1. Reconcile the canonical `control/WORKSPACE_LEDGER.json`; every mission-authorized target branch/workspace must have been registered before dispatch. Separately inventory historical compiler/recompile/baseline workspaces that predate or sit outside active dispatch records.
2. Record repository, branch, HEAD, dirtiness and role without mutating them.
3. Compare non-canonical control workspaces with canonical authority. Preserve unique evidence by hash when it has audit value.
4. Enumerate every target branch created by the mission and count commits beyond its compiled/frozen base.
5. Independently review every surviving candidate commit. A green local test is not settlement authority.
6. Resolve contradictory historical decisions by preserving the old record and attaching an explicit canonical supersession disposition.
7. Confirm the qualification's accepted target HEAD is the same accepted HEAD recorded in reconciliation.
8. Confirm no target branch or control workspace remains unclassified.
9. Load `handoff/WORKSPACE_RECONCILIATION.json` and only then close the mission.
10. Archive/remove temporary workspaces only after the canonical reconciliation artifact is immutable and closure is complete.

## Adversarial questions

The verifier should actively ask:

- Is there a branch with a real candidate commit that execution state still calls idle or unmutated?
- Does an old worktree contain an ACCEPTED result that a newer frontier superseded?
- Did a temporary compiler clone generate packets not represented in canonical control?
- Are dirty files being dismissed as caches when they actually contain evidence or authority transitions?
- Does a target candidate pass only because evidence paths, fingerprints or SHAs are caller assertions rather than derived facts?
- Is any unrelated repository being swept into cleanup merely because it shares the parent directory?

Closure fails until these have evidence-backed answers.
