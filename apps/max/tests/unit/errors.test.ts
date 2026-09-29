import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AppError, ERROR_CODES, errorToPublicPayload, errorToLogFields } from '../../src/shared/errors.js';

test('public errors expose stable message and request id, never cause or stack', () => {
  const error = new AppError(ERROR_CODES.AUTH_INVALID, 401, 'Недействительная подпись.', undefined, {
    cause: new Error('Authorization: secret-provider-value'),
  });
  const payload = JSON.stringify(errorToPublicPayload(error, 'request-1'));
  assert.match(payload, /AUTH_INVALID/u);
  assert.match(payload, /request-1/u);
  assert.doesNotMatch(payload, /secret-provider-value|cause|stack/u);
});

test('unknown internal errors become generic public failures', () => {
  const payload = errorToPublicPayload(new Error('private path /home/user/token'));
  assert.deepEqual(payload, { error: { code: 'INTERNAL_ERROR', message: 'Внутренняя ошибка сервиса.' } });
});

test('error logging excludes internal message and cause', () => {
  const fields = errorToLogFields(new Error('token=secret'));
  assert.deepEqual(fields, { errorName: 'Error' });
});