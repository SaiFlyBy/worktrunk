# Structured Output Contract Enforcement

Every future Mission Control binds **every required structured worker artifact** before dispatch and rejects malformed evidence before integration.

## Compile before execution

For each structured output, bind before worker launch:

- exact schema snapshot/identity;
- schema hash;
- constraint-valid canonical template;
- dependency-free or already-available validator command;
- same-attempt settlement/repair rule.

Generated templates must honor supported assertions such as `minItems` and `minLength`; knowingly invalid empty placeholders are forbidden.

This includes semantic results and ContextReceipts; additional typed receipts are equally strict when required.

## Compiler parity gate

Mutation compiler `--check` and real materialization must execute the **same complete in-memory per-cell packet construction and schema-validation path**. Only filesystem writes may differ.

Before any mutation worker is dispatched, run a disposable materialization parity proof:

```text
FULL PACKET DRY RUN PASS
+ DISPOSABLE MATERIALIZATION PASS
= packet-generation admission
```

The dry run must validate the CoreMutationContract, ContextManifest, all structured templates, reuse adjudication when present, and CompiledWorkCell. A check that passes while real materialization fails is a control-plane defect and blocks dispatch.

## Worker gate

A cell is not terminal until every required structured artifact validates.

On validation failure, keep the same attempt active and return exact errors to the same worker/session. Correct representation inside existing cell scope; do not broaden substantive target context merely to repair serialization.

## Orchestrator gate

Immediately after return and before integration, independently rerun every compiled validator against committed child artifacts.

```text
all worker validations PASS
+ all orchestrator validations PASS
= settlement eligible
```

Otherwise do not integrate or mark PASS. Return exact errors to the same attempt when available.

## Aggregate law

The aggregate layer never rewrites, normalizes or semantically reconstructs malformed worker evidence.

Final aggregate validation is redundant defense. If it is the first detector of an ordinary shape defect, classify a control-plane invariant breach and repair the earlier gate.

## Rerun law

A new semantic run is justified by missing/ambiguous substantive work or an unavailable/unrecoverable attempt—not by a representation error that the same session can correct before settlement.
