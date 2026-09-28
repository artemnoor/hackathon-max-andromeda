import { AppError, ERROR_CODES } from '../../shared/errors.js';
import {
  actorFromCallbackUpdate,
  callbackActionDefinitions,
  parseCallbackAction,
  type CallbackActionDefinition,
} from '../callbacks/actions.js';
import type { MaxUpdate } from './update.js';

export type MaxBotReply = Readonly<
  | { kind: 'chat'; text: string }
  | { kind: 'callback'; callbackId: string; text: string }
>;

const START_REPLY = 'MAX-контур запущен. Функции Andromeda пока не подключены.';
const HELP_REPLY = 'Это техническая основа MAX Bot. Сценарии Andromeda будут подключены отдельно.';
const CALLBACK_REPLY = 'Это действие сейчас недоступно.';
const UNAVAILABLE_REPLY = 'Функции Andromeda пока не подключены.';
const MAX_REPLY_BYTES = 2_000;

const isCommand = (text: string, command: 'start' | 'help'): boolean =>
  new RegExp(`^/${command}(?:@[A-Za-z0-9_]+)?(?:\\s|$)`, 'iu').test(text.trim());

const safeReply = (reply: MaxBotReply): MaxBotReply => {
  if (Buffer.byteLength(reply.text, 'utf8') > MAX_REPLY_BYTES) {
    throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'max_reply_size' });
  }
  return Object.freeze(reply);
};

export const createMaxUpdateHandler = (
  callbackDefinitions: readonly CallbackActionDefinition[] = callbackActionDefinitions(),
): ((update: MaxUpdate) => Promise<MaxBotReply | undefined>) => async (update) => {
  if (update.kind === 'lifecycle') return undefined;
  if (update.kind === 'bot_started') return safeReply({ kind: 'chat', text: START_REPLY });

  if (update.kind === 'message_callback') {
    if (!update.callbackId) return undefined;
    try {
      await parseCallbackAction(update.callbackPayload, callbackDefinitions, actorFromCallbackUpdate(update));
    } catch (error) {
      if (!(error instanceof AppError)
        || (error.code !== ERROR_CODES.FORBIDDEN && error.code !== ERROR_CODES.VALIDATION_FAILED)) throw error;
    }
    return safeReply({ kind: 'callback', callbackId: update.callbackId, text: CALLBACK_REPLY });
  }

  if (update.text && isCommand(update.text, 'start')) return safeReply({ kind: 'chat', text: START_REPLY });
  if (update.text && isCommand(update.text, 'help')) return safeReply({ kind: 'chat', text: HELP_REPLY });
  return safeReply({ kind: 'chat', text: UNAVAILABLE_REPLY });
};
