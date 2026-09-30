import { createLogger } from '../../shared/logger.js';

const logger = createLogger('interest-test');
export const interestLabels = ['Аналитика', 'Технологии', 'Бизнес и управление', 'Исследования и дизайн'];

export function calculateInterestProfile(answers) {
  const counts = [0, 0, 0, 0];
  for (const answer of answers) {
    const selected = Array.isArray(answer) ? answer : [answer];
    for (const choice of selected) {
      if (Number.isInteger(choice) && choice >= 0 && choice < counts.length) counts[choice] += 1;
    }
  }
  return Object.fromEntries(interestLabels.map((label, index) => [label, counts[index]]));
}

export function toggleInterestAnswer({ answer, state, updateState }) {
  updateState('interest-test.answer', (current) => {
    const saved = current.testAnswers[current.testStep];
    const selected = Array.isArray(saved) ? [...saved] : Number.isInteger(saved) ? [saved] : [];
    const index = selected.indexOf(answer);
    if (index >= 0) selected.splice(index, 1);
    else selected.push(answer);
    current.testAnswers[current.testStep] = selected;
  });
  logger.debug('answer.toggled', { step: state.testStep, answer });
}

export function recordInterestAnswer({ state, updateState, skip = false, finish = false }) {
  updateState('interest-test.advance', (current) => {
    if (skip) current.testAnswers[current.testStep] = [];
    if (finish) current.testFinished = true;
    else current.testStep += 1;
  });
  logger.debug('step.advanced', { fromStep: state.testStep, skip, finish });
}

export function restartInterestTest({ updateState }) {
  updateState('interest-test.restart', (current) => {
    current.testStep = 0;
    current.testAnswers = [];
    current.testNotes = [];
    current.testFinished = false;
  });
  logger.debug('restarted');
}
