import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createMaxUpdateHandler } from '../../src/max/bot/handler.js';
import { normalizeMaxUpdate } from '../../src/max/bot/update.js';
import type { AssistantQueryResponse } from '../../src/max/client/andromeda-api.js';

const normalized = (updateType: string, update: unknown) => {
  const result = normalizeMaxUpdate({ updateType, update });
  assert.ok(result);
  return result;
};

const completeResult: AssistantQueryResponse = {
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
    text: 'Ответ Andromeda',
    actions: [],
    evidence: [],
    policy_version: 'response-policy.v1',
  },
};

test('start and help expose exactly four fixed example prompts as message buttons', async () => {
  const handle = createMaxUpdateHandler();
  const start = normalized('bot_started', {
    update_type: 'bot_started', timestamp: 1, chat_id: 2, user: { user_id: 3 }, payload: 'ignored-payload',
  });
  const startReply = await handle(start);
  assert.equal(startReply?.kind, 'chat');
  if (startReply?.kind !== 'chat') assert.fail('expected start chat');
  assert.match(startReply.text, /Andromeda/u);
  assert.deepEqual(startReply.buttons?.flat().map((button) => button.text), [
    'Подобрать программу',
    'Сравнить программы',
    'Оценить поступление',
    'Проверить правила и льготы',
  ]);

  const help = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 2,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: '/help@andromeda_bot' } },
  });
  const helpReply = await handle(help);
  assert.equal(helpReply?.kind, 'chat');
  if (helpReply?.kind === 'chat') assert.equal(helpReply.buttons?.flat().length, 4);
});

test('ordinary free text goes through the single assistant interaction and renders its typed result', async () => {
  const queries: string[] = [];
  const handle = createMaxUpdateHandler({
    assistant: {
      async query(_update, text) {
        queries.push(text);
        return { result: completeResult, restartedSession: false };
      },
    },
  });
  const message = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 1,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: 'Какие программы доступны?' } },
  });
  const reply = await handle(message);
  assert.deepEqual(queries, ['Какие программы доступны?']);
  assert.equal(reply?.kind, 'chat');
  if (reply?.kind === 'chat') {
    assert.match(reply.text, /Ответ рассчитан по данным Andromeda/u);
    assert.match(reply.text, /Ответ Andromeda/u);
  }
});

test('user-selected example buttons remain plain text prompts and do not create a second routing path', async () => {
  const queries: string[] = [];
  const handle = createMaxUpdateHandler({
    assistant: {
      async query(_update, text) {
        queries.push(text);
        return { result: completeResult, restartedSession: false };
      },
    },
  });
  const prompts = [
    'Подобрать программу',
    'Сравнить программы',
    'Оценить поступление',
    'Проверить правила и льготы',
  ];
  for (const [index, text] of prompts.entries()) {
    const message = normalized('message_created', {
      update_type: 'message_created',
      timestamp: index + 1,
      message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text } },
    });
    await handle(message);
  }
  assert.deepEqual(queries, prompts);
});

test('API failures return a generic user-safe response; callback forgery and lifecycle remain inert', async () => {
  const handle = createMaxUpdateHandler({
    assistant: {
      async query() {
        throw new Error('secret upstream body must not escape');
      },
    },
  });
  const message = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 1,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: 'Подбери программу' } },
  });
  const reply = await handle(message);
  assert.equal(reply?.kind, 'chat');
  if (reply?.kind === 'chat') {
    assert.match(reply.text, /Связь с Andromeda/u);
    assert.doesNotMatch(reply.text, /secret upstream body/u);
  }

  const callback = normalized('message_callback', {
    update_type: 'message_callback',
    timestamp: 2,
    callback: { callback_id: 'callback-id', payload: 'forged:action:resource', user: { user_id: 3 } },
  });
  assert.deepEqual(await handle(callback), {
    kind: 'callback',
    callbackId: 'callback-id',
    text: 'Это действие сейчас недоступно.',
  });

  const lifecycle = normalized('bot_removed', { update_type: 'bot_removed', timestamp: 3, chat_id: 2 });
  assert.equal(await handle(lifecycle), undefined);
});
