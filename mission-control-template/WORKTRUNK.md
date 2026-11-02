# Worktrunk and Mission Control

This fork includes Mission Control v16 and a bridge that creates a Worktrunk
worktree for one compiled mutation cell. Python 3 and Worktrunk 0.81.0 or
newer must be available. Initialize and compile a mission with the normal
[Mission Control operator commands](README.md) first.

Once the cell is compiled, create its workspace and assign separate worker and
verifier identities:

```sh
python path/to/mission/runtime/tools/wt_mission.py prepare \
  --root path/to/mission --repo path/to/target \
  --cell M000 --workspace-id ws-M000 --branch mission/m000 \
  --worker worker-M000 --verifier verifier-M000
```

`--repo` is the existing target worktree root. `--path` may specify a
new worktree directory; otherwise Worktrunk chooses it. The adapter checks
the compiled repository against `origin`, creates the branch from the exact
compiled base, suppresses Worktrunk and Git checkout hooks for that creation,
and asks Mission Control to register the clean workspace before dispatch.
For a nonstandard origin, an operator who has verified it may supply its exact
URL with `--expected-origin`. Registration or dispatch failure leaves the
worktree in place for inspection. The bridge does not start or replay hooks:
run approved setup only after dispatch has granted the cell's resource claims.

Omit both `--worker` and `--verifier` to register without dispatch.
Mission Control's ordinary `dispatch` command can start it later. A conflict
in the class or resource claims remains a Mission Control dispatch error.

Inspect the independent adjudication, requirement links, candidate head and
evidence references for a scope:

```sh
python path/to/mission/runtime/tools/wt_mission.py report \
  --root path/to/mission --cell M000
```

The report is a bounded, read-only projection, not a new decision or evidence
that an unrecorded check ran. Settlement still needs the result, context
receipt, attempt number and separate verifier adjudication:

```sh
python path/to/mission/runtime/tools/wt_mission.py settle \
  --root path/to/mission --cell M000 --attempt 1 \
  --result result.json --context-receipt receipt.json --adjudication adjudication.json
```

An explicitly requested publication uses the accepted workspace head and opens
one draft PR. It checks GitHub access, the live remote base, the branch and
the accepted evidence before pushing; it never force-pushes, squashes, rebases,
merges or deletes a worktree:

```sh
python path/to/mission/runtime/tools/wt_mission.py publish \
  --root path/to/mission --cell M000 --base main \
  --title "Complete one coherent scope" --body "Evidence and limitations"
```

Publication checks that the current remote base is an ancestor of the exact
independently accepted candidate. If main advanced but was included before
verification, the scope can proceed without a separate aggregate branch. If
the current base is absent or cannot be checked locally, publication stops and
the branch is preserved. Reassess the candidate and which evidence is still
valid; a changed base does not automatically make prior checks valid or
invalid. A failed or uncertain push or PR creation must be reconciled before
retrying.

For final workspace accounting, prepare the reconciliation required by v16,
then load it and optionally close:

```sh
python path/to/mission/runtime/tools/wt_mission.py reconcile \
  --root path/to/mission --file workspace-reconciliation.json --close
```

The bridge does not make a local aggregate branch. Mission Control's existing
integration, qualification and closure evidence still applies. In v16 all
mutation cells in one mission are pinned to its frozen target baseline.
A later workspace still starts at that compiled base. After dispatch, the
worker can explicitly incorporate current main before independent verification;
the bridge never performs that merge automatically. If an already accepted
head lacks a later main commit, v16 cannot replace that accepted evidence in
place; a newly based mission is currently required. The bridge does not yet
transfer baseline or test evidence across missions automatically.

## Qualification dependencies

The original v16 proof inventory is retained, including checks tied to the
source repository's historical `archive/mission-control-v6` fixture and its
Mission Control CI workflow definitions. Those source-repository artifacts
are not included in this fork. Consequently the original full template
qualification cannot pass here yet: the legacy byte-custody test lacks the
archive, and the proof-runner contract test cannot find the two original
workflow definitions. The v16 golden lifecycle and the bridge's focused tests
do not replace those missing proofs. A future fork-specific CI integration
must supply equivalent evidence and preserve the existing required gates.
