import { createHash, randomBytes } from 'node:crypto';

import { AppError, ERROR_CODES } from './errors.js';

export type DeepLinkReference = Readonly<{
  version: 1;
  kind: 'start' | 'help';
  referenceId?: string;
}>;

export type UpdateReservation =
  | Readonly<{ status: 'reserved'; leaseToken: string }>
  | Readonly<{ status: 'processed' }>
  | Readonly<{ status: 'busy' }>;

export type AndromedaConversationMapping = Readonly<{
  version: 1;
  profileCookie: string;
  sessionId?: string;
  revision?: number;
  lastActivityAt: number;
}>;

export interface MaxTransportState {
  incrementWindow(key: string, ttlSeconds: number): Promise<number>;
  reserveUpdate(key: string, leaseTtlSeconds: number): Promise<UpdateReservation>;
  completeUpdate(key: string, leaseToken: string, doneTtlSeconds: number): Promise<boolean>;
  releaseUpdate(key: string, leaseToken: string): Promise<boolean>;
  storeDeepLink(nonce: string, reference: DeepLinkReference, ttlSeconds: number): Promise<boolean>;
  consumeDeepLink(nonce: string): Promise<DeepLinkReference | undefined>;
  reserveConversationTurn(userKey: string, leaseTtlSeconds: number): Promise<UpdateReservation>;
  releaseConversationTurn(userKey: string, leaseToken: string): Promise<boolean>;
  getAndromedaMapping(userKey: string): Promise<AndromedaConversationMapping | undefined>;
  saveAndromedaMapping(
    userKey: string,
    leaseToken: string,
    mapping: AndromedaConversationMapping,
    ttlSeconds: number,
  ): Promise<boolean>;
  resetAndromedaQuerySession(
    userKey: string,
    leaseToken: string,
    profileCookie: string,
    lastActivityAt: number,
    ttlSeconds: number,
  ): Promise<boolean>;
}

const VALID_KEY = /^[A-Za-z0-9._:-]{1,256}$/u;
const VALID_NONCE = /^[A-Za-z0-9_-]{16,128}$/u;
const VALID_OPAQUE_ID = /^[A-Za-z0-9_-]{22,128}$/u;
const VALID_LEASE = /^[A-Za-z0-9_-]{32,128}$/u;
const VALID_PROFILE_COOKIE = /^[A-Za-z0-9_-]{32,256}$/u;
const VALID_QUERY_SESSION = /^query-session:[0-9a-f]{32}$/u;

const validationError = (field: string): AppError =>
  new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field });

export const validateStateKey = (key: string): string => {
  if (typeof key !== 'string' || !VALID_KEY.test(key)) throw validationError('key');
  return key;
};

export const hashTransportKey = (value: string): string => createHash('sha256').update(value, 'utf8').digest('hex');

export const validateNonce = (nonce: string): string => {
  if (typeof nonce !== 'string' || !VALID_NONCE.test(nonce)) throw validationError('nonce');
  return nonce;
};

export const validateTtl = (ttlSeconds: number, min: number, max: number, field: string): number => {
  if (!Number.isSafeInteger(ttlSeconds) || ttlSeconds < min || ttlSeconds > max) throw validationError(field);
  return ttlSeconds;
};

export const validateLeaseToken = (leaseToken: string): string => {
  if (typeof leaseToken !== 'string' || !VALID_LEASE.test(leaseToken)) throw validationError('leaseToken');
  return leaseToken;
};

export const validateAndromedaConversationMapping = (
  mapping: AndromedaConversationMapping,
): AndromedaConversationMapping => {
  if (!mapping || typeof mapping !== 'object' || mapping.version !== 1
    || !VALID_PROFILE_COOKIE.test(mapping.profileCookie)
    || !Number.isSafeInteger(mapping.lastActivityAt) || mapping.lastActivityAt < 0
    || (mapping.sessionId !== undefined && !VALID_QUERY_SESSION.test(mapping.sessionId))
    || (mapping.sessionId === undefined && mapping.revision !== undefined)
    || (mapping.sessionId !== undefined
      && (!Number.isSafeInteger(mapping.revision) || (mapping.revision ?? 0) < 1))) {
    throw validationError('andromedaMapping');
  }
  const keys = Object.keys(mapping);
  if (keys.some((key) => !['version', 'profileCookie', 'sessionId', 'revision', 'lastActivityAt'].includes(key))) {
    throw validationError('andromedaMapping');
  }
  if (Buffer.byteLength(JSON.stringify(mapping), 'utf8') > 2_048) {
    throw validationError('andromedaMapping');
  }
  return Object.freeze({
    version: 1,
    profileCookie: mapping.profileCookie,
    ...(mapping.sessionId === undefined ? {} : { sessionId: mapping.sessionId }),
    ...(mapping.revision === undefined ? {} : { revision: mapping.revision }),
    lastActivityAt: mapping.lastActivityAt,
  });
};

export const validateDeepLinkReference = (reference: DeepLinkReference): DeepLinkReference => {
  if (!reference || typeof reference !== 'object' || reference.version !== 1
    || !['start', 'help'].includes(reference.kind)
    || (reference.referenceId !== undefined && !VALID_OPAQUE_ID.test(reference.referenceId))) {
    throw validationError('reference');
  }
  const normalized: DeepLinkReference = Object.freeze({
    version: 1,
    kind: reference.kind,
    ...(reference.referenceId ? { referenceId: reference.referenceId } : {}),
  });
  if (Buffer.byteLength(JSON.stringify(normalized), 'utf8') > 512) throw validationError('reference');
  return normalized;
};

export const createLeaseToken = (): string => randomBytes(24).toString('base64url');
