import { spawnSync } from 'node:child_process';

const commands = [
  'lint', 'typecheck', 'build', 'test', 'test:integration', 'test:browser',
  'check:miniapp', 'check:architecture', 'check:env', 'check:compose', 'check:secrets',
  'docs:check', 'coverage:check', 'audit',
];
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';

for (const command of commands) {
  process.stdout.write(`\n==> npm run ${command}\n`);
  const result = spawnSync(npm, ['run', command], {
    stdio: 'inherit',
    shell: process.platform === 'win32',
    env: process.env,
  });
  if (result.status !== 0) {
    process.exitCode = result.status ?? 1;
    process.stderr.write(`Verification stopped at npm run ${command}.\n`);
    break;
  }
}
