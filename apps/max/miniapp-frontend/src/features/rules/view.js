import { backendApi } from '../../api/client.js';
import { escapeHtml, safeHttpUrl } from '../../shared/dom.js';

export const rulesMarkup = `
  <section class="page" id="page-rules">
    <div class="page-title"><div><div class="eyebrow">Справка абитуриента</div><h1>Правила и льготы</h1><p>Правила загружаются для выбранной программы и года из Andromeda API.</p></div><div class="title-actions"><button class="btn btn-outline" data-page="news">Новости</button></div></div>
    <div class="panel rules-record-section"><label class="field" for="rules-program"><span>Программа</span><select id="rules-program"><option value="">Выберите программу</option></select></label><label class="field" for="rules-year"><span>Год приёма</span><input id="rules-year" type="number" min="2000" max="2100" value="2026"></label><button class="btn btn-primary" id="rules-load" type="button">Загрузить правила</button><div class="rules-grid" id="rules-records" aria-live="polite"></div></div>
    <section class="route-resources" aria-label="Дополнительные разделы"><span>Дополнительно</span><button class="text-btn" data-page="news">Новости о поступлении →</button><button class="text-btn" data-page="olympiads">Олимпиады →</button></section>
  </section>`;

export async function renderRulesPage({ root = globalThis.document, programs = [] } = {}) {
  const select = root.getElementById('rules-program');
  const container = root.getElementById('rules-records');
  if (!select || !container) return;
  const selected = select.value;
  select.innerHTML = '<option value="">Выберите программу</option>' + programs.map((program) => `<option value="${escapeHtml(program.id)}">${escapeHtml(program.code)} · ${escapeHtml(program.title)} · ${escapeHtml(program.university)}</option>`).join('');
  if (programs.some((program) => program.id === selected)) select.value = selected;
  const load = async () => {
    const id = select.value;
    const year = Number(root.getElementById('rules-year').value);
    if (!id || !Number.isInteger(year)) { container.innerHTML = '<p class="small muted">Выберите программу и год.</p>'; return; }
    container.innerHTML = '<p class="small muted">Загружаем правила…</p>';
    try {
      const response = await backendApi.getBenefits(id, year);
      const rules = response?.rules || [];
      container.innerHTML = rules.map((rule) => {
        const source = rule.provenance || {};
        const url = safeHttpUrl(source.sourceUrl || source.url);
        const conditions = (rule.conditions || []).map((condition) => condition.description || condition.kind || condition.type).filter(Boolean).join(' · ');
        return `<article class="rule rule-record"><div class="rule-top"><b>${escapeHtml(rule.benefitType)} · ${escapeHtml(rule.route)}</b><span class="status">${escapeHtml(rule.status)}</span></div><p>${escapeHtml(rule.sourceText || conditions || 'Условия в источнике не детализированы.')}</p><dl class="rule-metadata"><div><dt>Год</dt><dd>${rule.admissionYear}</dd></div><div><dt>Область</dt><dd>${escapeHtml(rule.scope?.kind || rule.scope?.type || 'см. источник')}</dd></div><div><dt>Подтверждение</dt><dd>${escapeHtml(rule.confirmationRequirement?.kind || rule.confirmationRequirement?.type || 'см. источник')}</dd></div><div><dt>Баллы</dt><dd>${escapeHtml(rule.points || 'не указаны')}</dd></div></dl>${url ? `<a class="text-btn" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.sourceName || 'Первоисточник')} ↗</a>` : '<span class="small muted">Ссылка на источник не приложена к записи API</span>'}</article>`;
      }).join('') || `<div class="panel empty"><strong>Для выбранной программы нет записей правил за ${year} год</strong>${(response?.sourceGaps || []).map(escapeHtml).join('<br>') || 'API не вернуло опубликованные правила.'}</div>`;
    } catch {
      container.innerHTML = '<div class="panel empty"><strong>Не удалось загрузить правила</strong>Проверьте доступность Andromeda API.</div>';
    }
  };
  const button = root.getElementById('rules-load');
  if (button && !button.dataset.bound) { button.dataset.bound = 'true'; button.addEventListener('click', load); }
  if (!select.dataset.bound) { select.dataset.bound = 'true'; select.addEventListener('change', load); }
  if (select.value) await load();
  else container.innerHTML = programs.length ? '<p class="small muted">Выберите программу для просмотра правил и льгот.</p>' : '<p class="small muted">Каталог API пока недоступен.</p>';
}
