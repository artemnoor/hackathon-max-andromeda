import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AppError } from '../../src/shared/errors.js';
import { callbackActionDefinitions, callbackTokenHash, parseCallbackAction } from '../../src/max/callbacks/actions.js';

const actor = { userId: 42, chatId: 77 };

test('callback actions are empty by default and only registered actions are accepted', async () => {
  assert.equal(callbackActionDefinitions().length, 0);
  await assert.rejects(() => parseCallbackAction('module:run', callbackActionDefinitions(), actor),
    (error: unknown) => error instanceof AppError && error.code === 'FORBIDDEN');

  const action = await parseCallbackAction('module:run:opaque-resource-1', callbackActionDefinitions([
    { namespace: 'module', verb: 'run', requiresResource: true, authorize: ({ resource }, current) => resource === 'opaque-resource-1' && current.userId === 42 },
  ]), actor);
  assert.deepEqual(action, { namespace: 'module', verb: 'run', resource: 'opaque-resource-1' });
});

test('callback parser rejects malformed, oversized, forged and resource-mismatched actions', async () => {
  const definitions = callbackActionDefinitions([{ namespace: 'module', verb: 'open', requiresResource: false }]);
  for (const input of ['', 'module', 'Module:open', 'module:open:', 'module:open:resource:extra', 'module:open:has space', 'module:open:' + 'x'.repeat(1024)]) {
    await assert.rejects(() => parseCallbackAction(input, definitions, actor), AppError);
  }
  await assert.rejects(() => parseCallbackAction('other:open', definitions, actor),
    (error: unknown) => error instanceof AppError && error.code === 'FORBIDDEN');
  await assert.rejects(() => parseCallbackAction('module:open:resource', definitions, actor),
    (error: unknown) => error instanceof AppError && error.code === 'FORBIDDEN');
});

test('resource callbacks require their declared capability authorization hook', async () => {
  const definition = { namespace: 'safe', verb: 'view', requiresResource: true, authorize: () => false };
  await assert.rejects(() => parseCallbackAction('safe:view:resource-1', [definition], actor),
    (error: unknown) => error instanceof AppError && error.code === 'FORBIDDEN');
  assert.equal(callbackTokenHash('safe:view:resource-1').length, 16);
});

test('callback parser response never echoes raw action or resource through public errors', async () => {
  const sentinel = 'opaque-sensitive-resource';
  await assert.rejects(() => parseCallbackAction(`forged:view:${sentinel}`, [], actor), (error: unknown) => {
    assert.ok(error instanceof AppError);
    assert.equal(JSON.stringify(error.toPublicPayload()).includes(sentinel), false);
    return true;
  });
});
