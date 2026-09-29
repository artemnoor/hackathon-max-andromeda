import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { AssistantQueryResponse } from '../client/andromeda-api.js';

export type MaxMessageButton = Readonly<{ text: string }>;
export type MaxChatMessage = Readonly<{
  text: string;
  buttons?: readonly (readonly MaxMessageButton[])[];
}>;

const MAX_MESSAGE_BYTES = 2_000;
const MAX_RESPONSE_BYTES = 64_000;
const MAX_RESPONSE_MESSAGES = 32;
const MAX_OPTION_BYTES = 128;
const MAX_EVIDENCE_ROWS = 6;

const STATUS_LABELS: Readonly<Record<string, string>> = Object.freeze({
  source_assertion: 'Источник сообщает',
  policy_resolved: 'Правило разрешено по данным Andromeda',
  conflict: 'Источники расходятся',
  no_evidence: 'Подтверждённых сведений пока нет',
  insufficient_data: 'Данных недостаточно для вывода',
  outside_coverage: 'Вопрос вне проверенной базы Andromeda',
  historical_state_unavailable: 'История состояния недоступна',
  review_required: 'Информация ожидает проверки',
  uncertain: 'Ответ пока не определён однозначно',
});

const ACTIONABILITY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  not_applicable: 'к вам не относится',
  future_only: 'может относиться в будущем',
  informational: 'для информации',
  action_recommended: 'рекомендуется проверить детали',
  action_required: 'требуется действие',
  uncertain: 'пока не определено',
  blocked_by_missing_data: 'нужны дополнительные данные',
});

const MODE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  deterministic: 'Ответ рассчитан по данным Andromeda.',
  source_backed_verbalization: 'Ответ подготовлен по проверенным данным Andromeda.',
  unverified_fallback: 'Это общий непроверенный ответ вне базы Andromeda.',
});

const safeDisplayText = (value: string, maxBytes = 20_000): string => {
  const normalized = Array.from(value.replace(/\r\n?/gu, '\n'))
    .filter((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint === 0x0a || codePoint >= 0x20 && codePoint !== 0x7f;
    })
    .join('')
    .trim();
  if (Buffer.byteLength(normalized, 'utf8') > maxBytes) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_text_size' });
  }
  return normalized;
};

const splitAtUtf8Boundaries = (value: string): string[] => {
  if (Buffer.byteLength(value, 'utf8') > MAX_RESPONSE_BYTES) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_total_size' });
  }
  const chunks: string[] = [];
  let current = '';
  let currentBytes = 0;
  for (const codePoint of value) {
    const bytes = Buffer.byteLength(codePoint, 'utf8');
    if (bytes > MAX_MESSAGE_BYTES) {
      throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_codepoint_size' });
    }
    if (currentBytes + bytes > MAX_MESSAGE_BYTES) {
      chunks.push(current);
      current = '';
      currentBytes = 0;
    }
    current += codePoint;
    currentBytes += bytes;
  }
  if (current.length > 0 || chunks.length === 0) chunks.push(current);
  if (chunks.length > MAX_RESPONSE_MESSAGES) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_message_count' });
  }
  return chunks;
};

const optionsKeyboard = (options: readonly string[]): readonly (readonly MaxMessageButton[])[] | undefined => {
  if (options.length === 0 || options.length > 4) return undefined;
  const safeOptions = options.map((option) => safeDisplayText(option, MAX_OPTION_BYTES));
  if (safeOptions.some((option) => option.length === 0)) return undefined;
  return Object.freeze(safeOptions.map((text) => Object.freeze([{ text }])));
};

const messagesFor = (
  text: string,
  buttons?: readonly (readonly MaxMessageButton[])[],
): readonly MaxChatMessage[] => {
  const chunks = splitAtUtf8Boundaries(text);
  return Object.freeze(chunks.map((chunk, index) => Object.freeze({
    text: chunk,
    ...(buttons && index === chunks.length - 1 ? { buttons } : {}),
  })));
};

const renderClarification = (result: AssistantQueryResponse): readonly MaxChatMessage[] => {
  const question = typeof result.question === 'string'
    ? safeDisplayText(result.question, 4_000)
    : 'Уточните, пожалуйста, что именно вы имеете в виду.';
  const intro = result.state === 'ambiguous' ? 'Не удалось определить однозначно.' : '';
  const text = [intro, question].filter(Boolean).join('\n\n');
  const buttons = optionsKeyboard(result.options);
  return messagesFor(
    buttons ? text : `${text}\n\nМожно ответить своими словами.`,
    buttons,
  );
};

const renderComplete = (result: AssistantQueryResponse, restartedSession: boolean): readonly MaxChatMessage[] => {
  const response = result.response;
  if (!response) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_missing' });
  }
  const body = safeDisplayText(response.text);
  if (body.length === 0) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_empty' });
  }
  const sections = [
    ...(restartedSession ? ['Контекст диалога был начат заново.'] : []),
    MODE_LABELS[response.response_mode] ?? 'Ответ получен от Andromeda.',
    body,
  ];

  const knowledge = response.knowledge;
  if (knowledge && typeof knowledge === 'object') {
    const status = STATUS_LABELS[knowledge.status];
    const actionability = ACTIONABILITY_LABELS[knowledge.actionability];
    if (status) sections.push(`Статус: ${status}.`);
    if (actionability) sections.push(`Применимость: ${actionability}.`);
  }

  const evidence = response.evidence
    .filter((item) => item && typeof item.metric_code === 'string'
      && typeof item.coverage === 'string' && Number.isSafeInteger(item.evidence_count)
      && item.evidence_count >= 0)
    .slice(0, MAX_EVIDENCE_ROWS)
    .map((item) => `${safeDisplayText(item.metric_code, 128)}: ${safeDisplayText(item.coverage, 256)} (${item.evidence_count})`);
  if (evidence.length > 0) sections.push(`Источники и покрытие:\n${evidence.map((line) => `• ${line}`).join('\n')}`);

  const actions = response.actions
    .filter((item) => item && typeof item.label === 'string' && item.label.trim().length > 0)
    .slice(0, 4)
    .map((item) => safeDisplayText(item.label, 256));
  if (actions.length > 0) sections.push(`Доступно в Andromeda:\n${actions.map((label) => `• ${label}`).join('\n')}`);

  return messagesFor(sections.join('\n\n'));
};

export const renderAssistantResult = (
  result: AssistantQueryResponse,
  options: Readonly<{ restartedSession?: boolean }> = {},
): readonly MaxChatMessage[] => {
  if (result.state === 'needs_clarification' || result.state === 'ambiguous') return renderClarification(result);
  if (result.state === 'complete') return renderComplete(result, options.restartedSession ?? false);
  throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_assistant_state' });
};

export const splitMaxResponseForTest = splitAtUtf8Boundaries;
