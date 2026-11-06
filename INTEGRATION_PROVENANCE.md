# Integration provenance

- Worktrunk: `max-sixty/worktrunk` at
  `f478bb3885b2c40120d511a0b3dfd1d14ba36bb7`, MIT OR Apache-2.0;
  the upstream `LICENSE` is retained.
- Mission Control template v16: `SaiFlyBy/flybyrefactor` at
  `29efd0ffcac21717fd789da2c7020a7e02501e00`. The owner authorized
  integration into this public fork. The template continues to lock the
  actual runtime and contract assets copied into each mission.
- P-stack: `cursor/plugins` at
  `4dd1d05818d19792e7cd6e818f1667f95f7e1dbe`, version 0.15.36,
  MIT. The license is in `docs/third_party/pstack/LICENSE`.

The Worktrunk bridge's bounded, read-only scope report adapts the useful
decision-projection idea from the P-stack `show-me-your-work` capability.
It reads Mission Control's own adjudication and evidence rather than importing
Maestro's event store or claiming its records are complete. The inspected
Factory staging tree was `c6f9341279256034e73c8d0ee36fd1841246211d`;
its decision projection file SHA-256 was
`ffcd0f952a709aa6170ae408170dfab269e65ab2c9ca7b8c0666f94583f9522d`.
The underlying P-stack skill was cataloged with SHA-256
`920a8217cbb62f92a2222fb81fc9eab17ecd554a0277e444a95a927195139bd1`.

The Factory forge observation/admission code is deliberately not activated:
its producer says the production issuer and acceptor are unavailable.
Worktrunk already provides project forge operations, and Mission Control owns
workspace and independent-verifier authority. Existing coherent-pr-synthesis
and evidence-based-ci skills remain the PR and CI guidance; no new skill is
introduced here.


## Cell-coordination synthesis (2026-11-06)

| Source identity | Owner | Disposition | Reason and verification |
| --- | --- | --- | --- |
| Accepted main `379e579307a490ce0e1e7ae7fceefccee85116e0` | SaiFlyBy repository | Base | Live accepted main refreshed before implementation. |
| PR #6 `11608df897c0688d07759697db240143cb7f3c1a` | Retained settlement-adapter producer | Reused exact bridge/test increment, extended for generation fencing | Identical-evidence lost-response reconciliation is necessary; it is not writer termination. Existing reconciliation regressions remain in the gate. Source worktree/PR preserved. |
| Reservation dirty candidate on `flyby/execution-reservation-v1-20261104` | Retained reservation producer (custody verified) | Reviewed; complete mechanism replaces its provisional proposal in this candidate | Runtime SHA-256 `9ffefc09e81e7912869fe40c2003bddf1b050961efe27e78da6d3c24dc91db94`; diff SHA-256 `6aba5ed012946c71fb98647616b8a9c257db5d304a9f124f52cd9580881b71ab`. Stable mission locking, exact workspace binding and fail-closed uncertain launch are preserved in the design. The provisional runtime rejects terminal reconciliation and has no ordered path queue. Its uncommitted files and worktree remain untouched. |
| PR #7 `d707c4dff4132d98f086689c1b2dad168d7e7ea5` | Retained lineage producer | Deferred, preserved | Optional lineage protection is a separate scope; not treated as accepted main or imported. v19 leaves its v18 identity available for serial integration. |
| Runner route `24063b033305e20c5ec51596227a16fcc2ff1b69` and dirty `owner-linux-ci-20261105` worktree | Separate CI scope; qualification now assigned to this task | Existing infrastructure proposal preserved; narrow capability gate reused | Dedicated Linux job `127613400386`, run `42049565892` attempt 2, passed checkout/build/bridge/both golden modes on runner 21. Existing Windows job remains cancelled. Owner-only Actions policy 10761 verified active, all workflows, only user 226779263. No policy or runner registration changed. |

`tests/test_cell_coordination.py` is registered in the canonical proof layers,
retained inventory, feature map and bridge gate. Candidate-specific execution
receipts and any remaining platform/legacy-fixture limitations are reported with
the final candidate; this source record alone does not establish a test pass.


The implementation adds only its fixed-branch, exact-SHA manual qualification
gate and the gate's qualified preparation action. It does not import the separate
proposal to reroute general Rust CI. The prototype routing worktree remains
separate; only the capability-specific gate belongs to this mechanism.
