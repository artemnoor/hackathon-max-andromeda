import { createLogger } from '../../shared/logger.js';
import { calculatePlanStats, hasMinimumComparisonPrograms, normalizeComparisonScope, selectComparisonPrograms } from './logic.js';
import { matchProgramToProfile } from '../../shared/program-analytics.js';
import { escapeHtml, safeHttpUrl } from '../../shared/dom.js';
import { isBackendConfigured } from '../../api/client.js';

const logger = createLogger('comparison');
const curriculumCategories = [
  { id: 'programming', label: 'Программирование', color: '#a4cda9' },
  { id: 'math', label: 'Математика', color: '#8fc3d8' },
  { id: 'data', label: 'Данные, аналитика и ИИ', color: '#c0a2d4' },
  { id: 'systems', label: 'Системы, базы и сети', color: '#dfc17b' },
  { id: 'engineering', label: 'Инженерные дисциплины', color: '#d99ba1' },
  { id: 'other', label: 'Бизнес и другие области', color: '#90aaa8' },
];

export const comparisonMarkup = `<section class="page" id="page-compare">
  <div class="page-title"><div><div class="eyebrow">Мой выбор · сравнение</div><h1>Сравнить программы</h1><p>Посмотрите, как устроено обучение, и сопоставьте программы по важным для вас критериям.</p></div><div class="title-actions"><button class="btn btn-outline" data-compare-share>Поделиться</button><button class="btn btn-primary" data-compare-print>Сохранить в PDF</button></div></div>
  <div class="compare-data-note"><span class="compare-note-mark" aria-hidden="true">i</span><p>Распределение часов и дисциплин строится по учебным планам, загруженным в приложение. Локальная выборка сокращена; для официального вывода нужны планы и источники вуза.</p></div>
  <section class="compare-picker" aria-labelledby="compare-picker-title"><div class="compare-picker-head"><div><div class="eyebrow">Ваш список</div><h2 id="compare-picker-title">Программы для сравнения</h2></div><span class="compare-picker-count" id="compare-selected-count"></span></div><div class="comparison-select" id="compare-select"></div><p>Отметьте от двух до четырёх программ. Выбор синхронизируется с кнопками сравнения в каталоге и карточках.</p></section>
  <div id="compare-content"></div>
</section>`;

function normalized(value) {
  return String(value || '').toLocaleLowerCase('ru-RU').replaceAll('ё', 'е');
}

function classifyCourse(row) {
  const name = normalized(row?.[0]);
  const area = normalized(row?.[1]);
  if (/программ|алгоритм|разработк|кодирован|ооп|компилятор/.test(name) || area.includes('программ')) return 'programming';
  if (/математ|алгебр|геометр|теори.*вероят|статистик|дискрет/.test(name) || area.includes('математ')) return 'math';
  if (/искусственн интеллект|машинн обуч|нейрон|анализ данных|аналитик|моделировани.*данн|data/.test(name) || area.includes('аналитик')) return 'data';
  if (/баз.*данных|информационн систем|компьютерн сет|сетев|операционн систем|облачн|корпоративн.*систем|хранилищ данных/.test(name)
    || ['технологии', 'информационные системы'].includes(area)) return 'systems';
  if (/инженер|физик|электротех|архитектур.*эвм|прибор|инфраструктур/.test(name) || area.includes('инженер')) return 'engineering';
  return 'other';
}

function summarizeProgram(program, scope) {
  const plan = scope === 'all' ? program.curriculum : program.curriculum.filter((row) => Number(row[2]) === Number(scope));
  const categories = curriculumCategories.map((item) => ({ ...item, hours: 0, subjects: [] }));
  const byId = new Map(categories.map((item) => [item.id, item]));
  for (const row of plan) {
    const hours = Number(row?.[3]);
    if (!Number.isFinite(hours) || hours <= 0) continue;
    const category = byId.get(classifyCourse(row));
    category.hours += hours;
    category.subjects.push({ name: row[0], hours, semester: row[2], assessment: row[4], mandatory: row[5] !== false });
  }
  const totalHours = categories.reduce((sum, item) => sum + item.hours, 0);
  for (const category of categories) {
    category.percent = totalHours ? (category.hours / totalHours) * 100 : 0;
  }
  return { categories, totalHours, subjectCount: plan.length };
}

