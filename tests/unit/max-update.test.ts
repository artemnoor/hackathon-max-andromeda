import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AppError } from '../../src/shared/errors.js';
import { normalizeMaxUpdate } from '../../src/max/bot/update.js';

const user = { user_id: 42, first_name: 'Private name', username: 'private_handle' };

test('normalizes supported message, callback, bot-start and lifecycle updates', () => {
  const receivedAt = 1_800_000_000_000;
  const options = { now: () => receivedAt };
  const message = normalizeMaxUpdate({
    updateType: 'message_created',
    update: {
      update_type: 'message_created', timestamp: 100,
      message: { sender: user, recipient: { chat_id: 77 }, body: { mid: 'message-1', text: 'hello', attachments: [] } },
    },
  }, options);
  assert.equal(message?.kind, 'message_created');
  if (message?.kind !== 'message_created') assert.fail('expected message update');
  assert.equal(message.userId, 42);
  assert.equal(message.chatId, 77);
  assert.equal(message.text, 'hello');
  assert.equal(message.receivedAt, receivedAt);

  const callback = normalizeMaxUpdate({
    updateType: 'message_callback',
    update: {
      update_type: 'message_callback', timestamp: 101,
      callback: { callback_id: 'callback-1', payload: 'module:run', user },
      message: { body: { mid: 'message-1' }, recipient: { chat_id: 77 } },
    },
  }, options);
  assert.equal(callback?.kind, 'message_callback');
  if (callback?.kind !== 'message_callback') assert.fail('expected callback update');
  assert.equal(callback.callbackPayload, 'module:run');
  assert.equal(callback.chatId, 77);

  const started = normalizeMaxUpdate({
    updateType: 'bot_started',
    update: { update_type: 'bot_started', timestamp: 102, chat_id: 77, user, payload: 'opaque-start' },
  }, options);
  assert.equal(started?.kind, 'bot_started');
  if (started?.kind !== 'bot_started') assert.fail('expected start update');
  assert.equal(started.startPayload, 'opaque-start');

  const lifecycle = normalizeMaxUpdate({
    updateType: 'bot_added',
    update: { update_type: 'bot_added', timestamp: 103, chat_id: 77, user, is_channel: false },
  }, options);
  assert.equal(lifecycle?.kind, 'lifecycle');
  if (lifecycle?.kind !== 'lifecycle') assert.fail('expected lifecycle update');
  assert.equal(lifecycle.updateType, 'bot_added');
  assert.equal(lifecycle.chatId, 77);
});

test('ignores unknown updates and rejects type mismatch or missing user identity', () => {
  assert.equal(normalizeMaxUpdate({ updateType: 'message_edited', update: {} }), undefined);
  assert.throws(() => normalizeMaxUpdate({ updateType: 'message_created', update: { update_type: 'message_callback' } }), AppError);
  assert.throws(() => normalizeMaxUpdate({
    updateType: 'message_created',
    update: { update_type: 'message_created', timestamp: 1, message: { recipient: { chat_id: 77 }, body: { text: 'x' } } },
  }), AppError);
});

test('rejects overlong text, callback and start payloads by UTF-8 bytes', () => {
  assert.throws(() => normalizeMaxUpdate({
    updateType: 'message_created',
    update: { update_type: 'message_created', timestamp: 1, message: { sender: user, recipient: { chat_id: 1 }, body: { text: 'x'.repeat(8193) } } },
  }), AppError);
  assert.throws(() => normalizeMaxUpdate({
    updateType: 'message_callback',
    update: { update_type: 'message_callback', timestamp: 1, callback: { user, payload: 'x'.repeat(1025) } },
  }), AppError);
  assert.throws(() => normalizeMaxUpdate({
    updateType: 'bot_started',
    update: { update_type: 'bot_started', timestamp: 1, chat_id: 1, user, payload: 'x'.repeat(513) },
  }), AppError);
  assert.throws(() => normalizeMaxUpdate({
    updateType: 'message_created',
    update: { update_type: 'message_created', timestamp: 1, message: { sender: user, recipient: { chat_id: 1 }, body: { text: 'я'.repeat(5000) } } },
  }), AppError);
});

test('drops MAX profile and attachment payloads, retaining only bounded attachment metadata', () => {
  const normalized = normalizeMaxUpdate({
    updateType: 'message_created',
    update: {
      update_type: 'message_created', timestamp: 1,
      message: {
        sender: user,
        recipient: { chat_id: 5 },
        body: {
          text: 'hello',
          attachments: [
            { type: 'audio', payload: { token: 'audio-secret', transcription: 'private audio text' } },
            { type: 'contact', payload: { hash: 'contact-secret', vcf_info: 'private contact data' } },
            { type: 'image', payload: { url: 'https://private.example/image' } },
          ],
        },
      },
    },
  });
  assert.equal(normalized?.kind, 'message_created');
  if (normalized?.kind !== 'message_created') assert.fail('expected message update');
  assert.deepEqual(normalized.attachments, [
    { type: 'audio', hasAudioToken: true },
    { type: 'contact', hasContactSignature: true },
    { type: 'image' },
  ]);
  const serialized = JSON.stringify(normalized);
  for (const forbidden of ['Private name', 'private_handle', 'audio-secret', 'private audio text', 'contact-secret', 'private contact data', 'private.example']) {
    assert.equal(serialized.includes(forbidden), false);
  }
  assert.equal(normalized.userId, 42);
});

test('caps attachments and normalizes malformed attachment shapes safely', () => {
  const base = (attachments: unknown) => ({
    updateType: 'message_created',
    update: { update_type: 'message_created', timestamp: 1, message: { sender: user, recipient: { chat_id: 1 }, body: { attachments } } },
  });
  assert.throws(() => normalizeMaxUpdate(base(Array.from({ length: 17 }, () => ({ type: 'image' })))), AppError);
  assert.throws(() => normalizeMaxUpdate(base({ type: 'image' })), AppError);
  const normalized = normalizeMaxUpdate(base([null, { type: 4, payload: { token: 'hidden' } }]));
  assert.equal(normalized?.kind, 'message_created');
  if (normalized?.kind !== 'message_created') assert.fail('expected message update');
  assert.deepEqual(normalized.attachments, [{ type: 'unknown' }, { type: 'unknown' }]);
});

test('fallback update ids are deterministic and remain bounded without platform message ids', () => {
  const context = {
    updateType: 'message_created',
    update: { update_type: 'message_created', timestamp: 1, message: { sender: user, recipient: { chat_id: 1 }, body: { text: 'same' } } },
  };
  const first = normalizeMaxUpdate(context);
  const second = normalizeMaxUpdate(context);
  assert.equal(first?.updateId, second?.updateId);
  assert.match(first?.updateId ?? '', /^max_[a-f0-9]{32}$/u);
  assert.equal(normalizeMaxUpdate({ ...context, update: { ...context.update, timestamp: 2 } })?.updateId === first?.updateId, false);

  const hugeId = normalizeMaxUpdate({
    updateType: 'message_created',
    update: { update_type: 'message_created', timestamp: 1, message: { sender: user, recipient: { chat_id: 1 }, body: { mid: 'm'.repeat(1_000_000), text: 'same' } } },
  });
  assert.match(hugeId?.updateId ?? '', /^max_[a-f0-9]{32}$/u);
});
