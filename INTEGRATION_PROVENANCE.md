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