function numberLabel(value) {
  return new Intl.NumberFormat('ru-RU').format(Math.round(Number(value) || 0));
}

function donutMarkup(program, summary, selectedCategoryId) {
  const radius = 78;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const slices = summary.categories.filter((category) => category.hours > 0).map((category) => {
    const length = circumference * category.percent / 100;
    const gap = Math.min(2.5, length / 3);
    const isActive = selectedCategoryId === category.id;
    const isDimmed = selectedCategoryId && !isActive;
    const markup = `<circle class="comparison-donut-segment ${isActive ? 'is-active' : ''} ${isDimmed ? 'is-dimmed' : ''}" data-category-select="${category.id}" data-category="${category.id}" data-program="${escapeHtml(program.id)}" cx="120" cy="120" r="${radius}" style="--slice-color:${category.color}" stroke-dasharray="${Math.max(0, length - gap)} ${circumference - length + gap}" stroke-dashoffset="${-offset}" />`;
    offset += length;
    return markup;
  }).join('');
  return `<svg class="comparison-donut" viewBox="0 0 240 240" role="img" aria-label="Распределение часов программы ${escapeHtml(program.code)} по областям">
    <circle class="comparison-donut-track" cx="120" cy="120" r="${radius}" />
    <g transform="rotate(-90 120 120)">${slices}</g>
  </svg>`;
}

function renderProgramDonutCard(program, summary, selectedCategoryId) {
  const selected = summary.categories.find((item) => item.id === selectedCategoryId);
  const selectedText = selected
    ? `<strong>${Math.round(selected.percent)}%</strong><span>${escapeHtml(selected.label)}</span><small>${numberLabel(selected.hours)} ч. из ${numberLabel(summary.totalHours)}</small>`
    : `<strong>100%</strong><span>Весь учебный план</span><small>Выберите категорию ниже</small>`;
  const detail = selected
    ? selected.subjects.length
      ? `<div class="donut-subject-head"><div><span class="eyebrow">${escapeHtml(selected.label)}</span><strong>${numberLabel(selected.hours)} ч. · ${Math.round(selected.percent)}%</strong></div><span>${selected.subjects.length} дисциплин</span></div><ul class="donut-subject-list">${selected.subjects.slice(0, 5).map((subject) => `<li><span>${escapeHtml(subject.name)}</span><small>${numberLabel(subject.hours)} ч.</small></li>`).join('')}${selected.subjects.length > 5 ? `<li class="donut-more">и ещё ${selected.subjects.length - 5}</li>` : ''}</ul>`
      : '<div class="donut-detail-empty">В этой категории нет часов в выбранном периоде.</div>'
    : '<div class="donut-detail-empty">Нажмите на цветной сектор или выберите предметный блок в общей легенде.</div>';
  return `<article class="comparison-program-card" data-program-card="${escapeHtml(program.id)}">
    <header class="comparison-program-head">
      <div class="comparison-program-identity"><span class="comparison-program-code">${escapeHtml(program.code)}</span><div><h3>${escapeHtml(program.title)}</h3><p>${escapeHtml(program.university)}</p></div></div>
      <div class="comparison-program-total"><strong>${numberLabel(summary.totalHours)} ч.</strong><span>${summary.subjectCount} записей</span></div>
    </header>
    <div class="comparison-chart-layout">
      <div class="comparison-chart-wrap">${donutMarkup(program, summary, selectedCategoryId)}<div class="comparison-chart-center" aria-live="polite">${selectedText}</div></div>
      <div class="comparison-donut-detail">${detail}</div>
    </div>
    <div class="comparison-program-footer"><span>План ${summary.subjectCount ? 'по выбранным дисциплинам' : 'не содержит сведений'}</span><button type="button" class="text-btn" data-page="program" data-program="${escapeHtml(program.id)}">Открыть карточку ↗</button></div>
  </article>`;
}

