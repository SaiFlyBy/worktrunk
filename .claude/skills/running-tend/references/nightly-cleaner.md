# Nightly Sweep — Worktrunk Specifics

## Survey Checklist

For each `.rs` file in the survey, also check:

- **System docstring** — modules with cached state, coordination logic, or non-obvious invariants need a spec docstring (see AGENTS.md "System Docstrings"). Flag if missing or stale.

## Branch Naming

`nightly/clean-$GITHUB_RUN_ID`

## Repo-Wide CI Breakage

Record failures and cancellations in the workflow summary; the fork does not run the upstream Tend failure reporter.
