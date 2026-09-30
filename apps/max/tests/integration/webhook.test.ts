import assert from 'node:assert/strict';
import { createServer as createHttpServer } from 'node:http';
import { createServer as createNetServer, type AddressInfo } from 'node:net';
import { test } from 'node:test';

import { AppError, ERROR_CODES } from '../../src/shared/errors.js';
import { createLogger } from '../../src/shared/logger.js';
import { MemoryMaxTransportState } from '../../src/shared/memory-transport-state.js';
import { createMaxBot, type MaxPlatform, type MaxSdkFactory } from '../../src/max/platform/bot.js';
import { withWebhookGuard } from '../../src/max/webhook/guard.js';
import { loadConfig } from '../../src/shared/config.js';

const portAvailable = async (): Promise<number> => {
  const server = createNetServer();
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve());
  });
  const port = (server.address() as AddressInfo).port;
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
};

const createWebhookConfig = (port: number) => loadConfig({
  NODE_ENV: 'test',
  MAX_BOT_TOKEN: 'test-token-value',
  MAX_TRANSPORT: 'webhook',
  MAX_WEBHOOK_DOMAIN: 'localhost',
  MAX_WEBHOOK_PORT: String(port),
  MAX_WEBHOOK_PATH: '/max/webhook',
  MAX_WEBHOOK_SECRET: 'integration-webhook-secret',
});

const factoryFor = (api: Record<string, unknown>): MaxSdkFactory => (() => ({ api } as unknown as MaxPlatform)) as MaxSdkFactory;
const headers = { 'content-type': 'application/json', 'x-max-bot-api-secret': 'integration-webhook-secret' };
const body = JSON.stringify({
  update_type: 'message_created', timestamp: 1700000000,
  message: { sender: { user_id: 42 }, recipient: { chat_id: 77 }, body: { mid: 'message-1', text: 'hello' } },
});

test('webhook guard checks path, method, secret, content type, body cap, and awaits processing before ACK', async (t) => {
  let received = 0;
  const server = createHttpServer(withWebhookGuard({
    path: '/max/webhook',
    secret: 'integration-webhook-secret',
    onBody: async (payload) => {
      received = payload.byteLength;
      if (payload.toString('utf8') === 'fail') throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
    },
  }));
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;
  t.after(async () => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())));
  const origin = `http://127.0.0.1:${port}`;

  const callbackStatus = (await fetch(`${origin}/wrong`, { method: 'POST', headers, body: '{}' })).status;
  assert.equal(callbackStatus, 404);
  assert.equal((await fetch(`${origin}/max/webhook`, { method: 'POST', headers: { ...headers, 'x-max-bot-api-secret': 'wrong-secret' }, body: '{}' })).status, 404);
  assert.equal((await fetch(`${origin}/max/webhook`, { method: 'GET', headers })).status, 404);
  assert.equal((await fetch(`${origin}/max/webhook`, { method: 'POST', headers: { ...headers, 'content-type': 'text/plain' }, body: '{}' })).status, 415);
  assert.equal((await fetch(`${origin}/max/webhook`, { method: 'POST', headers, body: 'fail' })).status, 503);

  const oversized = 'x'.repeat(1_048_577);
  assert.equal((await fetch(`${origin}/max/webhook`, { method: 'POST', headers, body: oversized })).status, 413);
  assert.equal((await fetch(`${origin}/max/webhook`, { method: 'POST', headers, body })).status, 200);
  assert.equal(received, Buffer.byteLength(body));
});

test('MAX webhook runtime returns success only after processing and retains remote subscription on stop', async (t) => {
  const port = await portAvailable();
  const sent: number[] = [];
  const subscriptions = [{ url: 'https://localhost/max/webhook' }];
  let subscribes = 0;
  let unsubscribes = 0;
  const api: Record<string, unknown> = {
    getMyInfo: async () => ({ user_id: 99, name: 'bot', first_name: 'bot', username: 'bot', is_bot: true, last_activity_time: 1 }),
    setMyCommands: async () => ({ commands: [] }),
    getSubscriptions: async () => subscriptions,
    subscribe: async (url: string) => { subscribes += 1; subscriptions.push({ url }); return { success: true }; },
    unsubscribe: async () => { unsubscribes += 1; return { success: true }; },
    sendMessageToChat: async (chatId: number) => { sent.push(chatId); return {}; },
  };
  const runtime = createMaxBot({
    config: createWebhookConfig(port),
    logger: createLogger({ level: 'silent' }),
    state: new MemoryMaxTransportState(),
    createSdkBot: factoryFor(api),
  });
  await runtime.start();
  t.after(() => runtime.stop());

  const url = `http://127.0.0.1:${port}/max/webhook`;
  const first = await fetch(url, { method: 'POST', headers, body });
  assert.equal(first.status, 200);
  const duplicate = await fetch(url, { method: 'POST', headers, body });
  assert.equal(duplicate.status, 200);
  assert.deepEqual(sent, [77]);
  assert.equal(subscribes, 0, 'an existing exact webhook is reused');

  await runtime.stop();
  assert.equal(unsubscribes, 0, 'shutdown must not remove an externally owned MAX subscription');
});

