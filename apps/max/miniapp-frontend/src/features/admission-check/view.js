import { EGE_SUBJECTS } from '../../data/exam-subjects.js';
import { escapeHtml } from '../../shared/dom.js';
import { backendApi, isBackendConfigured } from '../../api/client.js';
import { olympiads } from '../../data/olympiads.js';

const subjectAliases = [
  ['русский', 'russian'], ['математика', 'math'], ['информатика', 'informatics'],
  ['обществознание', 'social-studies'], ['история', 'history'], ['литература', 'literature'],
  ['иностранный', 'foreign-language'], ['физика', 'physics'], ['химия', 'chemistry'],
  ['биология', 'biology'], ['география', 'geography'],
];

function getRequiredSubjects(program) {
  return String(program.exams || '').split(/[·,]/).map((raw) => {
    const label = raw.trim();
    const alias = subjectAliases.find(([match]) => label.toLocaleLowerCase('ru-RU').includes(match));
    return alias ? { id: alias[1], label: EGE_SUBJECTS.find(({ id }) => id === alias[1])?.label || label } : { id: null, label };
  });
}

function readScenario(root) {
  const scores = {};
  const examStatuses = {};
  const examRanges = {};
  for (const row of root.querySelectorAll('[data-admission-subject]')) {
    const id = row.dataset.admissionSubject;
    const status = row.querySelector('[data-admission-status]')?.value || 'not-taken';
    const rawScore = row.querySelector('[data-admission-score]')?.value;
    examStatuses[id] = status;
    scores[id] = status === 'taken' && rawScore !== '' ? Number(rawScore) : null;
    if (status === 'range') {
      const min = row.querySelector('[data-admission-range-min]')?.value ?? '';
      const max = row.querySelector('[data-admission-range-max]')?.value ?? '';
      examRanges[id] = { min: min === '' ? null : Number(min), max: max === '' ? null : Number(max) };
    }
  }
  const selectedOlympiadText = root.getElementById('scenario-olympiad-record')?.value || '';
  const selectedOlympiadNumber = Number(selectedOlympiadText.match(/^\s*(\d+)\s*\./)?.[1]) || null;
  return {
    scores,
    examStatuses,
    examRanges,
    rights: {
      bvi: root.getElementById('scenario-bvi')?.checked === true,
      olympiad: root.getElementById('scenario-olympiad')?.checked === true,
      benefits: root.getElementById('scenario-benefit')?.checked === true,
      paidTrack: root.getElementById('scenario-paid')?.checked === true,
      olympiadNumber: selectedOlympiadNumber,
      olympiadProfile: root.getElementById('scenario-olympiad-profile')?.value.trim() || '',
      olympiadAward: root.getElementById('scenario-olympiad-award')?.value || 'winner',
      benefitId: root.getElementById('scenario-benefit-id')?.value.trim() || '',
    },
  };
}

