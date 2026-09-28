import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const root = resolve('src');
const files = [];
const collect = (directory) => {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) collect(path);
    else if (path.endsWith('.ts')) files.push(path);
  }
};
collect(root);
const errors = [];
const sdkOwner = 'src/max/platform/bot.ts';

for (const file of files) {
  const path = relative(process.cwd(), file).replaceAll('\\', '/');
  const source = readFileSync(file, 'utf8');
  if (/from\s+['"](?:@andromeda\/|andromeda-backend|fastapi|sqlalchemy|pg)['"]/u.test(source)) {
    errors.push(`${path} imports an excluded Andromeda backend or database dependency.`);
  }
  if (source.includes("from '@maxhub/max-bot-api'") && path !== sdkOwner) {
    errors.push(`${path} bypasses the MAX platform adapter.`);
  }
  if (path.startsWith('src/shared/') && /from\s+['"]\.\.\/max\//u.test(source)) {
    errors.push(`${path} makes shared code depend on the MAX protocol layer.`);
  }
}

if (errors.length) {
  for (const error of errors) process.stderr.write(`${error}\n`);
  process.exit(1);
}
process.stdout.write('Module boundary check passed.\n');
