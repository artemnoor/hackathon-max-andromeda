import { AppError, ERROR_CODES, errorToLogFields } from '../../shared/errors.js';
import type { Logger } from '../../shared/logger.js';
import { isAllowedMaxApiUrl } from '../../shared/url-policy.js';
import { MaxOutboundRateLimiter } from './rate-limiter.js';

export const MAX_API_RESPONSE_BYTES = 1_048_576;
const MAX_ATTEMPTS = 3;
const REQUEST_TIMEOUT_MS = 5_000;
const MAX_RETRY_AFTER_MS = 2_000;
const RETRYABLE_STATUSES = new Set([429, 502, 503, 504]);
const TRANSIENT_CODES = new Set([
  'ECONNABORTED', 'ECONNREFUSED', 'ECONNRESET', 'EAI_AGAIN', 'ENETUNREACH', 'EHOSTUNREACH',
  'ETIMEDOUT', 'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_SOCKET',
]);

type RetryableFailure = Error & Readonly<{ status?: number; code?: string; retryAfterMs?: number }>;

export type MaxApiClientOptions = Readonly<{
  limiter: MaxOutboundRateLimiter;
  logger?: Logger;
  sleep?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  random?: () => number;
  now?: () => number;
  requestTimeoutMs?: number;
}>;

const delay = (milliseconds: number, signal: AbortSignal): Promise<void> => new Promise((resolve, reject) => {
  if (signal.aborted) {
    reject(new Error('aborted'));
    return;
  }
  const timeout = setTimeout(finish, milliseconds);
  const onAbort = (): void => {
    clearTimeout(timeout);
    signal.removeEventListener('abort', onAbort);
    reject(new Error('aborted'));
  };
  function finish(): void {
    signal.removeEventListener('abort', onAbort);
    resolve();
  }
  signal.addEventListener('abort', onAbort, { once: true });
});

const statusOf = (error: unknown): number | undefined =>
  error && typeof error === 'object' && typeof (error as { status?: unknown }).status === 'number'
    ? (error as { status: number }).status
    : undefined;

const codeOf = (error: unknown): string | undefined => {
  if (!error || typeof error !== 'object') return undefined;
  const direct = (error as { code?: unknown }).code;
  const cause = (error as { cause?: unknown }).cause;
  const nested = cause && typeof cause === 'object' ? (cause as { code?: unknown }).code : undefined;
  return typeof direct === 'string' ? direct : typeof nested === 'string' ? nested : undefined;
};

const isRetryable = (error: unknown): boolean => {
  const status = statusOf(error);
  if (status !== undefined) return RETRYABLE_STATUSES.has(status);
  const code = codeOf(error);
  return code !== undefined && TRANSIENT_CODES.has(code);
};

const operationFrom = (method: string): string => `max.${method}`;

const retryAfterMilliseconds = (response: Response, now: () => number): number | undefined => {
  const value = response.headers.get('retry-after')?.trim();
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(MAX_RETRY_AFTER_MS, Math.ceil(seconds * 1000));
  const date = Date.parse(value);
  if (!Number.isFinite(date)) return undefined;
  return Math.min(MAX_RETRY_AFTER_MS, Math.max(0, date - now()));
};

const boundedResponse = async (response: Response): Promise<Response> => {
  const length = response.headers.get('content-length');
  if (length !== null && /^\d+$/u.test(length) && Number(length) > MAX_API_RESPONSE_BYTES) {
    await response.body?.cancel().catch(() => undefined);
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_api_response_size' });
  }
  if (!response.body) return response;

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      size += value.byteLength;
      if (size > MAX_API_RESPONSE_BYTES) {
        await reader.cancel().catch(() => undefined);
        throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_api_response_size' });
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new Response(bytes, { status: response.status, statusText: response.statusText, headers: response.headers });
};

const ensureOfficialApiUrl = (input: RequestInfo | URL): void => {
  let url: URL;
  try {
    url = new URL(input instanceof Request ? input.url : input instanceof URL ? input.href : input);
  } catch {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'maxApiUrl' });
  }
  if (!isAllowedMaxApiUrl(url.origin) || url.username || url.password || url.hash) {
    throw new AppError(ERROR_CODES.FORBIDDEN, 403, undefined, { operation: 'max_api_host' });
  }
};

