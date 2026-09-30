import { escapeHtml, safeHttpUrl } from '../../shared/dom.js';
import { bindNewsCarousel } from './carousel.js';
import { backendApi, isBackendConfigured } from '../../api/client.js';
import { educationNews } from './education-news.js';

const bridgeBoundCarousels = new WeakSet();

export function handleNewsLinkClick(event, webApp = globalThis.WebApp) {
  const link = event.target?.closest?.('.news-card-link[href]');
  if (!link || typeof webApp?.openLink !== 'function') return false;
  event.preventDefault();
  webApp.openLink(link.href);
  return true;
}

function bindNewsLinkBridge(carousel) {
  if (bridgeBoundCarousels.has(carousel)) return;
  carousel.addEventListener('click', (event) => handleNewsLinkClick(event));
  bridgeBoundCarousels.add(carousel);
}

function renderNewsCards(newsItems = [], { showStatus = false } = {}) {
  const copies = newsItems.length > 1 ? 3 : 1;
  return Array.from({ length: copies }, (_, setIndex) => newsItems.map((news, index) => {
    const sourceUrl = safeHttpUrl(news.url || news.sourceUrl);
    return `
      <article class="news-card" data-news-id="${escapeHtml(news.id)}" data-index="${setIndex * newsItems.length + index}" data-real-index="${index}" role="group" aria-roledescription="слайд" aria-label="${index + 1} из ${newsItems.length}">
        <div class="news-card-top"><time class="news-date" datetime="${escapeHtml(news.date)}">${escapeHtml(news.dateLabel)}</time>${showStatus ? `<span class="news-status">${escapeHtml(news.status || news.kind || 'Событие')}</span>` : ''}</div>
        <div class="news-card-copy"><h3>${escapeHtml(news.title)}</h3><p>${escapeHtml(news.summary)}</p></div>
        ${sourceUrl ? `<a class="news-card-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Читать новость на ${escapeHtml(news.source || news.sourceTitle || 'сайте источника')} <span aria-hidden="true">↗</span></a>` : `<span class="news-card-link">${escapeHtml(news.source || news.sourceTitle || 'Источник не подключён')}</span>`}
        <div class="news-progress" aria-hidden="true"><div class="news-progress-bar"></div></div>
      </article>`;
  }).join('')).join('');
}

export function renderNewsCarouselMarkup({ showStatus = false, newsItems = [] } = {}) {
  return `<div class="home-news-carousel" data-news-carousel data-news-count="${newsItems.length}" role="region" aria-roledescription="карусель" aria-label="Новости о поступлении">
    <div class="home-news-viewport" data-news-viewport><div class="home-news-track" data-news-track>${renderNewsCards(newsItems, { showStatus })}</div></div>
    <p class="sr-only" data-news-status aria-live="polite" aria-atomic="true"></p>
  </div>`;
}

export const newsMarkup = `
  <section class="page" id="page-news">
    <div class="page-title news-page-title">
      <div>
        <div class="eyebrow">Поступление · главное</div>
        <h1>Новости</h1>
        <p>Изменения правил, решения ведомств и события приёмной кампании. Источники и статус каждого сообщения — прямо в карточке.</p>
      </div>
    </div>
    <section class="news-page-feed" aria-labelledby="news-page-feed-title">
      <div class="home-news-heading"><h2 id="news-page-feed-title">Лента новостей</h2></div>
      ${renderNewsCarouselMarkup({ showStatus: true })}
      <p class="news-page-note">Карусель переключается автоматически. Её также можно листать жестом или нажатием на соседнюю карточку.</p>
    </section>
  </section>
`;

let newsItemsPromise;
async function loadNewsItems() {
  newsItemsPromise ||= backendApi.listNews({ limit: 20 }).then((payload) => {
    const records = payload?.items || payload;
    if (!Array.isArray(records)) throw new Error('Invalid events response');
    const apiItems = records.map((record) => {
      const date = String(record.startsAt || record.date || record.publishedAt || '').slice(0, 10);
      const parsedDate = date ? new Date(`${date}T00:00:00`) : null;
      return {
        ...record,
        id: String(record.id),
        summary: record.description || record.summary || '',
        date,
        dateLabel: parsedDate && !Number.isNaN(parsedDate.valueOf()) ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'long' }).format(parsedDate) : 'Дата не указана',
        source: record.provenance?.[0]?.sourceName || record.sourceName || 'Организатор',
        url: record.registrationUrl || record.provenance?.[0]?.url || record.url,
      };
    });
    const apiIds = new Set(apiItems.map((item) => item.id));
    const editorialItems = educationNews.filter((item) => !apiIds.has(item.id)).map((item) => {
      const parsedDate = new Date(`${item.publishedAt}T00:00:00`);
      return {
        ...item,
        date: item.publishedAt,
        dateLabel: new Intl.DateTimeFormat('ru-RU', { dateStyle: 'long' }).format(parsedDate),
        source: item.sourceName,
        status: item.kind,
      };
    });
    return [...apiItems, ...editorialItems]
      .sort((a, b) => String(b.date).localeCompare(String(a.date)))
      .slice(0, 20);
  }).catch((error) => { newsItemsPromise = null; throw error; });
  return newsItemsPromise;
}

export async function loadNewsCarousel(page) {
  const carousel = page?.querySelector?.('[data-news-carousel]');
  const track = carousel?.querySelector('[data-news-track]');
  if (!carousel || !track || !isBackendConfigured) return;
  bindNewsLinkBridge(carousel);
  try {
    const items = await loadNewsItems();
    page.classList.toggle('is-empty', items.length === 0);
    carousel.dataset.newsCount = String(items.length);
    track.innerHTML = renderNewsCards(items, { showStatus: page.id === 'page-news' });
    if (items.length > 1) bindNewsCarousel(page);
    else if (items.length === 1) track.style.transform = 'none';
    else track.innerHTML = '<p class="panel empty"><strong>Событий пока нет</strong>Andromeda API не вернуло опубликованных событий.</p>';
    page.dataset.newsApiStatus = 'loaded';
  } catch {
    page.dataset.newsApiStatus = 'unavailable';
    track.innerHTML = '<p class="panel empty"><strong>Не удалось загрузить события</strong>Andromeda API сейчас не ответило. Попробуйте позже.</p>';
  }
}

export function renderNewsPage({ root = globalThis.document } = {}) {
  return loadNewsCarousel(root.getElementById('page-news'));
}
