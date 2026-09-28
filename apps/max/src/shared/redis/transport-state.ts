import type { Redis } from 'ioredis';

import { AppError, ERROR_CODES } from '../errors.js';
import type { DeepLinkReference, MaxTransportState, UpdateReservation } from '../transport-state.js';
import {
  createLeaseToken,
  hashTransportKey,
  validateDeepLinkReference,
  validateLeaseToken,
  validateNonce,
  validateStateKey,
  validateTtl,
} from '../transport-state.js';

const KEY_PREFIX = 'andromeda:max:v1:';
const dependencyError = (operation: string, cause?: unknown): AppError =>
  new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation }, { cause });
const redisKey = (scope: 'window' | 'update' | 'deeplink', value: string): string => `${KEY_PREFIX}${scope}:${hashTransportKey(value)}`;

const INCREMENT_WINDOW = `
local count = redis.call('INCR', KEYS[1])
if count == 1 or redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
`;

const RESERVE_UPDATE = `
local current = redis.call('GET', KEYS[1])
if not current then
  redis.call('SET', KEYS[1], 'lease:' .. ARGV[1], 'EX', ARGV[2], 'NX')
  return {1, ARGV[1]}
end
if current == 'done' then return {2, ''} end
if string.sub(current, 1, 6) == 'lease:' then return {3, ''} end
return {4, ''}
`;

const COMPLETE_UPDATE = `
if redis.call('GET', KEYS[1]) ~= ('lease:' .. ARGV[1]) then return 0 end
redis.call('SET', KEYS[1], 'done', 'EX', ARGV[2])
return 1
`;

const RELEASE_UPDATE = `
if redis.call('GET', KEYS[1]) ~= ('lease:' .. ARGV[1]) then return 0 end
return redis.call('DEL', KEYS[1])
`;

const STORE_DEEP_LINK = `
return redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2], 'NX') and 1 or 0
`;

const CONSUME_DEEP_LINK = `
local value = redis.call('GET', KEYS[1])
if not value then return false end
redis.call('DEL', KEYS[1])
return value
`;

const parseDeepLinkReference = (value: string): DeepLinkReference => {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch (cause) {
    throw dependencyError('consume_deeplink_corrupt', cause);
  }
  try {
    return validateDeepLinkReference(parsed as DeepLinkReference);
  } catch (cause) {
    throw dependencyError('consume_deeplink_invalid', cause);
  }
};

export class RedisMaxTransportState implements MaxTransportState {
  constructor(private readonly redis: Redis) {}

  async incrementWindow(key: string, ttlSeconds: number): Promise<number> {
    const checkedKey = validateStateKey(key);
    validateTtl(ttlSeconds, 1, 86_400, 'ttlSeconds');
    try {
      const count = await this.redis.eval(INCREMENT_WINDOW, 1, redisKey('window', checkedKey), String(ttlSeconds));
      if (typeof count !== 'number' || !Number.isSafeInteger(count) || count < 1) throw dependencyError('increment_window_invalid_result');
      return count;
    } catch (cause) {
      if (cause instanceof AppError) throw cause;
      throw dependencyError('increment_window', cause);
    }
  }

  async reserveUpdate(key: string, leaseTtlSeconds: number): Promise<UpdateReservation> {
    const checkedKey = validateStateKey(key);
    validateTtl(leaseTtlSeconds, 1, 600, 'leaseTtlSeconds');
    const leaseToken = createLeaseToken();
    try {
      const result = await this.redis.eval(RESERVE_UPDATE, 1, redisKey('update', checkedKey), leaseToken, String(leaseTtlSeconds));
      if (!Array.isArray(result) || typeof result[0] !== 'number') throw dependencyError('reserve_update_invalid_result');
      if (result[0] === 1 && result[1] === leaseToken) return { status: 'reserved', leaseToken };
      if (result[0] === 2) return { status: 'processed' };
      if (result[0] === 3) return { status: 'busy' };
      throw dependencyError('reserve_update_corrupt_state');
    } catch (cause) {
      if (cause instanceof AppError) throw cause;
      throw dependencyError('reserve_update', cause);
    }
  }

  async completeUpdate(key: string, leaseToken: string, doneTtlSeconds: number): Promise<boolean> {
    const checkedKey = validateStateKey(key);
    const checkedToken = validateLeaseToken(leaseToken);
    validateTtl(doneTtlSeconds, 60, 604_800, 'doneTtlSeconds');
    try {
      return await this.redis.eval(COMPLETE_UPDATE, 1, redisKey('update', checkedKey), checkedToken, String(doneTtlSeconds)) === 1;
    } catch (cause) {
      throw dependencyError('complete_update', cause);
    }
  }

  async releaseUpdate(key: string, leaseToken: string): Promise<boolean> {
    const checkedKey = validateStateKey(key);
    const checkedToken = validateLeaseToken(leaseToken);
    try {
      return await this.redis.eval(RELEASE_UPDATE, 1, redisKey('update', checkedKey), checkedToken) === 1;
    } catch (cause) {
      throw dependencyError('release_update', cause);
    }
  }

  async storeDeepLink(nonce: string, reference: DeepLinkReference, ttlSeconds: number): Promise<boolean> {
    const checkedNonce = validateNonce(nonce);
    const checkedReference = validateDeepLinkReference(reference);
    validateTtl(ttlSeconds, 1, 86_400, 'ttlSeconds');
    try {
      const result = await this.redis.eval(
        STORE_DEEP_LINK,
        1,
        redisKey('deeplink', checkedNonce),
        JSON.stringify(checkedReference),
        String(ttlSeconds),
      );
      return result === 1;
    } catch (cause) {
      throw dependencyError('store_deeplink', cause);
    }
  }

  async consumeDeepLink(nonce: string): Promise<DeepLinkReference | undefined> {
    const checkedNonce = validateNonce(nonce);
    try {
      const value = await this.redis.eval(CONSUME_DEEP_LINK, 1, redisKey('deeplink', checkedNonce));
      if (value === null || value === undefined) return undefined;
      if (typeof value !== 'string' || Buffer.byteLength(value, 'utf8') > 512) throw dependencyError('consume_deeplink_invalid_size');
      return parseDeepLinkReference(value);
    } catch (cause) {
      if (cause instanceof AppError) throw cause;
      throw dependencyError('consume_deeplink', cause);
    }
  }
}