export class MaxApiClient {
  private readonly sleep: NonNullable<MaxApiClientOptions['sleep']>;
  private readonly random: () => number;
  private readonly now: () => number;
  private readonly requestTimeoutMs: number;

  constructor(private readonly options: MaxApiClientOptions) {
    this.sleep = options.sleep ?? delay;
    this.random = options.random ?? Math.random;
    this.now = options.now ?? Date.now;
    this.requestTimeoutMs = options.requestTimeoutMs ?? REQUEST_TIMEOUT_MS;
    if (!Number.isSafeInteger(this.requestTimeoutMs) || this.requestTimeoutMs < 1 || this.requestTimeoutMs > REQUEST_TIMEOUT_MS) {
      throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'requestTimeoutMs' });
    }
  }

  async fetch(input: RequestInfo | URL, init: RequestInit = {}, fetcher: typeof fetch = globalThis.fetch): Promise<Response> {
    ensureOfficialApiUrl(input);
    const method = String(init.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const idempotent = method === 'GET';
    const attempts = idempotent ? MAX_ATTEMPTS : 1;
    let lastError: unknown;

    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), this.requestTimeoutMs);
      const started = this.now();
      try {
        await this.options.limiter.acquire(controller.signal);
        const signal = init.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal;
        const response = await fetcher(input, { ...init, method, redirect: 'error', signal });
        if (RETRYABLE_STATUSES.has(response.status)) {
          const retryAfterMs = retryAfterMilliseconds(response, this.now);
          await response.body?.cancel().catch(() => undefined);
          throw Object.assign(new Error('MAX API transient response'), {
            status: response.status,
            ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
          }) satisfies RetryableFailure;
        }
        const bounded = await boundedResponse(response);
        this.options.logger?.debug({ operation: operationFrom(method), status: bounded.status, durationMs: Math.max(0, this.now() - started) });
        return bounded;
      } catch (caught) {
        const parentCancelled = init.signal?.aborted === true;
        lastError = controller.signal.aborted && !parentCancelled
          ? Object.assign(new Error('MAX API request timed out'), { code: 'ETIMEDOUT', cause: caught })
          : caught;
        const retry = !parentCancelled && idempotent && attempt < attempts && isRetryable(lastError);
        this.options.logger?.warn({
          operation: operationFrom(method),
          attempt,
          durationMs: Math.max(0, this.now() - started),
          retry,
          error: errorToLogFields(lastError),
        });
        if (!retry) {
          if (lastError instanceof AppError) throw lastError;
          throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: operationFrom(method) }, { cause: lastError });
        }
        const base = 100 * (2 ** (attempt - 1)) + Math.floor(this.random() * 100);
        const retryAfter = typeof lastError === 'object' && lastError !== null
          && Number.isFinite((lastError as RetryableFailure).retryAfterMs)
          ? Number((lastError as RetryableFailure).retryAfterMs)
          : 0;
        const backoff = Math.min(MAX_RETRY_AFTER_MS, Math.max(base, retryAfter));
        try {
          await this.sleep(backoff, init.signal ?? new AbortController().signal);
        } catch (cause) {
          throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: operationFrom(method) }, { cause });
        }
      } finally {
        clearTimeout(timeout);
      }
    }

    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: operationFrom('GET') }, { cause: lastError });
  }
}

export const createMaxApiFetch = (
  client: MaxApiClient,
  fetcher: typeof fetch = globalThis.fetch,
): typeof fetch => (input, init = {}) => client.fetch(input, init, fetcher);
