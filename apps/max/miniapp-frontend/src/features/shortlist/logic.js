import { createLogger } from '../../shared/logger.js';

const logger = createLogger('shortlist');

export const SHORTLIST_STATUSES = Object.freeze([
  { value: 'main', label: 'Основной вариант' },
  { value: 'backup', label: 'Запасной вариант' },
  { value: 'watching', label: 'Пока рассматриваю' },
  { value: 'excluded', label: 'Исключил' },
]);

export function toggleShortlist({ programId, state, updateState }) {
  const wasSaved = Boolean(state.shortlist[programId]);
  if (wasSaved) {
    updateState('shortlist.remove', (current) => {
      delete current.shortlist[programId];
      delete current.shortlistNotes?.[programId];
    });
  } else {
    updateState('shortlist.add', (current) => { current.shortlist[programId] = 'watching'; });
  }
  logger.debug('item.toggled', { programId, status: wasSaved ? 'removed' : 'watching' });
  return wasSaved ? 'removed' : 'added';
}

export function moveShortlistItem({ programId, status, updateState }) {
  updateState('shortlist.move', (current) => { current.shortlist[programId] = status; });
  logger.debug('item.moved', { programId, status });
}
