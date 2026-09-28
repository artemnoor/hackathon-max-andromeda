import { readFileSync } from 'node:fs';

const config = readFileSync('src/shared/config.ts', 'utf8');
const example = readFileSync('.env.example', 'utf8');
const schema = config.match(/const rawEnvironmentSchema = z\.object\(\{([\s\S]*?)\n\}\);/u)?.[1];
if (!schema) throw new Error('Could not locate the canonical environment schema.');

const declared = [...schema.matchAll(/^\s{2}([A-Z][A-Z0-9_]+):/gmu)].map((match) => match[1]).sort();
const documented = example.split(/\r?\n/u).filter((line) => line && !line.startsWith('#'))
  .map((line) => line.slice(0, line.indexOf('='))).sort();
if (JSON.stringify(declared) !== JSON.stringify(documented)) {
  process.stderr.write(`Environment example differs from config schema.\nSchema: ${declared.join(', ')}\nExample: ${documented.join(', ')}\n`);
  process.exit(1);
}
const allowedAndromedaVariables = new Set([
  'ANDROMEDA_API_BASE_URL',
  'ANDROMEDA_PROFILE_COOKIE_NAME',
  'ANDROMEDA_API_TIMEOUT_MS',
  'ANDROMEDA_PROFILE_TTL_SECONDS',
  'ANDROMEDA_QUERY_SESSION_TTL_SECONDS',
]);
const forbiddenTransportVariables = documented.filter((name) =>
  name.startsWith('TELEGRAM_') || (name.startsWith('ANDROMEDA_') && !allowedAndromedaVariables.has(name)));
if (forbiddenTransportVariables.length) {
  throw new Error(`Environment example contains unsupported transport variables: ${forbiddenTransportVariables.join(', ')}`);
}
process.stdout.write(`Environment example covers all ${declared.length} canonical variables.\n`);
