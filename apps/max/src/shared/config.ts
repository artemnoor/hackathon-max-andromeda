import { randomBytes } from 'node:crypto';

import { z } from 'zod';

import { ConfigError } from './errors.js';
import { isAllowedMaxApiUrl, isProductionOrigin, isPublicHostname, normalizeOrigins, parseHttpOrigin, isSafeHostname } from './url-policy.js';

export type NodeEnvironment = 'development' | 'test' | 'staging' | 'production';
export type MaxTransport = 'polling' | 'webhook';
export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'fatal' | 'silent';

export type AppConfig = Readonly<{
  nodeEnv: NodeEnvironment;
  isProduction: boolean;
  isProtected: boolean;
  maxBotToken: string;
  maxApiBaseUrl: string;
  transport: MaxTransport;
  webhookDomain: string;
  webhookPort: number;
  webhookPath: string;
  webhookSecret: string;
  miniAppPort: number;
  miniAppOrigins: readonly string[];
  maxInitDataTtlSeconds: number;
  maxDeepLinkSigningKey: string;
  redisUrl?: string;
  logLevel: LogLevel;
}>;

const parseNumber = (fallback: number) => (value: unknown): unknown => {
  if (value === undefined || value === '') return fallback;
  if (typeof value === 'number') return value;
  if (typeof value !== 'string') return value;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : value;
};

const parseOrigins = (value: unknown): unknown => {
  if (value === undefined || value === '') return ['http://localhost:8787'];
  if (Array.isArray(value)) return value;
  return typeof value === 'string' ? value.split(',').map((item) => item.trim()).filter(Boolean) : value;
};

const optionalTrimmedString = z.preprocess(
  (value) => typeof value === 'string' && value.trim() === '' ? undefined : value,
  z.string().trim().min(1).optional(),
);

const rawEnvironmentSchema = z.object({
  NODE_ENV: z.preprocess((value) => typeof value === 'string' ? value.trim().toLowerCase() : value,
    z.enum(['development', 'test', 'staging', 'production']).default('development')),
  MAX_BOT_TOKEN: z.string().trim().default(''),
  MAX_API_BASE_URL: z.string().trim().url().default('https://platform-api2.max.ru'),
  MAX_TRANSPORT: z.preprocess((value) => typeof value === 'string' ? value.trim().toLowerCase() : value,
    z.enum(['polling', 'webhook']).default('polling')),
  MAX_WEBHOOK_DOMAIN: z.string().trim().default(''),
  MAX_WEBHOOK_PORT: z.preprocess(parseNumber(3000), z.number().int().min(1).max(65535)),
  MAX_WEBHOOK_PATH: z.string().trim().default('/max/webhook'),
  MAX_WEBHOOK_SECRET: z.string().trim().default(''),
  MINI_APP_PORT: z.preprocess(parseNumber(8787), z.number().int().min(1).max(65535)),
  MINI_APP_ORIGINS: z.preprocess(parseOrigins, z.array(z.string().trim().url()).min(1)),
  MAX_INIT_DATA_TTL_SECONDS: z.preprocess(parseNumber(900), z.number().int().min(60).max(3600)),
  MAX_DEEPLINK_SIGNING_KEY: z.string().trim().default(''),
  REDIS_URL: optionalTrimmedString,
  LOG_LEVEL: z.preprocess((value) => typeof value === 'string' ? value.trim().toLowerCase() : value,
    z.enum(['debug', 'info', 'warn', 'error', 'fatal', 'silent']).default('info')),
});

type RawEnvironment = z.infer<typeof rawEnvironmentSchema>;

const fail = (key: string, environment: NodeEnvironment, reason: string): never => {
  throw new ConfigError(key, environment, reason);
};

const validDeepLinkKey = (value: string): boolean => {
  try {
    return Buffer.from(value, 'base64url').length === 32 && Buffer.from(value, 'base64url').toString('base64url') === value;
  } catch {
    return false;
  }
};

