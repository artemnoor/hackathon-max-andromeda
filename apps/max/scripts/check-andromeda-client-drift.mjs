import { detectClientDrift } from './andromeda-client-codegen.mjs';

try {
  const changed = await detectClientDrift();
  if (changed.length) {
    process.stderr.write(`Public API generated client drift: ${changed.join(', ')}. Run npm --prefix apps/max run generate:andromeda-client.\n`);
    process.exitCode = 1;
  } else {
    process.stdout.write('MAX Public API v1 client and provenance manifest match the canonical OpenAPI.\n');
  }
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : 'OpenAPI client drift check failed.'}\n`);
  process.exitCode = 1;
}
