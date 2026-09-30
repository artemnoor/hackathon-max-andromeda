const LEVELS = Object.freeze({ DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40, OFF: 100 });

function resolveLogLevel() {
  const override = globalThis.ANDROMEDA_LOG_LEVEL?.toUpperCase();
  if (override && Object.hasOwn(LEVELS, override)) return override;

  const debugEnabled = new URLSearchParams(globalThis.location?.search ?? '').get('debug') === '1';
  return debugEnabled ? 'DEBUG' : 'INFO';
}

function writeLog(namespace, level, message, details) {
  if (LEVELS[level] < LEVELS[resolveLogLevel()]) return;

  const output = console[level.toLowerCase()] ?? console.log;
  const prefix = `[andromeda:${namespace}] ${message}`;
  if (details === undefined) output.call(console, prefix);
  else output.call(console, prefix, details);
}

export function createLogger(namespace) {
  if (!namespace || typeof namespace !== 'string') {
    throw new TypeError('Logger namespace must be a non-empty string');
  }

  return Object.freeze({
    debug: (message, details) => writeLog(namespace, 'DEBUG', message, details),
    info: (message, details) => writeLog(namespace, 'INFO', message, details),
    warn: (message, details) => writeLog(namespace, 'WARN', message, details),
    error: (message, details) => writeLog(namespace, 'ERROR', message, details),
  });
}
