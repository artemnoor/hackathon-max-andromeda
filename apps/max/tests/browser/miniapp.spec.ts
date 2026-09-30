import { createServer as createNetServer, type AddressInfo } from 'node:net';
import { test, expect, type Page } from 'playwright/test';
import { loadConfig } from '../../src/shared/config.js';
import { createLogger } from '../../src/shared/logger.js';
import { buildMiniAppHandler } from '../../src/web/app.js';
import { createMiniAppServer } from '../../src/web/server.js';
import { TEST_BOT_TOKEN, createSignedInitData } from '../fixtures/max-init-data.js';

const reservePort = async (): Promise<number> => {
  const server = createNetServer();
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = (server.address() as AddressInfo).port;
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
};

let origin: string;
let server: ReturnType<typeof createMiniAppServer>;
test.beforeAll(async () => {
  const port = await reservePort();
  origin = `http://127.0.0.1:${port}`;
  const config = loadConfig({ NODE_ENV: 'test', MAX_BOT_TOKEN: TEST_BOT_TOKEN, MAX_INIT_DATA_TTL_SECONDS: '900', MINI_APP_PORT: String(port), MINI_APP_ORIGINS: origin });
  server = createMiniAppServer(buildMiniAppHandler({
    config,
    logger: createLogger({ sink: () => undefined }),
    ...(process.env['MAX_E2E_ANDROMEDA_URL'] ? { publicApiBaseUrl: process.env['MAX_E2E_ANDROMEDA_URL'] } : {}),
  }), port, '127.0.0.1');
  await server.start();
});
test.afterAll(async () => server?.stop());

const installLaunchProof = async (page: Page, proof: string): Promise<void> => {
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
  }, proof);
};

test('clone restores every original section without embedding program or curriculum samples', async ({ page }) => {
  await page.route('https://st.max.ru/**', (route) => route.abort());
  let sessionRequests = 0;
  page.on('request', (request) => { if (new URL(request.url()).pathname === '/api/max/session') sessionRequests += 1; });
  await page.goto(origin);
  await expect(page.locator('#page-home')).toBeVisible();
  await expect(page.locator('#app-sidebar [data-page]')).toHaveCount(13);
  await expect(page.locator('#app-sidebar [data-page="news"]')).toBeAttached();
  await expect(page.locator('#app-sidebar [data-page="olympiads"]')).toBeAttached();
  expect(sessionRequests).toBe(0);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
});

test('signed MAX proof reaches the same-origin verifier; the full clone shell stays usable', async ({ page }) => {
  const initData = createSignedInitData({ authDate: Math.floor(Date.now() / 1000), userId: 77123456 });
  await installLaunchProof(page, initData);
  let sessionRequest: { url: string; headers: Record<string, string> } | undefined;
  page.on('request', (request) => { if (new URL(request.url()).pathname === '/api/max/session') sessionRequest = { url: request.url(), headers: request.headers() }; });
  await page.goto(origin);
  await expect(page.locator('#page-home')).toBeVisible();
  await expect.poll(() => sessionRequest?.url).toBe(`${origin}/api/max/session`);
  expect(sessionRequest?.headers['x-max-init-data']).toBe(initData);
  expect(sessionRequest?.url.includes('initData')).toBe(false);
  const localState = await page.evaluate(() => localStorage.getItem('andromeda-state') || '');
  expect(localState).not.toContain('77123456');
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0);
  expect(await page.locator('body').innerText()).not.toContain('77123456');
});

test('signed Mini App loads actual programs, source-backed curriculum, and compare options through Public API', async ({ page }) => {
  test.skip(!process.env['MAX_E2E_ANDROMEDA_URL'], 'Requires a running Andromeda Public API.');
  await installLaunchProof(page, createSignedInitData({ authDate: Math.floor(Date.now() / 1000), userId: 77123457 }));
  await page.goto(origin);
  await expect(page.locator('#page-home .news-card')).toHaveCount(15);
  await page.goto(`${origin}/?page=catalog`);
  await expect(page.locator('#catalog-list .program-card')).toHaveCount(2);
  await page.locator('#catalog-search').fill('09.03.01-02');
  await expect(page.locator('#catalog-list .program-card')).toHaveCount(1);
  await page.locator('#catalog-search').fill('');
  await page.locator('#catalog-list [data-page="program"]').first().click();
  await expect(page.locator('#program-detail')).toContainText('Происхождение данных');
  await page.locator('[data-tab="curriculum"]').click();
  await expect(page.locator('#detail-tab-content tbody tr').first()).toBeVisible();
  await expect(page.locator('#detail-tab-content tbody tr')).toHaveCount(89);
  await expect(page.locator('#program-detail a[href^="https://"]').first()).toBeVisible();
  await page.locator('#page-program [data-page="catalog"]').click();
  await expect(page.locator('#catalog-list .program-card')).toHaveCount(2);
  await page.locator('#catalog-list [data-compare-toggle]').first().click();
  await page.locator('#catalog-list [data-compare-toggle]').last().click();
  await page.locator('#page-catalog .page-title [data-page="compare"]').click();
  await expect(page.locator('#compare-content')).toContainText('Из чего состоит обучение');
  await expect(page.locator('#compare-content tbody tr').first()).toBeVisible();
  await page.goto(`${origin}/?page=admission-check`);
  await expect(page.locator('#admission-subjects .admission-scenario-row').first()).toBeVisible();
  await page.locator('#admission-subjects .admission-scenario-row').first().locator('[data-admission-status]').selectOption('taken');
  await page.locator('#admission-subjects .admission-scenario-row').first().locator('[data-admission-score]').fill('90');
  await page.locator('#admission-check-rules').click();
  await expect(page.locator('#admission-results')).toContainText('Ответ backend');
});

test('tampered MAX proof never renders a user identity or private profile', async ({ page }) => {
  await installLaunchProof(page, 'tampered=proof');
  await page.goto(origin);
  await expect(page.locator('#page-home')).toBeVisible();
  const response = await page.request.get(`${origin}/api/max/session`, { headers: { 'X-Max-Init-Data': 'tampered=proof' } });
  expect(response.status()).toBe(401);
  expect(await page.locator('body').innerText()).not.toContain('userId');
});
