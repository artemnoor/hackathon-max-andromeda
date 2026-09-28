import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isAllowedMaxApiUrl, isProductionOrigin, isPublicHostname, normalizeOrigins, parseHttpOrigin } from '../../src/shared/url-policy.js';

test('MAX API allowlist accepts only official HTTPS origin', () => {
  assert.equal(isAllowedMaxApiUrl('https://platform-api2.max.ru'), true);
  assert.equal(isAllowedMaxApiUrl('https://platform-api2.max.ru/'), true);
  assert.equal(isAllowedMaxApiUrl('http://platform-api2.max.ru'), false);
  assert.equal(isAllowedMaxApiUrl('https://platform-api2.max.ru.evil.example'), false);
  assert.equal(isAllowedMaxApiUrl('https://user:pass@platform-api2.max.ru'), false);
  assert.equal(isAllowedMaxApiUrl('https://platform-api2.max.ru/path'), false);
});

test('origins discard path, credentials, query and fragments', () => {
  assert.equal(parseHttpOrigin('https://mini.example.org'), 'https://mini.example.org');
  assert.equal(parseHttpOrigin('https://mini.example.org/path'), undefined);
  assert.equal(parseHttpOrigin('https://user@mini.example.org'), undefined);
  assert.deepEqual(normalizeOrigins(['https://mini.example.org', 'https://mini.example.org/']), ['https://mini.example.org']);
});

test('protected origins require public HTTPS origin', () => {
  assert.equal(isProductionOrigin('https://mini.example.org'), true);
  assert.equal(isProductionOrigin('http://mini.example.org'), false);
  assert.equal(isProductionOrigin('https://localhost'), false);
  assert.equal(isProductionOrigin('https://mini.example.org/path'), false);
  assert.equal(isProductionOrigin('https://127.0.0.1'), false);
  assert.equal(isProductionOrigin('https://192.168.1.20'), false);
  assert.equal(isPublicHostname('redis'), false);
});