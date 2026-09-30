import { el } from '../dom.js';
import { createLogger } from '../logger.js';

const logger = createLogger('assistant-dialog');

export function openAssistant(programTitle) {
  const modal = el('assistant-modal');
  if (!modal) {
    logger.warn('element.missing', { elementId: 'assistant-modal' });
    return;
  }

  modal.classList.add('show');
  if (programTitle) {
    const answer = el('assistant-answer');
    if (answer) answer.textContent = `Я открыл контекст программы «${programTitle}». Выберите вопрос ниже — отвечу на основе доступных данных.`;
  }
  logger.debug('opened', { hasProgramContext: Boolean(programTitle) });
}

export function closeAssistant() {
  el('assistant-modal')?.classList.remove('show');
  logger.debug('closed');
}

export function handleAssistantClick(event) {
  const target = event.target.closest('#assistant-open, #assistant-close, #assistant-modal, #detail-ask, [data-ask]');
  if (!target) return false;

  if (target.id === 'assistant-open') openAssistant();
  else if (target.id === 'assistant-close' || (target.id === 'assistant-modal' && event.target === target)) closeAssistant();
  else if (target.id === 'detail-ask') openAssistant(target.dataset.programTitle);
  else if (target.hasAttribute('data-ask')) {
    const answer = el('assistant-answer');
    if (answer) {
      answer.textContent = `По данным Andromeda: ${target.dataset.ask} В демо-режиме я могу показать сравнение, условия приёма и учебный план выбранных программ.`;
    }
  }

  return true;
}
