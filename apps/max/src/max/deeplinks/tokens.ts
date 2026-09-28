import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

import { z } from 'zod';

import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { MaxTransportState, DeepLinkReference } from '../../shared/transport-state.js';
import { validateDeepLinkReference } from '../../shared/transport-state.js';

const DEFAULT_TTL_SECONDS = 300;
const MAX_TTL_SECONDS = 86_400;
const MAX_TOKEN_BYTES = 512;
const PURPOSE = /^[a-z][a-z0-9_-]{0,31}$/u;
const NONCE = /^[A-Za-z0-9_-]{32}$/u;
const BINDING = /^[A-Za-z0-9_-]{43}$/u;

const payloadSchema = z.object({
  v: z.literal(1),
  p: z.string().regex(PURPOSE),
  n: z.string().regex(NONCE),
  iat: z.number().int().positive().safe(),
  exp: z.number().int().positive().safe(),
  b: z.string().regex(BINDING).optional(),
}).strict();

type TokenPayload = z.infer<typeof payloadSchema>;
export type DeepLinkIssueRequest = Readonly<{
  purpose: string;
  reference: DeepLinkReference;
  userId?: number;
  ttlSeconds?: number;
}>;
export type DeepLinkConsumeRequest = Readonly<{
  purpose: string;
  userId?: number;
}>;

export type DeepLinkTokenService = Readonly<{
  issue(request: DeepLinkIssueRequest): Promise<string>;
  consume(token: string, request: DeepLinkConsumeRequest): Promise<DeepLinkReference>;
}>;

export type DeepLinkTokenOptions = Readonly<{
  signingKey: string;
  state: MaxTransportState;
  nowSeconds?: () => number;
  random?: (size: number) => Buffer;
}>;

const authInvalid = (): AppError => new AppError(ERROR_CODES.AUTH_INVALID, 401);
const authExpired = (): AppError => new AppError(ERROR_CODES.AUTH_EXPIRED, 401);

const decodeSigningKey = (value: string): Buffer => {
  try {
    const decoded = Buffer.from(value, 'base64url');
    if (decoded.length !== 32 || decoded.toString('base64url') !== value) throw authInvalid();
    return decoded;
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw authInvalid();
  }
};

const hmac = (key: Buffer, value: string): Buffer => createHmac('sha256', key).update(value, 'utf8').digest();
const safeEqual = (left: Buffer, right: Buffer): boolean => left.length === right.length && timingSafeEqual(left, right);
const validUserId = (userId: number | undefined): userId is number => userId !== undefined
  && Number.isSafeInteger(userId) && userId > 0;

const bindingFor = (key: Buffer, userId: number): string =>
  hmac(key, `max-deeplink-user:v1:${userId}`).toString('base64url');

const sign = (key: Buffer, encoded: string): string => hmac(key, `max-deeplink:v1:${encoded}`).toString('base64url');

const decodePayload = (encoded: string): TokenPayload => {
  let bytes: Buffer;
  try {
    bytes = Buffer.from(encoded, 'base64url');
    if (bytes.toString('base64url') !== encoded || bytes.byteLength > MAX_TOKEN_BYTES) throw authInvalid();
    const parsed: unknown = JSON.parse(bytes.toString('utf8'));
    const result = payloadSchema.safeParse(parsed);
    if (!result.success) throw authInvalid();
    return result.data;
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw authInvalid();
  }
};

export const createDeepLinkTokenService = (options: DeepLinkTokenOptions): DeepLinkTokenService => {
  const key = decodeSigningKey(options.signingKey);
  const nowSeconds = options.nowSeconds ?? (() => Math.floor(Date.now() / 1000));
  const random = options.random ?? randomBytes;

  return Object.freeze({
    async issue(request): Promise<string> {
      if (!PURPOSE.test(request.purpose)) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'purpose' });
      const reference = validateDeepLinkReference(request.reference);
      if (request.userId !== undefined && !validUserId(request.userId)) {
        throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'userId' });
      }
      const ttlSeconds = request.ttlSeconds ?? DEFAULT_TTL_SECONDS;
      if (!Number.isSafeInteger(ttlSeconds) || ttlSeconds < 1 || ttlSeconds > MAX_TTL_SECONDS) {
        throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'ttlSeconds' });
      }
      const issuedAt = nowSeconds();
      if (!Number.isSafeInteger(issuedAt) || issuedAt <= 0) throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500);

      for (let attempt = 0; attempt < 3; attempt += 1) {
        const nonce = random(24).toString('base64url');
        if (!NONCE.test(nonce)) throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'deeplink_nonce' });
        const payload: TokenPayload = {
          v: 1,
          p: request.purpose,
          n: nonce,
          iat: issuedAt,
          exp: issuedAt + ttlSeconds,
          ...(request.userId === undefined ? {} : { b: bindingFor(key, request.userId) }),
        };
        const encoded = Buffer.from(JSON.stringify(payload), 'utf8').toString('base64url');
        const token = `v1.${encoded}.${sign(key, encoded)}`;
        if (Buffer.byteLength(token, 'utf8') > MAX_TOKEN_BYTES) {
          throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'token' });
        }
        if (await options.state.storeDeepLink(nonce, reference, ttlSeconds)) return token;
      }
      throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'deeplink_nonce_collision' });
    },

    async consume(token, request): Promise<DeepLinkReference> {
      if (typeof token !== 'string' || Buffer.byteLength(token, 'utf8') > MAX_TOKEN_BYTES
        || typeof request.purpose !== 'string' || !PURPOSE.test(request.purpose)) throw authInvalid();
      if (request.userId !== undefined && !validUserId(request.userId)) throw authInvalid();
      const parts = token.split('.');
      if (parts.length !== 3 || parts[0] !== 'v1' || !parts[1] || !parts[2] || !BINDING.test(parts[2])) throw authInvalid();

      const encoded = parts[1];
      const expected = Buffer.from(sign(key, encoded), 'base64url');
      const actual = Buffer.from(parts[2], 'base64url');
      if (!safeEqual(expected, actual)) throw authInvalid();
      const payload = decodePayload(encoded);
      const now = nowSeconds();
      if (!Number.isSafeInteger(now) || now <= 0 || payload.iat > now + 30 || payload.exp <= payload.iat
        || payload.exp - payload.iat > MAX_TTL_SECONDS || payload.exp > now + MAX_TTL_SECONDS) throw authInvalid();
      if (payload.exp <= now) throw authExpired();
      if (payload.p !== request.purpose) throw authInvalid();
      if (payload.b !== undefined) {
        if (request.userId === undefined || !safeEqual(Buffer.from(payload.b), Buffer.from(bindingFor(key, request.userId)))) throw authInvalid();
      }

      const reference = await options.state.consumeDeepLink(payload.n);
      if (!reference) throw authExpired();
      return validateDeepLinkReference(reference);
    },
  });
};
