import { createLogger } from '../../shared/logger.js';
import { escapeHtml } from '../../shared/dom.js';
import { EGE_SUBJECT_GROUPS, EGE_SUBJECTS, getCompletedExamCount, getEnteredExamCount, getProfileScoreTotal } from '../../data/exam-subjects.js';
import { groupProgramsByScore } from './logic.js';

const logger = createLogger('profile');

export const profileMarkup = String.raw`
<section class="page" id="page-profile">
  <section class="profile-hero" aria-labelledby="profile-welcome-heading">
    <div class="eyebrow">Личный кабинет</div>
    <h1 id="profile-welcome-heading">Ваш путь к поступлению начинается здесь</h1>
    <p>Соберите результаты ЕГЭ в одном месте и держите важные баллы под рукой.</p>
    <span class="profile-hero-mark" aria-hidden="true">✦</span>
  </section>

  <div class="profile-summary-grid">
    <section class="panel personal-profile-card" aria-labelledby="personal-profile-heading">
      <div class="profile-personal-head">
        <div class="profile-avatar" id="profile-avatar" aria-hidden="true">Я</div>
        <div>
          <div class="eyebrow">Личные данные</div>
          <h2 id="personal-profile-heading">Абитуриент</h2>
        </div>
      </div>
      <div class="field">
        <label for="profile-name">Как к вам обращаться</label>
        <input id="profile-name" data-profile-info="name" type="text" maxlength="80" placeholder="Ваше имя" autocomplete="name">
      </div>
      <div class="field">
        <label for="profile-admission-year">Год поступления</label>
        <input id="profile-admission-year" data-profile-info="admissionYear" type="number" min="2024" max="2035" inputmode="numeric">
      </div>
      <p class="profile-private-note">Данные профиля сохраняются в этом браузере.</p>
    </section>

    <section class="panel active-profile-summary" aria-labelledby="active-profile-title">
      <div class="eyebrow">Предварительная оценка</div>
      <h2 id="active-profile-title">Основной профиль</h2>
      <p id="active-profile-year" class="muted small">ЕГЭ · 2026</p>
      <div class="profile-score-total"><span>Сумма баллов</span><strong id="profile-score-total">—</strong></div>
      <p id="profile-score-completed" class="small muted">Укажите результаты экзаменов ниже.</p>
    </section>
  </div>

  <section class="profile-exams" aria-labelledby="exam-profiles-heading">
    <div class="section-head profile-section-head">
      <div>
        <h2 id="exam-profiles-heading">Профили ЕГЭ</h2>
        <p class="small muted">Создавайте отдельные наборы баллов, например для пересдачи или другого года.</p>
      </div>
      <button class="btn btn-outline" id="add-exam-profile" type="button" aria-expanded="false" aria-controls="exam-profile-create">＋ Добавить профиль</button>
    </div>
    <div class="exam-profile-list" id="exam-profile-list" aria-label="Сохранённые профили ЕГЭ"></div>
    <form class="panel profile-create" id="exam-profile-create" hidden>
      <div>
        <div class="eyebrow">Новый набор результатов</div>
        <h3>Добавить профиль ЕГЭ</h3>
      </div>
      <div class="profile-create-fields">
        <div class="field">
          <label for="new-profile-name">Название профиля</label>
          <input id="new-profile-name" name="profileName" type="text" maxlength="80" placeholder="Например, Пересдача" required>
        </div>
        <div class="field">
          <label for="new-profile-year">Год ЕГЭ</label>
          <input id="new-profile-year" name="profileYear" type="number" min="2024" max="2035" required>
        </div>
      </div>
      <div class="profile-create-actions">
        <button class="btn btn-outline" id="cancel-exam-profile" type="button">Отмена</button>
        <button class="btn btn-primary" type="submit">Создать профиль</button>
      </div>
    </form>
  </section>

  <div class="section-head profile-score-heading">
    <div>
      <h2>Мои результаты ЕГЭ</h2>
      <p id="active-exam-profile-heading" class="small muted">Основной профиль · 2026</p>
      <p class="small muted">Предварительная сверка с локальными примерами, не официальный конкурсный прогноз.</p>
    </div>
  </div>
  <div class="score-layout">
    <section class="panel ege-editor" aria-labelledby="ege-editor-title">
      <div class="ege-editor-head">
        <div>
          <div class="eyebrow">Мои результаты</div>
          <h3 id="ege-editor-title">Предметы ЕГЭ</h3>
          <p class="small muted">Нажмите на предмет, чтобы заменить его.</p>
        </div>
      </div>
      <div class="exam-entry-list" id="exam-entries"></div>
      <button class="add-ege-subject" id="add-ege-subject" type="button">
        <span aria-hidden="true">＋</span> Добавить предмет
      </button>
      <div class="field ege-extra-field">
        <label for="score-extra">Дополнительные баллы · сверяйте с вузом</label>
        <input id="score-extra" type="number" data-extra-points placeholder="0–10 в модели прототипа" min="0" max="10" inputmode="numeric">
      </div>
      <div class="ege-editor-divider"></div>
      <div class="ege-score-bottom">
        <div><strong id="score-total">—</strong><p class="small muted">Предварительная сумма</p></div>
        <span class="small muted">Три лучших ЕГЭ + достижения</span>
      </div>
      <div class="ege-editor-actions">
        <button class="btn btn-primary" id="calculate-btn" type="button">Посмотреть итог <span aria-hidden="true">↗</span></button>
        <p class="small muted">Изменения сохраняются автоматически.</p>
      </div>
    </section>
    <div>
      <div id="fit-results" class="fit-sections" aria-live="polite">
        <div class="panel empty"><strong>Добавьте результаты ЕГЭ</strong>Укажите предметы и баллы — затем покажем предварительную оценку вариантов.</div>
      </div>
    </div>
  </div>

  <section class="panel profile-info-card" aria-labelledby="profile-info-title">
    <div class="profile-info-icon" aria-hidden="true">i</div>
    <h3 id="profile-info-title">Как считается сумма?</h3>
    <p>В модели прототипа складываются три наивысших результата ЕГЭ и введённые дополнительные баллы (ограничение интерфейса — 10). Реальный список достижений и лимит зависят от правил конкретного вуза.</p>
  </section>

  <section class="panel profile-preferences" aria-labelledby="profile-preferences-title">
    <div class="eyebrow">Ручная настройка</div><h2 id="profile-preferences-title">Предпочтения и уведомления</h2>
    <div class="profile-preference-grid">
      <label class="field"><span>Форма обучения</span><select data-preference="form"><option value="">Не важно</option><option>Очная</option><option>Очно-заочная</option><option>Заочная</option></select></label>
      <label class="field"><span>Стоимость в год, максимум</span><input data-preference="maxCost" type="number" min="0" step="10000" placeholder="Не ограничивать"></label>
      <label class="field"><span>Предпочтительный вуз</span><input data-preference="university" type="text" maxlength="120" placeholder="Не важно"></label>
      <label class="field"><span>Длительность</span><select data-preference="durationYears"><option value="">Не важно</option><option value="4">4 года</option><option value="5">5 лет</option><option value="6">6 лет</option></select></label>
      <label class="field"><span>Финансирование</span><select data-preference="budget"><option value="">Не важно</option><option value="budget">Бюджет</option><option value="paid">Платное</option></select></label>
      <label class="field"><span>Ступень обучения</span><input data-preference="degree" type="text" maxlength="80" placeholder="Например, бакалавриат"></label>
      <label class="field"><span>ВУЦ</span><select data-preference="vuc"><option value="">Не важно</option><option value="yes">Ищу программу с ВУЦ</option><option value="no">ВУЦ не нужен</option></select></label>
    </div>
    <fieldset class="profile-interest-picks"><legend>Интересы для рекомендаций</legend>${['Аналитика', 'Технологии', 'Бизнес и управление', 'Исследования и дизайн'].map((interest) => `<label><input type="checkbox" data-interest-preference="${escapeHtml(interest)}"><span>${escapeHtml(interest)}</span></label>`).join('')}</fieldset>
    <fieldset class="profile-interest-picks"><legend>Уведомления в MAX <small>настройка сохранится локально; подключение бота появится после интеграции backend</small></legend>${[['rules', 'Изменения правил'], ['deadlines', 'Сроки поступления'], ['news', 'Новости']].map(([key, label]) => `<label><input type="checkbox" data-max-notification="${key}"><span>${label}</span></label>`).join('')}<label><input type="checkbox" data-max-enabled><span>Включить уведомления после подключения MAX</span></label></fieldset>
  </section>

  <nav class="route-resources" aria-label="Инструменты профиля">
    <span>Инструменты поступления</span>
    <button class="text-btn" type="button" data-page="admission-check">Проверить поступление →</button>
    <button class="text-btn" type="button" data-page="proftest">Пройти ПрофТест →</button>
    <button class="text-btn" type="button" data-page="recommendations">Рекомендации →</button>
    <button class="text-btn" type="button" data-page="personal-route">Персональный маршрут →</button>
    <button class="text-btn" type="button" data-page="olympiads">Олимпиады →</button>
    <button class="text-btn" type="button" data-page="news">Новости →</button>
    <button class="text-btn" type="button" data-page="rules">Правила и льготы →</button>
  </nav>

  <dialog class="ege-picker" id="ege-subject-picker" aria-labelledby="ege-picker-title">
    <div class="ege-picker-header">
      <div class="ege-picker-title-row">
        <div>
          <div class="eyebrow">Выбор предмета</div>
          <h2 id="ege-picker-title">Какой предмет добавим?</h2>
          <p id="ege-picker-description">Найдите предмет или выберите его из списка.</p>
        </div>
        <button class="icon-btn ege-picker-close" id="close-ege-picker" type="button" aria-label="Закрыть">×</button>
      </div>
      <div class="ege-search-wrap">
        <input id="ege-subject-search" type="search" placeholder="Поиск по предметам" autocomplete="off" aria-label="Поиск по предметам">
      </div>
    </div>
    <div class="ege-picker-body" id="ege-picker-body"></div>
  </dialog>
</section>
`;

