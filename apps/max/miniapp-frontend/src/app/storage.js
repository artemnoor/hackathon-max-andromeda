import { createLogger } from '../shared/logger.js';

export const STORAGE_KEY = 'andromeda-state';

const logger = createLogger('storage');

function getBrowserStorage() {
  try {
    return globalThis.localStorage ?? null;
  } catch (error) {
    logger.warn('localStorage.unavailable', { errorName: error.name });
    return null;
  }
}

export function readStoredState(storage = getBrowserStorage()) {
  if (!storage) return null;

  try {
    const serialized = storage.getItem(STORAGE_KEY);
    if (!serialized) {
      logger.debug('state.read.empty', { key: STORAGE_KEY });
      return null;
    }

    const parsed = JSON.parse(serialized);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      logger.warn('state.read.invalid_shape', { key: STORAGE_KEY });
      return null;
    }

    logger.debug('state.read.complete', { key: STORAGE_KEY, fieldCount: Object.keys(parsed).length });
    return parsed;
  } catch (error) {
    logger.warn('state.read.failed', { key: STORAGE_KEY, errorName: error.name });
    return null;
  }
}

export function writeStoredState(state, storage = getBrowserStorage()) {
  if (!storage) {
    logger.warn('state.write.skipped', { key: STORAGE_KEY, reason: 'localStorage_unavailable' });
    return false;
  }

  try {
    const serialized = JSON.stringify(state);
    storage.setItem(STORAGE_KEY, serialized);
    logger.debug('state.write.complete', { key: STORAGE_KEY, fieldCount: Object.keys(state).length });
    return true;
  } catch (error) {
    logger.error('state.write.failed', { key: STORAGE_KEY, errorName: error.name });
    return false;
  }
}
