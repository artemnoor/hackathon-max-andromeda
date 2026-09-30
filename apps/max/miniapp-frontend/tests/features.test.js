import assert from 'node:assert/strict';
import test from 'node:test';
import { backendApi, ApiError } from '../src/api/client.js';
import { catalogRepository } from '../src/app/repository.js';
import { interestQuestions } from '../src/data/interest-questions.js';
import { programs } from '../src/data/programs.js';
import { hasMinimumComparisonPrograms, normalizeComparisonScope, selectComparisonPrograms, calculatePlanStats } from '../src/features/comparison/logic.js';
import { calculateInterestProfile } from '../src/features/interest-test/logic.js';

test('Public catalog can load outside MAX while personal recommendations require MAX launch data', async () => {
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (path, options) => {
    requests.push({ path, options });
    return Response.json({ items: [] });
  };
  try {
    await backendApi.listPrograms();
    assert.equal(requests[0].path, '/api/max/catalog/programs');
    assert.equal(new Headers(requests[0].options.headers).has('X-Max-Init-Data'), false);
    await assert.rejects(catalogRepository.getRecommendations(), (error) => error instanceof ApiError && error.status === 401);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('recommendations never fall back to hard-coded programs', async () => {
  await assert.rejects(catalogRepository.getRecommendations(), (error) => error instanceof ApiError && error.status === 401);
  assert.deepEqual(programs, []);
});

test('comparison uses returned program records and scopes their curriculum by semester', () => {
  const apiPrograms = [
    { id: 'program:test:01.01.01-01', curriculum: [['Алгебра', 'Математика', 1, 72, 'Экзамен', true]] },
    { id: 'program:test:01.01.01-02', curriculum: [['Программирование', 'Информатика', 2, 108, 'Экзамен', true]] },
  ];
  const byId = new Map(apiPrograms.map((program) => [program.id, program]));
  const selected = selectComparisonPrograms([...byId.keys()], (id) => byId.get(id));
  assert.equal(hasMinimumComparisonPrograms(selected), true);
  assert.equal(calculatePlanStats(selected[1], 2).total, 108);
  assert.equal(normalizeComparisonScope(99, selected).scope, 'all');
});

test('interest profile counts answers by the existing category order', () => {
  const profile = calculateInterestProfile([0, 1, 1, 3, 0]);
  assert.equal(profile['Аналитика'], 2);
  assert.equal(profile['Технологии'], 2);
  assert.equal(profile['Бизнес и управление'], 0);
  assert.equal(profile['Исследования и дизайн'], 1);
  assert.equal(interestQuestions.length, 5);
});
