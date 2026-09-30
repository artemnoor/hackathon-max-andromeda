import { olympiads } from '../../data/olympiads.js';
import { escapeHtml } from '../../shared/dom.js';

const uniqueSubjects = [...new Set(olympiads.flatMap((item) => item.profiles.flatMap((profile) => profile.subjects)))]
  .sort((a, b) => a.localeCompare(b, 'ru'));

export const olympiadsMarkup = `
  <section class="page" id="page-olympiads">
    <div class="page-title olympiads-title">
      <div>
        <div class="eyebrow">Поступление · особые права</div>
        <h1>Олимпиады</h1>
        <p>Информация об олимпиадах отображается только при наличии проверенных записей в API. Условия льгот сверяются по правилам программы и года.</p>
      </div>
      <div class="title-actions">
        <button class="btn btn-outline" type="button" data-page="catalog">Найти программы</button>
      </div>
    </div>

    <section class="olympiads-alert" aria-labelledby="olympiads-alert-title">
      <span class="olympiads-alert-mark" aria-hidden="true">!</span>
      <div>
        <h2 id="olympiads-alert-title">Льготу определяет вуз, а не уровень олимпиады</h2>
        <p>Победитель — диплом I степени, призёр — диплом II или III степени. В правилах конкретной программы вуз указывает, какой статус и профиль дают БВИ, 100 баллов ЕГЭ или дополнительные баллы. Сам по себе уровень I, II или III этого не гарантирует.</p>
      </div>
    </section>

    <section class="olympiads-benefits" aria-label="Возможные льготы">
      <article class="olympiads-benefit">
        <span class="olympiads-benefit-index">01</span>
        <div><h2>БВИ</h2><p>Поступление без вступительных испытаний — если вуз включил нужную олимпиаду, профиль и статус в свои правила.</p></div>
      </article>
      <article class="olympiads-benefit">
        <span class="olympiads-benefit-index">02</span>
        <div><h2>100 баллов ЕГЭ</h2><p>Зачёт максимума по профильному предмету. Вуз устанавливает перечень олимпиад и минимальный балл подтверждающего ЕГЭ.</p></div>
      </article>
      <article class="olympiads-benefit">
        <span class="olympiads-benefit-index">03</span>
        <div><h2>Дополнительные баллы</h2><p>Могут начисляться как за индивидуальное достижение. Количество и условия задаёт приёмная комиссия.</p></div>
      </article>
    </section>

    <section class="olympiads-rules-note" aria-label="Проверка правил">
      <div class="olympiads-rules-note-item"><span class="olympiads-note-tag">Проверка по источнику</span><p>Список дипломов и льгот должен соответствовать правилам приёма выбранного вуза, программы и года. В Andromeda можно открыть найденные правила для конкретной программы.</p><button class="text-btn" type="button" data-page="rules">Открыть правила и льготы →</button></div>
    </section>

    <section class="olympiads-catalog" aria-labelledby="olympiads-catalog-title">
      <div class="olympiads-catalog-heading">
        <div><span class="olympiads-section-kicker">Утверждённый перечень</span><h2 id="olympiads-catalog-title">Найдите олимпиаду</h2></div>
        <span class="olympiads-catalog-year">Данные из Andromeda API</span>
      </div>
      <div class="olympiads-filters" role="search" aria-label="Фильтры олимпиад">
        <label class="olympiads-search-field" for="olympiad-search">
          <span>Поиск</span>
          <input id="olympiad-search" type="search" placeholder="Название, профиль или предмет" autocomplete="off" />
        </label>
        <label for="olympiad-subject-filter"><span>Предмет ЕГЭ</span>
          <select id="olympiad-subject-filter"><option value="">Все предметы</option>${uniqueSubjects.map((subject) => `<option value="${escapeHtml(subject)}">${escapeHtml(subject)}</option>`).join('')}
          </select>
        </label>
        <label for="olympiad-level-filter"><span>Уровень</span>
          <select id="olympiad-level-filter"><option value="">Любой</option><option value="1">I уровень</option><option value="2">II уровень</option><option value="3">III уровень</option></select>
        </label>
        <button class="olympiads-reset" type="button" id="olympiad-filters-reset">Сбросить</button>
      </div>
      <div class="olympiads-results-meta"><p id="olympiads-result-count" aria-live="polite"></p><p>Раскройте карточку, чтобы увидеть все профили и предметы</p></div>
      <div class="olympiads-results" id="olympiads-results" aria-live="polite"></div>
      <div class="olympiads-source-line"><span>Проверяйте льготы в правилах выбранной программы и года.</span><button class="text-btn" type="button" data-page="rules">Перейти к правилам →</button></div>
    </section>
  </section>
`;

