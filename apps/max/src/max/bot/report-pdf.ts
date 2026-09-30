import { resolve } from 'node:path';
import PDFDocument from 'pdfkit';

import type { AssistantQueryResponse } from '../client/andromeda-api.js';

const MAX_REPORT_BYTES = 4_000_000;
const MAX_REPORT_ROWS = 40;
const MAX_REPORT_FACTS = 40;
const MAX_REPORT_SOURCES = 20;
const CONTENT_WIDTH = 507;
const LEFT = 44;
const PAGE_BOTTOM = 744;

const COLORS = Object.freeze({
  ink: '#1F2440',
  muted: '#626985',
  violet: '#5149A7',
  line: '#E0E2EC',
  teal: '#16877E',
  warning: '#9C5A11',
});

const STATUS_LABELS: Readonly<Record<string, string>> = Object.freeze({
  available: 'данные доступны',
  partial: 'данные частичные',
  unavailable: 'данные недоступны',
  not_available: 'опубликованные данные не найдены',
  realistic: 'сочетание выглядит реалистичным',
  borderline: 'пограничное сочетание',
  unlikely: 'текущих данных недостаточно для уверенного поступления',
  source_assertion: 'информация приведена как утверждение источника',
  policy_resolved: 'правило разрешено по проверенным данным',
  conflict: 'источники расходятся',
  no_evidence: 'подтверждённые сведения не найдены',
  insufficient_data: 'данных недостаточно для вывода',
  outside_coverage: 'вопрос вне проверенного покрытия Andromeda',
  historical_state_unavailable: 'история состояния недоступна',
  review_required: 'информация ожидает проверки',
  uncertain: 'ответ пока не определён однозначно',
  not_applicable: 'не относится к указанным условиям',
  future_only: 'может относиться в будущем',
  informational: 'информация к сведению',
  action_recommended: 'рекомендуется проверить детали',
  action_required: 'требуется действие',
  blocked_by_missing_data: 'для вывода не хватает данных',
  possible: 'возможно',
  announced: 'объявлено',
  proposal: 'предложение или проект',
  adopted: 'принято',
  published: 'опубликовано',
  future_effective: 'вступит в силу позднее',
  effective: 'действует',
  superseded: 'заменено новой редакцией',
  repealed: 'отменено',
  withdrawn: 'отозвано',
  rejected: 'отклонено',
  unknown: 'статус неизвестен',
});

const SOURCE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  bmstu_curriculum_document: 'Учебный план МГТУ им. Н. Э. Баумана',
  bmstu_major_detail: 'Каталог образовательных программ МГТУ им. Н. Э. Баумана',
});

const METRIC_LABELS: Readonly<Record<string, string>> = Object.freeze({
  math_share: 'Математика в учебном плане',
  mathematics_share: 'Математика в учебном плане',
  programming_share: 'Программирование в учебном плане',
  ai_share: 'Искусственный интеллект в учебном плане',
  physics_share: 'Физика в учебном плане',
  business_share: 'Бизнес-дисциплины в учебном плане',
  analytics_share: 'Аналитика в учебном плане',
  math_first_year_share: 'Математика на первых курсах',
  math_late_year_share: 'Математика на старших курсах',
  first_programming_semester: 'Семестр первого курса программирования',
  first_ai_semester: 'Семестр первого курса по ИИ',
});

const ACTIONABILITY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  not_applicable: 'не относится к указанным условиям',
  future_only: 'может относиться в будущем',
  informational: 'информация к сведению',
  action_recommended: 'рекомендуется проверить детали',
  action_required: 'требуется действие',
  uncertain: 'пока не определено',
  blocked_by_missing_data: 'для вывода не хватает данных',
});

const RELIABILITY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  primary_official: 'первичный официальный источник',
  official: 'официальный источник',
  trusted_secondary: 'проверенный вторичный источник',
  unverified_secondary: 'непроверенный вторичный источник',
  community: 'сообщественный источник',
  user_supplied: 'источник предоставлен пользователем',
  unknown: 'надёжность не установлена',
});

const SCOPE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  federal: 'федеральный уровень',
  university: 'уровень вуза',
  direction: 'направление подготовки',
  program: 'образовательная программа',
  admission_route: 'маршрут поступления',
  other: 'другая область применения',
});

const STUDY_FORM_LABELS: Readonly<Record<string, string>> = Object.freeze({
  full_time: 'очная',
  part_time: 'заочная',
  evening: 'вечерняя',
  online: 'дистанционная',
  unknown: 'не указана',
});

const FUNDING_LABELS: Readonly<Record<string, string>> = Object.freeze({
  budget: 'бюджет',
  paid: 'платное обучение',
  targeted: 'целевое обучение',
  unknown: 'не указан',
});

const DISPOSITION_LABELS: Readonly<Record<string, string>> = Object.freeze({
  selected: 'выбрано',
  considered: 'учтено',
  not_applicable: 'не подходит по области применения',
  future: 'ещё не действует',
  expired: 'срок действия завершён',
  incomplete_scope: 'область применения не определена',
  incomplete_data: 'не хватает данных',
  unavailable: 'недоступно',
  conflict: 'конфликт',
  unresolved: 'не разрешено',
});

