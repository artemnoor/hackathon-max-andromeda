import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createSignedInitData, TEST_BOT_TOKEN } from '../fixtures/max-init-data.js';
import { validateMaxInitData } from '../../src/max/auth/init-data.js';

const options = { botToken: TEST_BOT_TOKEN, ttlSeconds: 900, nowSeconds: () => 1_700_000_100 };

test('MAX initData validates the official signature and returns no identity data', () => {
  const result = validateMaxInitData(createSignedInitData({ authDate: 1_700_000_000, userId: 42 }), options);
  assert.equal(result, undefined);
});

test('MAX initData rejects duplicate decoded keys, bad encoding and tampered signatures', () => {
  const signed = createSignedInitData({ authDate: 1_700_000_000 });
  assert.throws(() => validateMaxInitData(`${signed}&hash=${'0'.repeat(64)}`, options), { code: 'AUTH_INVALID' });
  assert.throws(() => validateMaxInitData(`${signed}&%75ser=duplicate`, options), { code: 'AUTH_INVALID' });
  assert.throws(() => validateMaxInitData(signed.replace('Fixture', 'Altered'), options), { code: 'AUTH_INVALID' });
  assert.throws(() => validateMaxInitData(`${signed.slice(0, 12)}%${signed.slice(12)}`, options), { code: 'AUTH_INVALID' });
});

test('MAX initData rejects missing, expired, future, malformed and oversized values', () => {
  assert.throws(() => validateMaxInitData('', options), { code: 'AUTH_REQUIRED' });
  const signed = createSignedInitData({ authDate: 1_700_000_000 });
  assert.throws(() => validateMaxInitData(signed, { ...options, nowSeconds: () => 1_700_001_000 }), { code: 'AUTH_EXPIRED' });
  assert.throws(() => validateMaxInitData(signed, { ...options, nowSeconds: () => 1_699_999_000 }), { code: 'AUTH_INVALID' });
  assert.throws(() => validateMaxInitData(`${signed.slice(0, 12)}%${signed.slice(12)}`, options), { code: 'AUTH_INVALID' });
  assert.throws(() => validateMaxInitData('x'.repeat(16_385), options), { code: 'AUTH_INVALID' });
});

test('MAX user payload is strict and rejects unexpected profile/role fields', () => {
  const signed = createSignedInitData({ authDate: 1_700_000_000, userExtras: { role: 'admin' } });
  assert.throws(() => validateMaxInitData(signed, options), { code: 'AUTH_INVALID' });
  const invalidId = createSignedInitData({ authDate: 1_700_000_000, userId: -1 });
  assert.throws(() => validateMaxInitData(invalidId, options), { code: 'AUTH_INVALID' });
});
