import { createHash } from 'node:crypto';

import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { MaxUpdate } from '../bot/update.js';

export const MAX_CALLBACK_PAYLOAD_BYTES = 1024;

export type CallbackAction = Readonly<{
  namespace: string;
  verb: string;
  resource?: string;
}>;

export type CallbackActor = Readonly<{
  userId: number;
  chatId?: number;
}>;

export type CallbackActionDefinition = Readonly<{
  namespace: string;
  verb: string;
  requiresResource: boolean;
  authorize?: (action: CallbackAction, actor: CallbackActor) => Promise<boolean> | boolean;
}>;

const ACTION_PART = /^[a-z][a-z0-9_-]{0,31}$/u;
const RESOURCE_PART = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;

const invalid = (): AppError => new AppError(ERROR_CODES.VALIDATION_FAILED, 400);

export const callbackActionDefinitions = (extra: readonly CallbackActionDefinition[] = []): readonly CallbackActionDefinition[] =>
  Object.freeze([...extra]);

export const parseCallbackAction = async (
  raw: unknown,
  definitions: readonly CallbackActionDefinition[],
  actor: CallbackActor,
): Promise<CallbackAction> => {
  if (typeof raw !== 'string' || Buffer.byteLength(raw, 'utf8') > MAX_CALLBACK_PAYLOAD_BYTES) throw invalid();
  const parts = raw.split(':');
  if (parts.length < 2 || parts.length > 3 || parts.some((part) => !part)) throw invalid();
  const [namespace, verb, resource] = parts;
  if (!namespace || !verb || !ACTION_PART.test(namespace) || !ACTION_PART.test(verb)
    || (resource !== undefined && !RESOURCE_PART.test(resource))) throw invalid();

  const definition = definitions.find((candidate) => candidate.namespace === namespace && candidate.verb === verb);
  if (!definition || definition.requiresResource !== (resource !== undefined)) {
    throw new AppError(ERROR_CODES.FORBIDDEN, 403);
  }
  const action: CallbackAction = Object.freeze({
    namespace,
    verb,
    ...(resource === undefined ? {} : { resource }),
  });
  if (definition.authorize && !await definition.authorize(action, actor)) {
    throw new AppError(ERROR_CODES.FORBIDDEN, 403);
  }
  return action;
};

export const callbackTokenHash = (raw: string): string =>
  createHash('sha256').update(raw, 'utf8').digest('hex').slice(0, 16);

export const actorFromCallbackUpdate = (update: Extract<MaxUpdate, { kind: 'message_callback' }>): CallbackActor => ({
  userId: update.userId,
  ...(update.chatId === undefined ? {} : { chatId: update.chatId }),
});