function renderSharedLegend(programs, summaries, categories, selectedCategoryId) {
  const items = categories.map((category) => {
    const values = programs.map((program, index) => {
      const data = summaries[index].categories.find(({ id }) => id === category.id);
      return `<span><b>${escapeHtml(program.code)}</b> ${Math.round(data?.percent || 0)}%</span>`;
    }).join('');
    return `<button type="button" class="shared-legend-item ${selectedCategoryId === category.id ? 'is-active' : ''}" data-category-select="${category.id}" data-category="${category.id}" style="--category-color:${category.color}" aria-pressed="${selectedCategoryId === category.id}">
      <span class="shared-legend-dot" style="--category-color:${category.color}"></span><span class="shared-legend-name">${escapeHtml(category.label)}</span><span class="shared-legend-values">${values}</span>
    </button>`;
  }).join('');
  return `<section class="shared-legend-wrap" aria-labelledby="shared-legend-title">
    <div class="shared-legend-head"><div><div class="eyebrow">Общая легенда</div><h3 id="shared-legend-title">Одинаковый цвет — одна область</h3><p>Выбор подсветит эту область на всех диаграммах и покажет включённые дисциплины.</p></div><button class="compare-reset-category" type="button" data-category-reset ${selectedCategoryId ? '' : 'disabled'}>Сбросить выбор</button></div>
    <div class="shared-legend-grid">${items}</div>
  </section>`;
}

function renderCategoryCompare(programs, summaries, categories, selectedCategoryId) {
  return `<section class="category-compare-panel" aria-labelledby="category-compare-title">
    <div class="comparison-section-heading"><div><div class="eyebrow">Сопоставление долей</div><h3 id="category-compare-title">Часы по категориям</h3></div><span>Нажмите на строку, чтобы синхронно выделить её выше</span></div>
    <div class="category-compare-list" style="--program-count:${programs.length}">${categories.map((category) => `<button type="button" class="category-compare-row ${selectedCategoryId === category.id ? 'is-active' : ''}" data-category-select="${category.id}" data-category="${category.id}" style="--category-color:${category.color}" aria-pressed="${selectedCategoryId === category.id}">
      <span class="category-compare-name"><i style="--category-color:${category.color}"></i><b>${escapeHtml(category.label)}</b></span>
      <span class="category-compare-values">${programs.map((program, index) => {
        const data = summaries[index].categories.find(({ id }) => id === category.id);
        const percent = Math.round(data?.percent || 0);
        return `<span class="category-program-value"><span><small>${escapeHtml(program.code)}</small><b>${percent}%</b></span><i><em style="width:${percent}%;--category-color:${category.color}"></em></i><small class="category-hours">${numberLabel(data?.hours)} ч.</small></span>`;
      }).join('')}</span>
    </button>`).join('')}</div>
  </section>`;
}

function renderCourseDiff(selected) {
  const courseSets = selected.map((program) => new Set(program.curriculum.map((row) => row[0])));
  const commonCourses = [...(courseSets[0] || [])].filter((course) => courseSets.every((set) => set.has(course)));
  const uniqueCourses = selected.map((program, index) => ({
    program,
    courses: [...courseSets[index]].filter((course) => courseSets.every((set, other) => other === index || !set.has(course))),
  }));
  return `<section class="course-diff panel"><div class="eyebrow">Пересечение учебных планов</div><h3>${commonCourses.length} общих названий в текущих записях</h3><p>${commonCourses.length ? commonCourses.map(escapeHtml).join(' · ') : 'В представленных записях общих дисциплин не найдено.'}</p><div class="course-diff-grid">${uniqueCourses.map(({ program, courses }) => `<div><b>${escapeHtml(program.code)} · уникальные дисциплины</b><p>${courses.length ? courses.map(escapeHtml).join(' · ') : 'Уникальных записей не найдено.'}</p></div>`).join('')}</div><p class="small muted">Сравниваются точные названия в загруженных учебных планах. Сокращённая выборка может не отражать полный состав обучения.</p></section>`;
}