export function createExamRowMarkup({ rowId, rowNumber = 1, selectedSubject = '', score = null, status = '', range = {} }) {
  const subject = EGE_SUBJECTS.find(({ id }) => id === selectedSubject);
  if (!subject) return '';
  return `
    <div class="exam-row" data-exam-row="${escapeHtml(rowId)}" data-subject-id="${subject.id}">
      <button class="subject-button" data-edit-ege-subject type="button" aria-label="Заменить предмет ${subject.label}">
        <span class="subject-icon" style="--subject-color:${subject.color};--subject-bg:${subject.background}" aria-hidden="true">${subject.icon}</span>
        <span class="subject-text">
          <span class="subject-caption">Предмет ${rowNumber} · нажмите для замены</span>
          <span class="subject-name">${subject.label}</span>
        </span>
        <span class="subject-chevron" aria-hidden="true">⌄</span>
      </button>
      <div class="row-controls">
        <select class="exam-status" data-exam-status aria-label="Статус результата: ${subject.label}"><option value="taken" ${status === 'taken' || (!status && score !== null) ? 'selected' : ''}>Сдан</option><option value="expected" ${status === 'expected' ? 'selected' : ''}>Ожидается</option><option value="range" ${status === 'range' ? 'selected' : ''}>Диапазон</option><option value="not-taken" ${status === 'not-taken' || (!status && score === null) ? 'selected' : ''}>Не сдаю</option></select>
        <input class="points" type="number" data-exam-score aria-label="Баллы: ${subject.label}" placeholder="0–100" min="0" max="100" inputmode="numeric" value="${score ?? ''}" ${status === 'expected' || status === 'not-taken' ? 'disabled' : ''}>
        <div class="exam-range" data-exam-range-fields ${status === 'range' ? '' : 'hidden'}><input type="number" min="0" max="100" data-exam-range-min aria-label="Нижняя граница: ${subject.label}" placeholder="от" value="${range.min ?? ''}"><span>—</span><input type="number" min="0" max="100" data-exam-range-max aria-label="Верхняя граница: ${subject.label}" placeholder="до" value="${range.max ?? ''}"></div>
        <button class="remove-btn" data-exam-remove type="button" aria-label="Удалить ${subject.label}">×</button>
      </div>
    </div>
  `;
}