function evaluateProgram(program, scenario) {
  const required = getRequiredSubjects(program);
  const values = required.map((subject) => {
    if (!subject.id) return { ...subject, status: 'unknown', min: null, max: null };
    const status = scenario.examStatuses[subject.id] || (scenario.scores[subject.id] != null ? 'taken' : 'not-taken');
    if (status === 'taken' && scenario.scores[subject.id] !== null && Number.isFinite(Number(scenario.scores[subject.id]))) {
      return { ...subject, status, min: Number(scenario.scores[subject.id]), max: Number(scenario.scores[subject.id]) };
    }
    if (status === 'range') {
      const range = scenario.examRanges[subject.id] || {};
      if (range.min !== null && range.max !== null && Number.isFinite(Number(range.min)) && Number.isFinite(Number(range.max)) && Number(range.min) <= Number(range.max)) {
        return { ...subject, status, min: Number(range.min), max: Number(range.max) };
      }
    }
    return { ...subject, status, min: null, max: null };
  });
  const complete = values.every(({ min, max }) => min !== null && max !== null);
  const low = complete ? values.reduce((sum, item) => sum + item.min, 0) : null;
  const high = complete ? values.reduce((sum, item) => sum + item.max, 0) : null;
  const threshold = program.passing === null || program.passing === undefined || program.passing === '' ? null : Number(program.passing);
  let key = 'incomplete';
  let label = 'Нужны данные по предметам';
  let detail = `${values.filter(({ min }) => min !== null).length} из ${values.length} вступительных испытаний учтено; демонстрационный ориентир требует проверки.`;
  if (complete && threshold !== null && Number.isFinite(threshold)) {
    if (high < threshold) { key = 'below'; label = 'Интервал ниже демо-ориентира'; }
    else if (low >= threshold) { key = 'above'; label = 'Интервал выше демо-ориентира'; }
    else { key = 'overlap'; label = 'Интервал пересекает ориентир'; }
    detail = `Диапазон суммы ${low}–${high}; ориентир в локальной записи — ${threshold}, без подтверждённых года и источника.`;
  }
  const rightsSelected = [scenario.rights.bvi, scenario.rights.olympiad, scenario.rights.benefits, scenario.rights.paidTrack].some(Boolean);
  const rightsDetail = rightsSelected
    ? `${scenario.rights.paidTrack ? 'Отмечено платное обучение; отдельный порог не представлен. ' : ''}${scenario.rights.bvi ? 'БВИ заявлено, но локальные правила программы не подключены. ' : ''}${scenario.rights.olympiad ? (scenario.rights.olympiadNumber ? 'Олимпиада выбрана, но соответствие профиля и диплома правилам вуза не проверено. ' : 'Укажите олимпиаду из перечня; соответствие профиля и диплома всё равно проверяется по правилам вуза. ') : ''}${scenario.rights.benefits ? (scenario.rights.benefitId ? 'Льгота указана, но локальные правила программы не подключены.' : 'Льгота отмечена; укажите название или код документа для проверки backend.') : ''}`.trim()
    : 'БВИ и льготы не заявлены в сценарии.';
  return { program, key, label, detail, values, low, high, rightsSelected, rightsDetail, threshold };
}

function getSubjectIds(programs) {
  return [...new Set(programs.flatMap((program) => getRequiredSubjects(program).map(({ id }) => id).filter(Boolean)))];
}

function renderScenarioInputs(root, programs, state) {
  const selectedSubjects = getSubjectIds(programs);
  root.getElementById('admission-subjects').innerHTML = selectedSubjects.map((id) => {
    const subject = EGE_SUBJECTS.find((item) => item.id === id);
    const status = state.examStatuses?.[id] || (state.scores[id] != null ? 'taken' : 'expected');
    return `<div class="admission-scenario-row" data-admission-subject="${id}"><div class="admission-scenario-subject"><span class="subject-icon" style="--subject-color:${subject.color};--subject-bg:${subject.background}" aria-hidden="true">${subject.icon}</span><b>${escapeHtml(subject.label)}</b></div><select data-admission-status aria-label="Статус: ${escapeHtml(subject.label)}"><option value="taken" ${status === 'taken' ? 'selected' : ''}>Сдан</option><option value="expected" ${status === 'expected' ? 'selected' : ''}>Ожидается</option><option value="range" ${status === 'range' ? 'selected' : ''}>Диапазон</option><option value="not-taken" ${status === 'not-taken' ? 'selected' : ''}>Не сдаю</option></select><input data-admission-score aria-label="Баллы: ${escapeHtml(subject.label)}" type="number" min="0" max="100" inputmode="numeric" placeholder="0–100" value="${status === 'taken' ? escapeHtml(state.scores[id] ?? '') : ''}" ${status !== 'taken' ? 'disabled' : ''}><div class="admission-range-fields" ${status === 'range' ? '' : 'hidden'}><input data-admission-range-min type="number" min="0" max="100" aria-label="Нижняя граница ${escapeHtml(subject.label)}" placeholder="от" value="${escapeHtml(state.examRanges?.[id]?.min ?? '')}"><span>—</span><input data-admission-range-max type="number" min="0" max="100" aria-label="Верхняя граница ${escapeHtml(subject.label)}" placeholder="до" value="${escapeHtml(state.examRanges?.[id]?.max ?? '')}"></div></div>`;
  }).join('') || '<p class="small muted">Не удалось сопоставить предметы из локальных карточек.</p>';
}

