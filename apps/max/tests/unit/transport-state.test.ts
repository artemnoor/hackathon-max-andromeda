import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AppError, ERROR_CODES } from '../../src/shared/errors.js';
import { MemoryMaxTransportState } from '../../src/shared/memory-transport-state.js';

const token = 'A'.repeat(32);
const nonce = 'N'.repeat(22);
const opaqueId = 'R'.repeat(22);
const profileCookie = 'P'.repeat(64);
const querySessionId = `query-session:${'a'.repeat(32)}`;

test('memory fixed window increments atomically and expires at its first deadline', async () => {
  let now = 10_000;
  const state = new MemoryMaxTransportState(() => now);

  assert.equal(await state.incrementWindow('global:address', 5), 1);
  now += 4_000;
  assert.equal(await state.incrementWindow('global:address', 5), 2);
  now += 1_001;
  assert.equal(await state.incrementWindow('global:address', 5), 1);
});

test('update leases distinguish busy, completed, release, and expired ownership', async () => {
  let now = 20_000;
  const state = new MemoryMaxTransportState(() => now);

  const reservation = await state.reserveUpdate('update:42', 2);
  assert.equal(reservation.status, 'reserved');
  if (reservation.status !== 'reserved') assert.fail('expected lease');

  assert.deepEqual(await state.reserveUpdate('update:42', 2), { status: 'busy' });
  assert.equal(await state.completeUpdate('update:42', token, 60), false);
  assert.equal(await state.completeUpdate('update:42', reservation.leaseToken, 60), true);
  assert.deepEqual(await state.reserveUpdate('update:42', 2), { status: 'processed' });
  assert.equal(await state.releaseUpdate('update:42', reservation.leaseToken), false);

  now += 60_001;
  const afterDoneExpiry = await state.reserveUpdate('update:42', 2);
  assert.equal(afterDoneExpiry.status, 'reserved');
});

test('failed update work releases only its current lease for retry', async () => {
  const state = new MemoryMaxTransportState();
  const reservation = await state.reserveUpdate('update:retry', 30);
  assert.equal(reservation.status, 'reserved');
  if (reservation.status !== 'reserved') assert.fail('expected lease');

  assert.equal(await state.releaseUpdate('update:retry', token), false);
  assert.equal(await state.releaseUpdate('update:retry', reservation.leaseToken), true);
  assert.equal((await state.reserveUpdate('update:retry', 30)).status, 'reserved');
});

test('expired lease can be replaced and the stale owner cannot complete or release it', async () => {
  let now = 30_000;
  const state = new MemoryMaxTransportState(() => now);
  const first = await state.reserveUpdate('update:lease-expiry', 1);
  assert.equal(first.status, 'reserved');
  if (first.status !== 'reserved') assert.fail('expected lease');

  now += 1_001;
  const second = await state.reserveUpdate('update:lease-expiry', 10);
  assert.equal(second.status, 'reserved');
  if (second.status !== 'reserved') assert.fail('expected replacement lease');
  assert.notEqual(first.leaseToken, second.leaseToken);
  assert.equal(await state.completeUpdate('update:lease-expiry', first.leaseToken, 60), false);
  assert.equal(await state.releaseUpdate('update:lease-expiry', first.leaseToken), false);
});

test('deep links are bounded, expiring, collision-safe, and consumed once', async () => {
  let now = 40_000;
  const state = new MemoryMaxTransportState(() => now);
  const reference = { version: 1 as const, kind: 'help' as const, referenceId: opaqueId };

  assert.equal(await state.storeDeepLink(nonce, reference, 5), true);
  assert.equal(await state.storeDeepLink(nonce, { version: 1, kind: 'start' }, 5), false);
  assert.deepEqual(await state.consumeDeepLink(nonce), reference);
  assert.equal(await state.consumeDeepLink(nonce), undefined);

  assert.equal(await state.storeDeepLink(nonce, reference, 5), true);
  now += 5_001;
  assert.equal(await state.consumeDeepLink(nonce), undefined);
});

