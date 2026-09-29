import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, test } from 'node:test';

import { Redis } from 'ioredis';

import { RedisMaxTransportState } from '../../src/shared/redis/transport-state.js';

const redisUrl = process.env['MAX_TEST_REDIS_URL'];
if (redisUrl) {
  const parsed = new URL(redisUrl);
  const database = Number(parsed.pathname.slice(1));
  if (parsed.protocol !== 'redis:' || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
    || !Number.isInteger(database) || database < 1 || database > 15 || parsed.search || parsed.hash
    || parsed.username || parsed.password) {
    throw new Error('MAX_TEST_REDIS_URL must use unauthenticated loopback Redis database 1-15.');
  }
}
const redis = redisUrl ? new Redis(redisUrl, { lazyConnect: true, connectTimeout: 2_000, maxRetriesPerRequest: 1 }) : undefined;
const state = redis ? new RedisMaxTransportState(redis) : undefined;
const unique = (): string => `it:${randomUUID()}`;

before(async () => {
  if (redis) await redis.connect();
});

after(async () => {
  if (redis && redis.status !== 'end') await redis.quit();
});

test('Redis atomic MAX transport state contract', { skip: !redis || !state ? 'MAX_TEST_REDIS_URL is not set' : false }, async () => {
  assert.ok(state);

  const windowKey = unique();
  const counts = await Promise.all(Array.from({ length: 48 }, () => state.incrementWindow(windowKey, 30)));
  assert.deepEqual([...counts].sort((left, right) => left - right), Array.from({ length: 48 }, (_, index) => index + 1));

  const updateKey = unique();
  const reservations = await Promise.all(Array.from({ length: 32 }, () => state.reserveUpdate(updateKey, 30)));
  const acquired = reservations.filter((result) => result.status === 'reserved');
  assert.equal(acquired.length, 1);
  const lease = acquired[0];
  assert.ok(lease && lease.status === 'reserved');
  assert.equal(reservations.filter((result) => result.status === 'busy').length, 31);
  assert.equal(await state.completeUpdate(updateKey, 'X'.repeat(32), 60), false);
  assert.equal(await state.completeUpdate(updateKey, lease.leaseToken, 60), true);
  assert.equal((await state.reserveUpdate(updateKey, 30)).status, 'processed');

  const retryKey = unique();
  const retryLease = await state.reserveUpdate(retryKey, 30);
  assert.equal(retryLease.status, 'reserved');
  if (retryLease.status === 'reserved') {
    assert.equal(await state.releaseUpdate(retryKey, retryLease.leaseToken), true);
    assert.equal((await state.reserveUpdate(retryKey, 30)).status, 'reserved');
  }

  const nonce = randomUUID().replaceAll('-', '_').padEnd(22, 'N');
  const reference = { version: 1 as const, kind: 'help' as const };
  assert.equal(await state.storeDeepLink(nonce, reference, 30), true);
  assert.equal(await state.storeDeepLink(nonce, { version: 1, kind: 'start' }, 30), false);
  const consumed = await Promise.all(Array.from({ length: 24 }, () => state.consumeDeepLink(nonce)));
  assert.equal(consumed.filter((value) => value !== undefined).length, 1);
  assert.deepEqual(consumed.find((value) => value !== undefined), reference);

  const userKey = `max-user:${randomUUID()}`;
  const conversationLocks = await Promise.all(Array.from({ length: 24 }, () => state.reserveConversationTurn(userKey, 30)));
  const conversationLeases = conversationLocks.filter((value) => value.status === 'reserved');
  assert.equal(conversationLeases.length, 1);
  const conversationLease = conversationLeases[0];
  assert.ok(conversationLease && conversationLease.status === 'reserved');
  assert.equal(conversationLocks.filter((value) => value.status === 'busy').length, 23);

  const mapping = {
    version: 1 as const,
    profileCookie: 'P'.repeat(64),
    sessionId: `query-session:${'a'.repeat(32)}`,
    revision: 3,
    lastActivityAt: Date.now(),
  };
  assert.equal(await state.saveAndromedaMapping(userKey, conversationLease.leaseToken, mapping, 60), true);
  assert.deepEqual(await state.getAndromedaMapping(userKey), mapping);
  assert.equal(await state.releaseConversationTurn(userKey, conversationLease.leaseToken), true);

  const replacementConversationLease = await state.reserveConversationTurn(userKey, 30);
  assert.equal(replacementConversationLease.status, 'reserved');
  if (replacementConversationLease.status === 'reserved') {
    assert.equal(await state.saveAndromedaMapping(userKey, conversationLease.leaseToken, {
      ...mapping,
      revision: 4,
    }, 60), false);
    const resetAt = Date.now();
    assert.equal(await state.resetAndromedaQuerySession(
      userKey,
      replacementConversationLease.leaseToken,
      mapping.profileCookie,
      resetAt,
      60,
    ), true);
    assert.deepEqual(await state.getAndromedaMapping(userKey), {
      version: 1,
      profileCookie: mapping.profileCookie,
      lastActivityAt: resetAt,
    });
  }

  const expiringKey = unique();
  assert.equal(await state.incrementWindow(expiringKey, 1), 1);
  await new Promise((resolve) => setTimeout(resolve, 1_100));
  assert.equal(await state.incrementWindow(expiringKey, 30), 1);
});
