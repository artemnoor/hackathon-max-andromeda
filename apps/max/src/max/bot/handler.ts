import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { AssistantInteraction } from './assistant.js';
import { renderAssistantResult, type MaxChatMessage, type MaxMessageButton } from './response-renderer.js';
import {
  actorFromCallbackUpdate,
  callbackActionDefinitions,
  parseCallbackAction,
  type CallbackActionDefinition,
} from '../callbacks/actions.js';
import type { MaxUpdate } from './update.js';

export type MaxBotReply =
  | Readonly<{ kind: 'chat'; text: string; buttons?: readonly (readonly MaxMessageButton[])[] }>
  | Readonly<{ kind: 'batch'; messages: readonly MaxChatMessage[] }>
  | Readonly<{ kind: 'callback'; callbackId: string; text: string }>;

const START_REPLY = 'Здравствуйте! Я Andromeda. Задайте вопрос об образовательных программах и поступлении или выберите пример:';
const HELP_REPLY = 'Можно задать вопрос своими словами. Выберите пример или напишите, что хотите узнать:';
const CALLBACK_REPLY = 'Это действие сейчас недоступно.';
const DISCONNECTED_REPLY = 'Связь с Andromeda пока не настроена. Попробуйте позже.';
const INVALID_MESSAGE_REPLY = 'Отправьте текстовый вопрос без вложений.';
const MAX_REPLY_BYTES = 2_000;
const SCENARIO_BUTTONS: readonly (readonly MaxMessageButton[])[] = Object.freeze([
  Object.freeze([
    Object.freeze({ text: 'Подобрать программу' }),
    Object.freeze({ text: 'Сравнить программы' }),
  ]),
  Object.freeze([
    Object.freeze({ text: 'Оценить поступление' }),
    Object.freeze({ text: 'Проверить правила и льготы' }),
  ]),
]);

const isCommand = (text: string, command: 'start' | 'help'): boolean =>
  new RegExp('^/' + command + '(?:@[A-Za-z0-9_]+)?(?:\\s|$)', 'iu').test(text.trim());

const safeText = (text: string): string => {
  if (Buffer.byteLength(text, 'utf8') > MAX_REPLY_BYTES) {
    throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'max_reply_size' });
  }
  return text;
};

const safeChat = (text: string, buttons?: readonly (readonly MaxMessageButton[])[]): MaxBotReply =>
  Object.freeze({ kind: 'chat', text: safeText(text), ...(buttons ? { buttons } : {}) });

const safeBatch = (messages: readonly MaxChatMessage[]): MaxBotReply => {
  if (messages.length === 0 || messages.length > 32) {
    throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'max_reply_batch_size' });
  }
  const safeMessages = messages.map((message) => Object.freeze({
    text: safeText(message.text),
    ...(message.buttons ? { buttons: message.buttons } : {}),
  }));
  return Object.freeze({ kind: 'batch', messages: Object.freeze(safeMessages) });
};

const safeAssistantFailure = (error: unknown): string => {
  if (error instanceof AppError && error.code === ERROR_CODES.RATE_LIMITED) {
    return 'Сейчас много запросов. Попробуйте ещё раз немного позже.';
  }
  if (error instanceof AppError && error.code === ERROR_CODES.SESSION_CONFLICT) {
    return 'Контекст диалога изменился. Повторите вопрос ещё раз.';
  }
  return DISCONNECTED_REPLY;
};

export const createMaxUpdateHandler = (dependencies: Readonly<{
  assistant?: AssistantInteraction;
  callbackDefinitions?: readonly CallbackActionDefinition[];
}> = {}): ((update: MaxUpdate) => Promise<MaxBotReply | undefined>) => {
  const callbackDefinitions = dependencies.callbackDefinitions ?? callbackActionDefinitions();
  const startReply = (): MaxBotReply => safeChat(START_REPLY, SCENARIO_BUTTONS);
  const helpReply = (): MaxBotReply => safeChat(HELP_REPLY, SCENARIO_BUTTONS);

  return async (update) => {
    if (update.kind === 'lifecycle') return undefined;
    if (update.kind === 'bot_started') return startReply();

    if (update.kind === 'message_callback') {
      if (!update.callbackId) return undefined;
      try {
        await parseCallbackAction(update.callbackPayload, callbackDefinitions, actorFromCallbackUpdate(update));
      } catch (error) {
        if (!(error instanceof AppError)
          || (error.code !== ERROR_CODES.FORBIDDEN && error.code !== ERROR_CODES.VALIDATION_FAILED)) throw error;
      }
      return Object.freeze({ kind: 'callback', callbackId: update.callbackId, text: CALLBACK_REPLY });
    }

    if (update.text && isCommand(update.text, 'start')) return startReply();
    if (update.text && isCommand(update.text, 'help')) return helpReply();
    if (!update.text?.trim()) return safeChat(INVALID_MESSAGE_REPLY);

    if (!dependencies.assistant) return safeChat(DISCONNECTED_REPLY);
    try {
      const interaction = await dependencies.assistant.query(update, update.text);
      const messages = renderAssistantResult(interaction.result, { restartedSession: interaction.restartedSession });
      return messages.length === 1
        ? safeChat(messages[0]!.text, messages[0]!.buttons)
        : safeBatch(messages);
    } catch (error) {
      return safeChat(safeAssistantFailure(error));
    }
  };
};
