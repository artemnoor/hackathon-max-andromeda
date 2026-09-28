import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const rootArgument = process.argv[2] === '--root' ? process.argv[3] : undefined;
const projectRoot = resolve(rootArgument ?? join(scriptDirectory, '..'));
const sourceRoots = ['src', 'tests'].map((name) => join(projectRoot, name)).filter((path) => {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
});
const sourceFiles = [];
const sourceExtensions = new Set(['.ts', '.tsx', '.js', '.mjs', '.cjs']);

const collect = (directory) => {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    const metadata = statSync(path);
    if (metadata.isDirectory()) collect(path);
    else if (metadata.isFile() && [...sourceExtensions].some((extension) => path.endsWith(extension))) {
      sourceFiles.push(path);
    }
  }
};

for (const root of sourceRoots) collect(root);

const errors = [];
const sdkOwner = 'src/max/platform/bot.ts';
const importPattern = /(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s*)['"]([^'"]+)['"]/gu;
const forbiddenPackage = /^(?:@andromeda\/|andromeda-backend(?:\/|$)|fastapi(?:\/|$)|sqlalchemy(?:\/|$)|psycopg(?:\/|$)|pg(?:\/|$)|typesafe-sdk(?:\/|$)|system-one-adapter(?:\/|$)|jev(?:\/|$)|polza(?:\/|$)|deepseek(?:\/|$))/iu;

for (const file of sourceFiles) {
  const path = relative(projectRoot, file).replaceAll('\\', '/');
  const source = readFileSync(file, 'utf8');

  if (source.includes("from '@maxhub/max-bot-api'") && path !== sdkOwner) {
    errors.push(`${path} bypasses the MAX platform adapter.`);
  }
  if (path.startsWith('src/shared/') && /(?:\bfrom\s*|\bimport\s*\()\s*['"]\.\.\/max\//u.test(source)) {
    errors.push(`${path} makes shared code depend on the MAX protocol layer.`);
  }

  for (const match of source.matchAll(importPattern)) {
    const specifier = match[1];
    if (forbiddenPackage.test(specifier) || /(?:^|[/\\])services[/\\]andromeda(?:[/\\]|$)/iu.test(specifier)) {
      errors.push(`${path} imports excluded Andromeda backend or provider dependency '${specifier}'.`);
    }
  }
}

if (errors.length) {
  for (const error of errors) process.stderr.write(`${error}\n`);
  process.exit(1);
}
process.stdout.write('Module boundary check passed.\n');
