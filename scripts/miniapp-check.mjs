import { readFileSync } from 'node:fs';

const app = readFileSync('miniapp/app.js', 'utf8');
const bridge = readFileSync('miniapp/bridge.js', 'utf8');
const html = readFileSync('miniapp/index.html', 'utf8');
const handler = readFileSync('src/web/app.ts', 'utf8');
const policy = readFileSync('src/web/static-policy.ts', 'utf8');
const errors = [];

if (/\.initDataUnsafe\b|["']initDataUnsafe["']/u.test(`${app}\n${bridge}`)) errors.push('Mini App source must not read initDataUnsafe.');
for (const forbidden of ['localStorage', 'sessionStorage', 'document.cookie']) {
  if (`${app}\n${bridge}`.includes(forbidden)) errors.push(`Mini App source must not use ${forbidden}.`);
}
if (!app.includes("fetch('/api/max/session'")) errors.push('Mini App must use its same-origin session verification route.');
if (!app.includes("credentials: 'omit'")) errors.push('Mini App requests must omit browser credentials.');
if (!html.includes('https://st.max.ru/js/max-web-app.js')) errors.push('Mini App must load the official MAX bridge.');
for (const route of ["'/': 'index.html'", "'/styles.css': 'styles.css'", "'/app.js': 'app.js'", "'/bridge.js': 'bridge.js'"]) {
  if (!handler.includes(route)) errors.push(`Static allowlist is missing ${route}.`);
}
if (!policy.includes('frame-ancestors https://max.ru https://web.max.ru')) errors.push('MAX frame ancestor policy is missing.');
if (!handler.includes('realpath(') || !handler.includes('MAX_MINI_APP_RESPONSE_BYTES')) errors.push('Static file serving must retain path and byte bounds.');
if (!handler.includes("'/api/max/session'")) errors.push('Mini App must retain the bounded auth verification endpoint.');

if (errors.length) {
  for (const error of errors) process.stderr.write(`${error}\n`);
  process.exit(1);
}
process.stdout.write('Mini App boundary check passed.\n');