test('MAX platform adapter converts message, callback, and website buttons into a native keyboard attachment', async (t) => {
  const port = await portAvailable();
  let delivered: unknown[] | undefined;
  const api: Record<string, unknown> = {
    getMyInfo: async () => ({ user_id: 99, name: 'bot', first_name: 'bot', username: 'bot', is_bot: true, last_activity_time: 1 }),
    setMyCommands: async () => ({ commands: [] }),
    getSubscriptions: async () => [{ url: 'https://localhost/max/webhook' }],
    subscribe: async () => ({ success: true }),
    sendMessageToChat: async (...args: unknown[]) => { delivered = args; return {}; },
  };
  const runtime = createMaxBot({
    config: createWebhookConfig(port),
    logger: createLogger({ level: 'silent' }),
    state: new MemoryMaxTransportState(),
    createSdkBot: factoryFor(api),
    handleUpdate: async () => ({
      kind: 'chat',
      text: 'Выберите уточнение',
      buttons: [[
        { text: '2028' },
        { text: 'Сравнить программы', callbackPayload: 'assistant:compare' },
        { text: 'Открыть каталог', linkUrl: 'https://mini.example.org' },
      ]],
    }),
  });
  await runtime.start();
  t.after(() => runtime.stop());

  const started = JSON.stringify({
    update_type: 'bot_started',
    timestamp: 1_700_000_002,
    chat_id: 77,
    user: { user_id: 42 },
  });
  const result = await fetch('http://127.0.0.1:' + port + '/max/webhook', {
    method: 'POST',
    headers,
    body: started,
  });
  assert.equal(result.status, 200);
  assert.deepEqual(delivered, [
    77,
    'Выберите уточнение',
    {
      attachments: [{
        type: 'inline_keyboard',
        payload: {
          buttons: [[
            { type: 'message', text: '2028' },
            { type: 'callback', text: 'Сравнить программы', payload: 'assistant:compare' },
            { type: 'link', text: 'Открыть каталог', url: 'https://mini.example.org' },
          ]],
        },
      }],
    },
  ]);
});

test('MAX attachment rejection retries the user reply as plain text', async (t) => {
  const port = await portAvailable();
  const attempts: unknown[][] = [];
  const api: Record<string, unknown> = {
    getMyInfo: async () => ({ user_id: 99, name: 'bot', first_name: 'bot', username: 'bot', is_bot: true, last_activity_time: 1 }),
    setMyCommands: async () => ({ commands: [] }),
    getSubscriptions: async () => [{ url: 'https://localhost/max/webhook' }],
    sendMessageToChat: async (...args: unknown[]) => {
      attempts.push(args);
      if (args[2]) throw Object.assign(new Error('MAX rejected attachment'), { status: 400 });
      return {};
    },
  };
  const runtime = createMaxBot({
    config: createWebhookConfig(port),
    logger: createLogger({ level: 'silent' }),
    state: new MemoryMaxTransportState(),
    createSdkBot: factoryFor(api),
    handleUpdate: async () => ({
      kind: 'chat', text: 'Andromeda запущена',
      buttons: [[{ text: 'Открыть каталог', webAppUrl: 'https://mini.example.org' }]],
    }),
  });
  await runtime.start();
  t.after(() => runtime.stop());

  const result = await fetch(`http://127.0.0.1:${port}/max/webhook`, { method: 'POST', headers, body });

  assert.equal(result.status, 200);
  assert.equal(attempts.length, 2);
  assert.match(String(attempts[1]?.[1]), /Andromeda запущена/u);
  assert.equal(attempts[1]?.[2], undefined);
});

