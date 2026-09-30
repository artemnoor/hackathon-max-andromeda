import { createLogger } from '../../shared/logger.js';
import { matchProgramToProfile } from '../../shared/program-analytics.js';
import { escapeHtml } from '../../shared/dom.js';
import { isBackendConfigured } from '../../api/client.js';

const logger = createLogger('catalog');

export const catalogMarkup = String.raw`
<section class="page" id="page-catalog">
      <div class="page-title"><div><div class="eyebrow">Каталог</div><h1>Найти программы</h1><p>Ищите по названию, вузу, предметам ЕГЭ и содержанию учебного плана.</p></div><div class="title-actions"><button class="btn btn-dark" data-page="compare">Сравнить выбранные</button></div></div>
      <div class="catalog-toolbar">
        <p class="results-count" id="results-count" aria-live="polite"></p>
        <button class="catalog-filter-trigger" id="catalog-filter-trigger" type="button" aria-controls="catalog-filter-panel" aria-expanded="false">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 5h14M5.5 10h9M8 15h4" /></svg>
          <span>Фильтр</span><span class="filter-count" id="active-filter-count" hidden></span>
        </button>
      </div>
      <div class="catalog-filter-panel" id="catalog-filter-panel" role="region" aria-labelledby="catalog-filter-title" aria-hidden="true" inert>
        <div class="catalog-filter-panel-inner">
          <div class="catalog-filter-head"><div><div class="eyebrow">Настройте выдачу</div><h2 id="catalog-filter-title">Фильтры программ</h2><p>Фильтры применяются к полям, которые вернул API.</p></div></div>
          <form id="catalog-filter-form">
            <div class="catalog-filter-fields">
              <label class="catalog-filter-field" for="area-filter"><span>Направление</span><select class="filter" id="area-filter"><option value="">Все области</option><option>Программирование</option><option>Математика</option><option>Аналитика</option><option>Экономика</option><option>Инженерия</option><option>Технологии</option><option>Дизайн</option><option>Исследования</option></select></label>
              <label class="catalog-filter-field" for="university-filter"><span>Вуз</span><select class="filter" id="university-filter"><option value="">Любой вуз</option><option>МГТУ им. Н. Э. Баумана</option><option>Высшая школа экономики</option></select></label>
              <label class="catalog-filter-field" for="exam-filter"><span>Вступительный предмет</span><select class="filter" id="exam-filter"><option value="">Любой предмет</option><option>Русский</option><option>Математика</option><option>Информатика</option><option>Обществознание</option><option>Творческий конкурс</option></select></label>
              <label class="catalog-filter-field" for="budget-filter"><span>Условия оплаты</span><select class="filter" id="budget-filter"><option value="">Любые</option><option value="budget">Есть бюджетные места</option><option value="paid">Есть платное обучение</option></select></label>
              <label class="catalog-filter-field" for="max-cost-filter"><span>Стоимость в год, до</span><select class="filter" id="max-cost-filter"><option value="">Не ограничивать</option><option value="350000">350 000 ₽</option><option value="400000">400 000 ₽</option><option value="450000">450 000 ₽</option></select></label>
              <label class="catalog-filter-field" for="format-filter"><span>Форма обучения</span><select class="filter" id="format-filter"><option value="">Любая форма</option><option>Очная</option><option>Очно-заочная</option><option>Заочная</option></select></label>
              <label class="catalog-filter-field" for="duration-filter"><span>Длительность</span><select class="filter" id="duration-filter"><option value="">Любая</option><option value="4">4 года</option><option value="5">5 лет</option><option value="6">6 лет</option></select></label>
              <label class="catalog-filter-field" for="min-score-filter"><span>Проходной балл до</span><select class="filter" id="min-score-filter"><option value="">Любой</option><option value="260">260 баллов</option><option value="270">270 баллов</option><option value="280">280 баллов</option></select></label>
              <label class="catalog-filter-field" for="benefits-filter"><span>Льготы / особые права</span><select class="filter" id="benefits-filter"><option value="">Любые сведения</option><option value="available">Указаны</option><option value="unavailable">Не указаны</option><option value="unknown">Нет данных</option></select></label>
              <label class="catalog-filter-field" for="vuc-filter"><span>Военный учебный центр</span><select class="filter" id="vuc-filter"><option value="">Любые сведения</option><option value="yes">Есть</option><option value="no">Нет</option><option value="unknown">Нет данных</option></select></label>
            </div>
            <div class="catalog-filter-actions"><button class="catalog-filter-reset" id="reset-filter" type="button">Сбросить</button><button class="catalog-filter-apply" type="submit">Показать программы <span aria-hidden="true">→</span></button></div>
          </form>
        </div>
      </div>
      <p class="small muted catalog-data-note">Демонстрационные данные для прототипа. Проверяйте условия и цифры на официальных страницах вузов.</p>
      <label class="catalog-search-control" for="catalog-search">
        <span class="sr-only">Поиск программ</span>
        <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.7" cy="8.7" r="5.7" /><path d="m13 13 4 4" /></svg>
        <input class="search" id="catalog-search" type="search" placeholder="Например: ИИ, но меньше железа" autocomplete="off" />
      </label>
      <div class="cards-grid" id="catalog-list"></div><div class="context-cta"><div><strong>Уже посмотрели несколько программ?</strong><p>Сравните варианты или отдельно сверьте свои баллы с требованиями.</p></div><div class="card-actions"><button class="btn btn-light" data-page="compare">Сравнить их</button><button class="btn btn-outline" data-page="admission-check">Проверить поступление</button></div></div>
    </section>
`;

let catalogRenderVersion = 0;

