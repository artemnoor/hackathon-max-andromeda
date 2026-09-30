import { createLogger } from '../../shared/logger.js';
import { renderNewsCarouselMarkup } from '../news/view.js';
import { loadNewsCarousel } from '../news/view.js';

const logger = createLogger('home');

export const homeMarkup = String.raw`
  <section class="page active" id="page-home">
  <section class="home-hero" aria-labelledby="home-title">
    <div class="home-orbit home-orbit-left-top" aria-hidden="true"></div>
    <div class="home-orbit home-orbit-left-bottom" aria-hidden="true"></div>
    <div class="home-orbit home-orbit-right" aria-hidden="true"><span></span></div>
    <div class="home-hero-content">
      <svg class="hero-cap" viewBox="0 0 60 45" aria-hidden="true">
        <path d="M2 12 30 1 58 12 30 24 2 12Z" />
        <path d="M14 18v12c9 6 23 6 32 0V18" />
        <path d="M55 14v17" />
        <path d="M55 30c-2 3-2 7-2 10h4c0-3 0-7-2-10Z" />
      </svg>
      <h1 id="home-title">Выбираешь, куда поступать?<br>Давай разберёмся.</h1>
      <p class="hero-description">Посмотри программы обучения, сравни условия поступления и сохрани варианты, к которым захочешь вернуться.</p>
      <div class="home-hero-actions">
        <button class="home-hero-cta" data-page="catalog">Найти программы</button>
        <button class="home-hero-cta" data-page="profile">Мой профиль</button>
      </div>
    </div>
  </section>

  <section class="home-news" aria-labelledby="home-news-title">
    <div class="home-news-heading">
      <h2 id="home-news-title">Новости</h2>
    </div>
    ${renderNewsCarouselMarkup()}
  </section>

  <section class="home-actions" aria-labelledby="home-actions-title">
    <div class="home-section-heading">
      <div>
        <span class="eyebrow">Возможности</span>
        <h2 id="home-actions-title">Всё для уверенного выбора</h2>
      </div>
      <p>Начни с любого шага — к важным решениям можно возвращаться в удобном порядке.</p>
    </div>
    <div class="action-grid">
      <button class="action-card c1" type="button" data-page="catalog">
        <span class="feature-number">01</span>
        <span class="grid" aria-hidden="true"></span><span class="cross" aria-hidden="true"></span>
        <span class="action-copy"><strong>Найти программы</strong><span>По интересам, вузу, предметам и баллам.</span></span>
        <span class="action-arrow" aria-hidden="true"></span>
      </button>
      <button class="action-card c2" type="button" data-page="profile">
        <span class="feature-number">02</span>
        <span class="grid" aria-hidden="true"></span><span class="orbit" aria-hidden="true"></span><span class="cross" aria-hidden="true"></span>
        <span class="action-copy"><strong>Проверить поступление</strong><span>Шансы, ЕГЭ, бюджет, БВИ, льготы и правила.</span></span>
        <span class="action-arrow" aria-hidden="true"></span>
      </button>
      <button class="action-card c3" type="button" data-page="compare">
        <span class="feature-number">03</span>
        <span class="grid" aria-hidden="true"></span><span class="wire" aria-hidden="true"></span>
        <span class="action-copy"><strong>Сравнить программы</strong><span>Учебные планы, математика, программирование, ИИ, поступление.</span></span>
        <span class="action-arrow" aria-hidden="true"></span>
      </button>
      <button class="action-card c4" type="button" data-page="proftest">
        <span class="feature-number">04</span>
        <span class="ellipse" aria-hidden="true"></span><span class="cross" aria-hidden="true"></span>
        <span class="action-copy"><strong>Не знаю, что выбрать</strong><span>Коротко определить интересы и получить подборку.</span></span>
        <span class="action-arrow" aria-hidden="true"></span>
      </button>
    </div>
  </section>

  <section class="home-progress" aria-labelledby="home-progress-title">
    <div class="section-head">
      <h2 id="home-progress-title">Ваш путь</h2>
      <button class="text-btn home-progress-link" data-page="personal-route">Открыть маршрут<span aria-hidden="true">→</span></button>
    </div>
    <div class="dashboard-grid">
      <article class="panel progress-panel">
        <div class="progress-top">
          <div class="progress-copy">
            <h3>Вы уже ближе, чем кажется</h3>
            <p>Собирайте факты, а не сомнения — переходите между этапами в любом порядке.</p>
          </div>
          <div class="progress-ring" role="progressbar" aria-label="Заполненность вашего выбора" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"><b id="progress-percent">0%</b></div>
        </div>
        <div class="steps" aria-hidden="true"><i class="step"></i><i class="step"></i><i class="step"></i><i class="step"></i><i class="step"></i><i class="step"></i></div>
        <div class="stat-row" role="group" aria-label="Сводка по выбору">
          <div class="stat"><b id="shortlist-stat">0</b><span>в подборке</span></div>
          <div class="stat"><b id="viewed-stat">0</b><span>просмотрено</span></div>
          <div class="stat"><b id="exam-stat">—</b><span>баллов ЕГЭ</span></div>
        </div>
      </article>
      <article class="panel next-step">
        <div class="next-step-copy">
          <div class="eyebrow">Следующий полезный шаг</div>
          <h3>Сравните финальные варианты</h3>
          <p>Сохраните программы из каталога, чтобы сравнить выбранные варианты.</p>
        </div>
        <div class="next-icon" data-hugeicon="compare" aria-hidden="true"></div>
        <button class="btn btn-primary btn-sm next-step-action" data-page="compare">Сравнить<span aria-hidden="true">→</span></button>
      </article>
    </div>
  </section>

  <section class="home-recommendations" aria-labelledby="home-recommendations-title">
    <div class="section-head"><h2 id="home-recommendations-title">Возможно, вам стоит посмотреть</h2><button class="text-btn" data-page="recommendations">Все рекомендации <span aria-hidden="true">→</span></button></div>
    <div class="cards-grid" id="home-recs"></div>
  </section>
</section>
`;

