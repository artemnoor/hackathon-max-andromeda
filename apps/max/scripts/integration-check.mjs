import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const value = process.env['MAX_TEST_REDIS_URL'];
if (value) {
  let redisUrl;
  try {
    redisUrl = new URL(value);
  } catch {
    process.stderr.write('MAX_TEST_REDIS_URL must identify a loopback Redis test instance.\n');
    process.exit(2);
  }

  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(redisUrl.hostname);
  const database = Number(redisUrl.pathname.slice(1));
  if (redisUrl.protocol !== 'redis:' || !loopback || !Number.isInteger(database) || database < 1 || database > 15
    || redisUrl.search || redisUrl.hash || redisUrl.username || redisUrl.password) {
    process.stderr.write('MAX_TEST_REDIS_URL must use unauthenticated loopback Redis database 1-15 without query or fragment.\n');
    process.exit(2);
  }
} else {
  process.stdout.write('Redis-backed integration case will be skipped; other integration tests will run.\n');
}

const integrationFiles = readdirSync(resolve('tests/integration'))
  .filter((name) => name.endsWith('.test.ts'))
  .sort()
  .map((name) => `tests/integration/${name}`);
const result = spawnSync(process.execPath, ['--import', 'tsx', '--test', ...integrationFiles], {
  stdio: 'inherit',
  env: process.env,
});
process.exit(result.status ?? 1);
