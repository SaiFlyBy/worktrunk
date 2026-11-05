# Worktrunk CI automation

The fork keeps test results, Rust coverage, and benchmark outputs as GitHub Actions artifacts. Do not add third-party analytics, coverage uploads, or agent/bot workflows without an explicit decision. `.config/tend.yaml` disables the pinned generator's ordinary agent workflows; normal regeneration must continue to generate none.

## Admission and execution

GitHub Actions policy 10761 (`SaiFlyBy only`) must remain active for all workflows (`~ALL`, no exclusions), allowing only user ID 226779263. It blocks outsiders from starting workflows, including workflows changed in a pull request. Fork-PR approval settings are separate and are not a substitute for this owner-only policy. Verify the live policy before registering or starting a local runner; never relax it to make a job run.

The Linux Rust jobs in `ci.yaml` and the Linux Mission Control bridge use the dedicated repository-scoped labels `[self-hosted, Linux, X64, worktrunk-docker]`. Their entry guards require this repository, the owner's original actor ID and triggering login, and a same-repository head for PRs. These source checks are defense in depth, not the external-actor enforcement boundary. Owner-initiated PR work is allowed on this dedicated runner. Windows, macOS, ARM, release publication, and all other workflows retain their existing hosted runners. Never label a Linux x64 runner as another platform or use the generic `self-hosted` label alone.

The container must have its own work, tool and credential volumes, no host-directory or Docker-socket mounts, and no privileged mode. Its cleanup script is not disposable isolation: runner credentials, tool caches, and container changes can survive jobs. Only owner-admitted code may run there. Do not expose controller credentials or release secrets. Registration and security-setting changes require separate approval.

`pull_request_target` must not execute candidate code. GitHub can report skipped jobs as successful for required-check evaluation; a skipped PR is not tested. Require successful checks for the admitted exact candidate before acceptance.

## Reports and release destinations

Code coverage is Rust-only; do not infer Python integration coverage from it. The tag-triggered release workflow publishes GitHub release artifacts and may use Sigstore via packslip. The upstream SignPath organization is not configured; Windows artifacts are unsigned. Publishing packages to external registries requires a separate, explicit setup for this fork. Environment secrets are available to jobs naming the environment: pass each secret only to the step that needs it, and do not broaden branch or tag policies to make a job run. Upstream-owned Tend, gist, Winget, Homebrew tap, and AUR bot publishing are not configured in this fork. The optional `pre-commit.ci` app, if installed, is controlled outside this repository; its inherited config alone neither proves installation nor disables it.

## Build environment

Swatinem/rust-cache hashes the CARGO* and RUST* variables visible at the cache step. Workflows sharing a cache must set the same variables before that step. A mismatch restores nothing without failing the job. Keep the existing tests and checks unless an evidence-based change justifies adjusting them.