export async function renderHome({ root, repository, renderProgramCard, state }) {
  logger.debug('render.start');
  const shortlistCount = Object.keys(state?.shortlist || {}).length;
  const viewedCount = state?.viewed?.length || 0;
  const examStat = root.getElementById('exam-stat');
  const viewedStat = root.getElementById('viewed-stat');
  const progress = root.getElementById('progress-percent');
  const progressRing = progress?.closest('[role="progressbar"]');
  const milestones = [shortlistCount > 0, viewedCount > 0, Object.keys(state?.scores || {}).length > 0, Object.keys(state?.interests || {}).length > 0];
  const percent = Math.round(milestones.filter(Boolean).length / milestones.length * 100);
  root.getElementById('shortlist-stat').textContent = String(shortlistCount);
  if (viewedStat) viewedStat.textContent = String(viewedCount);
  if (examStat) examStat.textContent = String(Object.values(state?.scores || {}).filter(Number.isFinite).reduce((sum, score) => sum + score, 0) || '—');
  if (progress) progress.textContent = `${percent}%`;
  progressRing?.setAttribute('aria-valuenow', String(percent));
  root.querySelectorAll('.steps .step').forEach((step, index) => step.classList.toggle('done', Boolean(milestones[index])));
  try {
    const recommendations = await repository.getRecommendations();
    const recommendationsRoot = root.getElementById('home-recs');
    recommendationsRoot.innerHTML = recommendations.slice(0, 3).map((program) => renderProgramCard(program, false)).join('')
      || '<div class="empty"><strong>Рекомендаций пока нет</strong>Заполните профиль интересов или пройдите ПрофТест. Подборка появится, когда API вернёт подходящие программы.</div>';
  } catch (error) {
    const authRequired = error?.code === 'AUTH_REQUIRED' || error?.status === 401;
    root.getElementById('home-recs').innerHTML = authRequired
      ? '<div class="empty"><strong>Откройте Mini App из MAX</strong>MAX проверяет запуск, после чего здесь появятся программы и рекомендации из Andromeda API.</div>'
      : '<div class="empty"><strong>Данные временно недоступны</strong>Не удалось загрузить записи из Andromeda API. Попробуйте позже.</div>';
  }
  await loadNewsCarousel(root.getElementById('page-home'));
  logger.debug('render.complete', { recommendationCount: root.querySelectorAll('#home-recs .program-card').length });
}
