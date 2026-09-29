import { createHash } from 'node:crypto';

import { z } from 'zod';

import { AppError, ERROR_CODES } from '../../shared/errors.js';

const MAX_TEXT_BYTES = 8 * 1024;
const MAX_CALLBACK_BYTES = 1024;
const MAX_START_PAYLOAD_BYTES = 512;
const MAX_ATTACHMENTS = 16;
const MAX_ATTACHMENT_TYPE_BYTES = 32;
const MAX_MESSAGE_ID_BYTES = 128;

const updateTypeSchema = z.enum(['bot_added', 'user_added', 'bot_stopped', 'bot_removed']);
const attachmentSchema = z.object({
  type: z.string().min(1).max(MAX_ATTACHMENT_TYPE_BYTES),
  hasAudioToken: z.boolean().optional(),
  hasContactSignature: z.boolean().optional(),
}).strict();

const base = {
  updateId: z.string().regex(/^max_[a-f0-9]{32}$/u),
  receivedAt: z.number().int().nonnegative(),
  platformTimestamp: z.number().int().positive(),
};
const identity = { userId: z.number().int().positive().safe() };
const chat = { chatId: z.number().int().positive().safe().optional() };

export const maxUpdateSchema = z.discriminatedUnion('kind', [
  z.object({
    kind: z.literal('bot_started'), ...base, ...identity, ...chat,
    startPayload: z.string().max(MAX_START_PAYLOAD_BYTES).optional(),
  }).strict(),
  z.object({
    kind: z.literal('message_created'), ...base, ...identity, chatId: z.number().int().positive().safe(),
    text: z.string().max(MAX_TEXT_BYTES).optional(),
    messageId: z.string().min(1).max(MAX_MESSAGE_ID_BYTES).optional(),
    attachments: z.array(attachmentSchema).max(MAX_ATTACHMENTS),
  }).strict(),
  z.object({
    kind: z.literal('message_callback'), ...base, ...identity, ...chat,
    callbackId: z.string().max(256).optional(),
    callbackPayload: z.string().max(MAX_CALLBACK_BYTES),
    messageId: z.string().min(1).max(MAX_MESSAGE_ID_BYTES).optional(),
  }).strict(),
  z.object({
    kind: z.literal('lifecycle'), ...base, updateType: updateTypeSchema,
    userId: z.number().int().positive().safe().optional(), ...chat,
  }).strict(),
]);

export type MaxUpdate = z.infer<typeof maxUpdateSchema>;
export type SupportedLifecycleUpdate = z.infer<typeof updateTypeSchema>;
export type MaxUpdateContext = Readonly<{ updateType: string; update: unknown }>;
export type NormalizeMaxUpdateOptions = Readonly<{
  now?: () => number;
  maxTextBytes?: number;
  maxCallbackBytes?: number;
  maxStartPayloadBytes?: number;
}>;

type UnknownRecord = Record<string, unknown>;
const SUPPORTED_UPDATE_TYPES = new Set([
  'bot_started', 'message_created', 'message_callback',
  'bot_added', 'user_added', 'bot_stopped', 'bot_removed',
]);

const asRecord = (value: unknown): UnknownRecord | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as UnknownRecord : undefined;

const requiredRecord = (value: unknown, field: string): UnknownRecord => {
  const record = asRecord(value);
  if (!record) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field });
  return record;
};

const requiredPositiveInteger = (value: unknown, field: string): number => {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field });
  }
  return value;
};

const optionalPositiveInteger = (value: unknown, field: string): number | undefined => {
  if (value === null || value === undefined) return undefined;
  return requiredPositiveInteger(value, field);
};

const boundedOptionalString = (value: unknown, maxBytes: number, field: string): string | undefined => {
  if (value === null || value === undefined) return undefined;
  if (typeof value !== 'string' || Buffer.byteLength(value, 'utf8') > maxBytes) {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field, maxBytes });
  }
  return value;
};

const optionalIdentifier = (value: unknown, maxBytes: number): string | undefined =>
  typeof value === 'string' && Buffer.byteLength(value, 'utf8') <= maxBytes ? value : undefined;

const receivedTime = (now: () => number): number => {
  const value = now();
  if (!Number.isSafeInteger(value) || value < 0) throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500);
  return value;
};

const messageIdentity = (update: UnknownRecord, kind: string): { userId: number; chatId?: number; message?: UnknownRecord; body?: UnknownRecord } => {
  const callback = asRecord(update['callback']);
  const message = asRecord(update['message']);
  const sender = asRecord(message?.['sender']);
  const callbackUser = asRecord(callback?.['user']);
  const user = callbackUser ?? asRecord(update['user']) ?? sender;
  const userId = requiredPositiveInteger(user?.['user_id'], 'user');
  const recipient = asRecord(message?.['recipient']);
  const body = asRecord(message?.['body']);
  const chatId = optionalPositiveInteger(update['chat_id'] ?? recipient?.['chat_id'], 'chatId');
  if (kind === 'message_created' && chatId === undefined) {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'chatId' });
  }
  return {
    userId,
    ...(chatId === undefined ? {} : { chatId }),
    ...(message ? { message } : {}),
    ...(body ? { body } : {}),
  };
};

