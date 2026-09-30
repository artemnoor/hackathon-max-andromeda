import { createLogger } from '../../shared/logger.js';
import { escapeHtml } from '../../shared/dom.js';
import { SHORTLIST_STATUSES } from './logic.js';

export const shortlistMarkup = `<section class="page" id="page-shortlist">
  <div class="page-title"><div><div class="eyebrow">Ваши решения</div><h1>Мой выбор</h1><p>Распределите программы по статусу, добавьте заметки и сравните финальные варианты.</p></div><div class="title-actions"><button class="btn btn-primary" data-page="compare">Сравнить отмеченные</button></div></div>
  <div class="admission-demo-notice"><strong>Ваш рабочий список</strong><span>Статусы и заметки сохраняются в этом браузере. Даты подачи и обновления списков вузов пока не подключены.</span></div>
  <div class="shortlist-cols" id="shortlist-content"></div>
  <div class="route-resources" aria-label="Полезные шаги"><span>Дальше</span><button class="text-btn" data-page="admission-check">Проверить поступление →</button><button class="text-btn" data-page="rules">Правила и льготы →</button><button class="text-btn" data-page="catalog">Вернуться в каталог →</button></div>
</section>`;

const logger = createLogger('shortlist');

export function renderShortlist({ root, state, getProgram }) {
  const buckets = [
    ['main', 'Основные варианты'],
    ['backup', 'Запасные варианты'],
    ['watching', 'Пока рассматриваю'],
    ['excluded', 'Исключил'],
  ];

  root.getElementById('shortlist-content').innerHTML = buckets.map(([key, title]) => {
    const entries = Object.entries(state.shortlist).filter(([, status]) => status === key);
    const cards = entries.map(([id]) => {
      const program = getProgram(id);
      if (!program) return '';
      const statusIndex = SHORTLIST_STATUSES.findIndex(({ value }) => value === key);
      const higherStatus = SHORTLIST_STATUSES[statusIndex - 1];
      const lowerStatus = SHORTLIST_STATUSES[statusIndex + 1];
      const higherLabel = higherStatus ? `Переместить вверх в «${higherStatus.label}»` : 'Выше уже нет: основной вариант';
      const lowerLabel = lowerStatus ? `Переместить вниз в «${lowerStatus.label}»` : 'Ниже уже нет: пока рассматриваю';
      return `
        <article class="program-card">
          <div class="program-meta"><span class="code">${program.code}</span><button class="heart saved" data-save="${id}" aria-label="Убрать ${program.code} из списка">♥</button></div>
          <h3>${program.title}</h3>
          <div class="uni">${program.university}</div>
          <div class="move-controls" role="group" aria-label="Приоритет программы ${program.code}">
            <button class="move-button" type="button" data-shortlist-move="up" data-program-id="${id}" aria-label="${higherLabel}" title="${higherLabel}" ${higherStatus ? '' : 'disabled'}>↑</button>
            <button class="move-button" type="button" data-shortlist-move="down" data-program-id="${id}" aria-label="${lowerLabel}" title="${lowerLabel}" ${lowerStatus ? '' : 'disabled'}>↓</button>
          </div>
          <div class="card-actions"><button class="btn btn-outline btn-sm" data-page="program" data-program="${id}">Подробнее</button><button class="btn btn-outline btn-sm" data-compare-toggle="${id}" aria-pressed="${state.comparison.includes(id)}">${state.comparison.includes(id) ? 'Убрать из сравнения' : 'Сравнить'}</button></div>
          <label class="shortlist-note"><span>Заметка</span><textarea data-shortlist-note="${id}" rows="2" maxlength="240" placeholder="Почему рассматриваете этот вариант?">${escapeHtml(state.shortlistNotes?.[id] || '')}</textarea></label>
        </article>
      `;
    }).join('');
    const empty = '<div class="empty" style="padding:24px 5px;font-size:12px">Пока пусто.<br>Добавьте программу из каталога.</div>';
    return `<div class="bucket"><h3>${title}<span class="bucket-count">${entries.length}</span></h3>${cards || empty}</div>`;
  }).join('');

  logger.debug('render.complete', { itemCount: Object.keys(state.shortlist).length });
}
