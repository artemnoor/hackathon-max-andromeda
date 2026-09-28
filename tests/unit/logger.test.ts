import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createLogger, redact } from '../../src/shared/logger.js';

test('logger recursively redacts credentials, initData, payload and platform identifiers', () => {
  const lines: string[] = [];
  const logger = createLogger({ level: 'debug', sink: (line) => lines.push(line) });
  logger.info({
    authorization: 'Bearer very-secret',
    'X-Max-Init-Data': 'auth_date=1&hash=secret',
    maxBotToken: 'bot-secret',
    webhook_secret: 'hook-secret',
    userId: 991122,
    payload: { message: 'private' },
    safe: 'accepted',
  }, 'update');
  const output = lines.join('\n');
  for (const secret of ['very-secret', 'auth_date=1', 'bot-secret', 'hook-secret', '991122', 'private']) {
    assert.equal(output.includes(secret), false);
  }
  assert.match(output, /accepted/u);
});

test('redact handles arrays, Error objects and null', () => {
  const value = redact({ items: [{ token: 'sensitive' }, null], error: new Error('token=secret') });
  const output = JSON.stringify(value);
  assert.match(output, /REDACTED/u);
  assert.doesNotMatch(output, /sensitive|secret/u);
});