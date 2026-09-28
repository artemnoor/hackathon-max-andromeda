import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ConfigError } from '../../src/shared/errors.js';
import { loadConfig } from '../../src/shared/config.js';

const productionEnv = (extra: Record<string, string> = {}): NodeJS.ProcessEnv => ({
  NODE_ENV: 'production',
  ANDROMEDA_API_BASE_URL: 'https://api.example.org',
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
  assert.equal(config.andromedaApiBaseUrl, 'http://127.0.0.1:8000');
  assert.equal(config.andromedaProfileCookieName, 'andromeda_profile_session');
  assert.equal(config.andromedaApiTimeoutMs, 5_000);
  assert.equal(config.andromedaProfileTtlSeconds, 2_592_000);
  assert.equal(config.andromedaQuerySessionTtlSeconds, 86_400);
  assert.equal(config.transport, 'polling');
  assert.equal(config.isProtected, false);
  assert.equal(Buffer.from(config.maxDeepLinkSigningKey, 'base64url').length, 32);
});

test('development accepts only loopback or the compose Andromeda service and safe prefixes', () => {
  const loopback = loadConfig({ NODE_ENV: 'development', MAX_BOT_TOKEN: 'development-token' });
  const service = loadConfig({
    NODE_ENV: 'development',
    MAX_BOT_TOKEN: 'development-token',
    ANDROMEDA_API_BASE_URL: 'http://andromeda:8000/internal/api',
  });

  assert.equal(loopback.andromedaApiBaseUrl, 'http://127.0.0.1:8000');
  assert.equal(service.andromedaApiBaseUrl, 'http://andromeda:8000/internal/api');
  assert.throws(() => loadConfig({
    NODE_ENV: 'development',
    MAX_BOT_TOKEN: 'development-token',
    ANDROMEDA_API_BASE_URL: 'http://public.example.org',
  }), ConfigError);
});

test('protected environments require a public HTTPS Andromeda origin', () => {
  const config = loadConfig(productionEnv({
    ANDROMEDA_API_BASE_URL: 'https://api.example.org/andromeda',
  }));
  assert.equal(config.andromedaApiBaseUrl, 'https://api.example.org/andromeda');

  for (const value of [
    'http://api.example.org',
    'https://localhost',
    'https://127.0.0.1',
    'https://user:secret@api.example.org',
    'https://api.example.org?target=internal',
    'https://api.example.org/api/../other',
    'https://api.example.org/api/%2e%2e/other',
  ]) {
    assert.throws(() => loadConfig(productionEnv({ ANDROMEDA_API_BASE_URL: value })), ConfigError);
  }
});

test('Andromeda cookie and session limits are validated', () => {
  assert.throws(() => loadConfig({ NODE_ENV: 'test', ANDROMEDA_PROFILE_COOKIE_NAME: 'bad=name' }), ConfigError);
  assert.throws(() => loadConfig({ NODE_ENV: 'test', ANDROMEDA_API_TIMEOUT_MS: '50' }), ConfigError);
  assert.throws(() => loadConfig({ NODE_ENV: 'test', ANDROMEDA_QUERY_SESSION_TTL_SECONDS: '700000' }), ConfigError);
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
