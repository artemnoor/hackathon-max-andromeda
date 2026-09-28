import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AppError, ERROR_CODES } from '../../src/shared/errors.js';
import { MemoryMaxTransportState } from '../../src/shared/memory-transport-state.js';
import { createAssistantInteraction } from '../../src/max/bot/assistant.js';
import { normalizeMaxUpdate, type MaxUpdate } from '../../src/max/bot/update.js';
import type { AssistantQueryInput, AssistantQueryResponse } from '../../src/max/client/andromeda-api.js';

const COOKIE = 'C'.repeat(64);
const SESSION_1 = 'query-session:' + '1'.repeat(32);
const SESSION_2 = 'query-session:' + '2'.repeat(32);
const CONFIG = { andromedaProfileTtlSeconds: 3_600, andromedaQuerySessionTtlSeconds: 60 } as const;

const response = (sessionId = SESSION_1, revision = 1): AssistantQueryResponse => ({
  state: 'complete',
  session_id: sessionId,
  revision,
  options: [],
  missing_slots: [],
  admission_requests: [],
} as AssistantQueryResponse);

const messageUpdate = (userId = 701): MaxUpdate => {
  const normalized = normalizeMaxUpdate({
    updateType: 'message_created',
    update: {
      update_type: 'message_created',
      timestamp: 100,
      message: {
        sender: { user_id: userId },
        recipient: { chat_id: 900 },
        body: { text: 'Какие программы доступны?' },
      },
    },
  });
  assert.ok(normalized);
  return normalized;
};

test('conversation mapping carries only profile cookie and exact assistant session revision across turns', async () => {
  const state = new MemoryMaxTransportState();
  const calls: Array<{ body: AssistantQueryInput; cookie?: string }> = [];
  const api = {
    async queryAssistant(body: AssistantQueryInput, cookie?: string) {
      calls.push({ body, ...(cookie ? { cookie } : {}) });
      return calls.length === 1
        ? { result: response(SESSION_1, 1), profileCookie: COOKIE }
        : { result: response(SESSION_1, 2) };
    },
  };
  const interaction = createAssistantInteraction({ api, state, config: CONFIG, now: () => 100_000 });

  const first = await interaction.query(messageUpdate(), 'Поступление');
  const second = await interaction.query(messageUpdate(), 'А на бюджет?');
  assert.equal(first.result.revision, 1);
  assert.equal(second.result.revision, 2);
  assert.deepEqual(calls[0]?.body, { text: 'Поступление' });
  assert.deepEqual(calls[1]?.body, { text: 'А на бюджет?', sessionId: SESSION_1, expectedRevision: 1 });
  assert.equal(calls[1]?.cookie, COOKIE);
  assert.deepEqual(await state.getAndromedaMapping('max-user:701'), {
    version: 1,
    profileCookie: COOKIE,
    sessionId: SESSION_1,
    revision: 2,
    lastActivityAt: 100_000,
  });
});

test('expired QuerySession starts a new backend session while retaining the anonymous profile cookie', async () => {
  let now = 200_000;
  const state = new MemoryMaxTransportState(() => now);
  const firstLease = await state.reserveConversationTurn('max-user:702', 30);
  assert.equal(firstLease.status, 'reserved');
  if (firstLease.status !== 'reserved') assert.fail('expected lease');
  assert.equal(await state.saveAndromedaMapping('max-user:702', firstLease.leaseToken, {
    version: 1,
    profileCookie: COOKIE,
    sessionId: SESSION_1,
    revision: 8,
    lastActivityAt: now,
  }, 3_600), true);
  assert.equal(await state.releaseConversationTurn('max-user:702', firstLease.leaseToken), true);

  now += 60_000;
  const calls: Array<{ body: AssistantQueryInput; cookie?: string }> = [];
  const interaction = createAssistantInteraction({
    api: {
      async queryAssistant(body, cookie) {
        calls.push({ body, ...(cookie ? { cookie } : {}) });
        return { result: response(SESSION_2, 1) };
      },
    },
    state,
    config: CONFIG,
    now: () => now,
  });

  await interaction.query(messageUpdate(702), 'Правило на будущее');
  assert.deepEqual(calls, [{ body: { text: 'Правило на будущее' }, cookie: COOKIE }]);
  assert.equal((await state.getAndromedaMapping('max-user:702'))?.sessionId, SESSION_2);
});

test('expired and conflicting sessions recover once using the current question and same profile', async () => {
  const state = new MemoryMaxTransportState();
  const lease = await state.reserveConversationTurn('max-user:703', 30);
  assert.equal(lease.status, 'reserved');
  if (lease.status !== 'reserved') assert.fail('expected lease');
  assert.equal(await state.saveAndromedaMapping('max-user:703', lease.leaseToken, {
    version: 1,
    profileCookie: COOKIE,
    sessionId: SESSION_1,
    revision: 4,
    lastActivityAt: 300_000,
  }, 3_600), true);
  assert.equal(await state.releaseConversationTurn('max-user:703', lease.leaseToken), true);

  const calls: Array<{ body: AssistantQueryInput; cookie?: string }> = [];
  const interaction = createAssistantInteraction({
    api: {
      async queryAssistant(body, cookie) {
        calls.push({ body, ...(cookie ? { cookie } : {}) });
        if (calls.length === 1) throw new AppError(ERROR_CODES.SESSION_EXPIRED, 404);
        return { result: response(SESSION_2, 1) };
      },
    },
    state,
    config: CONFIG,
    now: () => 300_001,
  });

  const outcome = await interaction.query(messageUpdate(703), 'Тот же вопрос один раз');
  assert.equal(outcome.restartedSession, true);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1], { body: { text: 'Тот же вопрос один раз' }, cookie: COOKIE });
  assert.equal((await state.getAndromedaMapping('max-user:703'))?.sessionId, SESSION_2);
});

test('unknown backend failures are not retried and conversation lease is released', async () => {
  const state = new MemoryMaxTransportState();
  let calls = 0;
  const interaction = createAssistantInteraction({
    api: {
      async queryAssistant() {
        calls += 1;
        throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
      },
    },
    state,
    config: CONFIG,
    now: () => 400_000,
  });

  await assert.rejects(interaction.query(messageUpdate(704), 'Вопрос'), (error: unknown) =>
    error instanceof AppError && error.code === ERROR_CODES.DEPENDENCY_UNAVAILABLE);
  assert.equal(calls, 1);
  assert.equal((await state.reserveConversationTurn('max-user:704', 30)).status, 'reserved');
});

test('concurrent turns for one MAX user cannot race expectedRevision', async () => {
  const state = new MemoryMaxTransportState();
  let entered = false;
  let releaseApi: (() => void) | undefined;
  const waiting = new Promise<void>((resolve) => { releaseApi = resolve; });
  let calls = 0;
  const interaction = createAssistantInteraction({
    api: {
      async queryAssistant() {
        calls += 1;
        entered = true;
        await waiting;
        return { result: response(), profileCookie: COOKIE };
      },
    },
    state,
    config: CONFIG,
    now: () => 500_000,
  });
  const first = interaction.query(messageUpdate(705), 'Первый вопрос');
  while (!entered) await new Promise((resolve) => setTimeout(resolve, 1));
  await assert.rejects(interaction.query(messageUpdate(705), 'Параллельный вопрос'), (error: unknown) =>
    error instanceof AppError && error.code === ERROR_CODES.DEPENDENCY_UNAVAILABLE);
  releaseApi?.();
  await first;
  assert.equal(calls, 1);
});
