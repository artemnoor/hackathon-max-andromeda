import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  ANDROMEDA_ASSISTANT_PATH,
  AndromedaApiClient,
  MAX_ANDROMEDA_RESPONSE_BYTES,
  type AssistantQueryResponse,
} from '../../src/max/client/andromeda-api.js';
import { AppError, ERROR_CODES } from '../../src/shared/errors.js';
import type { Logger } from '../../src/shared/logger.js';

const PROFILE_COOKIE = 'p'.repeat(48);
const AUTH_COOKIE = 'a'.repeat(48);
const SESSION_ID = `query-session:${'1'.repeat(32)}`;

const assistantResult = (overrides: Record<string, unknown> = {}): AssistantQueryResponse => ({
  state: 'complete',
  session_id: SESSION_ID,
  revision: 2,
  options: [],
  missing_slots: [],
  admission_requests: [],
  ...overrides,
} as AssistantQueryResponse);

const responseEnvelope = (text = 'Проверенный ответ'): Record<string, unknown> => ({
  response_type: 'text',
  response_mode: 'deterministic',
  text,
  template: 'policy-resolution',
  actions: [],
  evidence: [],
  policy_version: 'response-policy.v1',
});

const apiResponse = (
  body: unknown = assistantResult(),
  options: { status?: number; headers?: HeadersInit } = {},
): Response => {
  const headers = new Headers({ 'content-type': 'application/json' });
  const additional = new Headers(options.headers);
  additional.forEach((value, key) => {
    if (key !== 'set-cookie') headers.set(key, value);
  });
  for (const cookie of additional.getSetCookie()) headers.append('set-cookie', cookie);
  return new Response(JSON.stringify(body), {
    status: options.status ?? 200,
    headers,
  });
};

const client = (options: Partial<ConstructorParameters<typeof AndromedaApiClient>[0]> = {}) =>
  new AndromedaApiClient({
    baseUrl: 'http://127.0.0.1:8000',
    environment: 'test',
    profileCookieName: 'andromeda_profile_session',
    timeoutMs: 5_000,
    profileCookieSecure: false,
    ...options,
  });

test('MAX calls the generated Public API path and forwards only the profile cookie', async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const instance = client({
    baseUrl: 'http://andromeda:8000/gateway',
    fetcher: async (input, init) => {
      calls.push({ input, ...(init ? { init } : {}) });
      return apiResponse(
        assistantResult({ response: responseEnvelope() }),
        { headers: {
          'set-cookie': '',
        } },
      );
    },
  });

  await instance.queryAssistant({ text: 'Подбери программу' });

  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.input, `http://andromeda:8000/gateway${ANDROMEDA_ASSISTANT_PATH}`);
  assert.equal(calls[0]?.init?.method, 'POST');
  assert.equal(calls[0]?.init?.redirect, 'error');
  assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), { text: 'Подбери программу' });
  const headers = new Headers(calls[0]?.init?.headers);
  assert.equal(headers.get('cookie'), null);
  assert.equal(headers.get('authorization'), null);
});

test('profile cookie is captured and rotated; auth cookie is never stored or forwarded', async () => {
  const calls: Request[] = [];
  let responseCount = 0;
  const instance = client({
    fetcher: async (input, init) => {
      calls.push(new Request(input, init));
      responseCount += 1;
      const headers = new Headers();
      if (responseCount === 1) {
        headers.append('set-cookie', `andromeda_profile_session=${PROFILE_COOKIE}; Path=/; HttpOnly; SameSite=Lax`);
        headers.append('set-cookie', `andromeda_auth_session=${AUTH_COOKIE}; Path=/; HttpOnly; SameSite=Lax`);
      } else {
        headers.append('set-cookie', `andromeda_profile_session=${'r'.repeat(48)}; Path=/; HttpOnly; SameSite=Lax`);
      }
      return apiResponse(assistantResult(), { headers });
    },
  });

  const first = await instance.queryAssistant({ text: 'Первый вопрос' });
  assert.equal(first.profileCookie, PROFILE_COOKIE);
  const second = await instance.queryAssistant(
    { text: 'Уточнение', sessionId: first.result.session_id, expectedRevision: first.result.revision },
    first.profileCookie,
  );

  assert.equal(second.profileCookie, 'r'.repeat(48));
  assert.deepEqual(calls.map((request) => request.headers.get('cookie')), [
    null,
    `andromeda_profile_session=${PROFILE_COOKIE}`,
  ]);
  assert.deepEqual(Object.keys(JSON.parse(await calls[1]!.clone().text())).sort(), [
    'expectedRevision', 'sessionId', 'text',
  ]);
  assert.equal(calls[1]?.headers.get('authorization'), null);
  assert.equal(calls[1]?.headers.get('cookie')?.includes(AUTH_COOKIE), false);
});

