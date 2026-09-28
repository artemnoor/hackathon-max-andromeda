import assert from 'node:assert/strict';
import { test } from 'node:test';

import { loadConfig } from '../../src/shared/config.js';
import { createLogger } from '../../src/shared/logger.js';
import { MemoryMaxTransportState } from '../../src/shared/memory-transport-state.js';
import { createMaxBot, type MaxPlatform, type MaxSdkFactory } from '../../src/max/platform/bot.js';

const startUpdate = {
  update_type: 'bot_started', timestamp: 123, chat_id: 77,
  user: { user_id: 42, first_name: 'Private' }, payload: 'opaque-start-token',
} as const;

const config = (transport: 'polling' | 'webhook' = 'polling', port = 3000) => loadConfig({
  NODE_ENV: 'test',
  MAX_BOT_TOKEN: 'test-token-value',
  MAX_TRANSPORT: transport,
  MAX_WEBHOOK_DOMAIN: 'localhost',
  MAX_WEBHOOK_PORT: String(port),
  MAX_WEBHOOK_PATH: '/max/webhook',
  MAX_WEBHOOK_SECRET: 'test-webhook-secret',
});

const factoryFor = (api: Record<string, unknown>): MaxSdkFactory => (() => ({ api } as unknown as MaxPlatform)) as MaxSdkFactory;

const waitFor = async (predicate: () => boolean, timeoutMs = 2_000): Promise<void> => {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error('Condition was not reached before timeout.');
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
};

test('polling processes updates sequentially, suppresses duplicates, and preserves marker until work succeeds', async () => {
  let calls = 0;
  let sendAttempts = 0;
  const sent: number[] = [];
  const markers: Array<number | undefined> = [];
  const api: Record<string, unknown> = {
    getMyInfo: async () => ({ user_id: 99, name: 'bot', first_name: 'bot', username: 'bot', is_bot: true, last_activity_time: 1 }),
    setMyCommands: async () => ({ commands: [] }),
    sendMessageToChat: async (chatId: number) => {
      sendAttempts += 1;
      if (sendAttempts === 1) throw new Error('temporary outbound failure');
      sent.push(chatId);
      return {};
    },
    getUpdates: async (_types: unknown, options: { marker?: number; signal?: AbortSignal }) => {
      calls += 1;
      markers.push(options.marker);
      if (calls === 1 || calls === 2) return { updates: [startUpdate], marker: 50 };
      return new Promise((_resolve, reject) => {
        options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
      });
    },
  };
  const runtime = createMaxBot({ config: config(), logger: createLogger({ level: 'silent' }), state: new MemoryMaxTransportState(), createSdkBot: factoryFor(api) });
  await runtime.start();
  await waitFor(() => calls >= 3 && sent.length === 1);
  await runtime.stop();

  assert.equal(sendAttempts, 2);
  assert.deepEqual(sent, [77]);
  assert.equal(markers[0], undefined);
  assert.equal(markers[1], undefined, 'failed work must keep the previous marker for retry');
  assert.equal(markers[2], 50, 'marker advances only after the batch succeeds');
});

test('protected bot runtime refuses local memory state', () => {
  const protectedConfig = loadConfig({
    NODE_ENV: 'production',
    MAX_BOT_TOKEN: 'test-token-value',
    MAX_TRANSPORT: 'webhook',
    MAX_WEBHOOK_DOMAIN: 'bot.example.org',
    MAX_WEBHOOK_SECRET: 'W'.repeat(40),
    REDIS_URL: 'rediss://redis.example.org:6380',
    MAX_DEEPLINK_SIGNING_KEY: Buffer.alloc(32, 7).toString('base64url'),
    MINI_APP_ORIGINS: 'https://mini.example.org',
  });
  assert.throws(() => createMaxBot({
    config: protectedConfig,
    logger: createLogger({ level: 'silent' }),
    createSdkBot: factoryFor({}),
  }), { code: 'CONFIG_INVALID' });
});

test('polling refuses MAX configuration that attempts to enable it in production', () => {
  assert.throws(() => loadConfig({
    NODE_ENV: 'production',
    MAX_BOT_TOKEN: 'test-token-value',
    MAX_TRANSPORT: 'polling',
    REDIS_URL: 'rediss://redis.example.org:6380',
    MAX_WEBHOOK_SECRET: 'W'.repeat(40),
    MAX_WEBHOOK_DOMAIN: 'bot.example.org',
    MAX_DEEPLINK_SIGNING_KEY: Buffer.alloc(32, 7).toString('base64url'),
    MINI_APP_ORIGINS: 'https://mini.example.org',
  }), { code: 'CONFIG_INVALID' });
});
