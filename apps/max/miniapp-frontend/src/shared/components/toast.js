import { el } from '../dom.js';
import { createLogger } from '../logger.js';

const logger = createLogger('toast');

export function showToast(message) {
  const toastElement = el('toast');
  if (!toastElement) {
    logger.warn('element.missing', { elementId: 'toast' });
    return;
  }

  toastElement.textContent = message;
  toastElement.classList.add('show');
  clearTimeout(globalThis.window?.toastTimer);
  globalThis.window.toastTimer = globalThis.window.setTimeout(() => toastElement.classList.remove('show'), 2600);
  logger.debug('shown', { characterCount: message.length });
}
