import { spawnSync } from 'node:child_process';

const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const result = spawnSync(npm, ['run', 'test:coverage'], {
  encoding: 'utf8',
  shell: process.platform === 'win32',
  env: process.env,
});
const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
if (result.status !== 0) {
  process.stderr.write(output);
  process.exit(result.status ?? 1);
}
const summary = output.match(/#\s*all files\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)/u);
if (!summary) throw new Error('Node test runner did not emit an aggregate coverage summary.');
const [lines, branches, functions] = summary.slice(1).map(Number);
if (lines < 80 || branches < 75 || functions < 80) {
  process.stderr.write(`Coverage thresholds failed: lines=${lines} branches=${branches} functions=${functions}; required 80/75/80.\n`);
  process.exit(1);
}
process.stdout.write(`Coverage passed: lines=${lines}% branches=${branches}% functions=${functions}%.\n`);
