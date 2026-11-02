import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const docsRoot = fs.realpathSync(fileURLToPath(new URL('..', import.meta.url)));
const astroRoot = path.join(docsRoot, 'node_modules', 'astro');
const astroCli = path.join(astroRoot, 'bin', 'astro.mjs');
const wrapper = path.join(docsRoot, 'scripts', 'astro.mjs');
const replacement = path.join(docsRoot, 'vendor', 'astro-telemetry');

test('Astro uses the reviewed local telemetry replacement', () => {
  const astro = JSON.parse(fs.readFileSync(path.join(astroRoot, 'package.json'), 'utf8'));
  const local = JSON.parse(fs.readFileSync(path.join(replacement, 'package.json'), 'utf8'));
  assert.equal(astro.dependencies['@astrojs/telemetry'], local.version,
    'review the replacement interface when upgrading Astro telemetry');
  assert.equal(fs.realpathSync(path.join(docsRoot, 'node_modules', '@astrojs', 'telemetry')),
    fs.realpathSync(replacement), 'the lockfile must resolve to the local replacement');
});

test('direct and supported Astro builds cannot send telemetry', { timeout: 120_000 }, (t) => {
  const root = fs.mkdtempSync(path.join(docsRoot, '.astro-privacy-test-'));
  t.after(() => {
    const resolved = fs.realpathSync(root);
    if (path.dirname(resolved) !== docsRoot || !path.basename(resolved).startsWith('.astro-privacy-test-')) {
      throw new Error('Refusing to remove an unexpected test directory');
    }
    fs.rmSync(resolved, { recursive: true, force: true });
  });

  const guard = path.join(root, 'network-guard.mjs');
  fs.writeFileSync(guard, [
    "import fs from 'node:fs';",
    "import os from 'node:os';",
    "os.homedir = () => process.env.ASTRO_PRIVACY_TEST_ROOT;",
    "globalThis.fetch = async (url) => {",
    "  fs.appendFileSync(process.env.ASTRO_PRIVACY_TEST_MARKER, String(url) + '\\n');",
    "  throw new Error('Network blocked by privacy test');",
    "};",
  ].join('\n'));

  function invoke(name, argv) {
    const project = path.join(root, name);
    const config = path.join(root, name + '-config');
    const marker = path.join(root, name + '-requests');
    fs.mkdirSync(path.join(project, 'src', 'pages'), { recursive: true });
    fs.writeFileSync(path.join(project, 'package.json'), '{"type":"module"}\n');
    fs.writeFileSync(path.join(project, 'src', 'pages', 'index.astro'), '<h1>Fixture</h1>\n');
    const env = { ...process.env, APPDATA: config, XDG_CONFIG_HOME: config,
      ASTRO_PRIVACY_TEST_ROOT: config, ASTRO_PRIVACY_TEST_MARKER: marker,
      GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: os.devNull, GIT_TERMINAL_PROMPT: '0' };
    for (const key of Object.keys(env)) {
      if (/TOKEN|SECRET|PASSWORD|AUTH/i.test(key) || key === 'ASTRO_TELEMETRY_DISABLED' ||
          key === 'TELEMETRY_DISABLED' || key === 'NODE_OPTIONS' || key === 'DEBUG' ||
          key === 'GIT_CONFIG_COUNT' || key === 'GIT_CONFIG_PARAMETERS' ||
          key.startsWith('GIT_CONFIG_KEY_') || key.startsWith('GIT_CONFIG_VALUE_')) delete env[key];
    }
    const result = spawnSync(process.execPath, ['--import', pathToFileURL(guard).href, ...argv], {
      cwd: project, env, encoding: 'utf8', timeout: 40_000, windowsHide: true,
    });
    return { marker, config, project, result };
  }

  const control = invoke('control', ['--input-type=module', '-e',
    "await fetch('https://telemetry.astro.build/test').catch(() => {})"]);
  assert.equal(control.result.status, 0, control.result.stderr);
  assert.match(fs.readFileSync(control.marker, 'utf8'), /telemetry\.astro\.build/,
    'the positive control proves telemetry fetches are intercepted');

  for (const [name, entry] of [['direct', astroCli], ['supported', wrapper]]) {
    const outcome = invoke(name, [entry, 'build']);
    assert.equal(outcome.result.status, 0, outcome.result.stderr || outcome.result.stdout || String(outcome.result.error));
    assert.ok(fs.existsSync(path.join(outcome.project, 'dist', 'index.html')), 'Astro built the fixture');
    assert.equal(fs.existsSync(outcome.marker), false, `${name} Astro attempted a fetch`);
    assert.equal(fs.existsSync(outcome.config), false, `${name} Astro created telemetry state`);
  }

  const enable = invoke('enable', [astroCli, 'telemetry', 'enable']);
  assert.notEqual(enable.result.status, 0, 'direct Astro must not report telemetry enabled');
  assert.match(enable.result.stderr + enable.result.stdout, /telemetry is disabled in this fork/);
  assert.equal(fs.existsSync(enable.marker), false);
  assert.equal(fs.existsSync(enable.config), false);
});
