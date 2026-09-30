import { createLogger } from '../shared/logger.js';
import { getProfileScoreTotal } from '../data/exam-subjects.js';

const logger = createLogger('shell');

export function updateShellStats(state, root = globalThis.document) {
  const shortlistCount = Object.keys(state.shortlist).length;
  const scoreTotal = getProfileScoreTotal(state.scores);

  root.querySelectorAll('.nav-count').forEach((element) => {
    element.textContent = shortlistCount || '';
  });

  const examStat = root.getElementById('exam-stat');
  const shortlistStat = root.getElementById('shortlist-stat');
  if (examStat) examStat.textContent = scoreTotal || '—';
  if (shortlistStat) shortlistStat.textContent = shortlistCount;

  logger.debug('stats.updated', { shortlistCount, hasScores: scoreTotal > 0 });
}
