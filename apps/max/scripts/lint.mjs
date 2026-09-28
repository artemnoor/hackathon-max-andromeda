import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const eslint = fileURLToPath(new URL('../node_modules/eslint/bin/eslint.js', import.meta.url));
const result = spawnSync(process.execPath, [eslint, 'src', 'tests', 'scripts', 'playwright.config.ts', '--max-warnings=0'], {
  stdio: 'inherit',
  env: process.env,
});
process.exit(result.status ?? 1);