export const loadConfig = (environment: NodeJS.ProcessEnv = process.env): AppConfig => {
  const parsed = rawEnvironmentSchema.safeParse(environment);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    throw new ConfigError(String(issue?.path[0] ?? 'environment'), String(environment['NODE_ENV'] ?? 'unknown'), issue?.message ?? 'invalid value');
  }

  const raw: RawEnvironment = parsed.data;
  const nodeEnv = raw.NODE_ENV;
  const isProtected = nodeEnv === 'staging' || nodeEnv === 'production';

  if (nodeEnv !== 'test' && raw.MAX_BOT_TOKEN.length < 12) fail('MAX_BOT_TOKEN', nodeEnv, 'is required outside test and must be non-empty');
  if (!isAllowedMaxApiUrl(raw.MAX_API_BASE_URL)) fail('MAX_API_BASE_URL', nodeEnv, 'must use the official MAX HTTPS API origin');
  if (raw.MAX_WEBHOOK_DOMAIN && !isSafeHostname(raw.MAX_WEBHOOK_DOMAIN)) fail('MAX_WEBHOOK_DOMAIN', nodeEnv, 'must be a hostname without scheme, path, port or credentials');
  if (isProtected && raw.MAX_WEBHOOK_DOMAIN && !isPublicHostname(raw.MAX_WEBHOOK_DOMAIN)) fail('MAX_WEBHOOK_DOMAIN', nodeEnv, 'protected environments require a public DNS hostname');
  if (!/^\/[A-Za-z0-9][A-Za-z0-9/_-]{0,127}$/u.test(raw.MAX_WEBHOOK_PATH) || raw.MAX_WEBHOOK_PATH.includes('//') || raw.MAX_WEBHOOK_PATH.includes('..')) {
    fail('MAX_WEBHOOK_PATH', nodeEnv, 'must be a normalized absolute path');
  }
  if (raw.MAX_WEBHOOK_SECRET && !/^[A-Za-z0-9_-]{5,256}$/u.test(raw.MAX_WEBHOOK_SECRET)) {
    fail('MAX_WEBHOOK_SECRET', nodeEnv, 'must contain 5-256 URL-safe characters');
  }
  if (raw.MAX_TRANSPORT === 'webhook' && (!raw.MAX_WEBHOOK_DOMAIN || !raw.MAX_WEBHOOK_SECRET)) {
    fail('MAX_TRANSPORT', nodeEnv, 'webhook requires MAX_WEBHOOK_DOMAIN and MAX_WEBHOOK_SECRET');
  }
  for (const origin of raw.MINI_APP_ORIGINS) {
    if (!parseHttpOrigin(origin)) fail('MINI_APP_ORIGINS', nodeEnv, 'must contain origins without paths, credentials, query or fragment');
    if (isProtected && !isProductionOrigin(origin)) fail('MINI_APP_ORIGINS', nodeEnv, 'protected environments require public HTTPS origins');
  }
  if (raw.REDIS_URL) {
    let redisUrl: URL;
    try {
      redisUrl = new URL(raw.REDIS_URL);
    } catch {
      return fail('REDIS_URL', nodeEnv, 'must be a valid Redis URL');
    }
    if (!['redis:', 'rediss:'].includes(redisUrl.protocol) || !redisUrl.hostname || redisUrl.hash || redisUrl.search) {
      fail('REDIS_URL', nodeEnv, 'must use redis or rediss without query or fragment');
    }
    if (isProtected && redisUrl.protocol !== 'rediss:') fail('REDIS_URL', nodeEnv, 'protected environments require verified Redis TLS');
  }
  if (isProtected) {
    if (raw.MAX_TRANSPORT !== 'webhook') fail('MAX_TRANSPORT', nodeEnv, 'must be webhook in protected environments');
    if (!raw.REDIS_URL) fail('REDIS_URL', nodeEnv, 'is required in protected environments');
    if (raw.MAX_WEBHOOK_SECRET.length < 32) fail('MAX_WEBHOOK_SECRET', nodeEnv, 'must contain at least 32 URL-safe characters in protected environments');
    if (!validDeepLinkKey(raw.MAX_DEEPLINK_SIGNING_KEY)) fail('MAX_DEEPLINK_SIGNING_KEY', nodeEnv, 'must encode exactly 32 random bytes as base64url');
  }

  return Object.freeze({
    nodeEnv,
    isProduction: nodeEnv === 'production',
    isProtected,
    maxBotToken: raw.MAX_BOT_TOKEN,
    maxApiBaseUrl: raw.MAX_API_BASE_URL,
    transport: raw.MAX_TRANSPORT,
    webhookDomain: raw.MAX_WEBHOOK_DOMAIN,
    webhookPort: raw.MAX_WEBHOOK_PORT,
    webhookPath: raw.MAX_WEBHOOK_PATH,
    webhookSecret: raw.MAX_WEBHOOK_SECRET,
    miniAppPort: raw.MINI_APP_PORT,
    miniAppOrigins: Object.freeze(normalizeOrigins(raw.MINI_APP_ORIGINS)),
    maxInitDataTtlSeconds: raw.MAX_INIT_DATA_TTL_SECONDS,
    maxDeepLinkSigningKey: raw.MAX_DEEPLINK_SIGNING_KEY || randomBytes(32).toString('base64url'),
    ...(raw.REDIS_URL ? { redisUrl: raw.REDIS_URL } : {}),
    logLevel: raw.LOG_LEVEL,
  });
};
