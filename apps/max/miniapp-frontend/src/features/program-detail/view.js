import { createLogger } from '../../shared/logger.js';
import { getCurriculumAnalysis, getExamFit, matchProgramToProfile } from '../../shared/program-analytics.js';
import { escapeHtml, safeHttpUrl } from '../../shared/dom.js';

const logger = createLogger('program-detail');

export const programDetailMarkup = String.raw`
<section class="page" id="page-program">
  <button class="back" data-page="catalog">← Вернуться к программам</button>
  <div id="program-detail"></div>
</section>
`;

export function renderProgram(id, { root, state, updateState, getProgram, programs }) {
  const program = getProgram(id) || programs[0];
  logger.debug('render.start', { programId: program.id });
  const profileFit = matchProgramToProfile(program, { scores: state.scores, examStatuses: state.examStatuses, interests: state.interests, preferences: state.preferences });
  const curriculumAnalysis = getCurriculumAnalysis(program);
  const examFit = getExamFit(program, state.scores, state.examStatuses);
  const provenance = program.provenance || {};
  const sourceUrl = safeHttpUrl(provenance.sourceUrl);

  if (!state.viewed.includes(program.id)) {
    updateState('program.viewed', (current) => current.viewed.push(program.id));
  }

  root.getElementById('program-detail').innerHTML = `
    <div class="detail-header">
      <div class="detail-code">${escapeHtml(program.code)}</div>
      <div>
        <div class="eyebrow">${escapeHtml(program.university)}</div>
        <h1>${escapeHtml(program.title)}</h1>
        <p class="muted">${escapeHtml(program.dept)}</p>
      </div>
      <div class="detail-actions">
        <button class="btn ${state.shortlist[program.id] ? 'btn-dark' : 'btn-outline'}" data-save="${escapeHtml(program.id)}">
          ${state.shortlist[program.id] ? '♥ В shortlist' : '♡ В shortlist'}
        </button>
        <button class="btn ${state.comparison.includes(program.id) ? 'btn-outline' : 'btn-primary'}" data-compare-toggle="${escapeHtml(program.id)}" aria-pressed="${state.comparison.includes(program.id)}" aria-label="${state.comparison.includes(program.id) ? 'Убрать из сравнения' : 'Добавить в сравнение'}" title="${state.comparison.includes(program.id) ? 'Убрать из сравнения' : 'Добавить в сравнение'}">${state.comparison.includes(program.id) ? 'Убрать из сравнения' : '⇄ Сравнить'}</button>
        <button class="btn btn-outline" id="detail-ask">✧ Спросить</button>
      </div>
    </div>
    <div class="detail-tabs">
      <button class="detail-tab active" data-tab="overview">Обзор</button>
      <button class="detail-tab" data-tab="curriculum">Учебный план</button>
      <button class="detail-tab" data-tab="admission">Поступление</button>
    </div>
    <div class="detail-layout">
      <div class="panel" id="detail-tab-content">
        <div class="eyebrow">О программе</div>
        <h3 style="margin-top:8px">${escapeHtml(program.description)}</h3>

        <div class="info-grid" style="margin-top:20px">
          <div class="info-tile"><b>${escapeHtml(program.passing ?? '—')}</b><span>проходной показатель из данных API</span></div>
          <div class="info-tile"><b>${escapeHtml(program.budget ?? '—')}</b><span>бюджетных мест · при наличии данных</span></div>
          <div class="info-tile"><b>${program.cost ? `${Math.round(program.cost / 1000)} тыс.` : '—'}</b><span>стоимость в год · при наличии данных</span></div>
        </div>
        <h3 style="margin-top:25px">Почему стоит изучить</h3>
        <div class="list">${program.fit.map((item) => `
          <div class="list-row"><span class="verified">✓</span><b style="flex:1">${escapeHtml(item)}</b></div>
        `).join('')}</div>
        <section class="program-personal-analysis"><div class="eyebrow">Для вашего профиля</div><h3>${profileFit.percent === null ? 'Добавьте критерии в профиль' : `${profileFit.percent}% совпадения по критериям`}</h3><p class="small muted">${profileFit.total ? `Совпало ${profileFit.matched} из ${profileFit.total} введённых критериев. Это не вероятность поступления.` : 'Процент появится после добавления предметов ЕГЭ, интересов или предпочтений.'}</p>${profileFit.criteria.map((criterion) => `<div class="analysis-line"><span>${criterion.matched ? '✓' : '·'} ${criterion.label}</span><small>${criterion.detail}</small></div>`).join('')}<div class="analysis-line"><span>Предметы ЕГЭ</span><small>${examFit.providedCount} из ${examFit.required.length} представлены в профиле; полный набор нужно сверить отдельно.</small></div></section>
        <section class="program-curriculum-analysis"><div class="eyebrow">Учебный план API</div><h3>Нагрузка по областям</h3><p class="small muted">Сводка рассчитана по дисциплинам и часам, возвращённым API.</p>${curriculumAnalysis.areas.map(({ area, hours, level, share }) => `<div class="analysis-line"><span>${escapeHtml(area)} · ${level.toLocaleLowerCase('ru-RU')}</span><small>${hours} ч. · ${Math.round(share * 100)}% представленных часов</small></div>`).join('')}</section>
      </div>
      <aside class="panel">
        <div class="eyebrow">Происхождение данных</div>
        <h3 style="margin-top:8px">${provenance.status === 'demo' || !provenance.status ? 'Запись программы из API' : `Статус записи: ${escapeHtml(provenance.status)}`}</h3>
        <div class="source"><span aria-hidden="true">ⓘ</span><span>${provenance.sourceTitle ? `Источник: ${escapeHtml(provenance.sourceTitle)}.` : 'Название источника не указано.'}${provenance.checkedAt ? ` Проверено: ${escapeHtml(provenance.checkedAt)}.` : ''} ${escapeHtml(provenance.note || 'Проверьте первоисточник и срок актуальности.')}</span></div>
        ${sourceUrl ? `<a class="text-btn" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Открыть источник ↗</a>` : ''}
        <div class="source" style="margin-top:8px"><span aria-hidden="true">ⓘ</span><span>План может содержать сокращённый набор дисциплин. Сверяйте объём с официальной версией.</span></div>
        <button class="btn btn-dark" style="width:100%;margin-top:15px" data-page="admission-check" data-program="${escapeHtml(program.id)}">Сверить поступление →</button>
        <button class="btn btn-outline" style="width:100%;margin-top:8px" data-page="rules">Открыть правила и льготы</button>
      </aside>
    </div>
  `;

  const askButton = root.getElementById('detail-ask');
  askButton.dataset.programId = program.id;
  askButton.dataset.programTitle = program.title;
  logger.debug('render.complete', { programId: program.id, curriculumCount: program.curriculum.length });
}

