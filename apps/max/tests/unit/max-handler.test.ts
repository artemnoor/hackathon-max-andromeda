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

const clarificationResult: AssistantQueryResponse = {
  ...completeResult,
  state: 'needs_clarification',
  response: null,
  question: 'Какие программы сравнить?',
  options: [],
  missing_slots: ['entity'],
};

const replyText = (reply: Awaited<ReturnType<ReturnType<typeof createMaxUpdateHandler>>>): string => {
  if (reply?.kind === 'chat') return reply.text;
  if (reply?.kind === 'batch') return reply.messages.map((message) => message.text).join('\n');
  return '';
};

const EXAMPLE_COMPARISON_QUERY = 'Чем ИУ5 (09.03.01-02) отличается от ИУ7 (09.03.04-01) по учебным планам?';

test('start and help open a free-text conversation without a fixed scenario menu', async () => {
  const handle = createMaxUpdateHandler();
  const start = normalized('bot_started', {
    update_type: 'bot_started', timestamp: 1, chat_id: 2, user: { user_id: 3 }, payload: 'ignored-payload',
  });
  const startReply = await handle(start);
  assert.equal(startReply?.kind, 'chat');
  if (startReply?.kind !== 'chat') assert.fail('expected start chat');
  assert.match(startReply.text, /Andromeda/u);
  assert.match(startReply.text, /своими словами/u);
  assert.deepEqual(startReply.buttons, [[{ text: EXAMPLE_COMPARISON_QUERY }]]);

  const help = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 2,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: '/help@andromeda_bot' } },
  });
  const helpReply = await handle(help);
  assert.equal(helpReply?.kind, 'chat');
  if (helpReply?.kind === 'chat') {
    assert.match(helpReply.text, /обычным сообщением/u);
    assert.equal(helpReply.buttons, undefined);
  }
});

test('start and help offer the configured catalog as a direct website link', async () => {
  const handle = createMaxUpdateHandler({ miniAppPublicUrl: 'https://mini.example.org' });
  const start = normalized('bot_started', {
    update_type: 'bot_started', timestamp: 1, chat_id: 2, user: { user_id: 3 }, payload: '',
  });
  const reply = await handle(start);
  assert.equal(reply?.kind, 'chat');
  if (reply?.kind !== 'chat') assert.fail('expected start chat');
  assert.deepEqual(reply.buttons, [
    [{ text: 'Открыть каталог', linkUrl: 'https://mini.example.org/?page=catalog' }],
    [{ text: EXAMPLE_COMPARISON_QUERY }],
  ]);
});

test('/start example is sent through the assistant and produces a PDF result', async () => {
  const queries: string[] = [];
  const handle = createMaxUpdateHandler({
    assistant: {
      async query(_update, text) { queries.push(text); return { result: completeResult, restartedSession: false }; },
      async resetConversation() {},
    },
  });
  const start = normalized('bot_started', {
    update_type: 'bot_started', timestamp: 1, chat_id: 2, user: { user_id: 3 }, payload: '',
  });
  const startReply = await handle(start);
  assert.equal(startReply?.kind, 'chat');
  if (startReply?.kind !== 'chat') assert.fail('expected start chat');

  const sample = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 2,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: startReply.buttons?.[0]?.[0]?.text } },
  });
  const result = await handle(sample);

  assert.deepEqual(queries, [EXAMPLE_COMPARISON_QUERY]);
  assert.equal(result?.kind, 'batch');
  if (result?.kind !== 'batch') assert.fail('expected answer with report');
  assert.equal(result.messages.at(-1)?.document?.content.subarray(0, 5).toString('ascii'), '%PDF-');
});

test('ordinary free text goes through the single assistant interaction and renders its typed result', async () => {
  const queries: string[] = [];
  const handle = createMaxUpdateHandler({
    assistant: {
      async query(_update, text) {
        queries.push(text);
        return { result: clarificationResult, restartedSession: false };
      },
      async resetConversation() {},
    },
  });
  const message = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 1,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: 'Какие программы доступны?' } },
  });
  const reply = await handle(message);
  assert.deepEqual(queries, ['Какие программы доступны?']);
  assert.match(replyText(reply), /Какие программы сравнить/u);
  assert.doesNotMatch(replyText(reply), /Ответ рассчитан по данным Andromeda/u);
});

