import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { AssistantQueryResponse } from '../../src/max/client/andromeda-api.js';
import {
  renderAssistantResult,
  renderAssistantResultWithReport,
} from '../../src/max/bot/response-renderer.js';

const result = (overrides: Record<string, unknown> = {}): AssistantQueryResponse => ({
  state: 'complete',
  session_id: 'query-session:' + 'a'.repeat(32),
  revision: 1,
  options: [],
  missing_slots: [],
  admission_requests: [],
  response: {
    response_type: 'text',
    response_mode: 'deterministic',
    template: 'assistant.answer',
    text: 'Ответ из структурированных данных.',
    actions: [],
    evidence: [],
    policy_version: 'response-policy.v1',
    data: { secret: 'never render raw data' },
    metadata: { internal: 'never render metadata' },
    knowledge: {
      schema_version: 'knowledge-response.v1',
      status: 'policy_resolved',
      actionability: 'informational',
      source_assertions: [],
      known_facts: [],
      affected_scope: [],
      exceptions: [],
      impact_delta: [],
      uncertainties: [],
    },
  },
  ...overrides,
} as unknown as AssistantQueryResponse);

test('clarification uses bounded message buttons and falls back to free text for larger option sets', () => {
  const bounded = renderAssistantResult(result({
    state: 'needs_clarification',
    question: 'На какой год вы планируете поступление?',
    options: ['2027', '2028', '2029', '2030'],
  }));
  assert.equal(bounded.length, 1);
  assert.equal(bounded[0]?.text, 'На какой год вы планируете поступление?\n\nНажмите вариант или напишите свой ответ.');
  assert.deepEqual(bounded[0]?.buttons?.flat().map((button) => button.text), ['2027', '2028', '2029', '2030']);

  const unbounded = renderAssistantResult(result({
    state: 'needs_clarification',
    question: 'Какой предмет?',
    options: ['Математика', 'Физика', 'Информатика', 'Химия', 'Биология'],
  }));
  assert.equal(unbounded[0]?.buttons, undefined);
  assert.match(unbounded[0]?.text ?? '', /можно своими словами/u);
});

test('exam clarification asks for real user values without sample scores', () => {
  const rendered = renderAssistantResult(result({
    state: 'needs_clarification',
    question: 'Какие баллы ЕГЭ у вас есть? Укажите предмет и результат каждого экзамена.',
    options: [],
  }));

  assert.equal(rendered.length, 1);
  assert.match(rendered[0]?.text ?? '', /баллы ЕГЭ/u);
  assert.doesNotMatch(rendered[0]?.text ?? '', /\d/u);
  assert.equal(rendered[0]?.buttons, undefined);
  assert.match(rendered[0]?.text ?? '', /Ответьте сообщением/u);
});