test('Andromeda session mappings are user-scoped, revisioned, and writable only by the current conversation lease', async () => {
  const state = new MemoryMaxTransportState();
  const first = await state.reserveConversationTurn('max-user:101', 30);
  assert.equal(first.status, 'reserved');
  if (first.status !== 'reserved') assert.fail('expected conversation lease');

  assert.deepEqual(await state.reserveConversationTurn('max-user:101', 30), { status: 'busy' });
  assert.equal(await state.getAndromedaMapping('max-user:101'), undefined);
  const mapping = {
    version: 1 as const,
    profileCookie,
    sessionId: querySessionId,
    revision: 4,
    lastActivityAt: 50_000,
  };
  assert.equal(await state.saveAndromedaMapping('max-user:101', token, mapping, 60), false);
  assert.equal(await state.saveAndromedaMapping('max-user:101', first.leaseToken, mapping, 60), true);
  assert.deepEqual(await state.getAndromedaMapping('max-user:101'), mapping);
  assert.equal(await state.releaseConversationTurn('max-user:101', first.leaseToken), true);

  const second = await state.reserveConversationTurn('max-user:101', 30);
  assert.equal(second.status, 'reserved');
  if (second.status !== 'reserved') assert.fail('expected replacement lease');
  assert.equal(await state.saveAndromedaMapping('max-user:101', first.leaseToken, {
    ...mapping,
    revision: 5,
  }, 60), false);
  assert.equal(await state.saveAndromedaMapping('max-user:101', second.leaseToken, {
    ...mapping,
    revision: 5,
    lastActivityAt: 60_000,
  }, 60), true);
  assert.equal((await state.getAndromedaMapping('max-user:101'))?.revision, 5);
  assert.equal(await state.getAndromedaMapping('max-user:102'), undefined);
});

test('Andromeda session reset preserves the profile cookie and rejects malformed mappings', async () => {
  let now = 100_000;
  const state = new MemoryMaxTransportState(() => now);
  const lease = await state.reserveConversationTurn('max-user:201', 1);
  assert.equal(lease.status, 'reserved');
  if (lease.status !== 'reserved') assert.fail('expected conversation lease');

  assert.equal(await state.saveAndromedaMapping('max-user:201', lease.leaseToken, {
    version: 1,
    profileCookie,
    sessionId: querySessionId,
    revision: 2,
    lastActivityAt: now,
  }, 60), true);
  now += 1_001;
  const replacement = await state.reserveConversationTurn('max-user:201', 30);
  assert.equal(replacement.status, 'reserved');
  if (replacement.status !== 'reserved') assert.fail('expected replacement lease');
  assert.equal(await state.resetAndromedaQuerySession('max-user:201', replacement.leaseToken, profileCookie, now, 60), true);
  assert.deepEqual(await state.getAndromedaMapping('max-user:201'), {
    version: 1,
    profileCookie,
    lastActivityAt: now,
  });

  await assert.rejects(
    state.saveAndromedaMapping('max-user:201', replacement.leaseToken, {
      version: 1,
      profileCookie,
      sessionId: querySessionId,
      revision: 0,
      lastActivityAt: now,
    }, 60),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.VALIDATION_FAILED,
  );
  await assert.rejects(
    state.saveAndromedaMapping('max-user:201', replacement.leaseToken, {
      version: 1,
      profileCookie,
      lastActivityAt: now,
      transcript: 'must not be persisted',
    } as never, 60),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.VALIDATION_FAILED,
  );
});

test('invalid keys, TTLs, lease tokens, nonce and deep-link payload fail before state access', async () => {
  const state = new MemoryMaxTransportState();
  const invalid = async (action: () => Promise<unknown>): Promise<void> => {
    await assert.rejects(action, (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.VALIDATION_FAILED);
  };

  await invalid(() => state.incrementWindow('raw user@email.test', 30));
  await invalid(() => state.incrementWindow('rate', 0));
  await invalid(() => state.reserveUpdate('update', 601));
  await invalid(() => state.completeUpdate('update', 'short', 60));
  await invalid(() => state.storeDeepLink('short', { version: 1, kind: 'help' }, 30));
  await invalid(() => state.storeDeepLink(nonce, { version: 1, kind: 'help', referenceId: 'email@example.test' }, 30));
});
