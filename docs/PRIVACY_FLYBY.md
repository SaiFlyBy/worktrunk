# Fork privacy and network inventory

Audited Worktrunk commit `f478bb3885b2c40120d511a0b3dfd1d14ba36bb7`.
The inspected CLI source and dependency declarations showed no usage-telemetry
client or analytics reporting module. Local command logs are stored under
`.git/wt/logs/commands.jsonl`; that is local logging, not remote reporting.

The documentation site's Google Analytics loader has been removed. The locked
npm install replaces Astro's telemetry package with a local no-op, including
for direct Astro CLI invocations from that install. The npm scripts also set
Astro's telemetry off switch before the CLI starts. Other package managers
may ignore npm overrides; verify their dependency resolution before invoking
Astro directly. Astro dependency upgrades must review the local interface and
run the privacy tests. The following separate network capabilities remain:

- Default-branch discovery may run `git ls-remote` on a cold cache, and
  Git fetch/push and PR/MR checkout communicate with the configured project.
- List, picker and statusline features may query forge CI, PR and comment
  data through the relevant forge command. These are project features.
- `wt config show --full` explicitly checks the latest Worktrunk release
  at the upstream GitHub API, sending a Worktrunk version user agent.
- The docs site still loads a GitHub-stars badge from shields.io and fonts
  from Google Fonts when browsed; those providers receive the corresponding
  resource requests. They are not CLI usage reporting.
- Configured LLM commands receive their prompt and potentially branch diffs;
  whether they transmit data depends on the command and provider selected.
- Approved hooks, aliases and execute commands are arbitrary programs. This
  fork's project hooks include asset/package downloads and a post-merge
  pull/push command; inspect and approve them according to Worktrunk's normal
  approval flow.
- GitHub Actions retains Rust coverage, JUnit test results and benchmark
  results as GitHub artifacts; the workflows do not upload them to Codecov.
  The inherited Tend bot workflows and upstream-owned benchmark and package
  bot publishing have been removed. Tag-triggered GitHub releases may
  use Sigstore via packslip; upstream SignPath submission has been removed,
  so Windows artifacts are unsigned. This fork does not automatically
  publish packages to external registries.
- A pre-commit.ci-specific config is inherited; its presence does not establish
  whether that external GitHub App is installed. If installed, disabling the
  service requires managing the app outside this repository.

This is a source audit, not a network sandbox. Git, GitHub clients, hooks,
configured LLMs, dependency installers and CI providers can communicate when
their corresponding features run.