export function collectExamScores(root) {
  const scores = {};
  for (const row of root.querySelectorAll('[data-exam-row]')) {
    const subject = row.dataset.subjectId;
    if (!subject) continue;
    const input = row.querySelector('[data-exam-score]');
    const status = row.querySelector('[data-exam-status]')?.value || 'taken';
    scores[subject] = status === 'taken' && input.value !== '' ? Number(input.value) : null;
  }
  const extra = root.querySelector('[data-extra-points]');
  if (extra?.value !== '') scores.extra = Number(extra.value);
  return scores;
}

export function collectExamMetadata(root) {
  const examStatuses = {};
  const examRanges = {};
  for (const row of root.querySelectorAll('[data-exam-row]')) {
    const subject = row.dataset.subjectId;
    if (!subject) continue;
    const status = row.querySelector('[data-exam-status]')?.value || 'not-taken';
    examStatuses[subject] = status;
    if (status === 'range') {
      const minValue = row.querySelector('[data-exam-range-min]')?.value ?? '';
      const maxValue = row.querySelector('[data-exam-range-max]')?.value ?? '';
      examRanges[subject] = {
        min: minValue === '' ? null : Number(minValue),
        max: maxValue === '' ? null : Number(maxValue),
      };
    }
  }
  return { examStatuses, examRanges };
}