function renderGroups(root, programs) {
  root.getElementById('admission-results').innerHTML = `<div class="admission-local-disclaimer"><strong>Проверка только по данным Andromeda API</strong><span>${programs.length ? 'Введите сданные баллы и нажмите «Сверить баллы через API». Локальные ориентиры и вероятности не рассчитываются.' : 'Каталог API недоступен или не содержит программ.'}</span></div>`;
  return [];
}

function baselineScenario(state) {
  return {
    scores: { ...state.scores },
    examStatuses: { ...(state.examStatuses || {}) },
    examRanges: { ...(state.examRanges || {}) },
    rights: { bvi: false, olympiad: false, benefits: false, paidTrack: false },
  };
}

function updateWhatIfSummary(root, programs, state, scenario) {
  const output = root.getElementById('what-if-summary');
  const entered = Object.values(scenario.examStatuses).filter((status) => status === 'taken').length;
  if (output) output.textContent = entered
    ? `Указаны баллы по ${entered} предметам. Результат появится после проверки API для ${programs.length} программ.`
    : 'Добавьте результаты ЕГЭ и запустите проверку через API.';
}

const olympiadOptions = olympiads.map((item) => `<option value="${item.number}. ${escapeHtml(item.name)}"></option>`).join('');

export const admissionCheckMarkup = `
  <section class="page" id="page-admission-check">
    <div class="page-title"><div><div class="eyebrow">Сценарий поступления</div><h1>Проверить поступление</h1><p>Сверьте весь список программ, статусы ЕГЭ и изменяйте баллы в what-if-сценарии.</p></div><div class="title-actions"><button class="btn btn-outline" data-page="profile">Мой профиль</button></div></div>
    <div class="admission-demo-notice"><strong>Это не прогноз шансов</strong><span>Результаты формируются только по сведениям из Andromeda API. При недостатке данных API вернёт это явно; результат не является вероятностью зачисления.</span></div>
    <div class="admission-scenario-layout"><section class="panel admission-scenario-editor"><div class="eyebrow">What-if · не меняет профиль</div><h2>Измените сценарий</h2><p class="small muted">Скопированы статусы и результаты активного профиля. Чтобы сохранить правки в профиль, нажмите отдельную кнопку.</p><div id="admission-subjects" class="admission-scenario-subjects"></div><fieldset class="admission-rights"><legend>Особые условия</legend><label><input id="scenario-bvi" type="checkbox"><span>Поступление по БВИ</span></label><label><input id="scenario-olympiad" type="checkbox"><span>Диплом олимпиады</span></label><label><input id="scenario-benefit" type="checkbox"><span>Льгота / особое право</span></label><label><input id="scenario-paid" type="checkbox"><span>Рассматривать платное место</span></label></fieldset><div class="admission-right-details" data-scenario-olympiad-fields hidden><label class="field" for="scenario-olympiad-record"><span>Олимпиада из перечня</span><input id="scenario-olympiad-record" list="scenario-olympiad-list" placeholder="Номер или название из списка"><datalist id="scenario-olympiad-list">${olympiadOptions}</datalist></label><label class="field" for="scenario-olympiad-profile"><span>Профиль диплома</span><input id="scenario-olympiad-profile" type="text" maxlength="120" placeholder="Как в дипломе"></label><label class="field" for="scenario-olympiad-award"><span>Результат</span><select id="scenario-olympiad-award"><option value="winner">Победитель</option><option value="prize">Призёр</option><option value="participant">Участник</option></select></label></div><label class="field admission-benefit-field" data-scenario-benefit-field hidden><span>Название льготы / код документа</span><input id="scenario-benefit-id" type="text" maxlength="120" placeholder="Укажите право, подтверждённое документом"></label><p id="what-if-summary" class="what-if-summary" aria-live="polite"></p><div class="admission-scenario-actions"><button class="btn btn-outline" id="admission-reset-scenario" type="button">Сбросить к профилю</button><button class="btn btn-outline" id="admission-save-profile" type="button">Сохранить баллы в профиль</button><button class="btn btn-primary" id="admission-check-rules" type="button">Сверить баллы через API</button></div><p class="small muted">Проверка сопоставляет введённые баллы с условиями набора, которые API вернуло для выбранного года. БВИ и льготы не оцениваются в этой проверке; для них откройте раздел «Правила и льготы».</p></section><section class="panel admission-results-panel"><div class="eyebrow">Все программы</div><div id="admission-results" aria-live="polite"></div></section></div>
    <div class="route-resources" aria-label="Другие инструменты поступления"><span>Продолжить</span><button class="text-btn" data-page="rules">Правила и льготы →</button><button class="text-btn" data-page="olympiads">Олимпиады →</button></div>
  </section>`;

