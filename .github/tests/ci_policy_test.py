"""Check the checked-in CI admission and reporting conventions.

These tests are regression checks, not an authorization boundary: a pull
request can modify its own workflow and these tests. The repository's active
owner-only Actions actor policy enforces admission independently of PR source.
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / '.github' / 'workflows'
EVENTS = {
    'affected.yaml': {'push', 'pull_request', 'workflow_dispatch'},
    'benchmarks.yaml': {'schedule', 'workflow_dispatch'},
    'ci.yaml': {'push', 'pull_request', 'workflow_dispatch'},
    'coverage.yaml': {'push', 'pull_request', 'workflow_dispatch'},
    'mission-control-bridge.yaml': {'push', 'pull_request', 'workflow_dispatch'},
    'nightly.yaml': {'schedule', 'workflow_dispatch', 'push', 'pull_request'},
    'publish-docs.yaml': {'push', 'pull_request', 'workflow_dispatch'},
    'release.yaml': {'pull_request', 'push'},
}
ENTRY_JOBS = {
    'affected.yaml': {'collect-affected', 'affected-tests'},
    'ci.yaml': {'lint', 'feature-check', 'test', 'fast-checks', 'changes'},
    'coverage.yaml': {'code-coverage'},
    'mission-control-bridge.yaml': {'bridge'},
    'nightly.yaml': {'gate'},
    'publish-docs.yaml': {'build-docs'},
    'release.yaml': {'plan'},
}
ENTRY_GUARD = ("${{ github.event_name != 'pull_request' || "
               "(github.event.pull_request.head.repo.id != null && "
               'github.event.pull_request.head.repo.id == github.event.repository.id) }}')
OWNER_GUARD = "${{ github.repository_id == '1443337118' && github.actor_id == '226779263' && github.triggering_actor == 'SaiFlyBy' && (github.event_name != 'pull_request' || (github.event.pull_request.head.repo.id != null && github.event.pull_request.head.repo.id == github.event.repository.id)) }}"
SELF_HOSTED_WORKFLOWS = {'ci.yaml', 'mission-control-bridge.yaml'}
RUNNER_LABELS = '[self-hosted, Linux, X64, worktrunk-docker]'
AFFECTED_GUARD = ("${{ github.event_name == 'pull_request' && "
                  'github.event.pull_request.head.repo.id != null && '
                  'github.event.pull_request.head.repo.id == github.event.repository.id }}')
COLLECT_GUARD = ("${{ (github.event_name == 'push' && github.ref == 'refs/heads/main') "
                 "|| github.event_name == 'workflow_dispatch' }}")
DEPENDENT_JOBS = {
    ('ci.yaml', 'msrv'): (['changes'], "needs.changes.outputs.cargo == 'true' || github.event_name == 'workflow_dispatch'"),
    ('ci.yaml', 'check-docs'): (['changes'], "needs.changes.outputs.docs == 'true' || github.event_name == 'workflow_dispatch'"),
    **{('nightly.yaml', job): (['gate'], "needs.gate.outputs.run == 'true'") for job in (
        'feature-powerset', 'full-tests', 'release-target', 'check-unused-dependencies',
        'minimal-versions', 'crate-build', 'link-check', 'nix-flake')},
    ('publish-docs.yaml', 'deploy-docs'): (['build-docs'], "${{ github.event_name != 'pull_request' && github.repository_owner == 'max-sixty' }}"),
    ('release.yaml', 'build-local-artifacts'): (['plan'], "${{ fromJson(needs.plan.outputs.val).ci.github.artifacts_matrix.include != null && (needs.plan.outputs.publishing == 'true' || fromJson(needs.plan.outputs.val).ci.github.pr_run_mode == 'upload') }}"),
    ('release.yaml', 'build-global-artifacts'): (['plan', 'build-local-artifacts'], None),
    ('release.yaml', 'host'): (['plan', 'build-local-artifacts', 'build-global-artifacts'],
        "${{ always() && needs.plan.result == 'success' && needs.plan.outputs.publishing == 'true' && "
        "(needs.build-global-artifacts.result == 'skipped' || needs.build-global-artifacts.result == 'success') && "
        "(needs.build-local-artifacts.result == 'skipped' || needs.build-local-artifacts.result == 'success') }}"),
    ('release.yaml', 'announce'): (['plan', 'host'], "${{ always() && needs.host.result == 'success' }}"),
}


def workflows():
    paths = {p.name: p for p in WORKFLOWS.iterdir() if p.suffix in {'.yaml', '.yml'}}
    if set(paths) != set(EVENTS):
        raise AssertionError(f'unreviewed workflow inventory: {sorted(paths)}')
    return {name: path.read_text(encoding='utf-8') for name, path in paths.items()}


def jobs(text):
    job_text = text.split('\njobs:\n', 1)[1]
    header = re.compile(r'^  ([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(?:#.*)?$')
    for line in job_text.splitlines():
        if re.match(r'^  [^ #\t]', line) and not header.fullmatch(line):
            raise AssertionError(f'unrecognized job declaration: {line!r}')
    matches = list(re.finditer(r'(?m)^  ([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(?:#.*)?$', job_text))
    if not matches:
        raise AssertionError('workflow has no readable jobs')
    result = {m.group(1): job_text[m.end():matches[i + 1].start() if i + 1 < len(matches) else None]
              for i, m in enumerate(matches)}
    allowed_keys = {'name', 'runs-on', 'if', 'needs', 'strategy', 'permissions',
                    'concurrency', 'env', 'outputs', 'environment', 'steps',
                    'timeout-minutes', 'continue-on-error', 'uses', 'with',
                    'secrets', 'container', 'defaults', 'services'}
    for name, block in result.items():
        keys = []
        for line in block.splitlines():
            if re.match(r'^    [^ #\t-]', line):
                match = re.fullmatch(r'^    ([a-z][a-z0-9-]*):(?:[ \t].*)?', line)
                if not match or match.group(1) not in allowed_keys:
                    raise AssertionError(f'noncanonical job-level key in {name}: {line!r}')
                keys.append(match.group(1))
        if len(keys) != len(set(keys)):
            raise AssertionError(f'duplicate job-level key in {name}')
    return result


def needs(block):
    match = re.search(r'(?m)^    needs:[ \t]*([^\n]*)\n((?:      - [^\n]+\n)*)', block)
    if not match:
        return []
    inline, lines = match.groups()
    if inline:
        return [inline.strip()]
    return re.findall(r'(?m)^      - ([A-Za-z_][A-Za-z0-9_-]*)[ \t]*$', lines)


def events(text):
    trigger = text.split('\non:\n', 1)[1]
    next_section = re.search(r'(?m)^[a-zA-Z_][^:\n]*:', trigger)
    if next_section is None:
        raise AssertionError('workflow has no section after triggers')
    trigger = trigger[:next_section.start()]
    declaration = re.compile(r'''^  (?:([A-Za-z_][A-Za-z0-9_-]*)|"([A-Za-z_][A-Za-z0-9_-]*)"|'([A-Za-z_][A-Za-z0-9_-]*)'):[ \t]*.*$''')
    names = []
    for line in trigger.splitlines():
        if re.match(r'^  [^ #\t]', line):
            match = declaration.fullmatch(line)
            if not match:
                raise AssertionError(f'unrecognized event declaration: {line!r}')
            names.append(next(group for group in match.groups() if group is not None))
    if len(names) != len(set(names)):
        raise AssertionError('duplicate event declarations')
    return set(names)


class CiPolicyTests(unittest.TestCase):
    def assert_events(self, name, text):
        self.assertEqual(events(text), EVENTS[name])

    def test_workflow_events_and_no_reporting_services(self):
        for name, text in workflows().items():
            with self.subTest(workflow=name):
                self.assert_events(name, text)
                for unwanted in ('codecov/codecov-action', 'CODECOV_TOKEN',
                                 'TEND_BOT_TOKEN', 'max-sixty/tend/',
                                 'gist.github.com/',
                                 'signpath/github-action-submit-signing-request',
                                 'SIGNPATH_API_TOKEN', 'cargo publish --package worktrunk'):
                    self.assertNotIn(unwanted.lower(), text.lower())

    def test_inline_and_quoted_target_events_are_rejected(self):
        source = workflows()['ci.yaml']
        for event in ('pull_request_target: {}', "'pull_request_target': {}"):
            changed = source.replace('\non:\n', f'\non:\n  {event}\n', 1)
            with self.subTest(event=event), self.assertRaises(AssertionError):
                self.assert_events('ci.yaml', changed)

    def assert_pr_jobs_guarded(self, name, text):
        found = jobs(text)
        expected_jobs = ENTRY_JOBS[name] | {job for workflow, job in DEPENDENT_JOBS if workflow == name}
        self.assertEqual(set(found), expected_jobs, 'unreviewed job inventory')
        for job, block in found.items():
            parents = needs(block)
            if not parents:
                condition = re.search(r'(?m)^    if: (.+)$', block)
                self.assertIsNotNone(condition, f'unguarded entry job: {name}/{job}')
                expected = (COLLECT_GUARD if (name, job) == ('affected.yaml', 'collect-affected')
                            else AFFECTED_GUARD if (name, job) == ('affected.yaml', 'affected-tests')
                            else OWNER_GUARD if name in SELF_HOSTED_WORKFLOWS
                            else ENTRY_GUARD)
                self.assertEqual(condition.group(1), expected)
            else:
                self.assertTrue(all(parent in found for parent in parents))
                condition = re.search(r'(?m)^    if: (.+)$', block)
                self.assertNotRegex(block, r'(?m)^    if:[ \t]*$')
                self.assertIn((name, job), DEPENDENT_JOBS, 'unreviewed dependent job')
                expected_needs, expected_condition = DEPENDENT_JOBS[(name, job)]
                self.assertEqual(parents, expected_needs, 'unreviewed prerequisites')
                self.assertEqual(condition.group(1) if condition else None, expected_condition,
                                 'unreviewed job condition')

        def visit(job, active):
            self.assertNotIn(job, active, 'cyclic job prerequisites')
            for parent in needs(found[job]):
                visit(parent, active | {job})
        for job in found:
            visit(job, set())

    def test_pr_entry_jobs_and_prerequisite_chains(self):
        for name, text in workflows().items():
            if 'pull_request' in EVENTS[name]:
                with self.subTest(workflow=name):
                    self.assert_pr_jobs_guarded(name, text)

    def test_unguarded_job_spellings_are_rejected(self):
        source = workflows()['coverage.yaml']
        for job in ('rogue_job', 'Rogue'):
            with self.subTest(job=job), self.assertRaisesRegex(AssertionError, 'unreviewed job inventory'):
                self.assert_pr_jobs_guarded('coverage.yaml', source + f'\n  {job}:\n    runs-on: ubuntu-24.04\n')

    def test_missing_nightly_full_suite_is_rejected(self):
        source = workflows()['nightly.yaml']
        self.assertEqual(source.count('\n  full-tests:\n'), 1)
        changed = source.replace('\n  full-tests:\n', '\n  removed-full-tests:\n')
        with self.assertRaisesRegex(AssertionError, 'unreviewed job inventory'):
            self.assert_pr_jobs_guarded('nightly.yaml', changed)

    def test_status_override_after_skipped_parent_is_rejected(self):
        source = workflows()['ci.yaml']
        old = "    if: needs.changes.outputs.cargo == 'true' || github.event_name == 'workflow_dispatch'"
        self.assertEqual(source.count(old), 1)
        changed = source.replace(old, '    if: ${{ !cancelled() }}')
        with self.assertRaisesRegex(AssertionError, 'unreviewed job condition'):
            self.assert_pr_jobs_guarded('ci.yaml', changed)

    def test_multiline_or_quoted_job_condition_is_rejected(self):
        source = workflows()['ci.yaml']
        old = "    if: needs.changes.outputs.cargo == 'true' || github.event_name == 'workflow_dispatch'"
        self.assertEqual(source.count(old), 1)
        for replacement in ("    if: >-\n      ${{ !cancelled() }}", "    'if': ${{ !cancelled() }}"):
            with self.subTest(replacement=replacement), self.assertRaises(AssertionError):
                self.assert_pr_jobs_guarded('ci.yaml', source.replace(old, replacement))


    def assert_runner_routing(self, files):
        for name, text in files.items():
            if name not in SELF_HOSTED_WORKFLOWS:
                self.assertNotIn('self-hosted', text)
        ci = jobs(files['ci.yaml'])
        for job in ('lint', 'feature-check', 'fast-checks'):
            self.assertIn(f'    runs-on: {RUNNER_LABELS}\n', ci[job])
        self.assertIn(
            f'          - os: {RUNNER_LABELS}\n'
            '            name: linux\n'
            '          - os: macos-26\n'
            '            name: macos\n'
            '          - os: windows-2025\n'
            '            name: windows\n', ci['test'])
        self.assertIn('    runs-on: ${{ matrix.os }}\n', ci['test'])
        for job in ('changes', 'msrv', 'check-docs'):
            self.assertIn('    runs-on: ubuntu-24.04\n', ci[job])
        bridge = jobs(files['mission-control-bridge.yaml'])['bridge']
        self.assertIn(
            '          - os: ubuntu-24.04\n'
            f'            runner: {RUNNER_LABELS}\n'
            '          - os: windows-2025\n'
            '            runner: windows-2025\n', bridge)
        self.assertIn('    name: bridge (${{ matrix.os }})\n', bridge)
        self.assertIn('    runs-on: ${{ matrix.runner }}\n', bridge)
        self.assertEqual(files['ci.yaml'].count(RUNNER_LABELS), 4)
        self.assertEqual(files['mission-control-bridge.yaml'].count(RUNNER_LABELS), 1)

    def test_dedicated_runner_routing_preserves_hosted_platforms(self):
        self.assert_runner_routing(workflows())

    def test_generic_or_mislabeled_runner_is_rejected(self):
        for replacement in ('self-hosted', '[self-hosted, Windows, X64, worktrunk-docker]',
                            '[self-hosted, Linux, ARM64, worktrunk-docker]',
                            '[self-hosted, Linux, X64]'):
            files = workflows()
            files['ci.yaml'] = files['ci.yaml'].replace(RUNNER_LABELS, replacement)
            with self.subTest(replacement=replacement), self.assertRaises(AssertionError):
                self.assert_runner_routing(files)

    def test_windows_or_macos_redirection_is_rejected(self):
        for platform in ('windows-2025', 'macos-26'):
            files = workflows()
            files['ci.yaml'] = files['ci.yaml'].replace(platform, RUNNER_LABELS)
            with self.subTest(platform=platform), self.assertRaises(AssertionError):
                self.assert_runner_routing(files)

    def test_owner_repo_and_rerun_guards_cannot_be_removed(self):
        for name in SELF_HOSTED_WORKFLOWS:
            source = workflows()[name]
            for predicate in ("github.repository_id == '1443337118' && ",
                              "github.actor_id == '226779263' && ",
                              "github.triggering_actor == 'SaiFlyBy' && "):
                with self.subTest(name=name, predicate=predicate), self.assertRaises(AssertionError):
                    self.assert_pr_jobs_guarded(name, source.replace(predicate, ''))

    def test_self_hosted_preparation_and_checkout_credentials(self):
        files = workflows()
        for name, job_names in (('ci.yaml', ('lint', 'feature-check', 'test', 'fast-checks')),
                                ('mission-control-bridge.yaml', ('bridge',))):
            self.assertIn('permissions:\n  contents: read\n', files[name])
            for job in job_names:
                block = jobs(files[name])[job]
                self.assertIn('persist-credentials: false', block)
                self.assertIn("if: runner.environment == 'self-hosted'", block)
                self.assertIn('uses: ./.github/actions/self-hosted-setup', block)
                self.assertLess(block.index('persist-credentials: false'),
                                block.index('uses: ./.github/actions/self-hosted-setup'))
        setup = (ROOT / '.github/actions/self-hosted-setup/action.yaml').read_text(encoding='utf-8')
        self.assertIn('rust-toolchain.toml', setup)
        self.assertIn('pkg-config libssl-dev', setup)
        self.assertIn('dtolnay/rust-toolchain@683b588c487a69d01f6c6ddf40f036ff682cc2c8', setup)
        self.assertNotIn('secrets.', setup)

    def assert_immutable_runner_actions(self, files, nested):
        sources = []
        for workflow, job_names in (
            ('ci.yaml', ('lint', 'feature-check', 'test', 'fast-checks')),
            ('mission-control-bridge.yaml', ('bridge',)),
        ):
            parsed = jobs(files[workflow])
            sources.extend((f'{workflow}/{job}', parsed[job]) for job in job_names)
        sources.extend(nested.items())
        allowed_local = {
            './.github/actions/self-hosted-setup',
            './.github/actions/test-setup',
        }
        for location, source in sources:
            references = re.findall(r'(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)', source)
            self.assertTrue(references, f'no action references found in {location}')
            for reference in references:
                if reference.startswith('./'):
                    self.assertIn(reference, allowed_local, location)
                else:
                    self.assertRegex(reference, r'@[0-9a-f]{40}$', f'{location}: {reference}')

    def runner_nested_actions(self):
        return {
            name: (ROOT / f'.github/actions/{name}/action.yaml').read_text(encoding='utf-8')
            for name in ('self-hosted-setup', 'test-setup')
        }

    def test_self_hosted_actions_are_pinned_to_commits(self):
        self.assert_immutable_runner_actions(workflows(), self.runner_nested_actions())

    def test_mutable_action_refs_on_runner_are_rejected(self):
        files = workflows()
        nested = self.runner_nested_actions()
        changed = dict(files)
        changed['ci.yaml'] = re.sub(
            r'(actions/checkout)@[0-9a-f]{40}', r'\1@v7', files['ci.yaml'], count=1,
        )
        self.assertNotEqual(changed['ci.yaml'], files['ci.yaml'])
        with self.assertRaises(AssertionError):
            self.assert_immutable_runner_actions(changed, nested)
        for action, dependency, tag in (
            ('test-setup', 'baptiste0928/cargo-install', 'v3'),
            ('self-hosted-setup', 'dtolnay/rust-toolchain', 'stable'),
        ):
            changed_nested = dict(nested)
            changed_nested[action] = re.sub(
                re.escape(dependency) + r'@[0-9a-f]{40}',
                dependency + '@' + tag, nested[action], count=1,
            )
            self.assertNotEqual(changed_nested[action], nested[action])
            with self.subTest(action=action), self.assertRaises(AssertionError):
                self.assert_immutable_runner_actions(files, changed_nested)

    def test_coverage_and_test_artifacts_are_retained(self):
        files = workflows()
        self.assertIn('cargo llvm-cov nextest --features shell-integration-tests', files['coverage.yaml'])
        self.assertIn('name: code-coverage-report', files['coverage.yaml'])
        self.assertIn('run: wt hook pre-merge --yes insta', files['ci.yaml'])
        self.assertIn('name: junit-${{ matrix.name }}', files['ci.yaml'])
        self.assertIn('path: target/criterion', files['benchmarks.yaml'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
