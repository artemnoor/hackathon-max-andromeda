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
    timeoutMs: 10_000,
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

test('HTTP AI program discovery clarifies interests and carries the same backend session on follow-up', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const assistant = interaction();
  const userId = randomInt(1_000_000, 2_000_000_000);
  const baseUrl = apiUrl;
  assert.ok(baseUrl);
  const catalogResponse = await fetch(`${baseUrl}/universities`);
  assert.equal(catalogResponse.status, 200);
  const catalog = await catalogResponse.json() as { items?: ReadonlyArray<{ id?: string }> };
  assert.ok(
    catalog.items?.some((item) => item.id === 'university:bmstu'),
    JSON.stringify(catalog),
  );
  const firstText = 'Покажи программы в university:bmstu';
  const first = await assistant.query(syntheticMessage(firstText, userId), firstText);

  assert.equal(first.result.state, 'needs_clarification', JSON.stringify(first.result));
  assert.ok(first.result.missing_slots.includes('interests'), JSON.stringify(first.result));
  assert.ok(first.result.session_id);

  const second = await assistant.query(syntheticMessage('AI', userId), 'AI');
  assert.equal(second.result.state, 'complete', JSON.stringify(second.result));
  assert.equal(second.result.session_id, first.result.session_id);
  assert.ok(second.result.revision > first.result.revision);
  assert.equal(second.result.response?.template, 'program-recommendations');
  const responseData: Record<string, unknown> | undefined = second.result.response?.data;
  assert.ok(responseData);
  assert.ok(
    Array.isArray(responseData['recommendations'])
      && responseData['recommendations'].length > 0,
  );
});

test('HTTP applicant score query reaches the existing admission-fit result with explicit inputs', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const result = await query(
    'Куда я прохожу с 270: русский 90, математика 90, информатика 90, university:bmstu, бюджет на 2026 год',
  );

  assert.equal(result.state, 'complete', JSON.stringify(result));
  assert.equal(result.admission_request?.admission_year, 2026);
  assert.equal(result.admission_request?.funding_type, 'budget');
  const admissionResult = result.admission_result;
  assert.ok(admissionResult);
  const byProgramId = admissionResult.by_program_id;
  assert.ok(byProgramId);
  assert.ok(Object.keys(byProgramId).length > 0);
});

test('HTTP multiple-university choice advances to asking for university names', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const assistant = interaction();
  const userId = randomInt(1_000_000, 2_000_000_000);
  const firstText = 'Куда я прохожу: русский 80, математика 85, информатика 88';
  const first = await assistant.query(syntheticMessage(firstText, userId), firstText);

  assert.equal(first.result.state, 'needs_clarification');
  assert.ok(first.result.missing_slots.includes('funding'));

  const second = await assistant.query(
    syntheticMessage('Несколько вузов', userId),
    'Несколько вузов',
  );
  assert.equal(second.result.state, 'needs_clarification');
  assert.equal(second.result.session_id, first.result.session_id);
  assert.equal(second.result.revision, first.result.revision + 1);
  assert.equal(
    second.result.question,
    'Напишите название одного или нескольких вузов через запятую.',
  );
  assert.deepEqual(second.result.options, []);
});

test('HTTP comparison query reaches the program analytics path', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const assistant = interaction();
  const userId = randomInt(1_000_000, 2_000_000_000);
  const firstText = 'Сравни ИУ5 и ИУ7 по программированию и математике';
  const first = await assistant.query(syntheticMessage(firstText, userId), firstText);

  assert.equal(first.result.state, 'needs_clarification');
  assert.ok(first.result.missing_slots.includes('entity'));
  assert.ok(first.result.session_id);

  const followUpText = 'Сравни program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12 по программированию и математике';
  const followUp = await assistant.query(
    syntheticMessage(followUpText, userId),
    followUpText,
  );
  const result = followUp.result;

  assert.equal(result.state, 'complete', JSON.stringify(result));
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
  assert.ok(
    ['deterministic', 'source_backed_verbalization'].includes(result.response?.response_mode ?? ''),
  );
  assert.equal(result.response?.response_type, 'text');
  assert.equal(result.response?.template, 'program-comparison-summary');
});

test('HTTP comparison renders a summary first and accepts a metric-only follow-up', {
  skip: testIsEnabled ? false : 'MAX_E2E_ANDROMEDA_URL is not set; run `python scripts/monorepo.py e2e` for fixture-backed HTTP coverage',
}, async () => {
  const assistant = interaction();
  const userId = randomInt(1_000_000, 2_000_000_000);
  const startText = 'Сравнить программы';
  const first = await assistant.query(
    syntheticMessage(startText, userId),
    startText,
  );

  assert.equal(first.result.state, 'needs_clarification', JSON.stringify(first.result));
  assert.ok(first.result.missing_slots.includes('entity'));
  assert.match(first.result.question ?? '', /направления или программы/u);

  const entityText = 'program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12';
  const second = await assistant.query(syntheticMessage(entityText, userId), entityText);
  assert.equal(second.result.state, 'complete', JSON.stringify(second.result));
  assert.equal(second.result.session_id, first.result.session_id);
  assert.ok(second.result.response?.data);
  assert.ok(second.result.query?.metrics.includes('programming_share'));
  assert.deepEqual(second.result.options, []);

  const thirdText = 'А теперь только по математике';
  const third = await assistant.query(syntheticMessage(thirdText, userId), thirdText);
  assert.equal(third.result.state, 'complete', JSON.stringify(third.result));
  assert.equal(third.result.session_id, second.result.session_id);
  assert.ok(third.result.revision > second.result.revision);
  assert.deepEqual(third.result.query?.metrics, ['math_share']);
  assert.ok(third.result.query?.metrics.includes('math_share'));
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
