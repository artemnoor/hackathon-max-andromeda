import test from 'node:test';
import assert from 'node:assert/strict';
import { educationNews } from '../src/features/news/education-news.js';
import { handleNewsLinkClick } from '../src/features/news/view.js';
import { normalizeRemoteProgram } from '../src/app/repository.js';

test('program exam labels preserve subject names returned as strings by admissions API', () => {
  const program = normalizeRemoteProgram({
    id: 'program:bmstu:01.03.02-01',
    exams: [
      { subject: 'Математика профильная', isRequired: true },
      { subject: { name: 'Русский язык' }, isRequired: true },
      { subjectId: 'physics' },
    ],
  });

  assert.equal(program.exams, 'Математика профильная · Русский язык · physics');
});

test('education news feed contains ten dated items with original official source links', () => {
  assert.equal(educationNews.length, 10);
  assert.equal(new Set(educationNews.map((item) => item.id)).size, 10);
  for (const item of educationNews) {
    assert.match(item.publishedAt, /^2026-\d{2}-\d{2}$/u);
    assert.ok(item.title.length > 10);
    assert.ok(item.summary.length > 20);
    assert.match(item.url, /^https:\/\/(?:edu\.gov\.ru|mephi\.ru)\//u);
    assert.ok(['Минпросвещения России', 'НИЯУ МИФИ'].includes(item.sourceName));
  }
});

test('news links open through MAX Bridge on a user click', () => {
  const calls = [];
  let prevented = false;
  const link = { href: 'https://edu.gov.ru/press/12122/story/' };
  const handled = handleNewsLinkClick({
    target: { closest: (selector) => selector === '.news-card-link[href]' ? link : null },
    preventDefault: () => { prevented = true; },
  }, { openLink: (url) => calls.push(url) });

  assert.equal(handled, true);
  assert.equal(prevented, true);
  assert.deepEqual(calls, [link.href]);
});
