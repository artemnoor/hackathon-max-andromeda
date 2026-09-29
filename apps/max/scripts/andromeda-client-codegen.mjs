import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript';

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const repositoryRoot = resolve(appRoot, '../..');
export const canonicalOpenApiPath = join(repositoryRoot, 'services', 'andromeda', 'openapi.json');
export const upstreamProvenancePath = join(repositoryRoot, 'UPSTREAM_ANDROMEDA.md');
export const generatedClientDirectory = join(appRoot, 'src', 'andromeda', 'generated');
export const generatedClientFiles = ['public-api.ts', 'manifest.json'];
export const generationCommand = 'npm --prefix apps/max run generate:andromeda-client';

function upstreamCommit() {
  const provenance = readFileSync(upstreamProvenancePath, 'utf8');
  const match = provenance.match(/^- Imported source commit: `([0-9a-f]{40})`$/mu);
  if (!match) throw new Error('UPSTREAM_ANDROMEDA.md does not contain a pinned source commit.');
  return match[1];
}

function manifestFor(specBytes) {
  return `${JSON.stringify({
    canonicalOpenApi: 'services/andromeda/openapi.json',
    formatVersion: 1,
    generationCommand,
    generator: 'openapi-typescript@7.13.0',
    openapiSha256: createHash('sha256').update(specBytes).digest('hex'),
    upstreamAndromedaCommit: upstreamCommit(),
  }, null, 2)}\n`;
}

async function publicApiTypes(specPath, specBytes) {
  let spec;
  try {
    spec = JSON.parse(specBytes.toString('utf8'));
  } catch {
    throw new Error(`Invalid OpenAPI JSON: ${specPath}`);
  }
  const paths = Object.keys(spec.paths ?? {});
  if (!paths.length || paths.some((path) => !path.startsWith('/api/v1/'))) {
    throw new Error(`Expected a non-empty Public API v1 OpenAPI document: ${specPath}`);
  }
  if (!spec.paths['/api/v1/assistant/query']?.post) {
    throw new Error(`Public API v1 assistant operation is missing: ${specPath}`);
  }
  const ast = await openapiTS(pathToFileURL(specPath));
  const provenance = [
    '// Canonical contract: services/andromeda/openapi.json',
    `// Upstream Andromeda: ${upstreamCommit()}`,
    `// OpenAPI SHA-256: ${createHash('sha256').update(specBytes).digest('hex')}`,
    '',
  ].join('\n');
  return `${COMMENT_HEADER}${provenance}${astToString(ast)}`;
}

export async function generateClientArtifacts({ specPath = canonicalOpenApiPath, outputDirectory = generatedClientDirectory } = {}) {
  const absoluteSpecPath = resolve(specPath);
  let sourceBytes;
  try {
    sourceBytes = readFileSync(absoluteSpecPath);
  } catch {
    throw new Error(`Canonical OpenAPI file is unavailable: ${absoluteSpecPath}`);
  }
  // Git may check out this text file with CRLF on Windows. Normalize before
  // hashing so the generated provenance is stable across developer and CI OSes.
  const specBytes = Buffer.from(sourceBytes.toString('utf8').replace(/\r\n?/gu, '\n'), 'utf8');
  const [client, manifest] = await Promise.all([
    publicApiTypes(absoluteSpecPath, specBytes),
    Promise.resolve(manifestFor(specBytes)),
  ]);
  const outputPath = resolve(outputDirectory);
  const { mkdirSync } = await import('node:fs');
  mkdirSync(outputPath, { recursive: true });
  writeFileSync(join(outputPath, generatedClientFiles[0]), client, 'utf8');
  writeFileSync(join(outputPath, generatedClientFiles[1]), manifest, 'utf8');
  return outputPath;
}

export async function detectClientDrift({ specPath = canonicalOpenApiPath, expectedDirectory = generatedClientDirectory } = {}) {
  const temporaryDirectory = mkdtempSync(join(tmpdir(), 'max-andromeda-client-'));
  try {
    await generateClientArtifacts({ specPath, outputDirectory: temporaryDirectory });
    return generatedClientFiles.filter((name) => {
      let expected;
      let actual;
      try {
        expected = readFileSync(join(expectedDirectory, name));
        actual = readFileSync(join(temporaryDirectory, name));
      } catch {
        return true;
      }
      return !expected.equals(actual);
    });
  } finally {
    rmSync(temporaryDirectory, { recursive: true, force: true });
  }
}