export function renderAdmissionCheck({ root, programs, state }) {
  renderScenarioInputs(root, programs, state);
  const scenario = baselineScenario(state);
  root.getElementById('scenario-bvi').checked = false;
  root.getElementById('scenario-olympiad').checked = false;
  root.getElementById('scenario-benefit').checked = false;
  root.getElementById('scenario-paid').checked = false;
  root.getElementById('scenario-olympiad-record').value = '';
  root.getElementById('scenario-olympiad-profile').value = '';
  root.getElementById('scenario-benefit-id').value = '';
  root.querySelector('[data-scenario-olympiad-fields]').hidden = true;
  root.querySelector('[data-scenario-benefit-field]').hidden = true;
  renderGroups(root, programs, scenario);
  updateWhatIfSummary(root, programs, state, scenario);
}

export function refreshAdmissionEstimate({ root, programs, state }) {
  const scenario = readScenario(root);
  const results = renderGroups(root, programs, scenario);
  updateWhatIfSummary(root, programs, state, scenario);
  const summary = root.getElementById('what-if-summary');
  if (summary && [scenario.rights.bvi, scenario.rights.olympiad, scenario.rights.benefits, scenario.rights.paidTrack].some(Boolean)) summary.textContent += ' Выбранные условия отмечены; без правил вуза локальная группа их не интерпретирует.';
  return { scenario, results };
}

export function collectAdmissionScores(root) {
  return readScenario(root).scores;
}

export function collectAdmissionScenario(root) {
  return readScenario(root);
}

export async function evaluateAdmissionWithBackend({ root, programs, state }) {
  const { scenario } = refreshAdmissionEstimate({ root, programs, state });
  if (!isBackendConfigured) return { configured: false };
  const payload = await backendApi.evaluateAdmission({
    programIds: programs.map(({ id }) => id),
    admissionYear: state.profileInfo.admissionYear,
    exams: Object.keys(scenario.examStatuses).map((subjectId) => ({
      subjectId,
      status: scenario.examStatuses[subjectId],
      score: scenario.scores[subjectId],
      minScore: scenario.examRanges[subjectId]?.min,
      maxScore: scenario.examRanges[subjectId]?.max,
    })),
    scenario: {
      extraPoints: Number(state.scores.extra) || 0,
      bvi: scenario.rights.bvi,
      olympiadIds: scenario.rights.olympiad && scenario.rights.olympiadNumber ? [`rsosh-2025-26-${scenario.rights.olympiadNumber}`] : [],
      olympiadResults: scenario.rights.olympiad ? [{ number: scenario.rights.olympiadNumber, profile: scenario.rights.olympiadProfile, award: scenario.rights.olympiadAward }] : [],
      benefitIds: scenario.rights.benefits && scenario.rights.benefitId ? [scenario.rights.benefitId] : [],
      paidTrack: scenario.rights.paidTrack,
    },
  });
  const records = payload?.results || [];
  const serverBlock = `<section class="admission-server-results"><div class="eyebrow">Ответ backend · правила по программам</div>${records.map((record) => `<article><b>${escapeHtml(record.programCode || record.programId || 'Программа')}</b><span>${escapeHtml(record.status || 'Недостаточно данных')}</span><p>${escapeHtml(record.explanation || record.summary || 'Получено правило; откройте первоисточник для деталей.')}</p>${record.sourceUrl ? `<a href="${escapeHtml(record.sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(record.sourceTitle || 'Первоисточник')} ↗</a>` : ''}</article>`).join('') || '<p>Сервер не вернул записей. Уточните контракт backend.</p>'}</section>`;
  root.getElementById('admission-results').insertAdjacentHTML('afterbegin', serverBlock);
  return { configured: true, payload };
}
