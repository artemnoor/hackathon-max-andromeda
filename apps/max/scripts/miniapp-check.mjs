import { readFileSync } from 'node:fs';

const main = readFileSync('miniapp-frontend/src/main.js', 'utf8');
const client = readFileSync('miniapp-frontend/src/api/client.js', 'utf8');
const html = readFileSync('miniapp-frontend/index.html', 'utf8');
const built = readFileSync('miniapp-frontend/dist/index.html', 'utf8');
const manifest = JSON.parse(readFileSync('miniapp-frontend/dist/.vite/manifest.json', 'utf8'));
const handler = readFileSync('src/web/app.ts', 'utf8');
const proxy = readFileSync('src/web/catalog-proxy.ts', 'utf8');
const policy = readFileSync('src/web/static-policy.ts', 'utf8');
const errors = [];

if (/\.initDataUnsafe\b|["']initDataUnsafe["']/u.test(`${main}\n${client}`)) errors.push('Mini App source must not read initDataUnsafe.');
for (const forbidden of ['localStorage', 'sessionStorage', 'document.cookie']) {
  if (`${main}\n${client}`.includes(forbidden)) errors.push(`Mini App source must not use ${forbidden}.`);
}
if (!client.includes("request('/api/max/session')")) errors.push('Mini App must verify its MAX launch.');
if (!client.includes("credentials: 'omit'")) errors.push('Mini App requests must omit browser credentials.');
if (!html.includes('https://st.max.ru/js/max-web-app.js')) errors.push('Mini App must load the official MAX bridge.');
if (!built.includes('/assets/')) errors.push('Mini App must serve its built Vite assets.');
if (!manifest['index.html']?.file) errors.push('Mini App Vite manifest is missing its entry.');
if (!handler.includes("'/': 'index.html'") || !handler.includes("'/index.html': 'index.html'")) errors.push('Static allowlist is missing its entry.');
if (!handler.includes("'/api/max/session'") || !handler.includes("'/api/max/catalog'")) errors.push('Mini App auth/catalog routes are missing.');
if (!handler.includes('loadStaticFiles(root)') || !handler.includes('realpath(') || !handler.includes('MAX_MINI_APP_RESPONSE_BYTES')) errors.push('Mini App static files must be manifest allowlisted and bounded.');
if (!proxy.includes('/api/v1/programs') || !proxy.includes('/api/v1/compare')) errors.push('Mini App catalog must use Public API v1.');
if (!policy.includes('frame-ancestors https://max.ru https://web.max.ru')) errors.push('MAX frame ancestor policy is missing.');

if (errors.length) {
  for (const error of errors) process.stderr.write(`${error}\n`);
  process.exit(1);
}
process.stdout.write('Mini App source, Vite asset and boundary checks passed.\n');