type RecordValue = Readonly<Record<string, unknown>>;

const isRecord = (value: unknown): value is RecordValue =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const asRecord = (value: unknown): RecordValue => isRecord(value) ? value : {};

const asArray = (value: unknown): readonly unknown[] => Array.isArray(value) ? value : [];

const safeText = (value: unknown, maximum = 3_000): string => {
  if (typeof value !== 'string') return '';
  return Array.from(value)
    .filter((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint === 0x09 || codePoint === 0x0a || codePoint === 0x0d
        || codePoint > 0x1f && codePoint !== 0x7f;
    })
    .slice(0, maximum)
    .join('')
    .trim();
};

const labelFor = (value: unknown, labels: Readonly<Record<string, string>>): string => {
  const raw = safeText(value, 128);
  return labels[raw] ?? raw.replaceAll('_', ' ');
};

const titleFor = (template: string): string => {
  if (template === 'program-comparison-summary') return 'Сравнение учебных программ';
  if (['analytics-summary', 'analytics-report', 'analytics-explorer', 'metric-comparison', 'metric-cards'].includes(template)) return 'Сравнение учебных программ';
  if (template === 'admission-fit-summary') return 'Оценка вариантов поступления';
  if (template === 'program-recommendations') return 'Подбор образовательных программ';
  if (template === 'policy-resolution') return 'Ответ о правилах приёма';
  return 'Ответ Andromeda';
};

const registerFonts = (document: InstanceType<typeof PDFDocument>): void => {
  const fontDirectory = resolve(process.cwd(), 'assets', 'fonts');
  document.registerFont('andromeda-regular', resolve(fontDirectory, 'noto-sans-regular.ttf'));
  document.registerFont('andromeda-bold', resolve(fontDirectory, 'noto-sans-bold.ttf'));
};

const writeRichText = (
  document: InstanceType<typeof PDFDocument>,
  text: string,
  options: Readonly<{ bold?: boolean; size?: number; color?: string; width?: number; lineGap?: number; x?: number; y?: number }> = {},
): void => {
  document
    .font(options.bold ? 'andromeda-bold' : 'andromeda-regular')
    .fontSize(options.size ?? 10)
    .fillColor(options.color ?? COLORS.ink)
    .text(text, {
      ...(options.width === undefined ? {} : { width: options.width }),
      ...(options.lineGap === undefined ? {} : { lineGap: options.lineGap }),
      ...(options.x === undefined ? {} : { x: options.x }),
      ...(options.y === undefined ? {} : { y: options.y }),
    });
};

const addSectionHeading = (document: InstanceType<typeof PDFDocument>, heading: string): void => {
  document.moveDown(0.8);
  ensureSpace(document, 34);
  writeRichText(document, heading, { bold: true, size: 15, color: COLORS.violet, width: CONTENT_WIDTH });
  document.moveDown(0.35);
  document.strokeColor(COLORS.line).moveTo(LEFT, document.y).lineTo(LEFT + CONTENT_WIDTH, document.y).stroke();
  document.moveDown(0.55);
};

const addSubheading = (document: InstanceType<typeof PDFDocument>, heading: string): void => {
  ensureSpace(document, 26);
  writeRichText(document, heading, { bold: true, size: 11, color: COLORS.ink, width: CONTENT_WIDTH });
  document.moveDown(0.2);
};

const addParagraph = (
  document: InstanceType<typeof PDFDocument>,
  text: string,
  options: Readonly<{ bold?: boolean; size?: number; color?: string }> = {},
): void => {
  const normalized = safeText(text);
  if (!normalized) return;
  ensureSpace(document, 24);
  writeRichText(document, normalized, { ...options, width: CONTENT_WIDTH, lineGap: 3 });
  document.moveDown(0.25);
};

const ensureSpace = (document: InstanceType<typeof PDFDocument>, height: number): void => {
  if (document.y + height > PAGE_BOTTOM) document.addPage();
};

const displayId = (value: unknown): string => {
  const identifier = safeText(value, 256);
  const segments = identifier.split(':').filter(Boolean);
  const code = segments.at(-1) ?? identifier;
  if (segments[0] === 'direction' && code) return `Направление подготовки ${code}`;
  if (segments[0] === 'program' && code) return `Образовательная программа ${code}`;
  if (segments[0] === 'university' && code) return `Вуз ${code}`;
  return code ? `Идентификатор: ${code}` : 'Объект';
};

const formatNumber = (value: unknown): string | undefined => {
  if ((typeof value !== 'string' && typeof value !== 'number') || String(value).trim() === '') return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return undefined;
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(parsed);
};

