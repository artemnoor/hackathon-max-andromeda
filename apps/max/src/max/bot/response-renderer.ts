import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { AssistantQueryResponse } from '../client/andromeda-api.js';
import { createAssistantReportPdf } from './report-pdf.js';
import { responseActionButton } from './response-actions.js';

export type MaxMessageButton = Readonly<{ text: string; callbackPayload?: string; webAppUrl?: string; linkUrl?: string }>;
export type MaxPdfDocument = Readonly<{ filename: string; content: Buffer }>;
export type MaxChatMessage = Readonly<{
  text: string;
  buttons?: readonly (readonly MaxMessageButton[])[];
  document?: MaxPdfDocument;
}>;

const MAX_MESSAGE_BYTES = 2_000;
const MAX_RESPONSE_BYTES = 64_000;
const MAX_RESPONSE_MESSAGES = 32;
const MAX_OPTION_BYTES = 128;
const MAX_EVIDENCE_ROWS = 6;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const STATUS_LABELS: Readonly<Record<string, string>> = Object.freeze({
  source_assertion: 'Источник сообщает',
  policy_resolved: 'Правило найдено в проверенных источниках',
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
  source_backed_verbalization: 'Ответ подготовлен по проверенным данным Andromeda.',
  unverified_fallback: '⚠️ Общий ответ вне проверенной базы Andromeda.',
});

const METRIC_LABELS: Readonly<Record<string, string>> = Object.freeze({
  math_share: 'Доля математики',
  mathematics_share: 'Доля математики',
  programming_share: 'Доля программирования',
  ai_share: 'Доля искусственного интеллекта',
  physics_share: 'Доля физики',
  business_share: 'Доля бизнес-дисциплин',
  analytics_share: 'Доля аналитики',
});

const ANALYTICS_TEMPLATES = new Set([
  'analytics-summary',
  'analytics-report',
  'analytics-explorer',
  'metric-comparison',
  'metric-cards',
]);

const coverageLabel = (coverage: string): string | undefined => {
  const normalized = coverage.trim().toLowerCase();
  if (normalized === 'partial') return 'частичное покрытие';
  if (normalized === 'full' || normalized === 'complete') return 'полное покрытие';
  if (normalized === 'none' || normalized === 'missing' || normalized === 'unavailable') return 'данных пока нет';
  const numeric = Number(normalized);
  if (!Number.isFinite(numeric) || numeric < 0 || numeric > 1) return undefined;
  return `охват ${Math.round(numeric * 100)}%`;
};

