import { readStoredState, writeStoredState } from './storage.js';
import { createLogger } from '../shared/logger.js';
import { normalizeExamScores } from '../data/exam-subjects.js';

const logger = createLogger('state');

export const defaultState = Object.freeze({
  scores: {},
  profileInfo: { name: '', admissionYear: 2026 },
  examProfiles: [{ id: 'exam-main', name: 'Основной профиль', year: 2026, scores: {}, examStatuses: {}, examRanges: {} }],
  activeExamProfileId: 'exam-main',
  shortlist: {},
  shortlistNotes: {},
  viewed: [],
  comparison: [],
  interests: {},
  preferences: { form: '', maxCost: '', vuc: '', university: '', durationYears: '', budget: '', degree: '' },
  maxNotifications: { enabled: false, topics: ['rules', 'deadlines'] },
  testStep: 0,
  testAnswers: [],
  testNotes: [],
  testFinished: false,
  finalChoice: null,
});

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function normalizeProfileInfo(value) {
  const profileInfo = isRecord(value) ? value : {};
  const admissionYear = Number(profileInfo.admissionYear);

  return {
    name: typeof profileInfo.name === 'string' ? profileInfo.name.slice(0, 80) : '',
    admissionYear: Number.isInteger(admissionYear) && admissionYear >= 2024 && admissionYear <= 2035
      ? admissionYear
      : defaultState.profileInfo.admissionYear,
  };
}

const EXAM_STATUSES = new Set(['taken', 'expected', 'range', 'not-taken']);

function normalizeExamMetadata(statusValue, rangeValue, scores) {
  const statuses = {};
  const ranges = {};
  const sourceStatuses = isRecord(statusValue) ? statusValue : {};
  const sourceRanges = isRecord(rangeValue) ? rangeValue : {};
  for (const subjectId of Object.keys(scores || {}).filter((id) => id !== 'extra')) {
    const candidate = sourceStatuses[subjectId];
    statuses[subjectId] = EXAM_STATUSES.has(candidate) ? candidate : (scores[subjectId] === null ? 'not-taken' : 'taken');
    const range = sourceRanges[subjectId];
    if (statuses[subjectId] === 'range' && isRecord(range)) {
      const min = range.min === '' || range.min == null ? null : Number(range.min);
      const max = range.max === '' || range.max == null ? null : Number(range.max);
      ranges[subjectId] = {
        min: Number.isInteger(min) && min >= 0 && min <= 100 ? min : null,
        max: Number.isInteger(max) && max >= 0 && max <= 100 ? max : null,
      };
    }
  }
  return { examStatuses: statuses, examRanges: ranges };
}

function normalizeExamProfiles(value, legacyScores, admissionYear) {
  const candidates = Array.isArray(value) ? value.filter(isRecord) : [];
  const profiles = [];
  const usedIds = new Set();

  for (const [index, candidate] of candidates.entries()) {
    const baseId = typeof candidate.id === 'string' && candidate.id.trim()
      ? candidate.id.trim()
      : `exam-profile-${index + 1}`;
    let id = baseId;
    let suffix = 2;
    while (usedIds.has(id)) id = `${baseId}-${suffix++}`;
    usedIds.add(id);

    const year = Number(candidate.year);
    const scores = normalizeExamScores(candidate.scores);
    const metadata = normalizeExamMetadata(candidate.examStatuses, candidate.examRanges, scores);
    profiles.push({
      id,
      name: typeof candidate.name === 'string' && candidate.name.trim()
        ? candidate.name.trim().slice(0, 80)
        : `Профиль ЕГЭ ${index + 1}`,
      year: Number.isInteger(year) && year >= 2024 && year <= 2035 ? year : admissionYear,
      scores,
      ...metadata,
    });
  }

  if (profiles.length) return profiles;
  const scores = normalizeExamScores(legacyScores);
  return [{
    id: 'exam-main',
    name: 'Основной профиль',
    year: admissionYear,
    scores,
    ...normalizeExamMetadata({}, {}, scores),
  }];
}

function createDefaultState() {
  return {
    ...defaultState,
    scores: { ...defaultState.scores },
    profileInfo: { ...defaultState.profileInfo },
    examProfiles: defaultState.examProfiles.map((profile) => ({
      ...profile,
      scores: { ...profile.scores },
    })),
    shortlist: {},
    shortlistNotes: {},
    viewed: [...defaultState.viewed],
    comparison: [],
    interests: { ...defaultState.interests },
    preferences: { ...defaultState.preferences },
    maxNotifications: { ...defaultState.maxNotifications, topics: [...defaultState.maxNotifications.topics] },
    testAnswers: [...defaultState.testAnswers],
    testNotes: [...defaultState.testNotes],
  };
}