export function renderExamPicker(root, { scores, query = '', currentSubjectId = null }) {
  const body = root.getElementById('ege-picker-body');
  const search = query.trim().toLocaleLowerCase('ru-RU');
  const usedSubjects = new Set(Object.keys(scores).filter((id) => id !== currentSubjectId));
  const title = root.getElementById('ege-picker-title');
  const description = root.getElementById('ege-picker-description');
  title.textContent = currentSubjectId ? 'На что заменим предмет?' : 'Какой предмет добавим?';
  description.textContent = currentSubjectId
    ? 'Баллы останутся на месте — изменится только предмет.'
    : 'Найдите нужный предмет или выберите его из списка.';
  body.replaceChildren();

  let matchCount = 0;
  for (const group of EGE_SUBJECT_GROUPS) {
    const subjects = EGE_SUBJECTS.filter((subject) => (
      subject.group === group && subject.label.toLocaleLowerCase('ru-RU').includes(search)
    ));
    if (!subjects.length) continue;
    matchCount += subjects.length;

    const heading = root.createElement('h3');
    heading.className = 'picker-group-title';
    heading.textContent = group;
    const grid = root.createElement('div');
    grid.className = 'subject-grid';

    for (const subject of subjects) {
      const isUsed = usedSubjects.has(subject.id);
      const option = root.createElement('button');
      option.type = 'button';
      option.className = 'subject-option';
      option.dataset.egeSubjectOption = subject.id;
      option.disabled = isUsed;

      const icon = root.createElement('span');
      icon.className = 'subject-icon';
      icon.textContent = subject.icon;
      icon.style.setProperty('--subject-color', subject.color);
      icon.style.setProperty('--subject-bg', subject.background);
      icon.setAttribute('aria-hidden', 'true');

      const text = root.createElement('span');
      text.className = 'option-text';
      text.textContent = subject.label;
      if (isUsed) {
        const note = root.createElement('small');
        note.textContent = 'Уже добавлен';
        text.append(note);
      }
      option.append(icon, text);
      grid.append(option);
    }
    body.append(heading, grid);
  }

  if (!matchCount) {
    const empty = root.createElement('p');
    empty.className = 'picker-empty';
    empty.textContent = 'Ничего не нашлось. Попробуйте другой запрос.';
    body.append(empty);
  }
}

