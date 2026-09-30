import assert from 'node:assert/strict';
import test from 'node:test';
import { mergePersistedState } from '../src/app/state.js';
import { getCompletedExamCount, getProfileScoreTotal, normalizeExamScores } from '../src/data/exam-subjects.js';

test('migrates saved EGE scores into a main profile without losing values', () => {
  const state = mergePersistedState({ scores: { russian: 91, math: 84, it: 97, extra: 7 } });

  assert.equal(state.examProfiles.length, 1);
  assert.equal(state.examProfiles[0].name, 'Основной профиль');
  assert.deepEqual(state.examProfiles[0].scores, { russian: 91, math: 84, informatics: 97, extra: 7 });
  assert.deepEqual(state.scores, state.examProfiles[0].scores);
});

test('restores the selected EGE profile and keeps its scores separate', () => {
  const state = mergePersistedState({
    examProfiles: [
      { id: 'first', name: 'Первый год', year: 2025, scores: { russian: 80 } },
      { id: 'second', name: 'Пересдача', year: 2026, scores: { russian: 95, math: 88 } },
    ],
    activeExamProfileId: 'second',
  });

  assert.equal(state.activeExamProfileId, 'second');
  assert.deepEqual(state.scores, { russian: 95, math: 88 });
  assert.deepEqual(state.examProfiles[0].scores, { russian: 80 });
});

test('ignores invalid or out-of-range stored exam scores', () => {
  const state = mergePersistedState({ scores: { russian: 101, math: -1, it: 'invalid', extra: 6 } });

  assert.deepEqual(state.scores, { extra: 6 });
});

test('keeps an incomplete selected subject and scores only the three highest EGE results', () => {
  const scores = normalizeExamScores({
    russian: 91,
    math: 84,
    informatics: 97,
    physics: null,
    history: 60,
    extra: 5,
  });

  assert.equal(scores.physics, null);
  assert.equal(getCompletedExamCount(scores), 4);
  assert.equal(getProfileScoreTotal(scores), 277);
});
