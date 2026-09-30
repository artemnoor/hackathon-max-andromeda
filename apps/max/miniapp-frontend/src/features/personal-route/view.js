import { createLogger } from '../../shared/logger.js';
import { getProfileScoreTotal } from '../../data/exam-subjects.js';

const logger = createLogger('personal-route');

export const personalRouteMarkup = `
  <section class="page" id="page-personal-route">
    <div class="page-title">
      <div>
        <div class="eyebrow">Ваш план поступления</div>
        <h1>Персональный маршрут</h1>
        <p>Соберите факты о программах и себе, чтобы перейти к уверенному выбору.</p>
      </div>
      <div class="title-actions">
        <button class="btn btn-outline" type="button" data-page="shortlist">Открыть мой выбор</button>
      </div>
    </div>

    <div id="personal-route-content"></div>
  </section>
`;

export function renderPersonalRoute({ root, state, questions }) {
  const viewedCount = state.viewed.length;
  const shortlistCount = Object.keys(state.shortlist).length;
  const scoreTotal = getProfileScoreTotal(state.scores);
  const hasLegacyInterestResult = state.testStep >= questions.length
    && state.testAnswers.length >= questions.length
    && state.testAnswers.slice(0, questions.length).every(Number.isInteger);
  const hasInterestResult = state.testFinished || state.testStep >= questions.length + 1 || hasLegacyInterestResult;

  const steps = [
    {
      id: 'explore',
      title: 'Изучить программы',
      description: viewedCount
        ? `Вы открыли программ: ${viewedCount}. Продолжайте исследовать направления, которые вам подходят.`
        : 'Посмотрите направления и откройте карточки программ, которые заинтересовали.',
      complete: viewedCount > 0,
      page: 'catalog',
      action: 'Найти программы',
    },
    {
      id: 'shortlist',
      title: 'Собрать варианты',
      description: shortlistCount
        ? `В «Моём выборе» сохранено программ: ${shortlistCount}. Расставьте приоритеты стрелками.`
        : 'Сохраняйте подходящие программы в «Мой выбор», чтобы не потерять их.',
      complete: shortlistCount > 0,
      page: 'shortlist',
      action: 'Открыть мой выбор',
    },
    {
      id: 'exams',
      title: 'Добавить баллы ЕГЭ',
      description: scoreTotal
        ? `В профиле указано баллов: ${scoreTotal}. Сверьте результаты с требованиями программ.`
        : 'Укажите предметы и баллы — так будет проще оценить подходящие варианты.',
      complete: scoreTotal > 0,
      page: 'profile',
      action: 'Заполнить профиль',
    },
    {
      id: 'interests',
      title: 'Определить интересы',
      description: hasInterestResult
        ? 'ПрофТест пройден. Посмотрите рекомендации по вашим интересам.'
        : 'Ответьте на несколько вопросов и получите отправную точку для поиска.',
      complete: hasInterestResult,
      page: 'proftest',
      action: hasInterestResult ? 'Открыть ПрофТест' : 'Пройти ПрофТест',
    },
  ];

  const completedCount = steps.filter(({ complete }) => complete).length;
  const progress = Math.round((completedCount / steps.length) * 100);
  const nextStep = steps.find(({ complete }) => !complete);
  const next = nextStep || {
    title: 'Сравнить финальные варианты',
    description: 'Основные этапы пройдены. Сопоставьте программы и выберите те, что подходят вам лучше.',
    page: 'compare',
    action: 'Сравнить программы',
  };

  root.getElementById('personal-route-content').innerHTML = `
    <div class="route-overview">
      <div class="route-progress-copy">
        <span class="eyebrow">Текущий прогресс</span>
        <h2>${completedCount === steps.length ? 'Пора сравнить финальные варианты' : 'Путь складывается из небольших шагов'}</h2>
        <p>Проходите этапы в удобном порядке. Ваш прогресс сохраняется в этом браузере.</p>
      </div>
      <div class="route-progress-ring" role="progressbar" aria-label="Прогресс персонального маршрута" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100" style="--route-progress: ${progress}%">
        <b>${progress}%</b>
      </div>
      <div class="route-stats" aria-label="Сводка персонального маршрута">
        <div><b>${shortlistCount}</b><span>в моём выборе</span></div>
        <div><b>${viewedCount}</b><span>программ изучено</span></div>
        <div><b>${scoreTotal || '—'}</b><span>баллов ЕГЭ</span></div>
      </div>
    </div>

    <section class="route-steps" aria-labelledby="route-steps-title">
      <div class="route-section-heading">
        <span class="eyebrow">План действий</span>
        <h2 id="route-steps-title">Ваши этапы</h2>
      </div>
      <div class="route-step-list">
        ${steps.map((step, index) => `
          <article class="route-step ${step.complete ? 'is-complete' : ''}" ${step === nextStep ? 'aria-current="step"' : ''}>
            <span class="route-step-index">0${index + 1}</span>
            <div class="route-step-copy">
              <div class="route-step-heading"><h3>${step.title}</h3><span class="route-step-status">${step.complete ? 'Готово' : 'Впереди'}</span></div>
              <p>${step.description}</p>
            </div>
            <button class="route-step-action" type="button" data-page="${step.page}" aria-label="${step.action}: ${step.title}">Открыть <span aria-hidden="true">→</span></button>
          </article>
        `).join('')}
      </div>
    </section>

    <section class="route-next" aria-labelledby="route-next-title">
      <div>
        <span class="eyebrow">Следующий полезный шаг</span>
        <h2 id="route-next-title">${next.title}</h2>
        <p>${next.description}</p>
      </div>
      <button class="btn btn-outline" type="button" data-page="${next.page}">${next.action}<span aria-hidden="true"> →</span></button>
    </section>

    <nav class="route-resources" aria-label="Полезные разделы">
      <span>Также полезно</span>
      <button class="text-btn" type="button" data-page="olympiads">Олимпиады <span aria-hidden="true">→</span></button>
      <button class="text-btn" type="button" data-page="rules">Правила и льготы <span aria-hidden="true">→</span></button>
    </nav>
  `;

  logger.debug('render.complete', { progress, completedCount, stepCount: steps.length });
}