function renderExamEntries(root, scores, examStatuses = {}, examRanges = {}) {
  const subjectsById = new Map(EGE_SUBJECTS.map((subject) => [subject.id, subject]));
  const subjectIds = [...new Set([...Object.keys(scores), ...Object.keys(examStatuses), ...Object.keys(examRanges)])];
  const rows = subjectIds
    .filter((id) => subjectsById.has(id))
    .map((id, index) => createExamRowMarkup({
      rowId: `saved-${id}`,
      rowNumber: index + 1,
      selectedSubject: id,
      score: scores[id],
      status: examStatuses[id],
      range: examRanges[id],
    }));

  root.getElementById('exam-entries').innerHTML = rows.length
    ? rows.join('')
    : '<div class="exam-empty-state"><strong>Пока нет предметов</strong><span>Добавьте первый предмет и укажите результат.</span></div>';
  const extraInput = root.getElementById('score-extra');
  extraInput.value = scores.extra ?? '';
  root.getElementById('add-ege-subject').disabled = getEnteredExamCount(scores) >= EGE_SUBJECTS.length;
}

export function renderProfile({ root, state, programs }) {
  const activeProfile = state.examProfiles.find((profile) => profile.id === state.activeExamProfileId)
    || state.examProfiles[0];

  renderExamEntries(root, state.scores, state.examStatuses, state.examRanges);
  root.getElementById('active-profile-title').textContent = activeProfile.name;
  root.getElementById('active-profile-year').textContent = `ЕГЭ · ${activeProfile.year}`;
  root.getElementById('active-exam-profile-heading').textContent = `${activeProfile.name} · ${activeProfile.year}`;

  const profileNameInput = root.getElementById('profile-name');
  const profileName = state.profileInfo.name;
  profileNameInput.value = profileName;
  root.getElementById('profile-avatar').textContent = profileName.trim().slice(0, 1).toLocaleUpperCase('ru-RU') || 'Я';
  root.getElementById('personal-profile-heading').textContent = profileName || 'Абитуриент';
  root.getElementById('profile-admission-year').value = state.profileInfo.admissionYear;
  root.getElementById('new-profile-year').value = state.profileInfo.admissionYear;
  for (const input of root.querySelectorAll('[data-preference]')) input.value = state.preferences?.[input.dataset.preference] ?? '';
  for (const input of root.querySelectorAll('[data-interest-preference]')) input.checked = Number(state.interests?.[input.dataset.interestPreference] || 0) > 0;
  for (const input of root.querySelectorAll('[data-max-notification]')) input.checked = (state.maxNotifications?.topics || []).includes(input.dataset.maxNotification);
  const notificationsEnabled = root.querySelector('[data-max-enabled]');
  if (notificationsEnabled) notificationsEnabled.checked = state.maxNotifications?.enabled === true;

  root.getElementById('exam-profile-list').innerHTML = state.examProfiles.map((profile) => {
    const isActive = profile.id === activeProfile.id;
    const profileTotal = getProfileScoreTotal(profile.scores);
    return `
      <button class="exam-profile-card ${isActive ? 'active' : ''}" type="button" data-exam-profile="${escapeHtml(profile.id)}" aria-pressed="${isActive}">
        <span class="exam-profile-card-main"><strong>${escapeHtml(profile.name)}</strong><small>ЕГЭ · ${profile.year}</small></span>
        <span class="exam-profile-card-total"><span class="exam-profile-card-points">${profileTotal || '—'}</span><small>баллов</small></span>
      </button>
    `;
  }).join('');

  root.getElementById('exam-profile-create').hidden = true;
  root.getElementById('add-exam-profile').setAttribute('aria-expanded', 'false');
  renderProfileSummary({ root, state, programs });
  logger.debug('render.complete', { subjectCount: getEnteredExamCount(state.scores), profileCount: state.examProfiles.length });
}

