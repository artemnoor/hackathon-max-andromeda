import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const compose = readFileSync('compose.yaml', 'utf8');
const required = [
  /^\s{2}redis:\s*$/mu,
  /^\s{2}bot:\s*$/mu,
  /^\s{2}miniapp:\s*$/mu,
  /redis:\/\/redis:6379\/0/u,
  /redis-cli.*ping/u,
  /read_only: true/u,
];
const missing = required.filter((pattern) => !pattern.test(compose));
if (missing.length) throw new Error(`Compose contract is incomplete (${missing.map(String).join(', ')}).`);

const result = spawnSync('docker', ['compose', 'config', '--quiet'], { encoding: 'utf8', stdio: 'pipe' });
if (result.error?.code === 'ENOENT') {
  if (process.env['CI']) throw new Error('Docker Compose is required in CI to validate the deployment manifest.');
  process.stdout.write('Compose static contract passed; Docker CLI is unavailable, so schema rendering was skipped locally.\n');
} else if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout || 'Docker Compose config validation failed.\n');
  process.exit(result.status ?? 1);
} else {
  process.stdout.write('Docker Compose contract and rendered configuration passed.\n');
}
