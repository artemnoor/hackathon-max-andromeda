import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AppError, ERROR_CODES } from '../../src/shared/errors.js';
import { MemoryMaxTransportState } from '../../src/shared/memory-transport-state.js';
import { createDeepLinkTokenService } from '../../src/max/deeplinks/tokens.js';

const signingKey = Buffer.alloc(32, 9).toString('base64url');
const makeService = (state = new MemoryMaxTransportState(), now = () => 1_800_000_000) =>
  createDeepLinkTokenService({ signingKey, state, nowSeconds: now });
const reference = { version: 1 as const, kind: 'help' as const, referenceId: 'R'.repeat(22) };

test('deep link token validates signature, purpose, optional identity binding, then consumes one-time state', async () => {
  const service = makeService();
  const token = await service.issue({ purpose: 'open-help', reference, userId: 42 });
  assert.ok(Buffer.byteLength(token, 'utf8') <= 512);
  assert.deepEqual(await service.consume(token, { purpose: 'open-help', userId: 42 }), reference);
  await assert.rejects(() => service.consume(token, { purpose: 'open-help', userId: 42 }),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.AUTH_EXPIRED);
});

test('deep link tokens reject tampering, wrong purpose, binding mismatch and missing binding identity', async () => {
  const service = makeService();
  const token = await service.issue({ purpose: 'route', reference, userId: 42 });
  const parts = token.split('.');
  assert.equal(parts.length, 3);
  const tampered = `${parts[0]}.${parts[1]}.${'A'.repeat(43)}`;
  await assert.rejects(() => service.consume(tampered, { purpose: 'route', userId: 42 }), { code: 'AUTH_INVALID' });
  await assert.rejects(() => service.consume(token, { purpose: 'other', userId: 42 }), { code: 'AUTH_INVALID' });
  await assert.rejects(() => service.consume(token, { purpose: 'route', userId: 43 }), { code: 'AUTH_INVALID' });
  await assert.rejects(() => service.consume(token, { purpose: 'route' }), { code: 'AUTH_INVALID' });
});

test('deep link token rejects expired, future and excessive lifetime payloads before consuming state', async () => {
  let now = 1_800_000_000;
  const service = makeService(new MemoryMaxTransportState(), () => now);
  const expired = await service.issue({ purpose: 'route', reference, ttlSeconds: 1 });
  now += 1;
  await assert.rejects(() => service.consume(expired, { purpose: 'route' }), { code: 'AUTH_EXPIRED' });

  const futureService = makeService(new MemoryMaxTransportState(), () => now + 1_000);
  const future = await futureService.issue({ purpose: 'route', reference });
  await assert.rejects(() => service.consume(future, { purpose: 'route' }), { code: 'AUTH_INVALID' });
});

test('deep link issuance bounds token, purpose, TTL, key and reference without storing user identity', async () => {
  const state = new MemoryMaxTransportState();
  const service = makeService(state);
  await assert.rejects(() => service.issue({ purpose: 'not valid', reference }), { code: 'VALIDATION_FAILED' });
  await assert.rejects(() => service.issue({ purpose: 'route', reference, ttlSeconds: 86_401 }), { code: 'VALIDATION_FAILED' });
  await assert.rejects(() => service.issue({ purpose: 'route', reference, userId: 0 }), { code: 'VALIDATION_FAILED' });
  assert.throws(() => createDeepLinkTokenService({ signingKey: 'short', state }), { code: 'AUTH_INVALID' });

  const token = await service.issue({ purpose: 'route', reference, userId: 42 });
  const [, encoded] = token.split('.');
  assert.ok(encoded);
  assert.equal(Buffer.from(encoded, 'base64url').toString('utf8').includes('42'), false);
});

test('Redis/deep-link storage outage fails closed without unsigned or local fallback', async () => {
  class UnavailableState extends MemoryMaxTransportState {
    override async consumeDeepLink(): Promise<undefined> {
      throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
    }
  }
  const state = new UnavailableState();
  const service = makeService(state);
  const token = await service.issue({ purpose: 'route', reference });
  await assert.rejects(() => service.consume(token, { purpose: 'route' }), { code: 'DEPENDENCY_UNAVAILABLE' });
});
