const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const cli = path.join(__dirname, '..', 'bin', 'subtitle-studio.cjs');

test('init creates a runnable source tree without local data or secrets', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'subtitle-studio-npm-'));
  const target = path.join(root, 'project');
  const run = spawnSync(process.execPath, [cli, 'init', target], { encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  for (const file of ['docker-compose.yml', '.env.example', 'backend/Dockerfile', 'frontend/index.html', 'mac-worker/requirements.txt', 'scripts/setup.sh']) {
    assert.ok(fs.existsSync(path.join(target, file)), file);
  }
  assert.ok(fs.statSync(path.join(target, 'data')).isDirectory());
  assert.equal(fs.existsSync(path.join(target, '.env')), false);
  assert.deepEqual(fs.readdirSync(path.join(target, 'data')), []);
});

test('init refuses to overwrite an existing directory', () => {
  const target = fs.mkdtempSync(path.join(os.tmpdir(), 'subtitle-studio-existing-'));
  const sentinel = path.join(target, 'keep.txt');
  fs.writeFileSync(sentinel, 'preserve');
  const run = spawnSync(process.execPath, [cli, 'init', target], { encoding: 'utf8' });
  assert.notEqual(run.status, 0);
  assert.match(run.stderr, /ya existe/);
  assert.equal(fs.readFileSync(sentinel, 'utf8'), 'preserve');
});