const boundedStablePart = (value: unknown): string => {
  if (typeof value === 'string') return value.slice(0, 256);
  if (typeof value === 'number' && Number.isSafeInteger(value)) return String(value);
  return '';
};

const createUpdateId = (parts: readonly unknown[]): string => {
  const digest = createHash('sha256').update(parts.map(boundedStablePart).join(':'), 'utf8').digest('hex').slice(0, 32);
  return `max_${digest}`;
};

const platformTimestamp = (update: UnknownRecord): number =>
  requiredPositiveInteger(update['timestamp'], 'timestamp');

export const normalizeMaxUpdate = (context: MaxUpdateContext, options: NormalizeMaxUpdateOptions = {}): MaxUpdate | undefined => {
  if (typeof context.updateType !== 'string' || !SUPPORTED_UPDATE_TYPES.has(context.updateType)) return undefined;
  const update = asRecord(context.update);
  if (!update || update['update_type'] !== context.updateType) {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'updateType' });
  }

  const timestamp = platformTimestamp(update);
  const receivedAt = receivedTime(options.now ?? Date.now);
  let normalized: unknown;

  if (context.updateType === 'message_created') {
    const { userId, chatId, body } = messageIdentity(update, context.updateType);
    const messageBody = body ?? requiredRecord(undefined, 'message.body');
    const text = boundedOptionalString(messageBody['text'], options.maxTextBytes ?? MAX_TEXT_BYTES, 'message.body.text');
    const rawAttachments = messageBody['attachments'];
    if (rawAttachments !== undefined && rawAttachments !== null && !Array.isArray(rawAttachments)) {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'message.body.attachments' });
    }
    const attachments = (rawAttachments ?? []) as unknown[];
    if (attachments.length > MAX_ATTACHMENTS) {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'message.body.attachments', maxItems: MAX_ATTACHMENTS });
    }
    const safeAttachments = attachments.map((value) => {
      const item = asRecord(value);
      const payload = asRecord(item?.['payload']);
      const type = optionalIdentifier(item?.['type'], MAX_ATTACHMENT_TYPE_BYTES) ?? 'unknown';
      return {
        type,
        ...(type === 'audio' ? { hasAudioToken: typeof payload?.['token'] === 'string' } : {}),
        ...(type === 'contact' ? { hasContactSignature: typeof payload?.['hash'] === 'string' } : {}),
      };
    });
    const messageId = optionalIdentifier(messageBody['mid'], MAX_MESSAGE_ID_BYTES);
    normalized = {
      kind: context.updateType,
      updateId: createUpdateId([context.updateType, timestamp, messageId, userId, chatId]),
      receivedAt,
      platformTimestamp: timestamp,
      userId,
      chatId,
      ...(text === undefined ? {} : { text }),
      ...(messageId === undefined || messageId === '' ? {} : { messageId }),
      attachments: safeAttachments,
    };
  } else if (context.updateType === 'message_callback') {
    const { userId, chatId, body } = messageIdentity(update, context.updateType);
    const callback = requiredRecord(update['callback'], 'callback');
    const callbackId = optionalIdentifier(callback['callback_id'], 256);
    const callbackPayload = boundedOptionalString(callback['payload'] ?? '', options.maxCallbackBytes ?? MAX_CALLBACK_BYTES, 'callback.payload') ?? '';
    const messageId = optionalIdentifier(body?.['mid'], MAX_MESSAGE_ID_BYTES);
    normalized = {
      kind: context.updateType,
      updateId: createUpdateId([context.updateType, timestamp, callbackId, messageId, userId]),
      receivedAt,
      platformTimestamp: timestamp,
      userId,
      ...(chatId === undefined ? {} : { chatId }),
      ...(callbackId === undefined ? {} : { callbackId }),
      callbackPayload,
      ...(messageId === undefined || messageId === '' ? {} : { messageId }),
    };
  } else if (context.updateType === 'bot_started') {
    const { userId, chatId } = messageIdentity(update, context.updateType);
    const startPayload = boundedOptionalString(update['payload'], options.maxStartPayloadBytes ?? MAX_START_PAYLOAD_BYTES, 'payload');
    normalized = {
      kind: context.updateType,
      updateId: createUpdateId([context.updateType, timestamp, chatId, userId, startPayload]),
      receivedAt,
      platformTimestamp: timestamp,
      userId,
      ...(chatId === undefined ? {} : { chatId }),
      ...(startPayload === undefined ? {} : { startPayload }),
    };
  } else {
    const user = asRecord(update['user']);
    const userId = user ? optionalPositiveInteger(user['user_id'], 'user') : undefined;
    const chatId = optionalPositiveInteger(update['chat_id'], 'chatId');
    normalized = {
      kind: 'lifecycle',
      updateType: context.updateType,
      updateId: createUpdateId([context.updateType, timestamp, chatId, userId]),
      receivedAt,
      platformTimestamp: timestamp,
      ...(userId === undefined ? {} : { userId }),
      ...(chatId === undefined ? {} : { chatId }),
    };
  }

  const parsed = maxUpdateSchema.safeParse(normalized);
  if (!parsed.success) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'update' });
  return parsed.data;
};

export const isSupportedMaxUpdateType = (value: string): boolean => SUPPORTED_UPDATE_TYPES.has(value);