export async function renderCatalog({ root, repository, renderProgramCard, filters = {}, profile = {}, syncControls = true }) {
  const renderVersion = ++catalogRenderVersion;
  const appliedFilters = {
    q: filters.q || '',
    area: filters.area || '',
    university: filters.university || '',
    exam: filters.exam || '',
    maxCost: filters.maxCost || '',
    budget: filters.budget || '',
    format: filters.format || '',
    duration: filters.duration || '',
    minScore: filters.minScore || '',
    benefits: filters.benefits || '',
    vuc: filters.vuc || '',
  };
  const searchInput = root.getElementById('catalog-search');
  if (searchInput.value !== appliedFilters.q) searchInput.value = appliedFilters.q;
  if (syncControls) {
    root.getElementById('area-filter').value = appliedFilters.area;
    root.getElementById('university-filter').value = appliedFilters.university;
    root.getElementById('exam-filter').value = appliedFilters.exam;
    root.getElementById('max-cost-filter').value = appliedFilters.maxCost;
    root.getElementById('budget-filter').value = appliedFilters.budget;
    root.getElementById('format-filter').value = appliedFilters.format;
    root.getElementById('duration-filter').value = appliedFilters.duration;
    root.getElementById('min-score-filter').value = appliedFilters.minScore;
    root.getElementById('benefits-filter').value = appliedFilters.benefits;
    root.getElementById('vuc-filter').value = appliedFilters.vuc;
  }
  const activeFilterCount = [appliedFilters.area, appliedFilters.university, appliedFilters.exam, appliedFilters.budget, appliedFilters.maxCost, appliedFilters.format, appliedFilters.duration, appliedFilters.minScore, appliedFilters.benefits, appliedFilters.vuc].filter(Boolean).length;
  root.querySelector('.catalog-data-note').textContent = isBackendConfigured
    ? 'Каталог загружается из Andromeda Public API. Отсутствующие в источнике сведения не подставляются.'
    : 'Каталог API не настроен.';
  const activeFilterBadge = root.getElementById('active-filter-count');
  activeFilterBadge.hidden = activeFilterCount === 0;
  activeFilterBadge.textContent = String(activeFilterCount);
  root.getElementById('catalog-filter-trigger').setAttribute(
    'aria-label',
    activeFilterCount ? `Открыть фильтры. Выбрано: ${activeFilterCount}` : 'Открыть фильтры',
  );

  logger.debug('render.start', {
    hasQuery: Boolean(appliedFilters.q),
    hasArea: Boolean(appliedFilters.area),
    budget: appliedFilters.budget || 'all',
    maxCost: appliedFilters.maxCost || 'all',
  });

  let programs;
  try {
    programs = await repository.listPrograms(appliedFilters);
  } catch (error) {
    if (renderVersion !== catalogRenderVersion) return;
    logger.warn('render.data_failed', { code: error.code, status: error.status });
    root.getElementById('catalog-list').innerHTML = '<div class="panel empty" style="grid-column:1/-1"><strong>Не удалось загрузить каталог</strong>Проверьте доступность Andromeda API и обновите страницу.</div>';
    root.getElementById('results-count').textContent = 'Каталог временно недоступен';
    return;
  }
  if (renderVersion !== catalogRenderVersion) return;
  const normalize = (value) => String(value ?? '').toLocaleLowerCase('ru-RU').replaceAll('ё', 'е');
  programs = programs.filter((program) => {
    const query = normalize(appliedFilters.q);
    const text = normalize(`${program.title} ${program.name} ${program.code} ${program.university}`);
    return (!query || text.includes(query))
      && (!appliedFilters.university || normalize(program.university) === normalize(appliedFilters.university))
      && (!appliedFilters.exam || normalize(program.exams).includes(normalize(appliedFilters.exam)))
      && (!appliedFilters.maxCost || (program.cost != null && Number(program.cost) <= Number(appliedFilters.maxCost)))
      && (!appliedFilters.budget || (appliedFilters.budget === 'budget' ? Number(program.budget) > 0 : Number(program.cost) > 0));
  });
  const listElement = root.getElementById('catalog-list');
  listElement.innerHTML = programs.length
    ? programs.map((program) => {
      const match = matchProgramToProfile(program, profile);
      const score = match.percent === null ? (match.criteria.length ? 'Недостаточно данных для сравнения' : 'Профиль пока не заполнен') : `${match.percent}% критериев · ${match.matched}/${match.total}`;
      const reasons = match.criteria.filter((criterion) => criterion.matched).slice(0, 2).map(({ detail }) => detail);
      const curriculum = match.curriculum.areas.slice(0, 3).map(({ area, level }) => `${escapeHtml(area)}: ${level.toLocaleLowerCase('ru-RU')}`).join(' · ');
      return `<div class="catalog-card-fit">${renderProgramCard(program)}<div class="catalog-fit" data-program-fit="${escapeHtml(program.id)}"><div><span class="catalog-fit-score">${escapeHtml(score)}</span>${reasons.length ? `<span>${reasons.map(escapeHtml).join(' · ')}</span>` : ''}</div><p><strong>Учебный план в полученных данных:</strong> ${curriculum || 'нет дисциплин с часами'}</p></div></div>`;
    }).join('')
    : '<div class="panel empty" style="grid-column:1/-1"><strong>Ничего не нашли</strong>Попробуйте изменить фильтры или убрать часть условий.</div>';
  root.getElementById('results-count').textContent = `${programs.length} ${programs.length === 1 ? 'программа' : 'программы'} · ${isBackendConfigured ? 'Andromeda API' : 'API не настроен'}`;
  logger.debug('render.complete', { resultCount: programs.length });
}
