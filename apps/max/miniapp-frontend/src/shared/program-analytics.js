const normalize = (value) => String(value ?? '')
  .toLocaleLowerCase('ru-RU')
  .normalize('NFKC')
  .replaceAll('ё', 'е')
  .replace(/[^\p{L}\p{N}]+/gu, ' ')
  .trim();

const concepts = [
  { terms: ['ии', 'искусственный интеллект', 'нейросет', 'машинное обучение', 'ai'], areas: ['Аналитика', 'Программирование', 'Технологии'], courses: ['искусственный интеллект', 'машинное обучение', 'нейрон'], courseOnly: true },
  { terms: ['желез', 'аппарат', 'электроник', 'микропроцессор', 'сети', 'компьютерные системы'], areas: ['Инженерия', 'Технологии'], courses: ['архитектура эвм', 'компьютерные сети', 'операционные системы', 'электрон'] },
  { terms: ['программирование', 'разработка', 'код', 'software'], areas: ['Программирование'], courses: ['программ', 'алгоритм', 'разработ'] },
  { terms: ['математик', 'математика', 'math'], areas: ['Математика'], courses: ['математ', 'статист', 'дискрет'] },
  { terms: ['бизнес', 'экономик', 'финанс'], areas: ['Экономика', 'Управление'], courses: ['эконом', 'финанс', 'бизнес', 'управлен'] },
  { terms: ['дизайн', 'интерфейс', 'пользовател'], areas: ['Дизайн', 'Исследования'], courses: ['дизайн', 'интерфейс', 'пользовател'] },
];

function wordsFor(query) {
  return normalize(query).split(/\s+/).filter(Boolean);
}

function isNegation(word) {
  return ['без', 'меньше', 'минимум', 'избегать', 'не'].includes(word);
}

/** Parse broad Russian intent into positive and negative catalog concepts. */
export function parseProgramIntent(query) {
  const words = wordsFor(query);
  const positive = new Set();
  const negative = new Set();
  for (let index = 0; index < words.length; index += 1) {
    const word = words[index];
    for (const concept of concepts) {
      if (!concept.terms.some((term) => normalize(term).split(' ').some((piece) => word.includes(piece) || piece.includes(word)))) continue;
      const negated = words.slice(Math.max(0, index - 2), index).some(isNegation);
      (negated ? negative : positive).add(concept);
    }
  }
  const ignored = new Set(['и', 'но', 'с', 'для', 'по', 'в', 'на', 'меньше', 'больше', 'без', 'хочу', 'интересует']);
  const literal = words.filter((word) => !ignored.has(word) && ![...positive, ...negative].some((concept) => concept.terms.some((term) => normalize(term).split(' ').some((piece) => word.includes(piece)))));
  return { positive: [...positive], negative: [...negative], literal };
}

function searchDocument(program) {
  return normalize([
    program.title, program.university, program.dept, program.code,
    ...(program.areas || []), program.exams, program.description,
    ...(program.curriculum || []).map(([name, area]) => `${name} ${area}`),
  ].join(' '));
}

export function scoreProgramSearch(program, query) {
  const intent = parseProgramIntent(query);
  const document = searchDocument(program);
  const positiveHits = intent.positive.filter((concept) => (concept.courseOnly ? false : concept.areas.some((area) => program.areas?.includes(area)))
    || concept.courses.some((course) => document.includes(normalize(course)))).length;
  const negativeHits = intent.negative.filter((concept) => concept.courses.some((course) => document.includes(normalize(course)))).length;
  const literalHits = intent.literal.filter((word) => document.includes(word)).length;
  const score = positiveHits * 3 + literalHits - negativeHits * 4;
  const matches = intent.literal.length === 0 || literalHits > 0 || positiveHits > 0;
  const requiredPositiveMatch = intent.positive.length === 0 || positiveHits > 0 || literalHits > 0;
  return { score, matches: matches && requiredPositiveMatch, positiveHits, negativeHits, intent };
}

export function getCurriculumAnalysis(program) {
  const hoursByArea = {};
  for (const row of program?.curriculum || []) {
    if (!row?.[1] || !Number.isFinite(Number(row[3]))) continue;
    hoursByArea[row[1]] = (hoursByArea[row[1]] || 0) + Number(row[3]);
  }
  const totalHours = Object.values(hoursByArea).reduce((sum, value) => sum + value, 0);
  const areas = Object.entries(hoursByArea).map(([area, hours]) => {
    const share = totalHours ? hours / totalHours : 0;
    return { area, hours, share, level: share >= 0.35 ? 'Много' : share >= 0.16 ? 'Средне' : 'Мало' };
  }).sort((a, b) => b.hours - a.hours);
  return { totalHours, areas, source: 'sample-curriculum' };
}