export function mergePersistedState(persistedState) {
  if (persistedState !== null && !isRecord(persistedState)) {
    logger.warn('state.restore.invalid_shape', { receivedType: typeof persistedState });
    persistedState = null;
  }

  const saved = persistedState ?? {};
  const merged = { ...createDefaultState(), ...saved };
  const legacyScores = isRecord(saved.scores) ? { ...saved.scores } : {};
  merged.profileInfo = normalizeProfileInfo(saved.profileInfo);
  merged.examProfiles = normalizeExamProfiles(saved.examProfiles, legacyScores, merged.profileInfo.admissionYear);
  const activeProfile = merged.examProfiles.find((profile) => profile.id === saved.activeExamProfileId)
    || merged.examProfiles[0];
  merged.activeExamProfileId = activeProfile.id;
  merged.scores = { ...activeProfile.scores };
  const activeMetadata = normalizeExamMetadata(activeProfile.examStatuses || saved.examStatuses, activeProfile.examRanges || saved.examRanges, activeProfile.scores);
  activeProfile.examStatuses = activeMetadata.examStatuses;
  activeProfile.examRanges = activeMetadata.examRanges;
  merged.examStatuses = { ...activeProfile.examStatuses };
  merged.examRanges = { ...activeProfile.examRanges };
  merged.shortlist = isRecord(saved.shortlist) ? saved.shortlist : {};
  merged.shortlistNotes = isRecord(saved.shortlistNotes) ? saved.shortlistNotes : {};
  merged.viewed = Array.isArray(saved.viewed) ? saved.viewed : [];
  merged.comparison = Array.isArray(saved.comparison) ? saved.comparison : [];
  merged.interests = isRecord(saved.interests) ? saved.interests : {};
  merged.preferences = {
    form: ['Очная', 'Очно-заочная', 'Заочная'].includes(saved.preferences?.form) ? saved.preferences.form : '',
    maxCost: Number(saved.preferences?.maxCost) > 0 ? Number(saved.preferences.maxCost) : '',
    vuc: ['yes', 'no'].includes(saved.preferences?.vuc) ? saved.preferences.vuc : '',
    university: typeof saved.preferences?.university === 'string' ? saved.preferences.university.slice(0, 120) : '',
    durationYears: [4, 5, 6].includes(Number(saved.preferences?.durationYears)) ? Number(saved.preferences.durationYears) : '',
    budget: ['budget', 'paid'].includes(saved.preferences?.budget) ? saved.preferences.budget : '',
    degree: typeof saved.preferences?.degree === 'string' ? saved.preferences.degree.slice(0, 80) : '',
  };
  merged.maxNotifications = {
    enabled: saved.maxNotifications?.enabled === true,
    topics: Array.isArray(saved.maxNotifications?.topics) ? saved.maxNotifications.topics.filter((topic) => ['rules', 'deadlines', 'news'].includes(topic)) : [...defaultState.maxNotifications.topics],
  };
  merged.testStep = Number.isInteger(saved.testStep) && saved.testStep >= 0 ? saved.testStep : 0;
  merged.testAnswers = Array.isArray(saved.testAnswers) ? saved.testAnswers : [];
  merged.testNotes = Array.isArray(saved.testNotes) ? saved.testNotes : [];
  merged.testFinished = saved.testFinished === true;
  merged.finalChoice = saved.finalChoice ?? null;

  if (saved.finalChoice === null) merged.finalChoice = null;
  return merged;
}

function createStateSummary(state) {
  return {
    fieldCount: Object.keys(state).length,
    shortlistCount: Object.keys(state.shortlist).length,
    viewedCount: state.viewed.length,
    comparisonCount: state.comparison.length,
    examProfileCount: state.examProfiles.length,
    activeExamProfileId: state.activeExamProfileId,
    quizStep: state.testStep,
    answerCount: state.testAnswers.length,
  };
}

export function createStateManager({ storage } = {}) {
  const savedState = readStoredState(storage);
  const state = mergePersistedState(savedState);
  const listeners = new Set();
  logger.debug('state.ready', createStateSummary(state));

  function notifyListeners() {
    for (const listener of listeners) {
      try {
        listener(state);
      } catch (error) {
        logger.error('state.listener.failed', { errorName: error.name });
      }
    }
  }

  function save() {
    logger.debug('state.save.start', createStateSummary(state));
    const persisted = writeStoredState(state, storage);
    notifyListeners();
    logger.debug('state.save.complete', { persisted });
    return persisted;
  }

  function update(action, mutate) {
    if (typeof mutate !== 'function') throw new TypeError('State update requires a mutator function');
    const previous = JSON.stringify(state);
    logger.debug('state.update.start', { action });
    mutate(state);
    const next = JSON.stringify(state);
    const changedFields = Object.keys(state).filter((field) => {
      const previousValue = JSON.parse(previous)[field];
      const nextValue = JSON.parse(next)[field];
      return JSON.stringify(previousValue) !== JSON.stringify(nextValue);
    });
    logger.debug('state.update.complete', { action, changedFields });
    save();
    return state;
  }

  function subscribe(listener) {
    if (typeof listener !== 'function') throw new TypeError('State listener must be a function');
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return { state, save, update, subscribe };
}

const appState = createStateManager();

export const state = appState.state;
export const saveState = appState.save;
export const updateState = appState.update;
export const subscribeToState = appState.subscribe;
