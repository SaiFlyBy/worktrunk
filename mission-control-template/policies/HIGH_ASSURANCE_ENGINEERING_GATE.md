# High-Assurance Engineering Gate

This policy turns the engineering-hardening assets into one qualification surface. Individual validators are diagnostics; they are not independent release authority.

## Adoption

A mission adopts this contract when owner intent, mission planning, or target risk requires exhaustive source accounting, specification-driven mutation, source-rights closure, structural mutation evidence, or exact CI qualification. Large MCV synthesis campaigns are expected to adopt it explicitly in their mission plan and acceptance criteria.

Adoption is sticky for the mission. Once the high-assurance contract is used to authorize design or mutation, later stages may not silently drop it to obtain a green result.

## Canonical command

The canonical aggregate validator is:

```text
python runtime/tools/validate_high_assurance.py --root <mission-root> --phase <design|pre-mutation|qualification>
```

It composes, in one fail-closed result:

- frozen dynamic source-collection membership and raw enumeration evidence custody;
- repository source-surface evidence custody, including root inventories and terminal receipts;
- specification, engineering-ledger, source-surface, structural-plan and CI-matrix semantic closure;
- engineering-ledger reuse/rights/obligation closure against canonical source rights;
- from `pre-mutation` onward, structural mutation plan binding to the canonical execution DAG, exact requirement set, target repository/base and bounded write scope.

Running one sub-validator successfully does not prove the aggregate gate. A mission may run sub-validators for diagnosis, but release or mutation authority cites the aggregate result.

## Phase law

`design` validates the semantic and evidence contracts before a mutation frontier necessarily exists.

`pre-mutation` is required after the mutation frontier has been compiled and before the first ordinary target mutation is dispatched. Missing DAG/ledger/plan bindings are blockers at this phase. Every high-assurance mutation plan must bind the exact canonical mutation cell it governs.

`qualification` is required on the exact integrated candidate after all meaning-bearing mutation has stopped. Any relevant change after a passing qualification result makes that result stale and requires re-running the gate.

## Binding into Mission Control

The mission plan and compiled acceptance graph must name the aggregate command as a required pre-mutation and final-qualification gate. A worker, wrapper, alternate orchestrator, or manual path that bypasses the aggregate validator does not gain mutation or release authority merely because individual artifacts exist.

A required failure, missing artifact, missing evidence file, stale hash, unresolved rights obligation, unbound structural plan, skipped CI path, or unauthorized waiver is blocking evidence. Do not weaken the validator, delete a proof, or substitute a narrower command to obtain green status.

## Evidence durability

The final mission record retains the exact aggregate command, phase, candidate identity where applicable, raw output/evidence reference, and the hashes/identities already required by the underlying contracts. Historical green evidence from an older candidate or older semantic authority is not transferable to a newer one.
