import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const checker = fileURLToPath(new URL('../../scripts/architecture-check.mjs', import.meta.url));

const withFixture = (run: (root: string) => void) => {
  const root = mkdtempSync(join(tmpdir(), 'max-architecture-'));
  mkdirSync(join(root, 'src'), { recursive: true });
  mkdirSync(join(root, 'tests'), { recursive: true });
  try {
    run(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
};

test('architecture check rejects imports of the Andromeda backend in application code', () => {
  withFixture((root) => {
    const backendSpecifier = ['..', '..', 'services', 'andromeda', 'backend', 'src', 'andromeda', 'api', 'main.py'].join('/');
    writeFileSync(
      join(root, 'src', 'client.ts'),
      `import { app } from '${backendSpecifier}';\n`,
    );
    const result = spawnSync(process.execPath, [checker, '--root', root], { encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /services\/andromeda\/backend/u);
  });
});

test('architecture check accepts generated Public API DTO imports from tests', () => {
  withFixture((root) => {
    writeFileSync(
      join(root, 'src', 'client.ts'),
      "import type { components } from './contracts/generated/public-api.js';\n",
    );
    writeFileSync(join(root, 'tests', 'client.test.ts'), "import type { paths } from '../src/contracts/generated/public-api.js';\n");
    const result = spawnSync(process.execPath, [checker, '--root', root], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Module boundary check passed/u);
  });
});
