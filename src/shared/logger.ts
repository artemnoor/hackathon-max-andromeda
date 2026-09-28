import { createHmac } from 'node:crypto';

import type { LogLevel } from './config.js';
import { errorToLogFields } from './errors.js';

type LogFields = Record<string, unknown>;
type LogSink = (line: string, level: LogLevel) => void;

export type LoggerOptions = Readonly<{
  level?: LogLevel;
  bindings?: LogFields;
  sink?: LogSink;
}>;

export type Logger = Readonly<{
  level: LogLevel;
  child(bindings: LogFields): Logger;
  debug(fields: unknown, message?: string): void;
  info(fields: unknown, message?: string): void;
  warn(fields: unknown, message?: string): void;
  error(fields: unknown, message?: string): void;
  fatal(fields: unknown, message?: string): void;
}>;

const LEVEL_WEIGHT: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  fatal: 50,
  silent: Number.POSITIVE_INFINITY,
};

const REDACTED_KEYS = new Set([
  'authorization', 'cookie', 'xmaxinitdata', 'initdata', 'initdataunsafe',
  'maxbottoken', 'bottoken', 'webhooksecret', 'maxdeeplinksigningkey',
  'deeplink', 'token', 'secret', 'password', 'redisurl', 'payload', 'body',
  'userid', 'chatid', 'phone', 'vcfinfo',
]);

const normalizedKey = (key: string): string => key.replace(/[-_]/g, '').toLowerCase();
const isSensitiveKey = (key: string): boolean => {
  const value = normalizedKey(key);
  return REDACTED_KEYS.has(value) || value.endsWith('token') || value.endsWith('secret');
};

export const redact = (value: unknown, key = ''): unknown => {
  if (key && isSensitiveKey(key)) return '[REDACTED]';
  if (value instanceof Error) return errorToLogFields(value);
  if (typeof value === 'string' && /(?:^|\s)(?:Bearer\s+\S+|(?:hash|auth_date|user)=\S+)/iu.test(value)) return '[REDACTED]';
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((item) => redact(item));
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .map(([childKey, childValue]) => [childKey, redact(childValue, childKey)]));
};

const defaultSink: LogSink = (line, level) => {
  const output = level === 'warn' || level === 'error' || level === 'fatal' ? process.stderr : process.stdout;
  output.write(line + '\n');
};

export const maxPrincipalHash = (userId: number, salt: string): string => {
  if (!Number.isSafeInteger(userId) || userId <= 0 || !salt) return 'unavailable';
  return createHmac('sha256', salt).update(String(userId)).digest('hex').slice(0, 16);
};

export const createLogger = (options: LoggerOptions = {}): Logger => {
  const level = options.level ?? 'info';
  const bindings = options.bindings ?? {};
  const sink = options.sink ?? defaultSink;

  const logger: Logger = {
    level,
    child(childBindings) {
      return createLogger({ level, bindings: { ...bindings, ...childBindings }, sink });
    },
    debug(fields, message) { write('debug', fields, message); },
    info(fields, message) { write('info', fields, message); },
    warn(fields, message) { write('warn', fields, message); },
    error(fields, message) { write('error', fields, message); },
    fatal(fields, message) { write('fatal', fields, message); },
  };

  const write = (entryLevel: Exclude<LogLevel, 'silent'>, fields: unknown, message?: string): void => {
    if (LEVEL_WEIGHT[entryLevel] < LEVEL_WEIGHT[level]) return;
    const normalized = fields && typeof fields === 'object' && !Array.isArray(fields)
      ? fields as LogFields
      : fields === undefined ? {} : { value: fields };
    const record = redact({
      time: new Date().toISOString(),
      level: entryLevel,
      ...bindings,
      ...normalized,
      ...(message ? { msg: message } : {}),
    }) as LogFields;
    sink(JSON.stringify(record), entryLevel);
  };

  return logger;
};