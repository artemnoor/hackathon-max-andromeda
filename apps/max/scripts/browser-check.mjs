import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const cli = fileURLToPath(new URL('../node_modules/playwright/cli.js', import.meta.url));
const result = spawnSync(process.execPath, [cli, 'test', '--config=playwright.config.ts'], {
  stdio: 'inherit',
  env: process.env,
});
process.exit(result.status ?? 1);
