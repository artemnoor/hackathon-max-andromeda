import { createHmac, timingSafeEqual } from 'node:crypto';

import { z } from 'zod';

import { AppError, ERROR_CODES } from '../../shared/errors.js';

const userSchema = z.object({
  id: z.number().int().positive().safe(),
  first_name: z.string().trim().min(1).max(128).optional(),
  last_name: z.string().trim().max(128).nullable().optional(),
  username: z.string().trim().max(128).nullable().optional(),
  language_code: z.string().trim().max(32).nullable().optional(),
  photo_url: z.string().trim().max(2048).nullable().optional(),
}).strict();

type InitDataPair = Readonly<{ key: string; value: string }>;
export type InitDataValidationOptions = Readonly<{
  botToken: string;
  ttlSeconds: number;
  nowSeconds?: () => number;
  futureSkewSeconds?: number;
  maxBytes?: number;
}>;

const authError = (code: typeof ERROR_CODES.AUTH_REQUIRED | typeof ERROR_CODES.AUTH_INVALID | typeof ERROR_CODES.AUTH_EXPIRED): AppError =>
  new AppError(code, 401);

const decode = (value: string): string => {
  try {
    return decodeURIComponent(value.replaceAll('+', ' '));
  } catch {
    throw authError(ERROR_CODES.AUTH_INVALID);
  }
};

const parsePairs = (raw: string): readonly InitDataPair[] => {
  if (!raw) throw authError(ERROR_CODES.AUTH_REQUIRED);
  const seen = new Set<string>();
  const pairs: InitDataPair[] = [];
  for (const part of raw.split('&')) {
    const separator = part.indexOf('=');
    if (separator <= 0) throw authError(ERROR_CODES.AUTH_INVALID);
    const key = decode(part.slice(0, separator));
    const value = decode(part.slice(separator + 1));
    if (!key || seen.has(key)) throw authError(ERROR_CODES.AUTH_INVALID);
    seen.add(key);
    pairs.push({ key, value });
  }
  return pairs;
};

const hashMatches = (expectedHex: string, actualHex: string): boolean => {
  if (!/^[a-f0-9]{64}$/iu.test(actualHex)) return false;
  const expected = Buffer.from(expectedHex, 'hex');
  const actual = Buffer.from(actualHex, 'hex');
  return expected.length === actual.length && timingSafeEqual(expected, actual);
};

/** Validates launch initData only; it intentionally returns no platform identity. */
export const validateMaxInitData = (raw: string, options: InitDataValidationOptions): void => {
  const maxBytes = options.maxBytes ?? 16 * 1024;
  if (typeof raw !== 'string' || Buffer.byteLength(raw, 'utf8') === 0) throw authError(ERROR_CODES.AUTH_REQUIRED);
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || Buffer.byteLength(raw, 'utf8') > maxBytes) throw authError(ERROR_CODES.AUTH_INVALID);
  if (!options.botToken || !Number.isSafeInteger(options.ttlSeconds) || options.ttlSeconds < 1) {
    throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'MAX_INIT_DATA_TTL_SECONDS' });
  }

  const pairs = parsePairs(raw);
  const values = new Map(pairs.map((pair) => [pair.key, pair.value]));
  const actualHash = values.get('hash');
  const authDateRaw = values.get('auth_date');
  const userRaw = values.get('user');
  if (!actualHash || !authDateRaw || !userRaw) throw authError(ERROR_CODES.AUTH_REQUIRED);
  if (!/^\d{1,12}$/u.test(authDateRaw)) throw authError(ERROR_CODES.AUTH_INVALID);

  const authDate = Number(authDateRaw);
  const now = options.nowSeconds?.() ?? Math.floor(Date.now() / 1000);
  const futureSkewSeconds = options.futureSkewSeconds ?? 60;
  if (!Number.isSafeInteger(now) || now <= 0 || !Number.isSafeInteger(futureSkewSeconds) || futureSkewSeconds < 0) {
    throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500);
  }
  if (authDate > now + futureSkewSeconds) throw authError(ERROR_CODES.AUTH_INVALID);
  if (now - authDate > options.ttlSeconds) throw authError(ERROR_CODES.AUTH_EXPIRED);

  const checkString = pairs
    .filter((pair) => pair.key !== 'hash')
    .sort((left, right) => left.key < right.key ? -1 : left.key > right.key ? 1 : 0)
    .map((pair) => `${pair.key}=${pair.value}`)
    .join('\n');
  const secret = createHmac('sha256', 'WebAppData').update(options.botToken, 'utf8').digest();
  const expectedHash = createHmac('sha256', secret).update(checkString, 'utf8').digest('hex');
  if (!hashMatches(expectedHash, actualHash.toLowerCase())) throw authError(ERROR_CODES.AUTH_INVALID);

  let user: unknown;
  try {
    user = JSON.parse(userRaw) as unknown;
  } catch {
    throw authError(ERROR_CODES.AUTH_INVALID);
  }
  if (!userSchema.safeParse(user).success) throw authError(ERROR_CODES.AUTH_INVALID);
};
