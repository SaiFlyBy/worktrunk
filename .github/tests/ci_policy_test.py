"""Check the checked-in CI admission and reporting conventions.

These tests are regression checks, not an authorization boundary: a pull
request can modify its own workflow and these tests. GitHub's external-PR
approval setting is needed to enforce admission independently of PR source.
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
    'mission-control-bridge.yaml': {'bridge', 'cell-candidate'},
    'nightly.yaml': {'gate'},
    'publish-docs.yaml': {'build-docs'},
    'release.yaml': {'plan'},
}
ENTRY_GUARD = ("${{ github.event_name != 'pull_request' || "
               "(github.event.pull_request.head.repo.id != null && "
               'github.event.pull_request.head.repo.id == github.event.repository.id) }}')
BRIDGE_GUARD = "${{ (" + ENTRY_GUARD[4:-3] + ")" + " && (github.event_name != 'workflow_dispatch' || inputs.candidate_sha == '') }}"
CANDIDATE_GUARD = "${{ github.repository_id == '1443337118' && github.actor_id == '226779263' && github.triggering_actor == 'SaiFlyBy' && github.event_name == 'workflow_dispatch' && inputs.candidate_sha != '' }}"
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
                            else BRIDGE_GUARD if (name, job) == ('mission-control-bridge.yaml', 'bridge')
                            else CANDIDATE_GUARD if (name, job) == ('mission-control-bridge.yaml', 'cell-candidate')
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


    def test_cell_qualification_route_is_owner_only_fixed_branch_and_exact_sha(self):
        files = workflows()
        labels = '[self-hosted, Linux, X64, worktrunk-docker]'
        lint_config = (ROOT / '.github/actionlint.yaml').read_text(encoding='utf-8')
        self.assertEqual(['worktrunk-docker'], re.findall(r'(?m)^    - (.+)$', lint_config))
        for name, source in files.items():
            if name != 'mission-control-bridge.yaml':
                self.assertNotIn('self-hosted', source)
        workflow = files['mission-control-bridge.yaml']
        parsed = jobs(workflow)
        block = parsed['cell-candidate']
        self.assertNotIn('self-hosted', parsed['bridge'])
        self.assertEqual(1, workflow.count(labels))
        self.assertIn('    runs-on: ' + labels, block)
        self.assertIn('ref: refs/heads/flyby/cell-enforcement-pro-20261105', block)
        self.assertIn('repository: SaiFlyBy/worktrunk', block)
        self.assertIn('ref: ${{ github.workflow_sha }}', block)
        self.assertIn('[[ "$EXPECTED_CANDIDATE" =~ ^[0-9a-f]{40}$ ]]', block)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_CANDIDATE"', block)
        self.assertLess(block.index('test "$(git rev-parse HEAD)" = "$EXPECTED_CANDIDATE"'),
                        block.index('cargo build --locked --bin wt'))
        self.assertIn('python tools/run_template_suite.py --expected-sha "$EXPECTED_CANDIDATE" --require-clean', block)
        self.assertIn('MC_SOURCE_PROOF_REPO="$RUNNER_TEMP/../worktrunk-cell-fixtures/29efd0ffcac21717fd789da2c7020a7e02501e00/', block)
        self.assertIn('WORKTRUNK_PRIVATE_PROOF="$RUNNER_TEMP/../worktrunk-cell-private-proof/', block)
        self.assertIn('persist-credentials: false', block)
        self.assertNotIn('secrets.', block)
        self.assertNotIn('pull_request_target', workflow)
        setup = (ROOT / '.github/actions/self-hosted-setup/action.yaml').read_text(encoding='utf-8')
        actions = re.findall(r'(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)', block + setup)
        self.assertTrue(actions)
        for action in actions:
            if action != './.github/actions/self-hosted-setup':
                self.assertRegex(action, r'@[0-9a-f]{40}$')

    def test_coverage_and_test_artifacts_are_retained(self):
        files = workflows()
        self.assertIn('cargo llvm-cov nextest --features shell-integration-tests', files['coverage.yaml'])
        self.assertIn('name: code-coverage-report', files['coverage.yaml'])
        self.assertIn('run: wt hook pre-merge --yes insta', files['ci.yaml'])
        self.assertIn('name: junit-${{ matrix.name }}', files['ci.yaml'])
        self.assertIn('path: target/criterion', files['benchmarks.yaml'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