test('MAX acknowledges response-action callbacks and delivers the assistant follow-up', async (t) => {
  const port = await portAvailable();
  const delivered: unknown[][] = [];
  const api: Record<string, unknown> = {
    getMyInfo: async () => ({ user_id: 99, name: 'bot', first_name: 'bot', username: 'bot', is_bot: true, last_activity_time: 1 }),
    setMyCommands: async () => ({ commands: [] }),
    getSubscriptions: async () => [{ url: 'https://localhost/max/webhook' }],
    answerOnCallback: async (...args: unknown[]) => { delivered.push(['callback', ...args]); return {}; },
    sendMessageToChat: async (...args: unknown[]) => { delivered.push(['chat', ...args]); return {}; },
  };
  const runtime = createMaxBot({
    config: createWebhookConfig(port),
    logger: createLogger({ level: 'silent' }),
    state: new MemoryMaxTransportState(),
    createSdkBot: factoryFor(api),
    handleUpdate: async (update) => {
      assert.equal(update.kind, 'message_callback');
      if (update.kind !== 'message_callback' || !update.callbackId) assert.fail('expected a valid callback update');
      return {
        kind: 'callback',
        callbackId: update.callbackId,
        text: 'Готово.',
        messages: [{ text: 'Сравнение готово' }],
      };
    },
  });
  await runtime.start();
  t.after(() => runtime.stop());

  const callbackBody = JSON.stringify({
    update_type: 'message_callback',
    timestamp: 1_700_000_003,
    chat_id: 77,
    callback: { callback_id: 'callback-2', payload: 'assistant:compare', user: { user_id: 42 } },
  });
  const result = await fetch(`http://127.0.0.1:${port}/max/webhook`, {
    method: 'POST',
    headers,
    body: callbackBody,
  });

  assert.equal(result.status, 200);
  assert.deepEqual(delivered, [
    ['callback', 'callback-2', { message: { text: 'Готово.' } }],
    ['chat', 77, 'Сравнение готово', undefined],
  ]);
});

test('webhook Redis outage fails closed with retryable response and does not run handler', async (t) => {
  const port = await portAvailable();
  let handlerCalls = 0;
  const unavailableState = {
    incrementWindow: async () => { throw new Error('unavailable'); },
    reserveUpdate: async () => { throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503); },
    completeUpdate: async () => false,
    releaseUpdate: async () => false,
    storeDeepLink: async () => false,
    consumeDeepLink: async () => undefined,
    reserveConversationTurn: async () => { throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503); },
    releaseConversationTurn: async () => false,
    getAndromedaMapping: async () => undefined,
    saveAndromedaMapping: async () => false,
    resetAndromedaQuerySession: async () => false,
  };
  const api: Record<string, unknown> = {
    getMyInfo: async () => ({ user_id: 99, name: 'bot', first_name: 'bot', username: 'bot', is_bot: true, last_activity_time: 1 }),
    setMyCommands: async () => ({ commands: [] }),
    getSubscriptions: async () => [],
    subscribe: async () => ({ success: true }),
  };
  const runtime = createMaxBot({
    config: createWebhookConfig(port),
    logger: createLogger({ level: 'silent' }),
    state: unavailableState,
    handleUpdate: async () => { handlerCalls += 1; return undefined; },
    createSdkBot: factoryFor(api),
  });
  await runtime.start();
  t.after(() => runtime.stop());

  const response = await fetch(`http://127.0.0.1:${port}/max/webhook`, { method: 'POST', headers, body });
  assert.equal(response.status, 503);
  assert.equal(handlerCalls, 0);
});

test('conflicting Webhook subscription aborts startup without deleting or changing it', async () => {
  const port = await portAvailable();
  let subscribes = 0;
  let unsubscribes = 0;
  const api: Record<string, unknown> = {
    getMyInfo: async () => ({ user_id: 99, name: 'bot', first_name: 'bot', username: 'bot', is_bot: true, last_activity_time: 1 }),
    setMyCommands: async () => ({ commands: [] }),
    getSubscriptions: async () => [{ url: 'https://other.example.org/max/webhook' }],
    subscribe: async () => { subscribes += 1; return { success: true }; },
    unsubscribe: async () => { unsubscribes += 1; return { success: true }; },
  };
  const runtime = createMaxBot({
    config: createWebhookConfig(port),
    logger: createLogger({ level: 'silent' }),
    state: new MemoryMaxTransportState(),
    createSdkBot: factoryFor(api),
  });
  await assert.rejects(() => runtime.start(), { code: 'CONFIG_INVALID' });
  await runtime.stop();
  assert.equal(subscribes, 0);
  assert.equal(unsubscribes, 0);
});
