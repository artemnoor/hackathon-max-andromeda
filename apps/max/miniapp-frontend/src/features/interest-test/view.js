import { createLogger } from '../../shared/logger.js';
import { escapeHtml } from '../../shared/dom.js';
import { calculateInterestProfile, interestLabels } from './logic.js';

const logger = createLogger('interest-test');
const followUpAnswers = [
  'Найти закономерность в данных',
  'Спроектировать и собрать технологическое решение',
  'Организовать людей и улучшить процесс',
  'Исследовать пользователей и создать понятный прототип',
];

function getSessionQuestions(questions, answers) {
  const counts = calculateInterestProfile(answers.slice(0, questions.length));
  const preferred = interestLabels.map((label, index) => ({ label, index, count: counts[label] }))
    .sort((a, b) => b.count - a.count)[0];
  const prompt = preferred?.count
    ? `Вы чаще отмечали «${preferred.label.toLocaleLowerCase('ru-RU')}». Что в этой области хочется попробовать первым?`
    : 'Какой тип задачи вам хочется попробовать первым?';
  return [...questions, ['Уточняющий вопрос', prompt, ...followUpAnswers]];
}

export const interestTestMarkup = `
  <section class="page" id="page-proftest">
    <div class="test-layout"><div class="page-title"><div><div class="eyebrow">Уточнение интересов</div><h1 id="test-title">Что вам интересно?</h1><p id="test-subtitle">Шесть коротких вопросов, последний подстраивается под ваши ответы. Можно выбрать несколько вариантов, пропустить вопрос или завершить раньше.</p></div></div><div class="test-progress"><i id="test-progress"></i></div><div id="test-content"></div></div>
  </section>`;

export function renderInterestTest({ root, state, questions, updateState }) {
  const sessionQuestions = getSessionQuestions(questions, state.testAnswers);
  const step = state.testStep || 0;
  const progress = root.getElementById('test-progress');
  const title = root.getElementById('test-title');
  const subtitle = root.getElementById('test-subtitle');
  const content = root.getElementById('test-content');
  const legacyComplete = step >= questions.length
    && state.testAnswers.length >= questions.length
    && state.testAnswers.slice(0, questions.length).every(Number.isInteger);

  if (state.testFinished || step >= sessionQuestions.length || legacyComplete) {
    const profile = calculateInterestProfile(state.testAnswers);
    const counts = interestLabels.map((label) => profile[label]);
    const totalSignals = counts.reduce((sum, value) => sum + value, 0);
    if (JSON.stringify(state.interests) !== JSON.stringify(profile)) updateState('interest-test.result', (current) => { current.interests = profile; });
    progress.style.width = '100%';
    title.textContent = 'Что показали ваши ответы';
    subtitle.textContent = 'Это ориентир для размышления, а не тест на профессию. Вы можете уточнить его позже.';
    content.innerHTML = `
      <div class="panel">
        ${counts.every((count) => count === 0) ? '<p class="muted">Пока нет выбранных ответов. Пройдите вопросы или начните заново.</p>' : ''}
        <div class="result-interests">${interestLabels.map((label, index) => {
          const value = totalSignals ? Math.round((counts[index] / totalSignals) * 100) : 0;
          return `<div class="interest-line"><b>${label}</b><div class="bar"><i style="width:${value}%"></i></div><span>${value}% отметок</span></div>`;
        }).join('')}</div>
        <p class="small muted">Проценты показывают распределение выбранных ответов, а не вероятность успеха или профессиональную диагностику.</p>
        <div class="interest-directions"><h3>Направления, которые стоит изучить</h3>${interestLabels.map((label, index) => {
          const value = totalSignals ? Math.round((counts[index] / totalSignals) * 100) : 0;
          const suggestions = {
            'Аналитика': 'Аналитика данных, прикладная математика, финансовое моделирование',
            'Технологии': 'Программная инженерия, ИИ и данные, компьютерные системы',
            'Бизнес и управление': 'Бизнес-информатика, управление цифровыми продуктами, экономика',
            'Исследования и дизайн': 'Дизайн цифровых продуктов, UX-исследования, проектирование интерфейсов',
          }[label];
          return counts[index] ? `<div class="interest-direction"><b>${label} · ${value}% выбранных ответов</b><span>${suggestions}</span></div>` : '';
        }).join('') || '<p class="muted">Отметок пока нет. Ответьте хотя бы на один вопрос, чтобы увидеть направления.</p>'}</div>
        <h3>Программы для дальнейшего изучения</h3>
        <p class="muted small">Покажем варианты и причины, по которым они могут совпасть с вашими интересами и предметами.</p>
        <div class="card-actions"><button class="btn btn-primary" data-page="recommendations">Открыть рекомендации →</button><button class="btn btn-outline" id="test-restart">Пройти заново</button><button class="btn btn-outline" data-page="profile">Вернуться в профиль</button></div>
      </div>`;
    logger.debug('result.rendered', { answerCount: state.testAnswers.length });
    return;
  }

  const question = sessionQuestions[step];
  const selected = Array.isArray(state.testAnswers[step]) ? state.testAnswers[step] : Number.isInteger(state.testAnswers[step]) ? [state.testAnswers[step]] : [];
  progress.style.width = `${(step / sessionQuestions.length) * 100}%`;
  title.textContent = `Вопрос ${step + 1} из ${sessionQuestions.length}`;
  subtitle.textContent = 'Отметьте один или несколько вариантов. Правильного ответа нет.';
  content.innerHTML = `
    <div class="panel question-card">
      <div class="eyebrow">${escapeHtml(question[0])}</div><h2>${escapeHtml(question[1])}</h2>
      <div class="answers">${question.slice(2).map((answer, index) => `<button type="button" class="answer ${selected.includes(index) ? 'is-selected' : ''}" data-answer="${index}" aria-pressed="${selected.includes(index)}">${escapeHtml(answer)}</button>`).join('')}</div>
      <label class="test-free-answer"><span>Своя заметка · не влияет на результат</span><textarea data-test-note rows="2" maxlength="240" placeholder="Запишите мысль, если хотите вернуться к ней позже">${escapeHtml(state.testNotes?.[step] || '')}</textarea></label>
      <details class="test-why"><summary>Зачем этот вопрос?</summary><p>Он помогает заметить, какие задачи и виды работы вам ближе. Ответы будут использованы только для обзорной подборки программ.</p></details>
      <div class="test-actions"><button type="button" class="btn btn-outline" id="test-skip">Пропустить</button><button type="button" class="btn btn-primary" id="test-next">${step === sessionQuestions.length - 1 ? 'Завершить' : 'Дальше'} →</button>${step > 0 ? '<button type="button" class="text-btn" id="test-finish">Завершить раньше</button>' : ''}</div>
    </div>`;
  logger.debug('question.rendered', { step, questionCount: questions.length, selectedCount: selected.length });
}
