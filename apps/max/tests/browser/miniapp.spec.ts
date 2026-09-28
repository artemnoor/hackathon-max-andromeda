import { createServer as createNetServer, type AddressInfo } from 'node:net';
import { test, expect } from 'playwright/test';

import { loadConfig } from '../../src/shared/config.js';
import { createLogger } from '../../src/shared/logger.js';
import { buildMiniAppHandler } from '../../src/web/app.js';
import { createMiniAppServer } from '../../src/web/server.js';
import { TEST_BOT_TOKEN, createSignedInitData } from '../fixtures/max-init-data.js';

const reservePort = async (): Promise<number> => {
  const server = createNetServer();
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = (server.address() as AddressInfo).port;
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
};

let origin: string;
let server: ReturnType<typeof createMiniAppServer>;

test.beforeAll(async () => {
  const port = await reservePort();
  origin = `http://127.0.0.1:${port}`;
  const config = loadConfig({
    NODE_ENV: 'test',
    MAX_BOT_TOKEN: TEST_BOT_TOKEN,
    MAX_INIT_DATA_TTL_SECONDS: '900',
    MINI_APP_PORT: String(port),
    MINI_APP_ORIGINS: origin,
  });
  server = createMiniAppServer(buildMiniAppHandler({ config, logger: createLogger({ sink: () => undefined }) }), port, '127.0.0.1');
  await server.start();
});

test.afterAll(async () => server?.stop());

test('preview shell renders without contacting auth or writing browser storage', async ({ page }) => {
  await page.route('https://st.max.ru/**', (route) => route.abort());
  let sessionRequests = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/max/session') sessionRequests += 1;
  });

  await page.goto(origin);

  await expect(page.locator('#status')).toContainText('preview оболочки');
  expect(sessionRequests).toBe(0);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
});

test('MAX launch proof is sent only in the same-origin header and no profile identity is persisted', async ({ page }) => {
  const initData = createSignedInitData({ authDate: Math.floor(Date.now() / 1000), userId: 77123456 });
  await page.addInitScript((value: string) => {
    const bridge: Record<string, unknown> = { initData: value };
    Object.defineProperty(bridge, 'initDataUnsafe', { get: () => { throw new Error('Unsafe bridge data must not be read.'); } });
    Object.defineProperty(window, 'WebApp', { value: bridge, configurable: false });
    const writes: string[] = [];
    Object.defineProperty(window, '__storageWrites', { value: writes });
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key: string, stored: string): void {
      writes.push(`${this === localStorage ? 'local' : 'session'}:${key}`);
      original.call(this, key, stored);
    };
  }, initData);

  let sessionRequest: { url: string; headers: Record<string, string> } | undefined;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/max/session') {
      sessionRequest = { url: request.url(), headers: request.headers() };
    }
  });

  await page.goto(origin);

  await expect(page.locator('#status')).toContainText('Подпись запуска MAX проверена');
  expect(sessionRequest?.url).toBe(`${origin}/api/max/session`);
  expect(sessionRequest?.headers['x-max-init-data']).toBe(initData);
  expect(sessionRequest?.url.includes('initData')).toBe(false);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length, (window as Window & { __storageWrites?: string[] }).__storageWrites ?? []]))
    .toEqual([0, 0, []]);
  expect(await page.locator('body').innerText()).not.toContain('77123456');
});

test('invalid launch proof stays unverified and MAX identity helpers are never consulted', async ({ page }) => {
  await page.addInitScript(() => {
    const bridge: Record<string, unknown> = { initData: 'tampered=proof' };
    Object.defineProperty(bridge, 'initDataUnsafe', { get: () => { throw new Error('Unsafe bridge data must not be read.'); } });
    Object.defineProperty(window, 'WebApp', { value: bridge, configurable: false });
  });

  await page.goto(origin);

  await expect(page.locator('#status')).toContainText('Не удалось проверить запуск');
  await expect(page.locator('.status-mark')).toHaveAttribute('data-state', 'unverified');
  expect(await page.locator('body').innerText()).not.toContain('userId');
});
