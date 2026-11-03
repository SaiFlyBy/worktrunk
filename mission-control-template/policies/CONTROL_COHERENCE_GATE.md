# Control Coherence Gate

Before any new dispatch or authoritative control-state transition, run a deterministic cross-authority coherence preflight.

It must fail closed when declared machine authorities disagree about matters such as:

- canonical topology/schema identity;
- static topology versus mutable execution state;
- barrier satisfaction contracts;
- promoted architecture/capability bindings;
- mutation requirement and transfer-ledger coverage;
- output settlement requirements;
- session reuse defaults/lifecycle;
- canonical template location/identity.

A historical or currently-running attempt may remain pinned to an older exact control revision only when that identity is explicitly recorded in execution state and clearly distinguished from current canonical authority.

The gate verifies control consistency, not target-product correctness. Passing it never substitutes for cell verification, evidence adjudication or hostile release evaluation.

When instantiating the template, adapt `tools/check_control_coherence.py` to the mission's concrete paths and architecture-specific invariants while preserving its fail-closed cross-authority checks.