const formatMetricValue = (metric: RecordValue): string => {
  const value = formatNumber(metric['value']);
  if (value === undefined) {
    const status = labelFor(metric['status'], STATUS_LABELS);
    return status ? `Нет значения: ${status}` : 'Подтверждённое значение отсутствует';
  }
  const unit = safeText(metric['unit'], 64).toLowerCase();
  const numeric = Number(metric['value']);
  if (unit === 'share' || unit === 'percent' || unit === 'percentage') {
    return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(numeric * (unit === 'share' ? 100 : 1))}%`;
  }
  const unitLabel: Readonly<Record<string, string>> = Object.freeze({
    semester: 'семестр',
    hours: 'часов',
    credits: 'зачётных единиц',
    count: 'объектов',
  });
  return unitLabel[unit] ? `${value} ${unitLabel[unit]}` : `${value}${unit ? ` ${unit}` : ''}`;
};

const dataSources = (response: AssistantQueryResponse): readonly RecordValue[] => {
  const knowledge = asRecord(response.response?.knowledge);
  const sources: RecordValue[] = [...asArray(knowledge['evidence']).filter(isRecord)];
  for (const assertion of asArray(knowledge['source_assertions']).filter(isRecord)) {
    sources.push(...asArray(assertion['evidence']).filter(isRecord));
  }
  const data = asRecord(response.response?.data);
  const comparison = asRecord(data['comparison']);
  for (const overview of asArray(comparison['programs']).filter(isRecord)) {
    const program = asRecord(overview['program']);
    for (const [url, sourceName] of [
      [program['studyPlanUrl'], 'Учебный план программы'],
      [program['sourceUrl'], 'Карточка программы'],
    ] as const) {
      if (typeof url === 'string') sources.push({ url, source_name: sourceName, kind: 'official' });
    }
  }
  sources.push(...asArray(data['sources']).filter(isRecord));
  for (const item of asArray(data['recommendations']).filter(isRecord)) {
    for (const provenance of asArray(item['provenance']).filter(isRecord)) {
      sources.push({
        url: provenance['url'],
        source_name: 'Источник учебного плана',
        locator: provenance['locator'],
        kind: provenance['kind'],
      });
    }
  }
  for (const row of asArray(data['rows']).filter(isRecord)) {
    for (const metric of Object.values(asRecord(row['metrics']))) {
      sources.push(...asArray(asRecord(metric)['provenance']).filter(isRecord));
    }
  }
  const outcomes = asRecord(asRecord(data['outcomes'])['by_program_id']);
  for (const outcome of Object.values(outcomes).filter(isRecord)) {
    const result = asRecord(outcome['result']);
    const reasons = [
      ...asArray(result['reasons']).filter(isRecord),
      ...asArray(result['anti_reasons']).filter(isRecord),
      ...asArray(result['data_gaps']).filter(isRecord),
      ...asArray(outcome['data_gaps']).filter(isRecord),
    ];
    for (const reason of reasons) {
      for (const provenance of asArray(reason['provenance']).filter(isRecord)) {
        sources.push({
          url: provenance['source_url'],
          source_name: provenance['source_name'],
          locator: provenance['locator'],
          kind: provenance['source_kind'],
        });
      }
    }
  }
  const unique = new Map<string, RecordValue>();
  for (const source of sources) {
    const url = safeText(source['url'], 2_048);
    if (/^https:\/\//iu.test(url) && !unique.has(url)) unique.set(url, source);
    if (unique.size >= MAX_REPORT_SOURCES) break;
  }
  return [...unique.values()];
};

const addAnalytics = (document: InstanceType<typeof PDFDocument>, response: AssistantQueryResponse): void => {
  const data = asRecord(response.response?.data);
  const rows = asArray(data['rows']).filter(isRecord).slice(0, MAX_REPORT_ROWS);
  const definitions = new Map<string, string>();
  for (const definition of asArray(data['metric_definitions']).filter(isRecord).slice(0, 12)) {
    const code = safeText(definition['code'], 96);
    const name = safeText(definition['name'], 128);
    if (code && name) definitions.set(code, name);
  }
  addSectionHeading(document, 'Сравнение по показателям');
  if (rows.length === 0) {
    addParagraph(document, 'В структурированном результате нет строк для сравнения.');
    return;
  }
  const metricCodes = [...new Set(rows.flatMap((row) => Object.keys(asRecord(row['metrics']))))].slice(0, 12);
  for (const code of metricCodes) {
    const label = definitions.get(code) ?? METRIC_LABELS[code] ?? code.replaceAll('_', ' ');
    addSubheading(document, label);
    const comparedValues = rows.map((row) => {
      const metric = asRecord(asRecord(row['metrics'])[code]);
      const rawValue = metric['value'];
      const numericValue = rawValue === null || rawValue === undefined || rawValue === '' ? undefined : Number(rawValue);
      return {
        row,
        metric,
        numericValue: numericValue !== undefined && Number.isFinite(numericValue) && numericValue >= 0
          ? numericValue
          : undefined,
      };
    });
    const maximum = Math.max(0, ...comparedValues.flatMap(({ numericValue }) => numericValue === undefined ? [] : [numericValue]));
    for (const { row, metric, numericValue } of comparedValues) {
      const entityLabel = safeText(row['entity_label'], 256) || displayId(row['entity_id']);
      const coverage = formatNumber(metric['coverage']);
      const basis = safeText(metric['basis'], 64);
      const details = [
        formatMetricValue(metric),
        coverage === undefined ? undefined : `покрытие ${new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 0 }).format(Number(metric['coverage']))}`,
        basis === 'hours' ? 'расчёт по часам' : basis === 'credits' ? 'расчёт по зачётным единицам' : undefined,
      ].filter(Boolean).join(' · ');
      ensureSpace(document, 58);
      writeRichText(document, entityLabel, { bold: true, size: 9.5, width: CONTENT_WIDTH });
      document.moveDown(0.15);
      addParagraph(document, details || 'Подтверждённое значение отсутствует.', { size: 9, color: COLORS.muted });
      const barY = document.y;
      document.save();
      document.roundedRect(LEFT, barY, CONTENT_WIDTH, 5, 2).fill(COLORS.line);
      if (numericValue !== undefined && maximum > 0) {
        const barWidth = Math.max(2, CONTENT_WIDTH * numericValue / maximum);
        document.roundedRect(LEFT, barY, barWidth, 5, 2).fill(COLORS.teal);
      }
      document.restore();
      document.y = barY + 11;
    }
  }
  if (rows.length > 1 && metricCodes.length > 0) {
    addParagraph(document, 'Полосы показывают величину одного и того же показателя в сравнении между строками; они не являются оценкой качества программы. Учитывайте охват данных.', { size: 8, color: COLORS.muted });
  }
  if (rows.length === MAX_REPORT_ROWS) addParagraph(document, 'Показаны первые 40 строк; исходный результат ограничен.', { color: COLORS.muted, size: 8.5 });
};

const addProgramComparison = (document: InstanceType<typeof PDFDocument>, response: AssistantQueryResponse): void => {
  const comparison = asRecord(asRecord(response.response?.data)['comparison']);
  addSectionHeading(document, 'Сравнение учебных планов');
  const programs = asArray(comparison['programs']).filter(isRecord).slice(0, 3);
  for (const overview of programs) {
    const program = asRecord(overview['program']);
    const name = safeText(program['name'], 256) || 'Образовательная программа';
    const code = safeText(program['code'], 96);
    addSubheading(document, `${name}${code ? ` (${code})` : ''}`);
    const totals = asRecord(overview['totals']);
    const hours = formatNumber(totals['hours']);
    const credits = formatNumber(totals['credits']);
    addParagraph(document, hours === undefined && credits === undefined
      ? 'Итоги учебного плана в источнике не рассчитаны.'
      : `Объём: ${hours === undefined ? 'часы не указаны' : `${hours} ч`}; ${credits === undefined ? 'ЗЕТ не указаны' : `${credits} ЗЕТ`}.`);
    const areas = asArray(overview['areaBreakdown']).filter(isRecord).slice(0, 5);
    for (const area of areas) {
      const label = safeText(area['name'], 160);
      const share = formatNumber(area['share']);
      if (label && share !== undefined) addParagraph(document, `${label}: ${new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 }).format(Number(area['share']))}.`, { size: 9 });
    }
  }

  const differences = asArray(comparison['keyDifferences']).filter(isRecord).slice(0, 24);
  addSubheading(document, 'Главные различия');
  if (differences.length === 0) addParagraph(document, 'Для этих программ ключевые различия не рассчитаны.');
  for (const item of differences) {
    const label = safeText(item['label'], 256);
    if (!label) continue;
    const dimension = safeText(item['dimension'], 32);
    const a = comparisonValue(item['valueA'], dimension);
    const b = comparisonValue(item['valueB'], dimension);
    addParagraph(document, `${label}: ${a} и ${b}.`, { size: 9 });
  }

  const gaps = asArray(comparison['sourceGaps']).filter(isRecord).slice(0, 8);
  if (gaps.length > 0) {
    addSubheading(document, 'Ограничения источников');
    for (const gap of gaps) addParagraph(document, safeText(gap['message'], 800), { size: 9, color: COLORS.warning });
  }
};

const comparisonValue = (value: unknown, dimension: string): string => {
  const numeric = formatNumber(value);
  if (numeric === undefined) return 'нет значения';
  if (dimension === 'area') {
    const parsed = Number(value);
    return Number.isFinite(parsed)
      ? `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(parsed * 100)}%`
      : numeric;
  }
  return dimension === 'workload' ? `${numeric} ч` : numeric;
};

const isAnalyticsResponse = (response: AssistantQueryResponse): boolean => {
  const data = asRecord(response.response?.data);
  return Array.isArray(data['rows']) && data['rows'].length > 0;
};

const analyticsSummaryText = (response: AssistantQueryResponse): string => {
  const data = asRecord(response.response?.data);
  const rows = asArray(data['rows']).filter(isRecord).slice(0, 4);
  const metricDefinitions = new Map<string, string>();
  for (const definition of asArray(data['metric_definitions']).filter(isRecord)) {
    const code = safeText(definition['code'], 96);
    const label = safeText(definition['name'], 128);
    if (code && label) metricDefinitions.set(code, label);
  }
  const metricCodes = [...new Set(rows.flatMap((row) => Object.keys(asRecord(row['metrics']))))].slice(0, 2);
  const comparisons = metricCodes.map((code) => {
    const label = metricDefinitions.get(code) ?? METRIC_LABELS[code] ?? code.replaceAll('_', ' ');
    const values = rows.slice(0, 2).map((row) => {
      const name = safeText(row['entity_label'], 160) || displayId(row['entity_id']);
      const metric = asRecord(asRecord(row['metrics'])[code]);
      const coverage = formatNumber(metric['coverage']);
      const coverageLabelText = coverage === undefined
        ? ''
        : ` (охват ${new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 0 }).format(Number(metric['coverage']))})`;
      return `${name} — ${formatMetricValue(metric)}${coverageLabelText}`;
    });
    return values.length > 0 ? `«${label}»: ${values.join('; ')}.` : undefined;
  }).filter((value): value is string => value !== undefined);
  const entityLabels = rows.map((row) => safeText(row['entity_label'], 160) || displayId(row['entity_id']));
  return [
    `Результаты для сравнения: ${entityLabels.slice(0, 2).join(' и ')}.`,
    ...comparisons,
    'Ниже приведены значения по каждому показателю, полнота данных и источники.',
  ].join('\n\n');
};

const addAdmission = (document: InstanceType<typeof PDFDocument>, response: AssistantQueryResponse): void => {
  const data = asRecord(response.response?.data);
  const outcomes = asRecord(asRecord(data['outcomes'])['by_program_id']);
  addSectionHeading(document, 'Оценка вариантов поступления');
  const entries = Object.entries(outcomes).slice(0, MAX_REPORT_ROWS);
  if (entries.length === 0) {
    addParagraph(document, 'В ответе нет детальной оценки по программам.');
    return;
  }
  for (const [programId, outcomeValue] of entries) {
    const outcome = asRecord(outcomeValue);
    const result = asRecord(outcome['result']);
    const programLabel = safeText(result['program_name'], 256) || displayId(programId);
    addSubheading(document, programLabel);
    const status = labelFor(result['status'] ?? outcome['status'], STATUS_LABELS);
    const score = formatNumber(result['score']);
    addParagraph(document, `Итог: ${status}${score === undefined ? '' : `. Индекс готовности — ${score} из 100; это не вероятность зачисления.`}`, { bold: true });
    const total = formatNumber(result['applicant_total_score']);
    if (total !== undefined) addParagraph(document, `Указанная сумма баллов: ${total}.`, { size: 9.5 });
    const breakdown = asRecord(result['breakdown']);
    for (const [key, label] of [
    ['minimum_readiness', 'Соответствие минимальным баллам'],
    ['passing_readiness', 'Сравнение с проходными баллами'],
    ['data_completeness', 'Сопоставление обязательных ЕГЭ'],
    ] as const) {
      const metric = asRecord(breakdown[key]);
      const metricValue = formatNumber(metric['value']);
      addParagraph(document, `${label}: ${metricValue === undefined ? labelFor(metric['status'], STATUS_LABELS) : `${metricValue} из 100`}.`, { size: 9.5 });
    }
    const reasons = [
      ...asArray(result['reasons']).filter(isRecord),
      ...asArray(result['anti_reasons']).filter(isRecord),
      ...asArray(result['data_gaps']).filter(isRecord),
      ...asArray(outcome['data_gaps']).filter(isRecord),
    ]
      .map((reason) => safeText(reason['message'], 512))
      .filter((message): message is string => Boolean(message));
    for (const message of [...new Set(reasons)].slice(0, 12)) {
      addParagraph(document, message, { size: 9.5, color: COLORS.muted });
    }
  }
};

const addRecommendations = (document: InstanceType<typeof PDFDocument>, response: AssistantQueryResponse): void => {
  const data = asRecord(response.response?.data);
  const recommendations = asArray(data['recommendations']).filter(isRecord).slice(0, 8);
  addSectionHeading(document, 'Подобранные программы');
  if (recommendations.length === 0) {
    addParagraph(document, 'Подтверждённых рекомендаций в ответе нет. Это не означает, что вузы не предлагают такие программы.');
    return;
  }
  for (const item of recommendations) {
    const name = safeText(item['program_name'], 256) || displayId(item['program_id']);
    const code = safeText(item['program_code'], 128);
    const university = safeText(item['university_name'], 256);
    addSubheading(document, `${name}${code ? ` (${code})` : ''}`);
    if (university) addParagraph(document, university, { size: 9.5, color: COLORS.muted });
    const score = formatNumber(item['content_fit']);
    addParagraph(document, `Совпадение содержания: ${score === undefined ? 'оценка отсутствует' : `${score} из 100`}. Это показатель Content Fit, а не вероятность зачисления.`, { bold: true });
    for (const reason of asArray(item['reasons']).filter(isRecord).slice(0, 4)) {
      const text = safeText(reason['text'], 512);
      if (text) addParagraph(document, text, { size: 9.5 });
    }
    for (const reason of asArray(item['anti_fit_reasons']).filter(isRecord).slice(0, 3)) {
      const text = safeText(reason['text'], 512);
      if (text) addParagraph(document, `Ограничение: ${text}`, { size: 9.5, color: COLORS.warning });
    }
    const evidence = asRecord(item['evidence']);
    const catalog = asRecord(evidence['catalog_completeness']);
    addParagraph(document, `Покрытие учебного плана: ${labelFor(catalog['status'], STATUS_LABELS)}.`, { size: 9, color: COLORS.muted });
    const gaps = asArray(item['source_gaps']).filter(isRecord)
      .map((gap) => safeText(gap['message'], 512)).filter(Boolean).slice(0, 6);
    for (const gap of gaps) addParagraph(document, `Не хватает данных: ${gap}`, { size: 9, color: COLORS.warning });
  }
};

const addKnowledge = (document: InstanceType<typeof PDFDocument>, response: AssistantQueryResponse): void => {
  const knowledge = asRecord(response.response?.knowledge);
  if (Object.keys(knowledge).length === 0) return;
  addSectionHeading(document, 'Что подтверждено');
  const status = labelFor(knowledge['status'], STATUS_LABELS);
  const actionability = labelFor(knowledge['actionability'], ACTIONABILITY_LABELS);
  addParagraph(document, `Статус: ${status}${actionability ? `. Применимость: ${actionability}` : ''}.`, { bold: true });
  for (const fact of asArray(knowledge['known_facts']).filter(isRecord).slice(0, MAX_REPORT_FACTS)) {
    const subject = safeText(fact['subject_label'], 160);
    const label = safeText(fact['label'], 160);
    const value = safeText(fact['value'], 512);
    const unit = safeText(fact['unit'], 64);
    addParagraph(document, `${subject ? `${subject}: ` : ''}${label} — ${value}${unit ? ` ${unit}` : ''}.`);
  }
  for (const fact of asArray(knowledge['impact_delta']).filter(isRecord).slice(0, MAX_REPORT_FACTS)) {
    const subject = safeText(fact['subject_label'], 160);
    const label = safeText(fact['label'], 160);
    const value = safeText(fact['value'], 512);
    const unit = safeText(fact['unit'], 64);
    addParagraph(document, `${subject ? `${subject}: ` : ''}${label} — ${value}${unit ? ` ${unit}` : ''}.`, { bold: true });
  }
  const cycleComparison = asRecord(knowledge['cycle_comparison']);
  const beforeYear = formatNumber(cycleComparison['before_admission_year']);
  const afterYear = formatNumber(cycleComparison['after_admission_year']);
  if (beforeYear && afterYear) addParagraph(document, `Сравниваются приёмные кампании ${beforeYear} и ${afterYear}.`, { bold: true });
  for (const change of asArray(asRecord(knowledge['cycle_comparison'])['changes']).filter(isRecord).slice(0, MAX_REPORT_FACTS)) {
    const path = safeText(change['path'], 192);
    const before = safeText(change['before'], 1_000) || 'значение не установлено';
    const after = safeText(change['after'], 1_000) || 'значение не установлено';
    addParagraph(document, `${path}: было «${before}», стало «${after}».`);
  }
  const resolution = asRecord(knowledge['resolution']);
  if (Object.keys(resolution).length > 0) {
    addSubheading(document, `Разрешение правил: ${labelFor(resolution['state'], STATUS_LABELS)}`);
    const selectedRules = asArray(resolution['selected_rules']).filter(isRecord).slice(0, 20);
    for (const item of selectedRules) {
      const rule = asRecord(item['rule'] ?? item);
      addParagraph(document, `Выбрано правило ${safeText(rule['rule_reference'], 128)} (редакция ${formatNumber(rule['revision']) ?? 'не указана'}).`, { size: 9.5 });
    }
    for (const item of asArray(resolution['considered_rules']).filter(isRecord).slice(0, 40)) {
      const rule = asRecord(item['rule']);
      const disposition = labelFor(item['disposition'], DISPOSITION_LABELS);
      const reference = safeText(rule['rule_reference'], 128);
      if (reference) addParagraph(document, `Правило ${reference}: ${disposition}.`, { size: 9, color: COLORS.muted });
    }
    const conflicts = asArray(resolution['conflicts']).filter(isRecord).slice(0, 12);
    for (const conflict of conflicts) {
      const references = asArray(conflict['rules']).filter(isRecord).map((rule) => safeText(rule['rule_reference'], 128)).filter(Boolean);
      if (references.length > 0) addParagraph(document, `Неразрешённое противоречие: ${references.join(' и ')}.`, { color: COLORS.warning });
    }
    const blockers = asArray(resolution['blockers']).map((item) => safeText(item, 256)).filter(Boolean).slice(0, 16);
    for (const blocker of blockers) addParagraph(document, `Ограничение разрешения: ${blocker}.`, { color: COLORS.warning });
  }
  const affectedScope = asArray(knowledge['affected_scope']).filter(isRecord).slice(0, 40);
  if (affectedScope.length > 0) {
    addSubheading(document, 'Область применения');
    for (const scope of affectedScope) {
      const label = labelFor(scope['scope_kind'], SCOPE_LABELS);
      const reference = safeText(scope['scope_reference'], 320);
      addParagraph(document, `${label}${reference ? `: ${reference}` : ''}.`, { size: 9.5 });
    }
  }
  for (const exception of asArray(knowledge['exceptions']).filter(isRecord).slice(0, 20)) {
    const rules = asArray(exception['rules']).filter(isRecord).map((rule) => safeText(rule['rule_reference'], 128)).filter(Boolean);
    const selected = safeText(asRecord(exception['selected_rule'])['rule_reference'], 128);
    if (rules.length > 0) addParagraph(document, `Исключение между правилами ${rules.join(' и ')}${selected ? `; применено правило ${selected}` : '; конкретное применённое правило не установлено'}.`);
  }
  for (const assertion of asArray(knowledge['source_assertions']).filter(isRecord).slice(0, 20)) {
    const name = safeText(assertion['source_name'], 256) || 'Источник не указан';
    const stage = labelFor(assertion['stage'], STATUS_LABELS);
    const reliability = labelFor(assertion['reliability'], RELIABILITY_LABELS);
    const statement = safeText(assertion['assertion'], 1_000);
    addSubheading(document, `${name} — ${stage} (${reliability})`);
    if (statement) addParagraph(document, statement);
    const published = safeText(assertion['published_at'], 96);
    if (published) addParagraph(document, `Опубликовано: ${published}.`, { size: 9.5 });
    const adopted = safeText(assertion['adopted_at'], 96);
    if (adopted) addParagraph(document, `Принято: ${adopted}.`, { size: 9.5 });
    const effective = safeText(assertion['effective_from'], 96);
    if (effective) addParagraph(document, `Начало действия по источнику: ${effective}.`, { size: 9.5 });
  }
  const missingData = asArray(knowledge['missing_data']).map((item) => safeText(item, 256)).filter(Boolean).slice(0, 16);
  if (missingData.length > 0) addParagraph(document, `Чего не хватает для вывода: ${missingData.join('; ')}.`, { color: COLORS.warning });
  const uncertainties = asArray(knowledge['uncertainties']).map((item) => labelFor(item, STATUS_LABELS)).filter(Boolean).slice(0, 16);
  if (uncertainties.length > 0) addParagraph(document, `Ограничения: ${uncertainties.join('; ')}.`, { color: COLORS.warning });
};

const addSources = (document: InstanceType<typeof PDFDocument>, response: AssistantQueryResponse): void => {
  const sources = dataSources(response);
  if (sources.length === 0) return;
  addSectionHeading(document, 'Источники и основание');
  for (const source of sources) {
    const url = safeText(source['url'], 2_048);
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      continue;
    }
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password) continue;
    const kind = safeText(source['kind'], 96);
    const name = safeText(source['source_name'], 256) || SOURCE_LABELS[kind] || kind.replaceAll('_', ' ') || parsed.hostname;
    const locatorValue = source['locator'];
    const locatorDetails = asRecord(locatorValue);
    const locator = typeof locatorValue === 'string'
      ? safeText(locatorValue, 256).replace(/\brow=(\d+)\b/giu, 'строка $1').replace(/\bpage=(\d+)\b/giu, 'страница $1')
      : [
        typeof locatorDetails['page'] === 'number' ? `страница ${locatorDetails['page']}` : undefined,
        safeText(locatorDetails['section'], 256),
        safeText(locatorDetails['table'], 256) ? `таблица ${safeText(locatorDetails['table'], 256)}` : undefined,
        typeof locatorDetails['row'] === 'number' ? `строка ${locatorDetails['row']}` : undefined,
      ].filter(Boolean).join(', ');
    addParagraph(document, `${name}${locator ? ` — ${locator}` : ''}`, { bold: true, size: 9.5 });
    document.font('andromeda-regular').fontSize(8).fillColor(COLORS.teal).text(url, { width: CONTENT_WIDTH, link: parsed.toString(), underline: true });
    document.moveDown(0.35);
  }
};

const addAssumptions = (document: InstanceType<typeof PDFDocument>, response: AssistantQueryResponse): void => {
  const metadata = asRecord(response.response?.metadata);
  const assumptions = asArray(metadata['assumptions']).map((value) => safeText(value, 512)).filter(Boolean).slice(0, 16);
  const facts = [
    typeof metadata['admission_year'] === 'number' ? `Год приёма: ${metadata['admission_year']}` : undefined,
    typeof metadata['study_form'] === 'string' ? `Форма обучения: ${labelFor(metadata['study_form'], STUDY_FORM_LABELS)}` : undefined,
    typeof metadata['funding_type'] === 'string' ? `Финансирование: ${labelFor(metadata['funding_type'], FUNDING_LABELS)}` : undefined,
    ...assumptions,
  ].filter((value): value is string => value !== undefined);
  if (facts.length === 0) return;
  addSectionHeading(document, 'Параметры и допущения');
  for (const fact of [...new Set(facts)]) addParagraph(document, fact);
};

const drawPageFrame = (document: InstanceType<typeof PDFDocument>): void => {
  document.save();
  document.font('andromeda-bold').fontSize(8).fillColor(COLORS.violet).text('ANDROMEDA', LEFT, 29, { lineBreak: false });
  writeRichText(document, 'ОБРАЗОВАНИЕ · ПОСТУПЛЕНИЕ', { size: 8, color: COLORS.muted, x: LEFT + 112, y: 29 });
  document.strokeColor(COLORS.line).moveTo(LEFT, 47).lineTo(LEFT + CONTENT_WIDTH, 47).stroke();
  document.restore();
};

const finalizePageFrames = (document: InstanceType<typeof PDFDocument>): void => {
  const range = document.bufferedPageRange();
  for (let page = range.start; page < range.start + range.count; page += 1) {
    document.switchToPage(page);
    document.save();
    document.strokeColor(COLORS.line).moveTo(LEFT, 755).lineTo(LEFT + CONTENT_WIDTH, 755).stroke();
    writeRichText(document, `Сформировано ${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'long' }).format(new Date())}`, { size: 7.5, color: COLORS.muted, x: LEFT, y: 764 });
    writeRichText(document, `Страница ${page + 1}`, { size: 7.5, color: COLORS.muted, width: 55, x: LEFT + CONTENT_WIDTH - 55, y: 764 });
    document.restore();
  }
};

export const createAssistantReportPdf = async (result: AssistantQueryResponse): Promise<Buffer> => {
  if (result.state !== 'complete' || !result.response) throw new Error('A completed assistant result is required for a report');
  const title = titleFor(safeText(result.response.template, 128));
  const document = new PDFDocument({
    size: 'A4',
    margins: { top: 64, right: 44, bottom: 54, left: LEFT },
    bufferPages: true,
    info: { Title: title, Author: 'Andromeda', Subject: 'Персональный отчёт по ответу Andromeda' },
  });
  const chunks: Buffer[] = [];
  let size = 0;
  let sizeExceeded = false;
  const output = new Promise<Buffer>((resolveOutput, rejectOutput) => {
    document.on('data', (chunk: Buffer) => {
      if (sizeExceeded) return;
      size += chunk.byteLength;
      if (size > MAX_REPORT_BYTES) {
        sizeExceeded = true;
        rejectOutput(new Error('Generated report exceeds its size limit'));
        document.destroy();
        return;
      }
      chunks.push(chunk);
    });
    document.on('error', rejectOutput);
    document.on('end', () => {
      if (!sizeExceeded) resolveOutput(Buffer.concat(chunks, size));
    });
  });

  try {
    registerFonts(document);
    document.on('pageAdded', () => drawPageFrame(document));
    drawPageFrame(document);
    writeRichText(document, title, { bold: true, size: 23, color: COLORS.ink, width: CONTENT_WIDTH });
    document.moveDown(0.45);
    const responseMode = result.response.response_mode;
    if (responseMode === 'unverified_fallback') {
      addParagraph(document, 'Ответ вне проверенного покрытия Andromeda. Этот текст не является подтверждённым правилом или источником.', { bold: true, color: COLORS.warning });
    } else if (responseMode === 'source_backed_verbalization') {
      addParagraph(document, 'Ответ сформулирован по структурированным данным Andromeda; AI не добавляет в отчёт новые числовые значения или правила.', { color: COLORS.muted });
    }
    addParagraph(document, isAnalyticsResponse(result)
      ? analyticsSummaryText(result)
      : safeText(result.response.text, 8_000), { size: 11 });

    addAssumptions(document, result);
    if (isAnalyticsResponse(result)) addAnalytics(document, result);
    if (result.response.template === 'program-comparison-summary') addProgramComparison(document, result);
    if (result.response.template === 'admission-fit-summary') addAdmission(document, result);
    if (result.response.template === 'program-recommendations') addRecommendations(document, result);
    addKnowledge(document, result);
    addSources(document, result);
    addSectionHeading(document, 'Как читать отчёт');
    addParagraph(document, 'Неуказанное или недоступное значение не означает ноль и не является отрицательным фактом. Итоговый текст, числовые значения, статусы и ссылки взяты из завершённого ответа Andromeda.', { size: 9, color: COLORS.muted });

    finalizePageFrames(document);
    document.end();
  } catch (error) {
    document.destroy(error instanceof Error ? error : new Error('Report generation failed'));
    await output.catch(() => undefined);
    throw error;
  }
  return output;
};
