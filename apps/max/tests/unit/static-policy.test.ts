import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MAX_BRIDGE_SCRIPT, miniAppContentSecurityPolicy } from '../../src/web/static-policy.js';

test('Mini App CSP permits only the official MAX bridge and required MAX frame parents', () => {
  assert.equal(MAX_BRIDGE_SCRIPT, 'https://st.max.ru/js/max-web-app.js');
  const policy = miniAppContentSecurityPolicy();
  assert.match(policy, /script-src 'self' https:\/\/st\.max\.ru/u);
  assert.match(policy, /frame-ancestors https:\/\/max\.ru https:\/\/web\.max\.ru/u);
  assert.match(policy, /connect-src 'self'/u);
  assert.match(policy, /style-src-attr 'unsafe-inline'/u);
  assert.doesNotMatch(policy, /script-src[^;]*unsafe-inline|unsafe-eval|\*/u);
});
