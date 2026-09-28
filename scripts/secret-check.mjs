import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const root = resolve('.');
const skippedDirectories = new Set(['.git', '.ai-factory', 'node_modules', 'dist', 'coverage', 'playwright-report', 'test-results']);
const files = [];
const collect = (directory) => {
  for (const name of readdirSync(directory)) {
    if (skippedDirectories.has(name)) continue;
    const path = join(directory, name);
    const info = statSync(path);
    if (info.isDirectory()) collect(path);
    else if (info.isFile() && !name.startsWith('.env') && !path.endsWith('.lock')) files.push(path);
  }
};
collect(root);

const suspicious = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/u,
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/u,
  /\bgithub_pat_[A-Za-z0-9_]{30,}\b/u,
  /\bsk-[A-Za-z0-9]{24,}\b/u,
];
const failures = [];
for (const file of files) {
  const path = relative(root, file).replaceAll('\\', '/');
  if (path === 'tests/fixtures/max-init-data.ts') continue;
  const source = readFileSync(file, 'utf8');
  if (suspicious.some((pattern) => pattern.test(source))) failures.push(path);
}

if (failures.length) {
  process.stderr.write(`Potential credential material found in: ${failures.join(', ')}\n`);
  process.exit(1);
}
process.stdout.write('Secret scan passed; no credential patterns found in repository files.\n');
