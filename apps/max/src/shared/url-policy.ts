import { isIP } from 'node:net';

const HOST_LABEL = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/u;
const MAX_API_HOST = 'platform-api2.max.ru';

export const isSafeHostname = (value: string): boolean => {
  if (value.length < 1 || value.length > 253 || value.endsWith('.')) return false;
  return value.split('.').every((label) => label.length > 0 && label.length <= 63 && HOST_LABEL.test(label));
};

export const parseHttpOrigin = (value: string): string | undefined => {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return undefined;
    if (url.pathname !== '/' || url.search || url.hash) return undefined;
    if (!isSafeHostname(url.hostname)) return undefined;
    return url.origin;
  } catch {
    return undefined;
  }
};

export const normalizeOrigins = (values: readonly string[]): readonly string[] =>
  [...new Set(values.flatMap((value) => {
    const origin = parseHttpOrigin(value);
    return origin ? [origin] : [];
  }))];

export const isAllowedMaxApiUrl = (value: string): boolean => {
  try {
    const url = new URL(value);
    return url.protocol === 'https:'
      && url.hostname.toLowerCase() === MAX_API_HOST
      && url.port === ''
      && !url.username
      && !url.password
      && url.pathname === '/'
      && !url.search
      && !url.hash;
  } catch {
    return false;
  }
};

export const isPublicHostname = (value: string): boolean => {
  const hostname = value.toLowerCase();
  return isSafeHostname(hostname)
    && isIP(hostname) === 0
    && hostname.includes('.')
    && hostname !== 'localhost'
    && !hostname.endsWith('.localhost')
    && !hostname.endsWith('.local')
    && !hostname.endsWith('.internal');
};
export const isProductionOrigin = (value: string): boolean => {
  const origin = parseHttpOrigin(value);
  if (!origin?.startsWith('https://')) return false;
  const parsed = new URL(origin);
  if (parsed.port) return false;
  return isPublicHostname(parsed.hostname);
};
