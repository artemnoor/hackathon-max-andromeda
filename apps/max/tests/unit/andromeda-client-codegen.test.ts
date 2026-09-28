import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import {
  canonicalOpenApiPath,
  detectClientDrift,
  generateClientArtifacts,
  generatedClientDirectory,
  generatedClientFiles,
} from '../../scripts/andromeda-client-codegen.mjs';

test('Public API client generation is byte-for-byte deterministic', async () => {
  const first = mkdtempSync(join(tmpdir(), 'andromeda-client-first-'));
  const second = mkdtempSync(join(tmpdir(), 'andromeda-client-second-'));
  try {
    await generateClientArtifacts({ outputDirectory: first });
    await generateClientArtifacts({ outputDirectory: second });
    for (const file of generatedClientFiles) {
      assert.deepEqual(readFileSync(join(first, file)), readFileSync(join(second, file)));
    }
  } finally {
    rmSync(first, { recursive: true, force: true });
    rmSync(second, { recursive: true, force: true });
  }
});

test('contract drift is reported without rewriting the checked-in generated client', async () => {
  const temporaryDirectory = mkdtempSync(join(tmpdir(), 'andromeda-client-drift-'));
  const temporarySpec = join(temporaryDirectory, 'openapi.json');
  const originalSpec = readFileSync(canonicalOpenApiPath);
  const checkedInFiles = new Map<string, Buffer>(generatedClientFiles.map((file) => [file, readFileSync(join(generatedClientDirectory, file))]));
  try {
    const changedSpec = JSON.parse(originalSpec.toString('utf8')) as {
      paths: Record<string, unknown>;
    };
    changedSpec.paths['/api/v1/temporary-drift-check'] = {
      get: {
        responses: {
          '200': {
            description: 'Temporary drift fixture',
            content: { 'application/json': { schema: { type: 'object', properties: { drift: { type: 'boolean' } } } } },
          },
        },
      },
    };
    writeFileSync(temporarySpec, `${JSON.stringify(changedSpec)}\n`);

    const drift = await detectClientDrift({ specPath: temporarySpec });
    assert.ok(drift.includes('public-api.ts'));
    assert.ok(drift.includes('manifest.json'));
    assert.deepEqual(readFileSync(canonicalOpenApiPath), originalSpec);
    for (const [file, before] of checkedInFiles) {
      assert.deepEqual(readFileSync(join(generatedClientDirectory, file)), before);
    }
  } finally {
    rmSync(temporaryDirectory, { recursive: true, force: true });
  }
});
