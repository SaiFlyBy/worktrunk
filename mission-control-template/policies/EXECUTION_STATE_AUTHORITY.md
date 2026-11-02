# Execution-State Authority

Future Mission Controls must keep **canonical topology/barrier contracts** and **mutable execution state** separate.

```text
CANONICAL EXECUTION DAG
  versioned dependencies
  conflict/topology metadata
  barrier satisfaction contracts
  NO mutable runtime status

EXECUTION STATE LEDGER
  accepted/pending barrier state
  cell/attempt/receipt state
  active frontier/attempt identities
  transition lineage
```

## Laws

- Completing work never rewrites topology merely to record progress.
- Barrier/cell acceptance, rejection, blocking and supersession mutate durable execution state and bind evidence/attempt identity.
- A dependency or barrier-acceptance-contract change requires an explicit topology revision.
- Every declared topology barrier has a machine-readable satisfaction contract; runtime state records whether that contract has been adjudicated/accepted.
- Crash/restart reconstructs the same frontier from canonical topology + durable state + accepted receipts.
- Stale/superseded attempts cannot overwrite newer accepted transitions.
- Runtime state cannot grant authority absent from governing topology/workcell/policy.
- The state ledger precedes descriptive status prose.
- A currently-running or historical attempt may remain pinned to an older exact control/topology revision when explicitly recorded. That pin does not make the older revision current canonical authority and cannot be retroactively rewritten.

## Minimum execution-state fields

```text
mission/program identity
canonical_topology ref + schema/version
control + target baseline identities
barrier states + evidence/contract refs
cell states + attempt/receipt refs
active frontier/attempt identity when applicable
pinned dispatch-control/topology identity for surviving older attempts
transition laws/lineage
next state transition
```

A mission may additionally project dependency-ready / compiled / admitted / running / candidate / accepted sets when useful.

Before new dispatch, cross-authority coherence must prove that canonical topology identity agrees with current authority/compiler control while any older pinned attempt is explicitly distinguished.

This mechanism is reusable Mission Control methodology. When the target itself performs long-horizon orchestration, transfer the same semantics into its target mutation corpus rather than leaving them as external-control ceremony.
