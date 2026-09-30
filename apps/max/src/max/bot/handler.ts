import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { AssistantInteraction } from './assistant.js';
import { renderAssistantResultWithReport, type MaxChatMessage, type MaxMessageButton, type MaxPdfDocument } from './response-renderer.js';
import {
  actorFromCallbackUpdate,
  parseCallbackAction,
  type CallbackAction,
  type CallbackActionDefinition,
} from '../callbacks/actions.js';
import {
  promptForResponseAction,
  responseActionCallbackDefinitions,
} from './response-actions.js';
import type { MaxUpdate } from './update.js';

export type MaxBotReply =
  | Readonly<{ kind: 'chat'; text: string; buttons?: readonly (readonly MaxMessageButton[])[]; document?: MaxPdfDocument }>
  | Readonly<{ kind: 'batch'; messages: readonly MaxChatMessage[] }>
  | Readonly<{ kind: 'callback'; callbackId: string; text: string; messages?: readonly MaxChatMessage[] }>;

const START_REPLY = '👋 Привет! Я Andromeda — помогу подобрать учебную программу, сравнить направления или оценить поступление по доступным данным. Напишите вопрос своими словами; если для точного ответа чего-то не хватит, я уточню.';
const HELP_REPLY = 'Опишите задачу обычным сообщением. Можно задать вопрос о поступлении, программах или правилах; уточнения можно отвечать текстом или нажатием на предложенный вариант.';
const CALLBACK_REPLY = 'Это действие сейчас недоступно.';
const DISCONNECTED_REPLY = 'Связь с Andromeda пока не настроена. Попробуйте позже.';
const INVALID_MESSAGE_REPLY = 'Напишите вопрос текстом.';
const MAX_REPLY_BYTES = 2_000;
const EXAMPLE_COMPARISON_QUERY = 'Чем ИУ5 (09.03.01-02) отличается от ИУ7 (09.03.04-01) по учебным планам?';

const isCommand = (text: string, command: 'start' | 'help'): boolean =>
  new RegExp('^/' + command + '(?:@[A-Za-z0-9_]+)?(?:\\s|$)', 'iu').test(text.trim());

const safeText = (text: string): string => {
  if (Buffer.byteLength(text, 'utf8') > MAX_REPLY_BYTES) {
    throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'max_reply_size' });
  }
  return text;
};

const safeChat = (
  text: string,
  buttons?: readonly (readonly MaxMessageButton[])[],
  document?: MaxPdfDocument,
): MaxBotReply => Object.freeze({
  kind: 'chat',
  text: safeText(text),
  ...(buttons ? { buttons } : {}),
  ...(document ? { document: safeDocument(document) } : {}),
});

const safeBatch = (messages: readonly MaxChatMessage[]): MaxBotReply => {
  return Object.freeze({ kind: 'batch', messages: safeMessages(messages) });
};

const safeMessages = (messages: readonly MaxChatMessage[]): readonly MaxChatMessage[] => {
  if (messages.length === 0 || messages.length > 32) {
    throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'max_reply_batch_size' });
  }
  return Object.freeze(messages.map((message) => Object.freeze({
    text: safeText(message.text),
    ...(message.buttons ? { buttons: message.buttons } : {}),
    ...(message.document ? { document: safeDocument(message.document) } : {}),
  })));
};

const safeDocument = (document: MaxPdfDocument): MaxPdfDocument => {
  if (!/^[a-z0-9-]{1,80}\.pdf$/iu.test(document.filename)
    || !Buffer.isBuffer(document.content)
    || document.content.byteLength < 8
    || document.content.byteLength > 4_000_000
    || document.content.subarray(0, 5).toString('ascii') !== '%PDF-') {
    throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'max_pdf_attachment_invalid' });
  }
  return Object.freeze({ filename: document.filename, content: Buffer.from(document.content) });
};

const safeCallback = (
  callbackId: string,
  text: string,
  messages?: readonly MaxChatMessage[],
): MaxBotReply => Object.freeze({
  kind: 'callback',
  callbackId,
  text: safeText(text),
  ...(messages ? { messages: safeMessages(messages) } : {}),
});

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
  miniAppPublicUrl?: string;
  callbackDefinitions?: readonly CallbackActionDefinition[];
  onReportFailure?: (error: unknown) => void;
}> = {}): ((update: MaxUpdate) => Promise<MaxBotReply | undefined>) => {
  const callbackDefinitions = dependencies.callbackDefinitions ?? responseActionCallbackDefinitions;
  const miniAppButtons = dependencies.miniAppPublicUrl
    ? [[{ text: 'Открыть каталог', linkUrl: new URL('/?page=catalog', dependencies.miniAppPublicUrl).toString() }]] as const
    : undefined;
  const startButtons = [
    ...(miniAppButtons ?? []),
    [{ text: EXAMPLE_COMPARISON_QUERY }],
  ] as const;
  const startReply = (): MaxBotReply => safeChat(START_REPLY, startButtons);
  const helpReply = (): MaxBotReply => safeChat(HELP_REPLY, miniAppButtons);

  const resetConversation = async (update: MaxUpdate): Promise<void> => {
    if (dependencies.assistant) await dependencies.assistant.resetConversation(update);
  };

  const startReplyAfterReset = async (update: MaxUpdate): Promise<MaxBotReply> => {
    try {
      await resetConversation(update);
      return startReply();
    } catch (error) {
      return safeChat(safeAssistantFailure(error));
    }
  };

  return async (update) => {
    if (update.kind === 'lifecycle') return undefined;
    if (update.kind === 'bot_started') return startReplyAfterReset(update);

    if (update.kind === 'message_callback') {
      if (!update.callbackId) return undefined;
      let action: CallbackAction;
      try {
        action = await parseCallbackAction(
          update.callbackPayload,
          callbackDefinitions,
          actorFromCallbackUpdate(update),
        );
      } catch (error) {
        if (!(error instanceof AppError)
          || (error.code !== ERROR_CODES.FORBIDDEN && error.code !== ERROR_CODES.VALIDATION_FAILED)) throw error;
        return safeCallback(update.callbackId, CALLBACK_REPLY);
      }
      const prompt = promptForResponseAction(action);
      if (!prompt || !dependencies.assistant) {
        return safeCallback(update.callbackId, CALLBACK_REPLY);
      }
      try {
        const interaction = await dependencies.assistant.query(update, prompt);
        const messages = await renderAssistantResultWithReport(
          interaction.result,
          { restartedSession: interaction.restartedSession },
          dependencies.onReportFailure,
        );
        return safeCallback(update.callbackId, 'Готово.', messages);
      } catch (error) {
        return safeCallback(update.callbackId, safeAssistantFailure(error));
      }
    }

    if (update.text && isCommand(update.text, 'start')) return startReplyAfterReset(update);
    if (update.text && isCommand(update.text, 'help')) return helpReply();
    if (!update.text?.trim()) return safeChat(INVALID_MESSAGE_REPLY);

    if (!dependencies.assistant) return safeChat(DISCONNECTED_REPLY);
    try {
      const interaction = await dependencies.assistant.query(update, update.text);
      const messages = await renderAssistantResultWithReport(
        interaction.result,
        { restartedSession: interaction.restartedSession },
        dependencies.onReportFailure,
      );
      return messages.length === 1
        ? safeChat(messages[0]!.text, messages[0]!.buttons, messages[0]!.document)
        : safeBatch(messages);
    } catch (error) {
      return safeChat(safeAssistantFailure(error));
    }
  };
};