function profileMatches(profile, { subject, level }) {
  return (!subject || profile.subjects.includes(subject)) && (!level || String(profile.level) === level);
}

function renderProfile(profile) {
  return `<li class="olympiad-profile-row">
    <div><strong>${escapeHtml(profile.profile)}</strong><span class="olympiad-level-pill">Уровень ${['', 'I', 'II', 'III'][profile.level]}</span></div>
    <p>Предметы: ${profile.subjects.map(escapeHtml).join(', ')}</p>
  </li>`;
}

function renderOlympiad(item, matchingProfiles) {
  const allProfiles = matchingProfiles.map(renderProfile).join('');
  const visibleLevels = [...new Set(matchingProfiles.map((profile) => profile.level))]
    .sort((a, b) => a - b).map((level) => `Уровень ${['', 'I', 'II', 'III'][level]}`).join(' · ');
  const verifiedGazprom = item.number === 69
    ? `<div class="olympiad-verified-rights"><span>Проверенный пример · МГТУ</span><p>За дипломы 10–11 классов: I степень — 8, II — 6, III — 4 дополнительных балла. По профилю «Информатика и ИКТ» также предусмотрены БВИ с ограничениями по направлениям и 100 баллов по информатике. Условия нужно сверить с правилами вашего года.</p><a href="https://olymp.bmstu.ru/ru/gazprom" target="_blank" rel="noopener noreferrer">Подробности на сайте МГТУ ↗</a></div>`
    : '';
  return `<details class="olympiad-card">
    <summary>
      <span class="olympiad-number">${String(item.number).padStart(2, '0')}</span>
      <span class="olympiad-card-main"><strong>${escapeHtml(item.name)}</strong><span>${matchingProfiles.length} ${matchingProfiles.length === 1 ? 'профиль' : matchingProfiles.length < 5 ? 'профиля' : 'профилей'} · ${escapeHtml(visibleLevels)}</span></span>
      <span class="olympiad-expand" aria-hidden="true">+</span>
    </summary>
    <div class="olympiad-card-content">
      <ul class="olympiad-profile-list">${allProfiles}</ul>
      ${verifiedGazprom}
      <p class="olympiad-per-program-note">Льгота за победу или призёрство в этой олимпиаде определяется правилами конкретного вуза и направления. Проверьте соответствие профиля, статус диплома, предмет ЕГЭ и год получения результата.</p>
      <a class="olympiad-organizer" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">Сайт олимпиады ↗</a>
    </div>
  </details>`;
}

export function renderOlympiads({ root = globalThis.document } = {}) {
  const results = root.getElementById('olympiads-results');
  if (!results) return;
  const query = root.getElementById('olympiad-search')?.value.trim().toLocaleLowerCase('ru-RU') || '';
  const subject = root.getElementById('olympiad-subject-filter')?.value || '';
  const level = root.getElementById('olympiad-level-filter')?.value || '';

  const filtered = olympiads.map((item) => ({
    item,
    profiles: item.profiles.filter((profile) => profileMatches(profile, { subject, level })),
  })).filter(({ item, profiles }) => {
    if (!profiles.length) return false;
    if (!query) return true;
    const text = `${item.name} ${profiles.map((profile) => `${profile.profile} ${profile.subjects.join(' ')}`).join(' ')}`
      .toLocaleLowerCase('ru-RU');
    return text.includes(query);
  });

  root.getElementById('olympiads-result-count').textContent = `Показано ${filtered.length} из ${olympiads.length} олимпиад`;
  results.innerHTML = filtered.length
    ? filtered.map(({ item, profiles }) => renderOlympiad(item, profiles)).join('')
    : '<p class="olympiads-empty">В каталоге API пока нет проверенных записей олимпиад. Правила и доступные льготы смотрите в карточке выбранной программы.</p>';
}
