import assert from 'node:assert/strict';
import { randomInt, randomUUID } from 'node:crypto';
import { after, before, test } from 'node:test';

import { Redis } from 'ioredis';

import { AndromedaApiClient, type AssistantQueryResponse } from '../../src/max/client/andromeda-api.js';
import { createAssistantInteraction } from '../../src/max/bot/assistant.js';
import type { MaxUpdate } from '../../src/max/bot/update.js';
import { MemoryMaxTransportState } from '../../src/shared/memory-transport-state.js';
import { RedisMaxTransportState } from '../../src/shared/redis/transport-state.js';
import type { MaxTransportState } from '../../src/shared/transport-state.js';
import { AppError, ERROR_CODES } from '../../src/shared/errors.js';

const apiUrl = process.env['MAX_E2E_ANDROMEDA_URL'];
const redisUrl = process.env['MAX_TEST_REDIS_URL'];
const testIsEnabled = Boolean(apiUrl);

if (apiUrl) {
  const parsed = new URL(apiUrl);
  if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
    || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error('MAX_E2E_ANDROMEDA_URL must be a plain HTTP loopback origin.');
  }
}

if (redisUrl) {
  const parsed = new URL(redisUrl);
  const database = Number(parsed.pathname.slice(1));
  if (parsed.protocol !== 'redis:' || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
    || !Number.isInteger(database) || database < 1 || database > 15 || parsed.search || parsed.hash
    || parsed.username || parsed.password) {
    throw new Error('MAX_TEST_REDIS_URL must use unauthenticated loopback Redis database 1-15.');
  }
}

const redis = testIsEnabled && redisUrl
  ? new Redis(redisUrl, { lazyConnect: true, connectTimeout: 2_000, maxRetriesPerRequest: 1 })
  : undefined;
let state: MaxTransportState = new MemoryMaxTransportState();
let api: AndromedaApiClient | undefined;

before(async () => {
  if (!apiUrl) return;
  api = new AndromedaApiClient({
    baseUrl: apiUrl,
    environment: 'test',
    profileCookieName: 'andromeda_profile_session',
    timeoutMs: 5_000,
    profileCookieSecure: false,
  });
  if (redis) {
    await redis.connect();
    state = new RedisMaxTransportState(redis);
  }
});

after(async () => {
  if (redis && redis.status !== 'end') await redis.quit();
});

const requireApi = (): AndromedaApiClient => {
  assert.ok(api, 'MAX_E2E_ANDROMEDA_URL must configure the real local Andromeda API');
  return api;
};

const syntheticMessage = (text: string, userId = randomInt(1_000_000, 2_000_000_000)): MaxUpdate => {
  const timestamp = Date.now();
  return {
    kind: 'message_created',
    updateId: `max_${randomUUID().replaceAll('-', '')}`,
    receivedAt: timestamp,
    platformTimestamp: Math.max(1, timestamp),
    userId,
    chatId: randomInt(2_000_000_001, 2_100_000_000),
    text,
    attachments: [],
  };
};

const interaction = () => createAssistantInteraction({
  api: requireApi(),
  state,
  config: {
    andromedaProfileTtlSeconds: 86_400,
    andromedaQuerySessionTtlSeconds: 86_400,
  },
});

const query = async (text: string): Promise<AssistantQueryResponse> => {
  const result = await interaction().query(syntheticMessage(text), text);
  return result.result;
};

test('HTTP AI program discovery clarifies a metric and carries the same backend session on follow-up', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const assistant = interaction();
  const userId = randomInt(1_000_000, 2_000_000_000);
  const update = syntheticMessage('Какие программы в МГТУ связаны с искусственным интеллектом?', userId);
  const first = await assistant.query(update, 'Какие программы в МГТУ связаны с искусственным интеллектом?');

  assert.equal(first.result.state, 'needs_clarification');
  assert.ok(first.result.missing_slots.includes('metric'));
  assert.ok(first.result.session_id);

  const second = await assistant.query(syntheticMessage('AI', userId), 'AI');
  assert.equal(second.result.state, 'complete');
  assert.equal(second.result.session_id, first.result.session_id);
  assert.ok(second.result.revision > first.result.revision);
  assert.ok(second.result.query?.metrics.includes('ai_share'));
});