export function renderProfileSummary({ root, state, programs }) {
  const total = getProfileScoreTotal(state.scores);
  const subjectCount = getEnteredExamCount(state.scores);
  const completedCount = getCompletedExamCount(state.scores);
  root.getElementById('score-total').textContent = total || '—';
  root.getElementById('profile-score-total').textContent = total || '—';
  const subjectCountWord = subjectCount === 1 ? 'предмет ЕГЭ добавлен'
    : subjectCount > 1 && subjectCount < 5 ? 'предмета ЕГЭ добавлено' : 'предметов ЕГЭ добавлено';
  root.getElementById('profile-score-completed').textContent = subjectCount
    ? `${subjectCount} ${subjectCountWord}`
    : 'Добавьте предметы и внесите результаты.';

  const activeCardPoints = root.querySelector('.exam-profile-card.active .exam-profile-card-points');
  if (activeCardPoints) activeCardPoints.textContent = total || '—';
  if (total && completedCount >= 3) renderProfileResults({ root, state, programs, total });
  else {
    const missingResults = Math.max(0, 3 - completedCount);
    const resultWord = missingResults === 1 ? 'результат' : missingResults > 1 && missingResults < 5 ? 'результата' : 'результатов';
    const message = subjectCount
      ? `Для предварительной оценки нужны три балла ЕГЭ. Осталось внести: ${missingResults} ${resultWord}.`
      : 'Добавьте предметы и внесите результаты — затем покажем предварительную оценку вариантов.';
    root.getElementById('fit-results').innerHTML = `<div class="panel empty"><strong>${subjectCount ? 'Нужно ещё немного данных' : 'Добавьте результаты ЕГЭ'}</strong>${message}</div>`;
  }
  return total;
}

export function renderProfileResults({ root, state, programs, total }) {
  const sections = groupProgramsByScore(programs, total);
  const groupsMarkup = sections.map(({ name, className, programs: matches }) => `
    <div class="fit-section">
      <h3>${name} <span class="fit-badge ${className}">${matches.length}</span></h3>
      ${matches.length ? matches.map((program) => `
        <div class="fit-card">
          <div>
            <b>${program.code} · ${program.title}</b>
            <p>Ваша сумма: ${total} · Пример порога в записи: ${program.passing || 'не указан'}</p>
            <div class="explain">Сравнение с демонстрационным значением без подтверждённых года и источника. Условия и набор предметов нужно сверить отдельно.</div>
          </div>
          <div class="card-actions"><button class="btn btn-outline btn-sm" data-page="admission-check" data-program="${program.id}">Сверить</button><button class="btn btn-outline btn-sm" data-save="${program.id}">${state.shortlist[program.id] ? '♥ Добавлено' : '＋ Добавить'}</button></div>
        </div>
      `).join('') : `
        <div class="panel empty" style="padding:22px"><strong>Пока нет вариантов</strong>Попробуйте проверить предметы или добавить информацию о льготах.</div>
      `}
    </div>
  `).join('');

  root.getElementById('fit-results').innerHTML = `${groupsMarkup}
      <div class="context-cta">
      <div><strong>Нашли несколько вариантов для изучения?</strong><p>Сохраните их в shortlist и сравните содержание.</p></div>
      <button class="btn btn-light" data-page="shortlist">Открыть мой выбор</button>
    </div>
  `;
  logger.debug('results.rendered', { groupCount: sections.length, fieldCount: Object.keys(state.scores).length });
}

export function saveAndCalculateScores({ root, state, updateState, programs }) {
  for (const input of [...root.querySelectorAll('[data-exam-score]'), ...root.querySelectorAll('[data-extra-points]')]) {
    if (!input.checkValidity()) {
      input.reportValidity();
      return null;
    }
  }
  const scores = collectExamScores(root);
    updateState('profile.scores.save', (current) => {
    current.scores = scores;
    const metadata = collectExamMetadata(root);
    current.examStatuses = metadata.examStatuses;
    current.examRanges = metadata.examRanges;
    const activeProfile = current.examProfiles.find((profile) => profile.id === current.activeExamProfileId);
    if (activeProfile) Object.assign(activeProfile, { scores: { ...scores }, ...metadata });
  });
  const total = renderProfileSummary({ root, state, programs });
  logger.debug('scores.calculated', {
    subjectCount: getEnteredExamCount(scores),
    completedFieldCount: Object.values(scores).filter((score) => Number(score) > 0).length,
  });
  return total;
}