test('task-like phrases and ordinary questions use the same assistant interaction', async () => {
  const queries: Array<{ text: string }> = [];
  const resets: number[] = [];
  const handle = createMaxUpdateHandler({
    assistant: {
      async query(_update, text) {
        queries.push({ text });
        return { result: clarificationResult, restartedSession: false };
      },
      async resetConversation(update) {
        if ('userId' in update && update.userId) resets.push(update.userId);
      },
    },
  });
  const prompts = ['Куда я поступлю с моими баллами?', 'Сравни программную инженерию и бизнес-информатику'];
  for (const [index, text] of prompts.entries()) {
    const message = normalized('message_created', {
      update_type: 'message_created',
      timestamp: index + 1,
      message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text } },
    });
    await handle(message);
  }
  assert.deepEqual(queries, prompts.map((text) => ({ text })));

  const ownQuestion = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 3,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: 'Что можно узнать о поступлении?' } },
  });
  const reply = await handle(ownQuestion);
  assert.match(replyText(reply), /Какие программы сравнить/u);
  assert.equal(queries.length, 3);
  assert.deepEqual(resets, []);
});

test('/start resets prior conversation context before opening free text', async () => {
  const resets: number[] = [];
  const handle = createMaxUpdateHandler({
    assistant: {
      async query() { return { result: completeResult, restartedSession: false }; },
      async resetConversation(update) {
        if ('userId' in update && update.userId) resets.push(update.userId);
      },
    },
  });
  const start = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 4,
    message: { sender: { user_id: 18 }, recipient: { chat_id: 2 }, body: { text: '/start' } },
  });

  const reply = await handle(start);

  assert.equal(reply?.kind, 'chat');
  assert.deepEqual(resets, [18]);
});

test('former home-menu label is ordinary user text, not a hidden scenario command', async () => {
  const queries: string[] = [];
  const resets: number[] = [];
  const handle = createMaxUpdateHandler({
    assistant: {
      async query(_update, text) { queries.push(text); return { result: clarificationResult, restartedSession: false }; },
      async resetConversation(update) {
        if ('userId' in update && update.userId) resets.push(update.userId);
      },
    },
  });
  const message = normalized('message_created', {
    update_type: 'message_created',
    timestamp: 5,
    message: { sender: { user_id: 19 }, recipient: { chat_id: 2 }, body: { text: '🏠 Главное меню' } },
  });

  const reply = await handle(message);

  assert.equal(reply?.kind, 'chat');
  assert.deepEqual(queries, ['🏠 Главное меню']);
  assert.deepEqual(resets, []);
});

test('approved read-only response actions are callbacks routed through the same assistant session', async () => {
  const queries: string[] = [];
  const result: AssistantQueryResponse = {
    ...completeResult,
    response: {
      ...completeResult.response!,
      actions: [{ action: 'compare', label: 'Сравнить программы' }],
    },
  };
  const handle = createMaxUpdateHandler({
    assistant: {
      async query(_update, text) {
        queries.push(text);
        return { result, restartedSession: false };
      },
      async resetConversation() {},
    },
  });
  const callback = normalized('message_callback', {
    update_type: 'message_callback',
    timestamp: 2,
    chat_id: 77,
    callback: { callback_id: 'callback-id', payload: 'assistant:compare', user: { user_id: 3 } },
  });

  const reply = await handle(callback);

  assert.deepEqual(queries, ['Сравни первые две программы из подборки']);
  assert.equal(reply?.kind, 'callback');
  if (reply?.kind !== 'callback') assert.fail('expected callback reply');
  assert.equal(reply.callbackId, 'callback-id');
  assert.equal(reply.text, 'Готово.');
  assert.equal(reply.messages?.length, 2);
  assert.match(reply.messages?.[0]?.text ?? '', /Ответ Andromeda/u);
  assert.deepEqual(reply.messages?.[1]?.buttons, [
    [{ text: 'Сравнить программы', callbackPayload: 'assistant:compare' }],
  ]);
  assert.equal(reply.messages?.[1]?.document?.content.subarray(0, 5).toString('ascii'), '%PDF-');
  assert.equal(result.response?.actions[0]?.action, 'compare');
});

test('API failures return a generic user-safe response; callback forgery and lifecycle remain inert', async () => {
  const handle = createMaxUpdateHandler({
    assistant: {
      async query() {
        throw new Error('secret upstream body must not escape');
      },
      async resetConversation() {},
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