test('API status mapping keeps conflict, expired session, rate limit and dependency failures distinct', async () => {
  const cases = [
    { status: 409, code: 'CONFLICT', session: true, expected: ERROR_CODES.SESSION_CONFLICT },
    { status: 404, code: 'NOT_FOUND', session: true, expected: ERROR_CODES.SESSION_EXPIRED },
    { status: 404, code: 'NOT_FOUND', session: false, expected: ERROR_CODES.DEPENDENCY_UNAVAILABLE },
    { status: 429, code: 'RATE_LIMITED', session: false, expected: ERROR_CODES.RATE_LIMITED },
    { status: 500, code: 'INTERNAL_ERROR', session: false, expected: ERROR_CODES.DEPENDENCY_UNAVAILABLE },
  ] as const;

  for (const item of cases) {
    const instance = client({
      fetcher: async () => apiResponse(
        { code: item.code, message: 'private backend details', details: [] },
        { status: item.status },
      ),
    });
    await assert.rejects(
      () => instance.queryAssistant({
        text: 'Question',
        ...(item.session ? { sessionId: SESSION_ID, expectedRevision: 2 } : {}),
      }),
      (error: unknown) => error instanceof AppError && error.code === item.expected,
    );
  }
});

test('invalid JSON, malformed response and oversized body fail closed', async () => {
  const invalidJson = client({ fetcher: async () => new Response('{', {
    status: 200, headers: { 'content-type': 'application/json' },
  }) });
  await assert.rejects(
    () => invalidJson.queryAssistant({ text: 'Question' }),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.DEPENDENCY_UNAVAILABLE,
  );

  const malformed = client({ fetcher: async () => apiResponse({ state: 'complete' }) });
  await assert.rejects(
    () => malformed.queryAssistant({ text: 'Question' }),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.DEPENDENCY_UNAVAILABLE,
  );

  const oversized = client({ fetcher: async () => new Response('x'.repeat(MAX_ANDROMEDA_RESPONSE_BYTES + 1), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  }) });
  await assert.rejects(
    () => oversized.queryAssistant({ text: 'Question' }),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.DEPENDENCY_UNAVAILABLE,
  );
});

test('redirects are disabled and POST is never blindly retried', async () => {
  let calls = 0;
  const instance = client({ fetcher: async (_input, init) => {
    calls += 1;
    assert.equal(init?.redirect, 'error');
    return apiResponse({ code: 'INTERNAL_ERROR', message: 'private', details: [] }, { status: 503 });
  } });

  await assert.rejects(() => instance.queryAssistant({ text: 'Question' }));
  assert.equal(calls, 1);
});

test('timeout and cookie validation return safe errors without logging message or credentials', async () => {
  const logs: unknown[] = [];
  const logger: Logger = {
    level: 'debug',
    child: () => logger,
    debug: (fields) => logs.push(fields),
    info: (fields) => logs.push(fields),
    warn: (fields) => logs.push(fields),
    error: (fields) => logs.push(fields),
    fatal: (fields) => logs.push(fields),
  };
  const timeoutClient = client({
    timeoutMs: 250,
    logger,
    fetcher: (_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new TypeError('private network details')));
    }),
  });
  await assert.rejects(
    () => timeoutClient.queryAssistant({ text: 'PII question do not log' }),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.DEPENDENCY_UNAVAILABLE,
  );

  const invalidCookie = client({ fetcher: async () => {
    const headers = new Headers();
    headers.append('set-cookie', 'andromeda_profile_session=short; Path=/; HttpOnly');
    return apiResponse(assistantResult(), { headers });
  } });
  await assert.rejects(() => invalidCookie.queryAssistant({ text: 'Question' }));

  const serializedLogs = JSON.stringify(logs);
  assert.doesNotMatch(serializedLogs, /PII question|private network details|andromeda_profile_session=|cookie/u);
});

test('client rejects unsafe request and profile cookie before network access', async () => {
  let calls = 0;
  const instance = client({ fetcher: async () => { calls += 1; return apiResponse(); } });
  await assert.rejects(
    () => instance.queryAssistant({ text: ' '.repeat(2) }),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.VALIDATION_FAILED,
  );
  await assert.rejects(
    () => instance.queryAssistant({ text: 'Question' }, 'bad cookie'),
    (error: unknown) => error instanceof AppError && error.code === ERROR_CODES.VALIDATION_FAILED,
  );
  assert.equal(calls, 0);
});