export function getExamFit(program, scores = {}, examStatuses = {}) {
  const aliases = [
    ['Русский', 'russian'], ['Математика', 'math'], ['Информатика', 'informatics'],
    ['Обществознание', 'social-studies'], ['Физика', 'physics'], ['История', 'history'],
    ['Химия', 'chemistry'], ['Биология', 'biology'], ['Литература', 'literature'],
    ['Иностранный', 'foreign-language'],
  ];
  const required = String(program?.exams || '').split(/[·,]/).map((raw) => {
    const label = raw.trim();
    const match = aliases.find(([name]) => normalize(label).includes(normalize(name)));
    return { label, id: match?.[1] || null };
  });
  const items = required.map(({ label, id }) => {
    const value = id ? scores[id] : null;
    const status = examStatuses[id] || (value !== null && value !== undefined && value !== '' ? 'taken' : 'not-taken');
    return { label, id, status, score: value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null };
  });
  const unknown = items.filter((item) => !item.id);
  const missing = items.filter((item) => item.id && ['not-taken', 'expected'].includes(item.status));
  const provided = items.filter((item) => item.id && item.score !== null);
  return { required: items, providedCount: provided.length, missingCount: missing.length, unknownCount: unknown.length, complete: !missing.length && !unknown.length, source: 'demo-requirements' };
}

export function matchProgramToProfile(program, profile = {}) {
  const criteria = [];
  const interests = Object.entries(profile.interests || {}).filter(([, score]) => Number(score) > 0).map(([name]) => name);
  const areaAliases = {
    'Аналитика': ['Аналитика', 'Математика', 'Исследования'],
    'Технологии': ['Программирование', 'Технологии', 'Инженерия'],
    'Бизнес и управление': ['Экономика', 'Управление', 'Аналитика'],
    'Исследования и дизайн': ['Дизайн', 'Исследования', 'Технологии'],
  };
  const matchedInterests = interests.filter((interest) => (areaAliases[interest] || [interest]).some((area) => program.areas?.includes(area)));
  if (interests.length) criteria.push({ key: 'interests', label: 'Интересы', matched: matchedInterests.length > 0, detail: matchedInterests.length ? `Совпадает область: ${matchedInterests.join(', ')}` : 'Пока нет совпадения с отмеченными областями' });

  const subjectFit = getExamFit(program, profile.scores || {}, profile.examStatuses || {});
  if (Object.keys(profile.scores || {}).length || Object.keys(profile.examStatuses || {}).length) criteria.push({ key: 'exams', label: 'Предметы ЕГЭ', matched: subjectFit.providedCount > 0, detail: subjectFit.providedCount ? `Есть ${subjectFit.providedCount} совпадающих предмета из ${subjectFit.required.length}` : 'Нужные предметы пока не указаны' });

  const preferences = profile.preferences || {};
  if (preferences.form) criteria.push({ key: 'form', label: 'Форма', matched: program.format == null ? null : program.format === preferences.form, detail: `Вы выбрали: ${preferences.form}` });
  if (preferences.maxCost !== null && preferences.maxCost !== undefined && preferences.maxCost !== '') criteria.push({ key: 'cost', label: 'Стоимость', matched: program.cost == null ? null : Number(program.cost) > 0 && Number(program.cost) <= Number(preferences.maxCost), detail: `Предел: ${Number(preferences.maxCost).toLocaleString('ru-RU')} ₽ / год` });
  if (preferences.university) criteria.push({ key: 'university', label: 'Вуз', matched: program.university ? normalize(program.university).includes(normalize(preferences.university)) : null, detail: `Ищете: ${preferences.university}` });
  if (preferences.durationYears) criteria.push({ key: 'duration', label: 'Длительность', matched: program.durationYears == null ? null : Number(program.durationYears) === Number(preferences.durationYears), detail: `Предпочитаете: ${preferences.durationYears} лет` });
  if (preferences.degree) criteria.push({ key: 'degree', label: 'Ступень', matched: program.degree ? normalize(program.degree).includes(normalize(preferences.degree)) : null, detail: `Ищете: ${preferences.degree}` });
  if (preferences.budget) {
    const value = preferences.budget === 'budget' ? program.budget : program.cost;
    criteria.push({ key: 'budget', label: 'Финансирование', matched: value == null ? null : Number(value) > 0, detail: `Предпочитаете: ${preferences.budget === 'budget' ? 'бюджетное место' : 'платное обучение'}` });
  }
  if (preferences.vuc) criteria.push({ key: 'vuc', label: 'ВУЦ', matched: program.vuc === 'unknown' || program.vuc == null ? null : program.vuc === preferences.vuc, detail: program.vuc === 'unknown' || program.vuc == null ? 'По записи нет подтверждённых сведений о ВУЦ' : `Пожелание: ${preferences.vuc === 'yes' ? 'нужен ВУЦ' : 'ВУЦ не нужен'}` });

  const evaluable = criteria.filter(({ matched: value }) => value !== null);
  const matched = evaluable.filter(({ matched: value }) => value).length;
  return {
    matched,
    total: evaluable.length,
    percent: evaluable.length ? Math.round((matched / evaluable.length) * 100) : null,
    criteria,
    curriculum: getCurriculumAnalysis(program),
    exams: subjectFit,
  };
}
