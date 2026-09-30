import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { expandedCurriculum } from '../src/data/curriculum.js';
import { admissionCheckMarkup } from '../src/features/admission-check/view.js';
import { newsMarkup } from '../src/features/news/view.js';
import { olympiadsMarkup } from '../src/features/olympiads/view.js';
import { personalRouteMarkup } from '../src/features/personal-route/view.js';
import { interestQuestions } from '../src/data/interest-questions.js';
import { programs } from '../src/data/programs.js';
import { STORAGE_KEY } from '../src/app/storage.js';
import { homeMarkup } from '../src/features/home/view.js';
import { catalogMarkup } from '../src/features/catalog/view.js';
import { programDetailMarkup } from '../src/features/program-detail/view.js';
import { comparisonMarkup } from '../src/features/comparison/view.js';
import { profileMarkup } from '../src/features/profile/view.js';
import { shortlistMarkup } from '../src/features/shortlist/view.js';
import { interestTestMarkup } from '../src/features/interest-test/view.js';
import { recommendationsMarkup } from '../src/features/recommendations/view.js';
import { rulesMarkup } from '../src/features/rules/view.js';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const pageMarkup = [
  homeMarkup,
  catalogMarkup,
  programDetailMarkup,
  comparisonMarkup,
  profileMarkup,
  shortlistMarkup,
  interestTestMarkup,
  recommendationsMarkup,
  rulesMarkup,
  newsMarkup,
  olympiadsMarkup,
  personalRouteMarkup,
  admissionCheckMarkup,
].join('\n');

test('preserves the cloned app title and all restored page roots', () => {
  assert.match(html, /<title>Andromeda — выбор программы<\/title>/);
  assert.deepEqual(
    [...pageMarkup.matchAll(/id="page-([^"]+)"/g)].map((match) => match[1]),
    ['home', 'catalog', 'program', 'compare', 'profile', 'shortlist', 'proftest', 'recommendations', 'rules', 'news', 'olympiads', 'personal-route', 'admission-check'],
  );
});

test('loads separated stylesheets and the native module entry point', () => {
  assert.doesNotMatch(html, /<style\b/i);
  assert.ok([...html.matchAll(/<link rel="stylesheet"/g)].length >= 24);
  assert.match(html, /src\/features\/catalog\/styles\.css/);
  assert.match(html, /https:\/\/st\.max\.ru\/js\/max-web-app\.js/);
  assert.match(html, /<script type="module" src="src\/main\.js"><\/script>/);
});

test('does not ship mock programs or curriculum records', () => {
  assert.deepEqual(programs, []);
  assert.deepEqual(expandedCurriculum, {});
});

test('preserves five interest-test questions and the local storage key', () => {
  assert.equal(interestQuestions.length, 5);
  assert.equal(STORAGE_KEY, 'andromeda-state');
});