test('HTTP applicant score query reaches the existing admission-fit result with explicit inputs', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const result = await query(
    'Куда я поступлю с 270 баллами: русский 90, математика 90, информатика 90 в university:bmstu на бюджет в 2026 году?',
  );

  assert.equal(result.state, 'complete');
  assert.equal(result.admission_request?.admission_year, 2026);
  assert.equal(result.admission_request?.funding_type, 'budget');
  const admissionResult = result.admission_result;
  assert.ok(admissionResult);
  const byProgramId = admissionResult.by_program_id;
  assert.ok(byProgramId);
  assert.ok(Object.keys(byProgramId).length > 0);
});

test('HTTP comparison query reaches the deterministic program analytics path', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const assistant = interaction();
  const userId = randomInt(1_000_000, 2_000_000_000);
  const firstText = 'Сравни ИУ5 и ИУ7 по программированию и математике';
  const first = await assistant.query(syntheticMessage(firstText, userId), firstText);

  assert.equal(first.result.state, 'needs_clarification');
  assert.ok(first.result.missing_slots.includes('entity'));
  assert.ok(first.result.session_id);

  const followUpText = 'Сравни program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12 по programming_share и mathematics_share';
  const followUp = await assistant.query(
    syntheticMessage(followUpText, userId),
    followUpText,
  );
  const result = followUp.result;

  assert.equal(result.state, 'complete');
  assert.equal(result.session_id, first.result.session_id);
  assert.ok(result.revision > first.result.revision);
  assert.equal(result.query?.scope, 'program');
  assert.deepEqual(
    [...(result.query?.metrics ?? [])].sort(),
    ['math_share', 'programming_share'],
  );
  assert.deepEqual(
    [...(result.query?.scope_ids ?? [])].sort(),
    ['program:bmstu:09.03.01-02', 'program:bmstu:09.03.01-12'],
  );
  assert.equal(result.response?.response_mode, 'deterministic');
  assert.equal(result.response?.response_type, 'image');
});

test('HTTP BVI policy question reports missing evidence as uncertainty, not as a negative rule', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const result = await query('Правда ли, что с 2028 года изменятся правила БВИ?');
  const knowledge = result.response?.knowledge;

  assert.equal(result.state, 'complete');
  assert.ok(knowledge);
  assert.ok(['outside_coverage', 'no_evidence'].includes(knowledge.status));
  assert.equal(
    result.response?.response_mode,
    knowledge.status === 'outside_coverage' ? 'unverified_fallback' : 'deterministic',
  );
  assert.equal(knowledge.evidence.length, 0);
  assert.ok(knowledge.uncertainties.length > 0);
  assert.doesNotMatch(result.response?.text ?? '', /льгот нет|правило отсутствует|исключений нет/iu);
});

test('HTTP unsupported general question stays outside verified coverage and has no source evidence', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const result = await query('Что нового обсуждают в мире поступления?');

  assert.equal(result.state, 'complete');
  assert.equal(result.response?.response_mode, 'unverified_fallback');
  assert.equal(result.response?.knowledge?.status, 'outside_coverage');
  assert.equal(result.response?.knowledge?.evidence.length, 0);
});

test('HTTP stale assistant revision fails closed after a newer turn', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const client = requireApi();
  const first = await client.queryAssistant({ text: 'Какие программы в МГТУ связаны с искусственным интеллектом?' });
  assert.ok(first.profileCookie);

  const second = await client.queryAssistant({
    text: 'AI',
    sessionId: first.result.session_id,
    expectedRevision: first.result.revision,
  }, first.profileCookie);
  assert.ok(second.result.revision > first.result.revision);

  await assert.rejects(
    () => client.queryAssistant({
      text: 'Устаревшее уточнение',
      sessionId: first.result.session_id,
      expectedRevision: first.result.revision,
    }, first.profileCookie),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.SESSION_CONFLICT,
  );
});