export function renderProgramTab(program, tabName, { root, formatMoney, state = {} }) {
  const content = root.getElementById('detail-tab-content');
  if (!content || !program) return;

  logger.debug('tab.render', { programId: program.id, tab: tabName });
  if (tabName === 'curriculum') {
    const interestAreas = {
      'Аналитика': ['Аналитика', 'Математика', 'Исследования'],
      'Технологии': ['Программирование', 'Технологии', 'Инженерия'],
      'Бизнес и управление': ['Экономика', 'Управление', 'Аналитика'],
      'Исследования и дизайн': ['Дизайн', 'Исследования', 'Технологии'],
    };
    const selectedInterests = Object.entries(state.interests || {}).filter(([, score]) => Number(score) > 0).map(([label]) => label);
    const selectedAreas = new Set(selectedInterests.flatMap((interest) => interestAreas[interest] || [interest]));
    const interestCourses = selectedAreas.size ? program.curriculum.filter((row) => selectedAreas.has(row[1])) : [];
    const interestHours = interestCourses.reduce((sum, row) => sum + Number(row[3] || 0), 0);
    content.innerHTML = `
      <div class="eyebrow">Учебный план</div>
      <h3 style="margin-top:8px">Что вы будете изучать</h3>
      <p class="muted small">Показаны дисциплины, полученные из учебного плана в API.</p>
      <div class="program-curriculum-analysis"><div class="eyebrow">Сводка по учебному плану</div><div class="analysis-grid">${getCurriculumAnalysis(program).areas.map(({ area, hours, level, share }) => `<div class="analysis-tile"><strong>${level} · ${area}</strong><span>${hours} ч. (${Math.round(share * 100)}% записанных часов)</span></div>`).join('')}</div><p class="small muted">«Много» — от 35% часов, «средне» — от 16%. Доля считается внутри этой сокращённой выборки.</p></div>
      <section class="program-personal-analysis"><div class="eyebrow">Относительно ваших интересов</div>${selectedInterests.length ? `<h3>${interestCourses.length} подходящих записей · ${interestHours} ч.</h3><p class="small muted">Области сопоставлены с интересами: ${selectedInterests.join(', ')}. Это тематическая связь, не индивидуальная оценка качества программы.</p><div class="interest-course-list">${interestCourses.length ? interestCourses.map((row) => `<div class="analysis-line"><span>${row[0]}</span><small>${row[1]} · ${row[3]} ч.</small></div>`).join('') : '<p class="small muted">В полученном учебном плане не найдено дисциплин по выбранным интересам.</p>'}</div>` : '<p class="small muted">Отметьте интересы в профиле, чтобы увидеть связанные дисциплины.</p>'}</section>
      <div class="compare-table"><table>
        <thead><tr><th>Дисциплина</th><th>Область</th><th>Семестр</th><th>Часы</th><th>Контроль</th><th>Статус</th></tr></thead>
        <tbody>${program.curriculum.map((row) => `
          <tr><td><b>${escapeHtml(row[0])}</b></td><td>${escapeHtml(row[1])}</td><td>${escapeHtml(row[2] ?? '—')}</td><td>${escapeHtml(row[3] ?? '—')}</td><td>${escapeHtml(row[4] ?? '—')}</td><td>${row[5] === false ? 'Элективная' : 'Обязательная'}</td></tr>
        `).join('')}</tbody>
      </table></div>
    `;
    return;
  }

  if (tabName === 'admission') {
    const fit = getExamFit(program, state.scores || {}, state.examStatuses || {});
    content.innerHTML = `
      <div class="eyebrow">Условия поступления</div>
      <h3 style="margin-top:8px">${escapeHtml(program.exams)}</h3>
      <div class="list" style="margin-top:16px">
        <div class="list-row"><span>Проходной показатель в записи API</span><b>${escapeHtml(program.passing ?? 'Не указано')}</b></div>
        <div class="list-row"><span>Бюджетные места · при наличии данных</span><b>${escapeHtml(program.budget ?? 'Не указано')}</b></div>
        <div class="list-row"><span>Стоимость обучения в записи API</span><b>${program.cost ? `${formatMoney(program.cost)} / год` : 'Не указано'}</b></div>
        <div class="list-row"><span>Форма обучения</span><b>${escapeHtml(program.format ?? 'Не указана')}</b></div>
      </div>
      <div class="source" style="margin-top:18px"><span>ⓘ</span><span>Это не официальное объявление и не гарантия приёма. Проверяйте актуальные условия на странице приёмной комиссии.</span></div>
      <div class="program-personal-analysis"><div class="eyebrow">Ваши предметы</div><h3>${fit.providedCount} из ${fit.required.length} отражены в профиле</h3>${fit.required.map((item) => `<div class="analysis-line"><span>${item.label}</span><small>${item.status === 'taken' ? (item.score === null ? 'сдан, балл не указан' : `${item.score} баллов`) : item.status === 'expected' ? 'ожидается' : item.status === 'range' ? 'баллы заданы диапазоном' : item.status === 'not-taken' ? 'не сдаётся' : 'предмет не сопоставлен'}</small></div>`).join('')}</div>
    `;
  }
}
