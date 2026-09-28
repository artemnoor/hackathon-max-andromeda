import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { AssistantQueryResponse } from '../../src/max/client/andromeda-api.js';
import { renderAssistantResult } from '../../src/max/bot/response-renderer.js';

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
  assert.equal(bounded[0]?.text, 'На какой год вы планируете поступление?');
  assert.deepEqual(bounded[0]?.buttons?.flat().map((button) => button.text), ['2027', '2028', '2029', '2030']);

  const unbounded = renderAssistantResult(result({
    state: 'needs_clarification',
    question: 'Какой предмет?',
    options: ['Математика', 'Физика', 'Информатика', 'Химия', 'Биология'],
  }));
  assert.equal(unbounded[0]?.buttons, undefined);
  assert.match(unbounded[0]?.text ?? '', /ответить своими словами/u);
});

test('completion renders only allowlisted human fields and clearly labels unverified fallback', () => {
  const rendered = renderAssistantResult(result({
    response: {
      response_type: 'text',
      response_mode: 'source_backed_verbalization',
      template: 'assistant.answer',
      text: 'Условия подтверждены источником.',
      actions: [{ action: 'compare', label: 'Сравнить программы' }],
      evidence: [{ metric_code: 'admission.minimum_score', coverage: '2 официальных источника', evidence_count: 2 }],
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
  assert.match(text, /Правило разрешено по данным Andromeda/u);
  assert.match(text, /может относиться в будущем/u);
  assert.match(text, /официальных источника/u);
  assert.match(text, /Сравнить программы/u);
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
  assert.match(fallback[0]?.text ?? '', /непроверенный ответ вне базы Andromeda/u);
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
  assert.ok(rendered.map((message) => message.text).join('').includes(body));

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