test('completion renders only allowlisted human fields and clearly labels unverified fallback', () => {
  const rendered = renderAssistantResult(result({
    response: {
      response_type: 'text',
      response_mode: 'source_backed_verbalization',
      template: 'assistant.answer',
      text: 'Условия подтверждены источником.',
      actions: [
        { action: 'compare', label: 'Сравнить программы' },
        { action: 'show_details', label: 'Подробнее' },
        { action: 'change_scope', label: 'Изменить параметры' },
        { action: 'show_curriculum', label: 'Учебный план' },
        { action: 'add_to_shortlist', label: 'Добавить в мой выбор' },
      ],
      evidence: [
        { metric_code: 'admission.minimum_score', coverage: '2 официальных источника', evidence_count: 2 },
        { metric_code: 'math_share', coverage: '0.8', evidence_count: 5 },
      ],
      policy_version: 'response-policy.v1',
      data: { private: 'INTERNAL_DATA_MARKER' },
      metadata: { private: 'INTERNAL_METADATA_MARKER' },
      knowledge: {
        schema_version: 'knowledge-response.v1',
        status: 'policy_resolved',
        actionability: 'future_only',
        source_assertions: [],
        known_facts: [],
        affected_scope: [],
        exceptions: [],
        impact_delta: [],
        uncertainties: [],
      },
    },
  }));
  const text = rendered.map((message) => message.text).join('\n');
  assert.match(text, /проверенным данным Andromeda/u);
  assert.match(text, /Правило найдено в проверенных источниках/u);
  assert.match(text, /может относиться в будущем/u);
  assert.match(text, /Доля математики: охват 80%/u);
  assert.doesNotMatch(text, /admission\.minimum_score|math_share|официальных источника/u);
  assert.doesNotMatch(text, /Доступно в Andromeda|Добавить в мой выбор/u);
  assert.deepEqual(rendered.at(-1)?.buttons, [
    [{ text: 'Сравнить программы', callbackPayload: 'assistant:compare' }],
    [{ text: 'Подробнее', callbackPayload: 'assistant:show_details' }],
    [{ text: 'Изменить параметры', callbackPayload: 'assistant:change_scope' }],
    [{ text: 'Учебный план', callbackPayload: 'assistant:show_curriculum' }],
  ]);
  assert.doesNotMatch(text, /INTERNAL_DATA_MARKER|INTERNAL_METADATA_MARKER/u);

  const fallback = renderAssistantResult(result({
    response: {
      response_type: 'text',
      response_mode: 'unverified_fallback',
      template: 'assistant.answer',
      text: 'Общий ответ.',
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
    },
  }));
  assert.match(fallback[0]?.text ?? '', /Общий ответ вне проверенной базы Andromeda/u);
  assert.deepEqual(fallback[0]?.buttons, []);
});

test('unverified AI fallback has one clear warning and does not promise source details in the PDF', async () => {
  const rendered = await renderAssistantResultWithReport(result({
    response: {
      response_type: 'text',
      response_mode: 'unverified_fallback',
      template: 'assistant.unverified',
      text: '⚠️ Общий ответ ИИ, не подтверждённый данными Andromeda.\\n\\nСравнить это по проверенной базе не могу.',
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
    },
  }));
  const renderedText = rendered.map((message) => message.text).join('\\n');
  const warnings = renderedText.match(/Общий ответ/gu) ?? [];

  assert.equal(warnings.length, 1);
  assert.match(renderedText, /Полный текст общего ответа приложен в PDF/u);
  assert.doesNotMatch(renderedText, /доступные источники/u);
  assert.equal(rendered.flatMap((message) => message.document ? [message.document] : []).length, 1);
});


test('completed structured results include a valid PDF report attachment', async () => {
  const rendered = await renderAssistantResultWithReport(result({
    response: {
      response_type: 'text',
      response_mode: 'deterministic',
      template: 'admission-fit-summary',
      text: 'Проверено программ: 1.',
      data: {
        outcomes: {
          by_program_id: {
            'program:bmstu:09.03.01-02': {
              result: {
                program_name: 'Информатика и вычислительная техника',
                status: 'realistic',
                score: 82,
                applicant_total_score: '270',
                breakdown: {},
                reasons: [],
                anti_reasons: [],
                data_gaps: [],
              },
            },
          },
        },
      },
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
      metadata: { study_form: 'full_time', funding_type: 'budget' },
    },
  }));
  const documents = rendered.flatMap((message) => message.document ? [message.document] : []);

  assert.equal(documents.length, 1);
  assert.match(documents[0]?.filename ?? '', /^andromeda-otchet-[0-9-]+\.pdf$/u);
  assert.equal(documents[0]?.content.subarray(0, 5).toString('ascii'), '%PDF-');
});

test('long Russian response is sent completely in UTF-8 bounded chunks and never silently truncated', () => {
  const body = 'абв🙂'.repeat(1_800);
  const rendered = renderAssistantResult(result({
    response: {
      response_type: 'text',
      response_mode: 'deterministic',
      template: 'assistant.answer',
      text: body,
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
    },
  }));
  assert.ok(rendered.length > 1);
  assert.ok(rendered.every((message) => Buffer.byteLength(message.text, 'utf8') <= 2_000));
  assert.ok(rendered.map((message) => message.text).join('').startsWith(body));
  assert.match(rendered.map((message) => message.text).join(''), /Подробный разбор и доступные источники/u);

  assert.throws(() => renderAssistantResult(result({
    response: {
      response_type: 'text',
      response_mode: 'deterministic',
      template: 'assistant.answer',
      text: 'слишком длинно'.repeat(7_000),
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
    },
  })));
});

