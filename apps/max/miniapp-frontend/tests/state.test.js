import assert from 'node:assert/strict';
import test from 'node:test';
import { createStateManager, mergePersistedState } from '../src/app/state.js';
import { STORAGE_KEY } from '../src/app/storage.js';

test('missing persisted fields merge with defaults', () => {
  const restored = mergePersistedState({ scores: { russian: 91 }, shortlist: { iu5: 'backup' } });

  assert.equal(restored.scores.russian, 91);
  assert.equal(restored.shortlist.iu5, 'backup');
  assert.deepEqual(restored.comparison, []);
  assert.ok(Array.isArray(restored.comparison));
  assert.equal(restored.testStep, 0);
});

test('existing state survives a save and reload under the current storage key', () => {
  const values = new Map([[STORAGE_KEY, JSON.stringify({
    scores: { russian: 89, math: 93 },
    shortlist: { iu5: 'main', design: 'backup' },
    viewed: ['iu7'],
    comparison: ['iu5', 'iu7'],
    interests: { 'Аналитика': 3 },
    testStep: 2,
    testAnswers: [0, 1],
    finalChoice: 'iu7',
  })]]);
  const storage = {
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, value); },
  };

  const firstLoad = createStateManager({ storage });
  assert.equal(firstLoad.state.scores.russian, 89);
  assert.equal(firstLoad.state.shortlist.design, 'backup');
  firstLoad.update('test.persisted-change', (current) => { current.finalChoice = 'iu5'; });

  const reloaded = createStateManager({ storage });
  assert.equal(reloaded.state.scores.math, 93);
  assert.equal(reloaded.state.shortlist.design, 'backup');
  assert.deepEqual(reloaded.state.viewed, ['iu7']);
  assert.deepEqual(reloaded.state.comparison, ['iu5', 'iu7']);
  assert.equal(reloaded.state.interests['Аналитика'], 3);
  assert.equal(reloaded.state.testStep, 2);
  assert.equal(reloaded.state.testAnswers.length, 2);
  assert.equal(reloaded.state.finalChoice, 'iu5');
  assert.equal(values.has(STORAGE_KEY), true);
});