const metricValueLabel = (metric: Record<string, unknown>): string => {
  const value = metric['value'];
  if (typeof value !== 'number' && typeof value !== 'string') {
    const status = typeof metric['status'] === 'string' ? STATUS_LABELS[metric['status']] : undefined;
    return status ?? 'значение не установлено';
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 'значение не установлено';
  const unit = typeof metric['unit'] === 'string' ? metric['unit'].toLowerCase() : '';
  if (unit === 'share' || unit === 'percent' || unit === 'percentage') {
    const percent = unit === 'share' ? parsed * 100 : parsed;
    return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(percent)}%`;
  }
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(parsed)}${unit === 'hours' ? ' ч' : unit === 'credits' ? ' зач. ед.' : ''}`;
};

const displayEntityId = (value: unknown): string => {
  const identifier = typeof value === 'string' ? safeDisplayText(value, 256) : '';
  const [kind = '', ...segments] = identifier.split(':').filter(Boolean);
  const code = segments.at(-1) ?? identifier;
  if (kind === 'direction' && code) return `направление ${code}`;
  if (kind === 'program' && code) return `программа ${code}`;
  return identifier || 'объект';
};

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
  let remaining = value;
  while (Buffer.byteLength(remaining, 'utf8') > MAX_MESSAGE_BYTES) {
    let prefix = '';
    let prefixBytes = 0;
    for (const codePoint of remaining) {
      const bytes = Buffer.byteLength(codePoint, 'utf8');
      if (bytes > MAX_MESSAGE_BYTES) {
        throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_codepoint_size' });
      }
      if (prefixBytes + bytes > MAX_MESSAGE_BYTES) break;
      prefix += codePoint;
      prefixBytes += bytes;
    }
    const findBoundary = (pattern: RegExp, minimumBytes: number): number | undefined => {
      let boundary: number | undefined;
      for (const match of prefix.matchAll(pattern)) {
        const end = (match.index ?? 0) + match[0].length;
        if (Buffer.byteLength(prefix.slice(0, end), 'utf8') >= minimumBytes) boundary = end;
      }
      return boundary;
    };
    const splitAt = findBoundary(/\n[ \t]*\n/gu, MAX_MESSAGE_BYTES * 0.45)
      ?? findBoundary(/[.!?…]["'»”)]*[ \t]+/gu, MAX_MESSAGE_BYTES * 0.58)
      ?? findBoundary(/\s+/gu, MAX_MESSAGE_BYTES * 0.72)
      ?? prefix.length;
    if (splitAt === 0) {
      throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_split_boundary' });
    }
    chunks.push(remaining.slice(0, splitAt));
    remaining = remaining.slice(splitAt);
  }
  if (remaining.length > 0 || chunks.length === 0) chunks.push(remaining);
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

const safeActionLabel = (value: string): string | undefined => {
  try {
    const normalized = safeDisplayText(value, MAX_OPTION_BYTES).replace(/\s+/gu, ' ').trim();
    return normalized.length > 0 ? normalized : undefined;
  } catch {
    return undefined;
  }
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
  const buttons = optionsKeyboard(result.options);
  const guidance = buttons
    ? 'Нажмите вариант или напишите свой ответ.'
    : 'Ответьте сообщением — можно своими словами.';
  const text = [intro, question, guidance].filter(Boolean).join('\n\n');
  return messagesFor(
    text,
    buttons,
  );
};

const renderComplete = (result: AssistantQueryResponse, restartedSession: boolean): readonly MaxChatMessage[] => {
  const response = result.response;
  if (!response) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_missing' });
  }
  let body = safeDisplayText(response.text);
  if (body.length === 0) {
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_response_empty' });
  }
  if (ANALYTICS_TEMPLATES.has(response.template)) {
    const data: Record<string, unknown> = isRecord(response.data) ? response.data : {};
    const rows = Array.isArray(data['rows']) ? data['rows'] : [];
    const labelRows = rows.filter(isRecord);
    const labels = labelRows.map((row) => typeof row['entity_label'] === 'string'
      ? safeDisplayText(row['entity_label'], 512)
      : displayEntityId(row['entity_id']));
    const metricCodes = new Set<string>();
    for (const row of labelRows) {
      if (isRecord(row['metrics'])) for (const code of Object.keys(row['metrics'])) metricCodes.add(code);
    }
    const definitions = new Map<string, string>();
    for (const definition of Array.isArray(data['metric_definitions']) ? data['metric_definitions'].filter(isRecord) : []) {
      if (typeof definition['code'] === 'string' && typeof definition['name'] === 'string') {
        definitions.set(definition['code'], safeDisplayText(definition['name'], 128));
      }
    }
    const preview = [...metricCodes].slice(0, 2).flatMap((code) => {
      const values = labelRows.slice(0, 2).map((row) => {
        const label = typeof row['entity_label'] === 'string'
          ? safeDisplayText(row['entity_label'], 512)
          : typeof row['entity_id'] === 'string'
            ? safeDisplayText(row['entity_id'], 96)
            : 'Объект';
        const metric: Record<string, unknown> = isRecord(row['metrics']) && isRecord(row['metrics'][code]) ? row['metrics'][code] : {};
        const coverage = typeof metric['coverage'] === 'string' ? coverageLabel(metric['coverage']) : undefined;
        return `${label}: ${metricValueLabel(metric)}${coverage ? ` (${coverage})` : ''}`;
      });
      const name = definitions.get(code) ?? METRIC_LABELS[code] ?? code.replaceAll('_', ' ');
      return values.length > 0 ? [`${name} — ${values.join('; ')}`] : [];
    });
    const entitySummary = labels.length > 0
      ? `Сравнила: ${labels.slice(0, 4).join('; ')}.`
      : `Результат по ${rows.length} объектам.`;
    body = [entitySummary, ...preview, 'Полная таблица, охват данных и источники — в приложенном PDF.'].join('\n');
  } else if (response.template === 'admission-fit-summary') {
    body = `${body}\n\nПодробная оценка по каждой программе, условия расчёта и пробелы в данных — в приложенном PDF.`;
  } else if (response.template === 'program-recommendations') {
    const data: Record<string, unknown> = isRecord(response.data) ? response.data : {};
    const recommendations = Array.isArray(data['recommendations'])
      ? data['recommendations'].filter(isRecord).slice(0, 3)
      : [];
    const preview = recommendations.flatMap((item) => {
      const name = typeof item['program_name'] === 'string'
        ? safeDisplayText(item['program_name'], 512)
        : 'Программа';
      const code = typeof item['program_code'] === 'string'
        ? safeDisplayText(item['program_code'], 128)
        : '';
      const score = typeof item['content_fit'] === 'number'
        && Number.isInteger(item['content_fit'])
        && item['content_fit'] >= 0 && item['content_fit'] <= 100
        ? `Content Fit: ${item['content_fit']}/100 (не шанс поступления)`
        : 'Оценка совпадения не рассчитана';
      const reasonRows = Array.isArray(item['reasons'])
        ? item['reasons'].filter(isRecord).slice(0, 2)
        : [];
      const reasons = reasonRows.flatMap((reason) => typeof reason['text'] === 'string'
        ? [`• ${safeDisplayText(reason['text'], 400)}`]
        : []);
      const university = typeof item['university_name'] === 'string'
        ? ` — ${safeDisplayText(item['university_name'], 512)}`
        : '';
      return [`${name}${code ? ` (${code})` : ''}${university}`, score, ...reasons];
    });
    body = [body, ...preview, 'Подробные обоснования, покрытие данных и источники — в PDF.'].join('\n\n');
  } else if (response.template === 'program-comparison-summary') {
    body = `${body}\n\nСводка различий, учебная нагрузка и источники — в приложенном PDF.`;
  } else if (response.response_mode !== 'unverified_fallback') {
    body = `${body}\n\nПодробный разбор и доступные источники — в приложенном PDF.`;
  }
  const modeLabel = MODE_LABELS[response.response_mode];
  const alreadyMarkedUnverified = response.response_mode === 'unverified_fallback'
    && body.includes('не подтверждённый данными Andromeda');
  const sections = [
    ...(restartedSession ? ['Контекст диалога был начат заново.'] : []),
    ...(modeLabel && !alreadyMarkedUnverified ? [modeLabel] : []),
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
    .flatMap((item) => {
      const metric = METRIC_LABELS[item.metric_code];
      const coverage = coverageLabel(item.coverage);
      return metric && coverage ? [`${metric}: ${coverage}`] : [];
    });
  if (evidence.length > 0) sections.push(`Данные по программе:\n${evidence.map((line) => `• ${line}`).join('\n')}`);

  const actionButtons: (readonly MaxMessageButton[])[] = response.actions
    .filter((item) => item && typeof item.action === 'string' && typeof item.label === 'string')
    .map((item) => responseActionButton(item, safeActionLabel))
    .filter((button): button is Readonly<{ text: string; callbackPayload: string }> => button !== undefined)
    .slice(0, 4)
    .map((button) => Object.freeze([button]));

  return messagesFor(sections.join('\n\n'), actionButtons);
};

export const renderAssistantResult = (
  result: AssistantQueryResponse,
  options: Readonly<{ restartedSession?: boolean }> = {},
): readonly MaxChatMessage[] => {
  if (result.state === 'needs_clarification' || result.state === 'ambiguous') return renderClarification(result);
  if (result.state === 'complete') return renderComplete(result, options.restartedSession ?? false);
  throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_assistant_state' });
};

export const renderAssistantResultWithReport = async (
  result: AssistantQueryResponse,
  options: Readonly<{ restartedSession?: boolean }> = {},
  onReportFailure?: (error: unknown) => void,
): Promise<readonly MaxChatMessage[]> => {
  const messages = renderAssistantResult(result, options);
  if (result.state !== 'complete' || !result.response) return messages;

  try {
    const content = await createAssistantReportPdf(result);
    const lastMessage = messages.at(-1);
    const date = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short' }).format(new Date());
    const document = Object.freeze({ filename: `andromeda-otchet-${date.replaceAll('.', '-')}.pdf`, content });
    if (messages.length >= MAX_RESPONSE_MESSAGES && lastMessage) {
      return Object.freeze([
        ...messages.slice(0, -1),
        Object.freeze({ ...lastMessage, document }),
      ]);
    }
    const withoutActionButtons = messages.map((message, index) => index === messages.length - 1 && message.buttons
      ? Object.freeze({ text: message.text })
      : message);
    const reportMessage: MaxChatMessage = Object.freeze({
      text: result.response?.response_mode === 'unverified_fallback'
        ? 'Полный текст общего ответа приложен в PDF «Andromeda — отчёт ' + date + '».'
        : 'Подробный разбор, таблицы и доступные источники — в PDF «Andromeda — отчёт ' + date + '».',
      document,
      ...(lastMessage?.buttons ? { buttons: lastMessage.buttons } : {}),
    });
    return Object.freeze([...withoutActionButtons, reportMessage]);
  } catch (error) {
    onReportFailure?.(error);
    return Object.freeze(messages.map((message) => Object.freeze({
      ...message,
      text: message.text
        .replace('Полная таблица, охват данных и источники — в приложенном PDF.', 'Подробная таблица и источники в этот раз не сформировались.')
        .replace('Подробная оценка по каждой программе, условия расчёта и пробелы в данных — в приложенном PDF.', 'Полная оценка по программам в этот раз не сформировалась.')
        .replace('Подробный разбор и доступные источники — в приложенном PDF.', 'Подробный разбор и источники в этот раз не сформировались.')
        .replace(/Подробный разбор, таблицы и доступные источники — в PDF «Andromeda — отчёт [^»]+»\./u, 'PDF-отчёт в этот раз не сформировался.'),
    })));
  }
};

export const splitMaxResponseForTest = splitAtUtf8Boundaries;
