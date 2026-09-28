import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createMaxUpdateHandler } from '../../src/max/bot/handler.js';
import { normalizeMaxUpdate } from '../../src/max/bot/update.js';

const normalized = (updateType: string, update: unknown) => {
  const result = normalizeMaxUpdate({ updateType, update });
  assert.ok(result);
  return result;
};

test('neutral /start and /help replies make the disconnected product boundary explicit', async () => {
  const handle = createMaxUpdateHandler();
  const start = normalized('bot_started', { update_type: 'bot_started', timestamp: 1, chat_id: 2, user: { user_id: 3 }, payload: 'ignored-payload' });
  assert.deepEqual(await handle(start), { kind: 'chat', text: 'MAX-контур запущен. Функции Andromeda пока не подключены.' });

  const help = normalized('message_created', {
    update_type: 'message_created', timestamp: 2,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: '/help@andromeda_bot' } },
  });
  assert.deepEqual(await handle(help), { kind: 'chat', text: 'Это техническая основа MAX Bot. Сценарии Andromeda будут подключены отдельно.' });
});

test('unknown messages and callbacks receive bounded honest fallback without business routing', async () => {
  const handle = createMaxUpdateHandler();
  const message = normalized('message_created', {
    update_type: 'message_created', timestamp: 1,
    message: { sender: { user_id: 3 }, recipient: { chat_id: 2 }, body: { text: 'Подбери программу' } },
  });
  assert.deepEqual(await handle(message), { kind: 'chat', text: 'Функции Andromeda пока не подключены.' });

  const callback = normalized('message_callback', {
    update_type: 'message_callback', timestamp: 2,
    callback: { callback_id: 'callback-id', payload: 'forged:action:resource', user: { user_id: 3 } },
  });
  assert.deepEqual(await handle(callback), { kind: 'callback', callbackId: 'callback-id', text: 'Это действие сейчас недоступно.' });

  const lifecycle = normalized('bot_removed', { update_type: 'bot_removed', timestamp: 3, chat_id: 2 });
  assert.equal(await handle(lifecycle), undefined);
});
