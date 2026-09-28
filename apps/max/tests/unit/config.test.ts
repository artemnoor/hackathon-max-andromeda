import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ConfigError } from '../../src/shared/errors.js';
import { loadConfig } from '../../src/shared/config.js';

const productionEnv = (extra: Record<string, string> = {}): NodeJS.ProcessEnv => ({
  NODE_ENV: 'production',
  MAX_BOT_TOKEN: 'max-bot-token-for-tests',
  MAX_TRANSPORT: 'webhook',
  MAX_WEBHOOK_DOMAIN: 'bot.example.org',
  MAX_WEBHOOK_SECRET: 'a'.repeat(40),
  MINI_APP_ORIGINS: 'https://mini.example.org',
  REDIS_URL: 'rediss://user:secret@redis.example.org:6380/0',
  MAX_DEEPLINK_SIGNING_KEY: Buffer.alloc(32, 7).toString('base64url'),
  ...extra,
});

test('test config accepts empty MAX token and defaults to official API host', () => {
  const config = loadConfig({ NODE_ENV: 'test' });
  assert.equal(config.maxApiBaseUrl, 'https://platform-api2.max.ru');
  assert.equal(config.transport, 'polling');
  assert.equal(config.isProtected, false);
  assert.equal(Buffer.from(config.maxDeepLinkSigningKey, 'base64url').length, 32);
});

test('production config requires webhook, TLS Redis and strong independent deep-link key', () => {
  const config = loadConfig(productionEnv());
  assert.equal(config.transport, 'webhook');
  assert.equal(config.redisUrl?.startsWith('rediss://'), true);
  assert.equal(config.miniAppOrigins[0], 'https://mini.example.org');
  assert.equal(config.isProduction, true);
});

test('production refuses polling and missing transport settings', () => {
  assert.throws(() => loadConfig(productionEnv({ MAX_TRANSPORT: 'polling' })), ConfigError);
  assert.throws(() => loadConfig(productionEnv({ REDIS_URL: '' })), ConfigError);
  assert.throws(() => loadConfig(productionEnv({ MAX_WEBHOOK_SECRET: 'short' })), ConfigError);
  assert.throws(() => loadConfig(productionEnv({ MAX_DEEPLINK_SIGNING_KEY: '' })), ConfigError);
});

test('production refuses plaintext Redis, noncanonical MAX host and insecure origins', () => {
  assert.throws(() => loadConfig(productionEnv({ REDIS_URL: 'redis://redis.example.org:6379/0' })), ConfigError);
  assert.throws(() => loadConfig(productionEnv({ MAX_API_BASE_URL: 'https://evil.example/' })), ConfigError);
  assert.throws(() => loadConfig(productionEnv({ MINI_APP_ORIGINS: 'http://mini.example.org' })), ConfigError);
});

test('webhook path and host reject path traversal and malformed values', () => {
  assert.throws(() => loadConfig({ NODE_ENV: 'test', MAX_WEBHOOK_PATH: '/a/../b' }), ConfigError);
  assert.throws(() => loadConfig({ NODE_ENV: 'test', MAX_WEBHOOK_DOMAIN: 'https://example.org/path' }), ConfigError);
});

test('old unrelated environment variables are ignored rather than becoming runtime config', () => {
  const config = loadConfig({ NODE_ENV: 'test', UNRELATED_FEATURE_FLAG: 'true' });
  assert.equal('unrelatedFeatureFlag' in config, false);
});
