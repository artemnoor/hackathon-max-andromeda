import { Redis } from 'ioredis';

import type { AppConfig } from '../config.js';
import { AppError, ConfigError, ERROR_CODES } from '../errors.js';
import type { Logger } from '../logger.js';

export const createRedisClient = (config: Pick<AppConfig, 'redisUrl' | 'isProtected'>, logger: Logger): Redis => {
  const redisUrl = config.redisUrl;
  if (!redisUrl) throw new ConfigError('REDIS_URL', config.isProtected ? 'protected' : 'development', 'is required for Redis transport state');

  let parsed: URL;
  try {
    parsed = new URL(redisUrl);
  } catch {
    throw new ConfigError('REDIS_URL', config.isProtected ? 'protected' : 'development', 'must be a valid Redis URL');
  }
  if (!['redis:', 'rediss:'].includes(parsed.protocol) || !parsed.hostname || parsed.search || parsed.hash
    || (config.isProtected && parsed.protocol !== 'rediss:')) {
    throw new ConfigError('REDIS_URL', config.isProtected ? 'protected' : 'development', 'has an unsupported transport policy');
  }

  const client = new Redis(redisUrl, {
    lazyConnect: true,
    connectTimeout: 5_000,
    commandTimeout: 5_000,
    enableReadyCheck: true,
    maxRetriesPerRequest: 1,
    enableOfflineQueue: false,
    autoResubscribe: false,
    autoResendUnfulfilledCommands: false,
    keepAlive: 10_000,
    retryStrategy(attempt) {
      return attempt <= 3 ? Math.min(attempt * 250, 750) : null;
    },
    ...(parsed.protocol === 'rediss:' ? { tls: { rejectUnauthorized: true, minVersion: 'TLSv1.2' as const } } : {}),
  });
  client.on('error', () => logger.warn({ event: 'redis_connection_error' }));
  return client;
};

export const connectRedisClient = async (client: Redis): Promise<void> => {
  try {
    if (client.status === 'wait') await client.connect();
    if (client.status !== 'ready') throw new Error('Redis is not ready');
  } catch (cause) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'redis_connect' }, { cause });
  }
};

export const closeRedisClient = async (client: Redis): Promise<void> => {
  if (client.status === 'end') return;
  if (client.status !== 'ready') {
    client.disconnect();
    return;
  }
  try {
    await client.quit();
  } catch {
    client.disconnect();
  }
};
