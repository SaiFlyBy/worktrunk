# Worktrunk CI automation

The fork keeps test results, Rust coverage, and benchmark outputs as GitHub Actions artifacts. Do not add third-party analytics, coverage uploads, or agent/bot workflows without an explicit decision. `.config/tend.yaml` disables the pinned generator's ordinary agent workflows; normal regeneration must continue to generate none.

## Admission and execution

For the checked-in workflows, PR jobs that initiate tests run only when the head repository is this repository; a maintainer can deliberately bring an admitted change into a repository branch or run an authorized dispatch. Untrusted PRs can change their own workflow definitions, so these source-level guards are not an enforcement boundary. GitHub's repository setting must require approval for all external contributors to enforce that boundary. `pull_request_target` must not execute candidate code. Use GitHub-hosted runners for PR work, not a maintainer's local runner. Verify current repository settings rather than assuming they match this policy. GitHub can report a skipped job as successful for required-check evaluation; a skipped PR is not tested. Require successful checks for the admitted exact candidate before acceptance.

## Reports and release destinations

Code coverage is Rust-only; do not infer Python integration coverage from it. The tag-triggered release workflow publishes GitHub release artifacts and may use Sigstore via packslip. The upstream SignPath organization is not configured; Windows artifacts are unsigned. Publishing packages to external registries requires a separate, explicit setup for this fork. Environment secrets are available to jobs naming the environment: pass each secret only to the step that needs it, and do not broaden branch or tag policies to make a job run. Upstream-owned Tend, gist, Winget, Homebrew tap, and AUR bot publishing are not configured in this fork. The optional `pre-commit.ci` app, if installed, is controlled outside this repository; its inherited config alone neither proves installation nor disables it.

## Build environment

Swatinem/rust-cache hashes the CARGO* and RUST* variables visible at the cache step. Workflows sharing a cache must set the same variables before that step. A mismatch restores nothing without failing the job. Keep the existing tests and checks unless an evidence-based change justifies adjusting them.


The manual `cell-candidate` gate is the bounded exception for this owner-admitted
cell-coordination implementation. It uses only the already-qualified repository
runner `[self-hosted, Linux, X64, worktrunk-docker]`, requires the owner as both
actor and triggering actor, checks out the fixed implementation branch and
refuses a SHA mismatch before executing candidate code. Live Actions policy
10761 must remain active for all workflows, allowing only user 226779263. Normal
PR/CI routing is unchanged. This gate has contents-read credentials only and
does not permit arbitrary repositories, refs, commands or fork candidates.
