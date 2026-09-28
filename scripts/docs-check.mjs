import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const requiredFiles = [
  'README.md', 'SECURITY.md', 'docs/architecture.md', 'docs/development.md', 'docs/deployment.md', 'docs/testing.md',
];
const failures = requiredFiles.filter((path) => !existsSync(path));
for (const path of requiredFiles.filter(existsSync)) {
  const content = readFileSync(path, 'utf8');
  for (const match of content.matchAll(/\[[^\]]+\]\(([^)]+)\)/gu)) {
    const target = match[1];
    if (!target || /^(?:https?:|mailto:|#)/iu.test(target)) continue;
    const clean = target.split('#', 1)[0]?.split('?', 1)[0];
    if (clean && !existsSync(resolve(dirname(path), clean))) failures.push(`${path} -> ${target}`);
  }
}
if (failures.length) {
  process.stderr.write(`Documentation files/links are missing: ${failures.join(', ')}\n`);
  process.exit(1);
}
process.stdout.write('Required documentation and local links passed.\n');