export function renderComparison({ root, programs, state, getProgram, formatMoney, scope, criterion = { value: 'admission' }, selectedCategory = { value: null } }) {
  const selector = root.getElementById('compare-select');
  const content = root.getElementById('compare-content');
  const selectedIds = state.comparison || [];
  const selected = selectComparisonPrograms(selectedIds, getProgram);
  selector.innerHTML = programs.map((program) => `<label class="compare-program-chip ${selectedIds.includes(program.id) ? 'is-selected' : ''}">
    <input type="checkbox" data-compare="${escapeHtml(program.id)}" ${selectedIds.includes(program.id) ? 'checked' : ''}>
    <span class="compare-chip-check" aria-hidden="true"></span><span><b>${escapeHtml(program.code)}</b><small>${escapeHtml(program.title)}</small></span>
  </label>`).join('');
  const count = root.getElementById('compare-selected-count');
  if (count) count.textContent = `${selected.length} из 4 выбрано`;

  if (!hasMinimumComparisonPrograms(selected)) {
    content.innerHTML = '<div class="comparison-empty"><span class="eyebrow">Нужно выбрать ещё один вариант</span><h2>Сравнение появится здесь</h2><p>Отметьте минимум две программы в списке выше.</p></div>';
    return;
  }

  const period = normalizeComparisonScope(scope.value, selected);
  scope.value = period.scope;
  const { maxSemester } = period;
  const scopeText = scope.value === 'all' ? 'Весь учебный план' : `${scope.value} семестр`;
  const summaries = selected.map((program) => summarizeProgram(program, scope.value));
  const availableCategoryIds = new Set(summaries.flatMap((summary) => summary.categories.filter((item) => item.hours > 0).map((item) => item.id)));
  const categories = curriculumCategories.filter(({ id }) => availableCategoryIds.has(id));
  if (!categories.some(({ id }) => id === selectedCategory.value)) selectedCategory.value = null;
  const selectedCategoryId = selectedCategory.value;
  const programCards = selected.map((program, index) => renderProgramDonutCard(program, summaries[index], selectedCategoryId)).join('');
  const totalCurriculumHours = summaries.reduce((sum, summary) => sum + summary.totalHours, 0);

  const differenceCards = selected.map((program, index) => {
    const summary = summaries[index];
    const leading = [...summary.categories].sort((a, b) => b.hours - a.hours)[0];
    return `<div class="compare-highlight"><span class="compare-highlight-code">${escapeHtml(program.code)}</span><strong>${escapeHtml(leading?.label || 'Нет данных')}</strong><span>${numberLabel(leading?.hours || 0)} ч. · ${Math.round(leading?.percent || 0)}% представленной выборки</span></div>`;
  }).join('');

  const semesterButtons = Array.from({ length: maxSemester }, (_, index) => `<button type="button" data-semester="${index + 1}" class="${scope.value === index + 1 ? 'active' : ''}" aria-pressed="${scope.value === index + 1}">${index + 1}</button>`).join('');
  const plans = selected.map((program) => {
    const stats = calculatePlanStats(program, scope.value);
    const areaRows = summaries[selected.indexOf(program)].categories.filter(({ hours }) => hours > 0).map((category) => {
      const width = stats.total ? Math.round((category.hours / stats.total) * 100) : 0;
      return `<div class="plan-row"><div class="plan-row-top"><span><i style="--category-color:${category.color}"></i>${escapeHtml(category.label)}</span><b>${numberLabel(category.hours)} ч.</b></div><div class="bar"><i style="width:${width}%;--category-color:${category.color}"></i></div></div>`;
    }).join('');
    const subjectRows = stats.subjects.length ? stats.subjects.map((row) => `<li class="subject-item"><b>${escapeHtml(row[0])}</b><span>${escapeHtml(row[1])} · ${escapeHtml(row[2] ?? '—')} семестр · ${numberLabel(row[3])} ч. · ${escapeHtml(row[4] || 'форма контроля не указана')} · ${row[5] === false ? 'элективная' : 'обязательная'}</span></li>`).join('') : '<li class="small muted">В выбранном периоде нет дисциплин.</li>';
    return `<article class="plan-card"><div class="plan-card-title"><span>${escapeHtml(program.code)}</span><h4>${escapeHtml(program.title)}</h4></div><p class="plan-total">${numberLabel(stats.total)} ч. · ${stats.subjects.length} записей · ${escapeHtml(scopeText)}</p><div class="plan-bars">${areaRows}</div><ul class="subject-list">${subjectRows}</ul></article>`;
  }).join('');

  const comparisonHeaders = selected.map((program) => `<th>${escapeHtml(program.code)}<span>${escapeHtml(program.title)}</span></th>`).join('');
  const profile = { scores: state.scores, examStatuses: state.examStatuses, interests: state.interests, preferences: state.preferences };
  const criteriaFit = selected.map((program) => matchProgramToProfile(program, profile));
  const cells = (mapper) => selected.map((program, index) => `<td>${mapper(program, criteriaFit[index])}</td>`).join('');
  const rowsByCriterion = {
    admission: [
      ['Исторический ориентир · год и источник нужно сверить', cells((program) => `<b>${escapeHtml(program.passing ?? '—')}</b>`)],
      ['Предметы ЕГЭ', cells((program) => escapeHtml(program.exams || 'Нет данных'))],
      ['Бюджетные места из API', cells((program) => escapeHtml(program.budget ?? '—'))],
      ['Совпадение с профилем', cells((program, fit) => fit.percent === null ? 'Недостаточно данных' : `${fit.percent}% · ${fit.matched}/${fit.total} критериев`)],
    ],
    learning: [
      [`Области учебного плана · ${scopeText.toLocaleLowerCase('ru-RU')}`, cells((program) => {
        const summary = summarizeProgram(program, scope.value);
        return summary.categories.filter(({ hours }) => hours > 0).map(({ label, hours }) => `${escapeHtml(label)}: ${numberLabel(hours)} ч.`).join('<br>') || 'Нет данных';
      })],
      ['Совпадение с предпочтениями', cells((program, fit) => fit.percent === null ? 'Нет данных' : `${fit.percent}% · ${fit.matched}/${fit.total}`)],
    ],
    cost: [
      ['Стоимость за год из API', cells((program) => escapeHtml(formatMoney(program.cost)))],
    ],
    conditions: [
      ['Форма обучения', cells((program) => escapeHtml(program.format || 'Не указана'))],
      ['Длительность по данным API', cells((program) => program.durationYears ? `${program.durationYears} лет` : 'Нет данных')],
      ['ВУЦ', cells((program) => program.vuc === 'yes' ? 'Есть' : program.vuc === 'no' ? 'Нет' : 'Нет подтверждённых данных')],
      ['Льготы / особые права', cells((program) => program.benefits === 'available' ? 'Указаны в данных API' : program.benefits === 'unavailable' ? 'Не указаны' : 'Нет подтверждённых данных')],
    ],
  };
  const rows = (rowsByCriterion[criterion.value] || rowsByCriterion.admission).map(([label, values]) => `<tr><th scope="row">${escapeHtml(label)}</th>${values}</tr>`).join('');

  const courseDiff = criterion.value === 'learning' ? renderCourseDiff(selected) : '';
  const exportDate = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'long' }).format(new Date());
  const sourceLinks = selected.map((program) => {
    const url = safeHttpUrl(program.provenance?.sourceUrl);
    return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(program.provenance.sourceTitle || program.code)}</a>` : '';
  }).filter(Boolean);
  const sourceSummary = sourceLinks.length ? sourceLinks.join(' · ') : (isBackendConfigured
    ? 'API не вернул ссылки на первоисточники.'
    : 'Нет ссылок на первоисточники в ответе API.');

  content.innerHTML = `<section class="comparison-board" aria-labelledby="comparison-board-title">
    <div class="comparison-board-head"><div><div class="eyebrow">Структура учебного плана</div><h2 id="comparison-board-title">Из чего состоит обучение</h2><p>Наведите или нажмите на категорию: одна область подсветится во всех программах.</p></div><div class="comparison-board-total"><strong>${numberLabel(totalCurriculumHours)} ч.</strong><span>учтено в выборке</span></div></div>
    <div class="comparison-program-grid">${programCards}</div>
    ${renderSharedLegend(selected, summaries, categories, selectedCategoryId)}
    ${renderCategoryCompare(selected, summaries, categories, selectedCategoryId)}
    <div class="comparison-highlight-row"><span class="eyebrow">Самый объёмный блок в каждой записи</span><div>${differenceCards}</div></div>
    <p class="comparison-source-note">Проценты рассчитаны от часов дисциплин, которые есть в загруженном плане. Пустые и неизвестные значения исключены; выборка может быть неполной.</p>
  </section>

  <section class="comparison-details" aria-labelledby="comparison-details-title">
    <div class="comparison-section-heading comparison-details-heading"><div><div class="eyebrow">Сводка</div><h2 id="comparison-details-title">Сравнить по критериям</h2></div><div class="comparison-criteria" role="tablist" aria-label="Критерии сравнения">${[['admission', 'Поступление'], ['learning', 'Обучение'], ['cost', 'Стоимость'], ['conditions', 'Условия']].map(([key, label]) => `<button type="button" role="tab" aria-selected="${criterion.value === key}" data-compare-criterion="${key}" class="${criterion.value === key ? 'active' : ''}">${label}</button>`).join('')}</div></div>
    <div class="compare-table"><table><thead><tr><th scope="col">Критерий</th>${comparisonHeaders}</tr></thead><tbody>${rows}</tbody></table></div>
    ${criterion.value === 'learning' ? `<div class="comparison-curriculum">
      <div class="curriculum-head"><div><div class="eyebrow">По семестрам</div><h3>Дисциплины и часы</h3><p>Переключите период, чтобы увидеть его состав в каждой программе.</p></div><div class="semester-switch" role="group" aria-label="Период учебного плана"><button type="button" data-semester="all" class="${scope.value === 'all' ? 'active' : ''}" aria-pressed="${scope.value === 'all'}">Весь план</button>${semesterButtons}</div></div>
      <div class="curriculum-subhead"><div class="eyebrow">${escapeHtml(scopeText)}</div><div class="plan-toggle" role="group" aria-label="Вид учебного плана"><button type="button" class="active">Часы</button><button type="button">Предметы</button></div></div>
      <div class="plan-grid hours-only">${plans}</div>
    </div>` : ''}
    ${courseDiff}
    <div class="print-export-meta"><strong>Сравнение Andromeda</strong><span>Сформировано ${exportDate}</span><span>Источники: ${sourceSummary}</span><span>Сведения о поступлении требуют проверки по правилам вуза.</span></div>
    <div class="compare-next-step"><div><strong>Сверить ЕГЭ с условиями программ?</strong><p>Откройте сценарий поступления для всего выбранного списка.</p></div><button class="btn btn-outline" data-page="admission-check">Проверить поступление →</button></div>
  </section>`;
  bindComparisonHover(root, selectedCategoryId);
  logger.debug('render.complete', { selectedCount: selected.length, curriculumScope: scope.value, categoryCount: categories.length });
}

function bindComparisonHover(root, selectedCategoryId) {
  const comparisonRoot = root.getElementById('compare-content');
  if (!comparisonRoot) return;
  const highlight = (categoryId) => {
    comparisonRoot.querySelectorAll('[data-category]').forEach((element) => {
      element.classList.toggle('is-hover', Boolean(categoryId) && element.dataset.category === categoryId);
      if (element.matches('.comparison-donut-segment')) {
        element.classList.toggle('is-dimmed', Boolean(categoryId) && element.dataset.category !== categoryId && element.dataset.category !== selectedCategoryId);
      }
    });
    comparisonRoot.querySelectorAll('.comparison-donut-segment').forEach((element) => {
      if (!categoryId) element.classList.toggle('is-dimmed', Boolean(selectedCategoryId) && element.dataset.category !== selectedCategoryId);
    });
  };
  comparisonRoot.querySelectorAll('[data-category-select]').forEach((element) => {
    element.addEventListener('mouseenter', () => highlight(element.dataset.categorySelect));
    element.addEventListener('mouseleave', () => highlight(null));
    element.addEventListener('focus', () => highlight(element.dataset.categorySelect));
    element.addEventListener('blur', () => highlight(null));
  });
}
