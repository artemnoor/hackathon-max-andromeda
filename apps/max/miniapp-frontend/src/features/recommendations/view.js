import { createLogger } from '../../shared/logger.js';
import { EGE_SUBJECTS } from '../../data/exam-subjects.js';
import { matchProgramToProfile } from '../../shared/program-analytics.js';
import { backendApi, isBackendConfigured } from '../../api/client.js';
import { escapeHtml } from '../../shared/dom.js';

const logger = createLogger('recommendations');
export const recommendationsMarkup = `
  <section class="page" id="page-recommendations">
    <div class="page-title"><div><div class="eyebrow">По вашим критериям</div><h1>Рекомендации</h1><p>Подборку возвращает Andromeda API для серверного профиля. Данные, заполненные только в этой вкладке, в API не отправляются.</p></div><div class="title-actions"><button class="btn btn-outline" data-page="profile">Настроить профиль</button></div></div>
    <div class="admission-demo-notice"><strong>Рекомендации не означают прогноз зачисления</strong><span>Показываются рекомендации, возвращённые Andromeda API. Совпадение не является вероятностью зачисления.</span></div>
    <div class="panel" id="recommendations-list"></div><div class="context-cta"><div><strong>Уточните критерии, чтобы список отражал ваши интересы</strong><p>Добавьте результаты ЕГЭ, пройдите профтест или сохраните предпочтительные программы.</p></div><button class="btn btn-light" data-page="proftest">Пройти ПрофТест</button></div>
  </section>`;

function renderRanked(root, ranked, state) {
  root.getElementById('recommendations-list').innerHTML = ranked.map(({ program, reasons, fit }) => `
    <div class="recommendation">
      <div class="rec-code">${escapeHtml(program.code)}</div>
      <div><h3>${escapeHtml(program.title)}</h3><div class="uni">${escapeHtml(program.university)}</div><div class="rec-match">${Number.isFinite(fit) ? `<b>${Math.round(fit)}%</b> content fit по данным API; это не шанс поступления` : 'API не вернуло оценку совпадения'}</div><div class="why">${reasons.map((reason) => `<span>${escapeHtml(reason)}</span>`).join('')}</div></div>
      <div class="rec-actions"><button class="btn btn-outline btn-sm" data-page="program" data-program="${escapeHtml(program.id)}">Подробнее</button><button class="btn btn-primary btn-sm" data-save="${escapeHtml(program.id)}">${state.shortlist[program.id] ? '♥' : '＋'}</button></div>
    </div>
  `).join('') || '<div class="empty"><strong>Рекомендации пока не доступны</strong>Andromeda API не вернуло подходящие программы для текущего профиля.</div>';
}

export async function renderRecommendations({ root, programs, state }) {
  const list = root.getElementById('recommendations-list');
  list.innerHTML = '<p class="small muted">Загружаем рекомендации из Andromeda API…</p>';
  if (!isBackendConfigured) { renderRanked(root, [], state); return; }
  try {
    const response = await backendApi.getRecommendations({ limit: 10 });
    const items = response?.items || response?.recommendations || [];
    const ranked = items.map((item) => {
      const program = programs.find(({ id }) => id === item.programId);
      if (!program || state.shortlist?.[program.id] === 'excluded') return null;
      const reasons = (item.reasons || []).map((reason) => typeof reason === 'string' ? reason : reason.message || reason.label).filter(Boolean);
      return { program, reasons, fit: Number(item.contentFit) };
    }).filter(Boolean);
    renderRanked(root, ranked, state);
  } catch (error) {
    logger.warn('backend.fetch_failed', { code: error.code });
    list.innerHTML = error?.code === 'AUTH_REQUIRED' || error?.status === 401
      ? '<div class="empty"><strong>Откройте Mini App из MAX</strong>Персональный API доступен только в подписанной сессии MAX.</div>'
      : error?.status === 404
        ? '<div class="empty"><strong>В Andromeda пока нет серверного профиля</strong>Личные данные, введённые в этой вкладке, сохранены в браузере и не отправлялись в API.</div>'
        : '<div class="empty"><strong>Не удалось загрузить рекомендации</strong>Andromeda API сейчас не ответило. Попробуйте позже.</div>';
  }
}
