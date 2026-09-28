import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AppError } from '../../src/shared/errors.js';
import { createLogger } from '../../src/shared/logger.js';
import { MemoryMaxTransportState } from '../../src/shared/memory-transport-state.js';
import { MaxApiClient, MAX_API_RESPONSE_BYTES, createMaxApiFetch } from '../../src/max/client/api-fetch.js';
import { MaxOutboundRateLimiter } from '../../src/max/client/rate-limiter.js';

const testLimiter = (maxRequests = 25) => new MaxOutboundRateLimiter({ maxRequests, allowMemory: true });
type ClientOverrides = Partial<Omit<ConstructorParameters<typeof MaxApiClient>[0], 'limiter'>>;
const client = (options: ClientOverrides = {}) => new MaxApiClient({ limiter: testLimiter(), ...options });

test('distributed MAX outbound limiter enforces shared 25-per-second ceiling and resets by TTL', async () => {
  let now = 1_000;
  const state = new MemoryMaxTransportState(() => now);
  const limiter = new MaxOutboundRateLimiter({ state, maxRequests: 2 });
  await limiter.acquire();
  await limiter.acquire();
  await assert.rejects(() => limiter.acquire(), (error: unknown) => error instanceof AppError && error.code === 'RATE_LIMITED');
  now += 1_000;
  await assert.doesNotReject(() => limiter.acquire());
  assert.throws(() => new MaxOutboundRateLimiter({ state, maxRequests: 26 }), AppError);
  assert.throws(() => new MaxOutboundRateLimiter(), AppError);
});

test('MAX SDK fetch retries only GET on transient failures and never retries writes', async () => {
  let calls = 0;
  const fetcher = createMaxApiFetch(client({ sleep: async () => undefined, random: () => 0 }), async (_input, init) => {
    calls += 1;
    assert.equal(init?.redirect, 'error');
    assert.ok(init?.signal);
    return init?.method === 'POST'
      ? new Response(null, { status: 503 })
      : calls === 1 ? new Response(null, { status: 429 }) : new Response('{"ok":true}', { status: 200 });
  });

  const read = await fetcher('https://platform-api2.max.ru/me', { method: 'GET' });
  assert.equal(read.status, 200);
  assert.equal(calls, 2);
  await assert.rejects(() => fetcher('https://platform-api2.max.ru/messages', { method: 'POST', body: '{"text":"do not log"}' }),
    (error: unknown) => error instanceof AppError && error.code === 'DEPENDENCY_UNAVAILABLE');
  assert.equal(calls, 3);
});

test('retry honors a bounded Retry-After while transient exhaustion remains generic', async () => {
  const sleeps: number[] = [];
  let calls = 0;
  const fetcher = createMaxApiFetch(client({ sleep: async (milliseconds) => { sleeps.push(milliseconds); }, random: () => 0 }), async () => {
    calls += 1;
    return calls === 1
      ? new Response(null, { status: 429, headers: { 'retry-after': '60' } })
      : new Response('{}', { status: 200 });
  });
  await fetcher('https://platform-api2.max.ru/me', { method: 'GET' });
  assert.deepEqual(sleeps, [2_000]);

  const unavailable = createMaxApiFetch(client({ sleep: async () => undefined, random: () => 0 }), async () => new Response(null, { status: 503 }));
  await assert.rejects(() => unavailable('https://platform-api2.max.ru/me'),
    (error: unknown) => error instanceof AppError && error.code === 'DEPENDENCY_UNAVAILABLE');
});

test('outbound API URL is pinned to the official origin and redirects are never followed', async () => {
  const fetcher = createMaxApiFetch(client(), async () => new Response('{}'));
  for (const url of ['http://platform-api2.max.ru/me', 'https://platform-api2.max.ru.evil.example/me', 'https://user@platform-api2.max.ru/me', 'https://platform-api2.max.ru/me#fragment']) {
    await assert.rejects(() => fetcher(url), AppError);
  }
  const response = await fetcher(new URL('https://platform-api2.max.ru/me?token=private'));
  assert.equal(response.status, 200);
});

test('response bodies are byte-bounded and oversized streams are cancelled', async () => {
  let cancelled = false;
  const tooLarge = new Response(new ReadableStream<Uint8Array>({
    pull(controller) { controller.enqueue(new Uint8Array(MAX_API_RESPONSE_BYTES + 1)); },
    cancel() { cancelled = true; },
  }), { status: 200 });
  const fetcher = createMaxApiFetch(client(), async () => tooLarge);
  await assert.rejects(() => fetcher('https://platform-api2.max.ru/me', { method: 'POST' }),
    (error: unknown) => error instanceof AppError && error.code === 'DEPENDENCY_UNAVAILABLE');
  assert.equal(cancelled, true);

  const headerOverflow = createMaxApiFetch(client(), async () => new Response('{}', {
    headers: { 'content-length': String(MAX_API_RESPONSE_BYTES + 1) },
  }));
  await assert.rejects(() => headerOverflow('https://platform-api2.max.ru/me', { method: 'POST' }), AppError);
});

test('request timeout aborts GET and permits only bounded retry', async () => {
  let calls = 0;
  const fetcher = createMaxApiFetch(client({ requestTimeoutMs: 10, sleep: async () => undefined, random: () => 0 }), async (_input, init) => {
    calls += 1;
    if (calls === 3) return new Response('{}', { status: 200 });
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { code: 'ABORT_ERR' })), { once: true });
    });
  });
  const response = await fetcher('https://platform-api2.max.ru/me');
  assert.equal(response.status, 200);
  assert.equal(calls, 3);
});

test('limiter runs before fetch and logs contain no URL query or request credentials', async () => {
  const lines: string[] = [];
  const logger = createLogger({ sink: (line) => lines.push(line) });
  const limiter = new MaxOutboundRateLimiter({ maxRequests: 1, allowMemory: true });
  const bounded = new MaxApiClient({ limiter, logger });
  let calls = 0;
  const fetcher = createMaxApiFetch(bounded, async () => {
    calls += 1;
    return new Response('{}', { status: 200 });
  });

  await fetcher('https://platform-api2.max.ru/me?access_token=url-secret', { headers: { authorization: 'Bearer header-secret' } });
  assert.equal(calls, 1);
  assert.equal(lines.some((line) => line.includes('url-secret') || line.includes('header-secret')), false);

  const limited = createMaxApiFetch(new MaxApiClient({ limiter: new MaxOutboundRateLimiter({ maxRequests: 1, allowMemory: true }) }), async () => {
    return new Response('{}', { status: 200 });
  });
  await limited('https://platform-api2.max.ru/me');
  await assert.rejects(() => limited('https://platform-api2.max.ru/me'),
    (error: unknown) => error instanceof AppError && error.code === 'RATE_LIMITED');
});