test('long natural language is split at paragraph or sentence boundaries without losing content', () => {
  const sentence = 'Первое предложение объясняет данные пользователю. Второе предложение содержит следующий шаг.';
  const paragraph = Array.from({ length: 20 }, () => sentence).join(' ');
  const body = `${paragraph}\n\n${paragraph}\n\n${paragraph}`;
  const rendered = renderAssistantResult(result({
    response: {
      response_type: 'text',
      response_mode: 'deterministic',
      template: 'assistant.answer',
      text: body,
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
    },
  }));

  assert.ok(rendered.length > 1);
  assert.ok(rendered.map((message) => message.text).join('').startsWith(body));
  assert.match(rendered.map((message) => message.text).join(''), /Подробный разбор и доступные источники/u);
  assert.ok(rendered.every((message) => Buffer.byteLength(message.text, 'utf8') <= 2_000));
  assert.ok(rendered.slice(0, -1).every((message) => /\s$/u.test(message.text)));
});


test('program recommendations render the university long name used by official source data', () => {
  const longUniversityName = 'федеральное государственное автономное образовательное учреждение высшего образования «Московский государственный технический университет имени Н.Э. Баумана (национальный исследовательский университет)»';
  const rendered = renderAssistantResult(result({
    response: {
      response_type: 'text',
      response_mode: 'deterministic',
      template: 'program-recommendations',
      text: 'Найдены программы.',
      data: {
        recommendations: [{
          program_id: 'program:bmstu:09.03.01-12',
          program_code: '09.03.01-12',
          program_name: 'Искусственный интеллект в системах обработки информации и управления',
          university_name: longUniversityName,
          content_fit: 50,
          reasons: [],
        }],
      },
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
    },
  }));
  const renderedText = rendered.map((message) => message.text).join('\\n');

  assert.ok(Buffer.byteLength(longUniversityName, 'utf8') > 256);
  assert.match(renderedText, /Московский государственный технический университет имени Н\.Э\. Баумана/u);
});


test('program discovery renders source-backed recommendations and attaches their detailed PDF', async () => {
  const rendered = await renderAssistantResultWithReport(result({
    response: {
      response_type: 'text',
      response_mode: 'deterministic',
      template: 'program-recommendations',
      text: 'Нашла одну программу по проверяемому учебному плану.',
      data: {
        recommendations: [{
          program_id: 'program:bmstu:09.03.01-02',
          program_code: '09.03.01-02',
          program_name: 'Информатика и вычислительная техника',
          university_name: 'МГТУ им. Н. Э. Баумана',
          content_fit: 82,
          reasons: [{ text: 'В учебном плане есть программирование.', provenance: [{ url: 'https://example.edu/plan.pdf', kind: 'curriculum', locator: 'стр. 4' }] }],
          anti_fit_reasons: [],
          evidence: { catalog_completeness: { status: 'partial' } },
          provenance: [{ url: 'https://example.edu/plan.pdf', kind: 'curriculum', locator: 'стр. 4' }],
          source_gaps: [],
        }],
        sources: [{ url: 'https://example.edu/plan.pdf', source_name: 'Учебный план', kind: 'curriculum', locator: 'стр. 4' }],
      },
      actions: [],
      evidence: [],
      policy_version: 'response-policy.v1',
    },
  }));
  const messages = rendered.map((message) => message.text).join('\n');
  const pdf = rendered.flatMap((message) => message.document ? [message.document] : []);

  assert.match(messages, /Информатика и вычислительная техника/u);
  assert.match(messages, /82\/100/u);
  assert.match(messages, /не шанс поступления/u);
  assert.equal(pdf.length, 1);
  assert.equal(pdf[0]?.content.subarray(0, 5).toString('ascii'), '%PDF-');
});
