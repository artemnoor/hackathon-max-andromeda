import assert from 'node:assert/strict';
import { createServer as createNetServer, type AddressInfo } from 'node:net';
import { test } from 'node:test';

import { loadConfig } from '../../src/shared/config.js';
import { createLogger } from '../../src/shared/logger.js';
import { buildMiniAppHandler } from '../../src/web/app.js';
import { createMiniAppServer } from '../../src/web/server.js';
import { TEST_BOT_TOKEN, createSignedInitData } from '../fixtures/max-init-data.js';

const availablePort = async (): Promise<number> => {
  const server = createNetServer();
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = (server.address() as AddressInfo).port;
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
};

test('Mini App host verifies header initData and serves only bounded static/health/auth surfaces', async (t) => {
  const port = await availablePort();
  const origin = `http://127.0.0.1:${port}`;
  const logLines: string[] = [];
  const config = loadConfig({
    NODE_ENV: 'test',
    MAX_BOT_TOKEN: TEST_BOT_TOKEN,
    MAX_INIT_DATA_TTL_SECONDS: '900',
    MINI_APP_PORT: String(port),
    MINI_APP_ORIGINS: origin,
  });
  const server = createMiniAppServer(buildMiniAppHandler({
    config,
    logger: createLogger({ sink: (line) => logLines.push(line) }),
    nowSeconds: () => 1_700_000_100,
  }), port, '127.0.0.1');
  await server.start();
  t.after(() => server.stop());

  const live = await fetch(`${origin}/health/live`);
  assert.equal(live.status, 200);
  assert.deepEqual(await live.json(), { status: 'ok' });
  assert.equal((await fetch(`${origin}/health/ready`)).status, 200);

  const signed = createSignedInitData({ authDate: 1_700_000_000, userId: 42424242 });
  const verified = await fetch(`${origin}/api/max/session`, {
    headers: { 'X-Max-Init-Data': signed, origin },
  });
  assert.equal(verified.status, 200);
  const result = await verified.json() as Record<string, unknown>;
  assert.deepEqual(result, { authenticated: true });
  assert.equal(JSON.stringify(result).includes('42424242'), false);
  assert.equal(verified.headers.get('set-cookie'), null);
  assert.equal(verified.headers.get('access-control-allow-credentials'), null);

  assert.equal((await fetch(`${origin}/api/max/session`)).status, 401);
  assert.equal((await fetch(`${origin}/api/max/session?initData=${encodeURIComponent(signed)}`)).status, 400);
  assert.equal((await fetch(`${origin}/api/max/session?UserId=42424242`)).status, 400);
  assert.equal((await fetch(`${origin}/api/max/session?role=admin`)).status, 400);
  assert.equal((await fetch(`${origin}/api/max/session`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ userId: 42424242, role: 'admin' }),
  })).status, 405);
  assert.equal((await fetch(`${origin}/api/max/session`, { headers: { 'X-Max-Init-Data': signed.replace('hash=', 'hash=0') } })).status, 401);
  assert.equal((await fetch(`${origin}/api/max/session`, { headers: { origin: 'https://evil.example' } })).status, 403);

  const preflight = await fetch(`${origin}/api/max/session`, {
    method: 'OPTIONS',
    headers: { origin, 'access-control-request-method': 'GET', 'access-control-request-headers': 'x-max-init-data' },
  });
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get('access-control-allow-origin'), origin);
  assert.equal(preflight.headers.get('access-control-allow-credentials'), null);

  const shell = await fetch(origin);
  assert.equal(shell.status, 200);
  assert.match(shell.headers.get('content-type') ?? '', /^text\/html/u);
  assert.equal(shell.headers.get('x-frame-options'), null);
  assert.match(shell.headers.get('content-security-policy') ?? '', /frame-ancestors https:\/\/max\.ru https:\/\/web\.max\.ru/u);
  const html = await shell.text();
  assert.match(html, /Andromeda — выбор программы/u);
  const cssAsset = /href="(\/assets\/[A-Za-z0-9._-]+\.css)"/u.exec(html)?.[1];
  const jsAsset = /src="(\/assets\/[A-Za-z0-9._-]+\.js)"/u.exec(html)?.[1];
  assert.ok(cssAsset);
  assert.ok(jsAsset);
  assert.equal((await fetch(`${origin}${cssAsset}`)).headers.get('content-type'), 'text/css; charset=utf-8');
  assert.equal((await fetch(`${origin}${jsAsset}`)).headers.get('content-type'), 'text/javascript; charset=utf-8');
  assert.equal((await fetch(`${origin}/styles.css`)).status, 404);
  assert.equal((await fetch(`${origin}/app.js.map`)).status, 404);
  assert.equal((await fetch(`${origin}/.env`)).status, 404);
  const traversal = await fetch(`${origin}/%2e%2e/.env`);
  assert.ok(traversal.status === 403 || traversal.status === 404);
  assert.equal((await fetch(`${origin}/unknown`)).status, 404);
  assert.equal((await fetch(`${origin}/unknown`, { method: 'POST' })).headers.get('x-frame-options'), 'DENY');

  const combinedLog = logLines.join('\n');
  assert.equal(combinedLog.includes(signed), false);
  assert.equal(combinedLog.includes('42424242'), false);
});

test('Mini App exposes source-backed read-only catalog outside MAX and keeps personal routes authenticated', async (t) => {
  const port = await availablePort();
  const origin = `http://127.0.0.1:${port}`;
  const upstream: string[] = [];
  const config = loadConfig({
    NODE_ENV: 'test', MAX_BOT_TOKEN: TEST_BOT_TOKEN,
    MAX_INIT_DATA_TTL_SECONDS: '900', MINI_APP_PORT: String(port), MINI_APP_ORIGINS: origin,
  });
  const server = createMiniAppServer(buildMiniAppHandler({
    config,
    logger: createLogger({ sink: () => undefined }),
    nowSeconds: () => 1_700_000_100,
    publicApiBaseUrl: 'http://127.0.0.1:8123',
    fetcher: async (input, init) => {
      upstream.push(String(input));
      assert.equal(new Headers(init?.headers).has('x-max-init-data'), false);
      return Response.json({ items: [] });
    },
  }), port, '127.0.0.1');
  await server.start();
  t.after(() => server.stop());
  const signed = createSignedInitData({ authDate: 1_700_000_000, userId: 42424242 });
  const path = `${origin}/api/max/catalog/programs`;
  const response = await fetch(path);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { items: [] });
  assert.deepEqual(upstream, ['http://127.0.0.1:8123/api/v1/programs']);
  assert.equal((await fetch(`${origin}/api/max/data/profile`)).status, 401);
  assert.equal((await fetch(`${origin}/api/max/data/profile`, { headers: { 'X-Max-Init-Data': 'invalid' } })).status, 401);
  assert.equal((await fetch(`${origin}/api/max/data/profile`, { headers: { 'X-Max-Init-Data': signed } })).status, 200);
  assert.equal((await fetch(`${path}?unexpected=1`, { headers: { 'X-Max-Init-Data': signed } })).status, 400);
  assert.equal((await fetch(`${origin}/api/max/catalog/programs/not-a-program`, { headers: { 'X-Max-Init-Data': signed } })).status, 400);
  assert.equal((await fetch(`${origin}/api/max/catalog/compare?programIds=one,two`, { headers: { 'X-Max-Init-Data': signed } })).status, 400);
  assert.equal(upstream.length, 2);
});
