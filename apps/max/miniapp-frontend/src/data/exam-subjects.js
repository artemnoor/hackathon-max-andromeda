export const EGE_SUBJECTS = Object.freeze([
  { id: 'russian', label: 'Русский язык', icon: 'А', group: 'Основные', color: '#bacaff', background: '#181c25' },
  { id: 'math', label: 'Математика (профильная)', icon: '∑', group: 'Основные', color: '#91abff', background: '#181c25' },
  { id: 'math-basic', label: 'Математика (базовая)', icon: 'π', group: 'Основные', color: '#91abff', background: '#181c25' },
  { id: 'social-studies', label: 'Обществознание', icon: '◎', group: 'Гуманитарные', color: '#e7b66d', background: '#332716' },
  { id: 'history', label: 'История', icon: '⌛', group: 'Гуманитарные', color: '#f28d91', background: '#381d20' },
  { id: 'literature', label: 'Литература', icon: '✒', group: 'Гуманитарные', color: '#baa2f4', background: '#29213b' },
  { id: 'foreign-language', label: 'Иностранный язык', icon: '文', group: 'Гуманитарные', color: '#70d5a8', background: '#142f25' },
  { id: 'informatics', label: 'Информатика', icon: '⌘', group: 'Естественные и технические', color: '#bacaff', background: '#181c25' },
  { id: 'physics', label: 'Физика', icon: '⚛', group: 'Естественные и технические', color: '#70d5a8', background: '#142f25' },
  { id: 'chemistry', label: 'Химия', icon: '◇', group: 'Естественные и технические', color: '#70d5a8', background: '#142f25' },
  { id: 'biology', label: 'Биология', icon: '✿', group: 'Естественные и технические', color: '#70d5a8', background: '#142f25' },
  { id: 'geography', label: 'География', icon: '◉', group: 'Естественные и технические', color: '#e7b66d', background: '#332716' },
]);

export const EGE_SUBJECT_GROUPS = Object.freeze([
  'Основные',
  'Гуманитарные',
  'Естественные и технические',
]);

const egeSubjectIds = new Set(EGE_SUBJECTS.map(({ id }) => id));

export function normalizeExamScores(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return {};

  const scores = {};
  for (const [sourceKey, rawScore] of Object.entries(value)) {
    const subjectId = sourceKey === 'it' ? 'informatics' : sourceKey;
    if (!egeSubjectIds.has(subjectId)) continue;
    if (rawScore === null || rawScore === '') {
      scores[subjectId] = null;
      continue;
    }
    const score = Number(rawScore);
    if (Number.isFinite(score) && score >= 0 && score <= 100) scores[subjectId] = score;
  }

  if (Object.hasOwn(value, 'extra')) {
    const extra = Number(value.extra);
    if (Number.isFinite(extra) && extra >= 0 && extra <= 10) scores.extra = extra;
  }
  return scores;
}

export function getProfileScoreTotal(scores = {}) {
  const egeScores = Object.entries(scores)
    .filter(([subjectId, score]) => egeSubjectIds.has(subjectId) && Number.isFinite(Number(score)))
    .map(([, score]) => Number(score))
    .sort((left, right) => right - left)
    .slice(0, 3);
  return egeScores.reduce((total, score) => total + score, Number(scores.extra || 0));
}

export function getEnteredExamCount(scores = {}) {
  return Object.keys(scores).filter((subjectId) => egeSubjectIds.has(subjectId)).length;
}

export function getCompletedExamCount(scores = {}) {
  return Object.entries(scores).filter(([subjectId, score]) => (
    egeSubjectIds.has(subjectId) && score !== null && score !== '' && Number.isFinite(Number(score))
  )).length;
}
