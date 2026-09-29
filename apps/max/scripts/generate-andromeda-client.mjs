import { generateClientArtifacts } from './andromeda-client-codegen.mjs';

try {
  const output = await generateClientArtifacts();
  process.stdout.write(`Generated Public API v1 client in ${output}.\n`);
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : 'OpenAPI client generation failed.'}\n`);
  process.exitCode = 1;
}
