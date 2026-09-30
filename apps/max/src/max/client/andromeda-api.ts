import type { components, paths } from '../../andromeda/generated/public-api.js';
import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { Logger } from '../../shared/logger.js';
import type { NodeEnvironment } from '../../shared/config.js';
import { normalizeAndromedaApiBaseUrl } from '../../shared/url-policy.js';

type AssistantOperation = NonNullable<paths['/api/v1/assistant/query']['post']>;
type OpenApiAssistantQueryRequest = AssistantOperation['requestBody']['content']['application/json'];
type CompareSummaryOperation = NonNullable<paths['/api/v1/compare/summary']['get']>;
type CompareSummaryResponse = CompareSummaryOperation['responses'][200]['content']['application/json'];
export type AssistantQueryInput = Pick<OpenApiAssistantQueryRequest, 'text' | 'sessionId' | 'expectedRevision'>;
export type AssistantQueryResponse = AssistantOperation['responses'][200]['content']['application/json'];
export type ProgramComparisonSummary = CompareSummaryResponse;
type AndromedaErrorResponse = components['schemas']['ErrorResponse'];

export type AssistantQueryResult = Readonly<{
  result: AssistantQueryResponse;
  profileCookie?: string;
}>;

export type AndromedaApiClientOptions = Readonly<{
  baseUrl: string;
  environment: NodeEnvironment;
  profileCookieName: string;
  timeoutMs: number;
  profileCookieSecure: boolean;
  fetcher?: typeof fetch;
  logger?: Logger;
  now?: () => number;
}>;

export const ANDROMEDA_ASSISTANT_PATH = '/api/v1/assistant/query';
export const ANDROMEDA_COMPARE_SUMMARY_PATH = '/api/v1/compare/summary';
export const MAX_ANDROMEDA_RESPONSE_BYTES = 128_000;
const MAX_ASSISTANT_TEXT_CODEPOINTS = 4_000;
const MAX_ASSISTANT_TEXT_BYTES = 16_000;
const SESSION_ID_PATTERN = /^query-session:[0-9a-f]{32}$/u;
const PROGRAM_ID_PATTERN = /^program:[a-z0-9-]+:[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}$/u;
const PROFILE_COOKIE_PATTERN = /^[A-Za-z0-9_-]{32,256}$/u;
const COOKIE_NAME_PATTERN = /^[A-Za-z0-9_-]{1,64}$/u;
const VALID_RESPONSE_MODES = new Set([
  'deterministic',
  'source_backed_verbalization',
  'unverified_fallback',
]);
const VALID_ASSISTANT_STATES = new Set(['needs_clarification', 'complete', 'ambiguous']);
const VALID_ANDROMEDA_ERROR_CODES = new Set([
  'VALIDATION_ERROR',
  'RATE_LIMITED',
  'UNAUTHORIZED',
  'FORBIDDEN',
  'NOT_FOUND',
  'CONFLICT',
  'SOURCE_CONTRACT_ERROR',
  'CONTRACT_ERROR',
  'INTERNAL_ERROR',
  'UNSUPPORTED_METRIC',
  'UNSUPPORTED_AGGREGATION',
  'INVALID_QUERY',
  'AMBIGUOUS_ENTITY',
  'INSUFFICIENT_DATA',
]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const dependencyError = (operation: string, cause?: unknown): AppError =>
  new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation }, { cause });

const parseAssistantResult = (value: unknown): AssistantQueryResponse => {
  if (!isRecord(value)
    || typeof value['state'] !== 'string'
    || !VALID_ASSISTANT_STATES.has(value['state'])
    || typeof value['session_id'] !== 'string'
    || !SESSION_ID_PATTERN.test(value['session_id'])
    || !Number.isSafeInteger(value['revision'])
    || Number(value['revision']) < 1
    || !Array.isArray(value['options'])
    || value['options'].length > 32
    || !value['options'].every((option) => typeof option === 'string' && option.length <= 512)
    || !Array.isArray(value['missing_slots'])
    || !Array.isArray(value['admission_requests'])) {
    throw dependencyError('andromeda_assistant_schema');
  }
  if (value['state'] === 'needs_clarification' && typeof value['question'] !== 'string') {
    throw dependencyError('andromeda_assistant_clarification_schema');
  }
  const response = value['response'];
  if (response !== undefined && response !== null) {
    if (!isRecord(response)
      || typeof response['text'] !== 'string'
      || response['text'].length > 20_000
      || typeof response['response_mode'] !== 'string'
      || !VALID_RESPONSE_MODES.has(response['response_mode'])
      || !Array.isArray(response['actions'])
      || !Array.isArray(response['evidence'])) {
      throw dependencyError('andromeda_response_envelope_schema');
    }
  }
  return value as AssistantQueryResponse;
};

const parseErrorResponse = (value: unknown): AndromedaErrorResponse | undefined => {
  if (!isRecord(value)
    || typeof value['code'] !== 'string'
    || !VALID_ANDROMEDA_ERROR_CODES.has(value['code'])
    || typeof value['message'] !== 'string'
    || !Array.isArray(value['details'])) return undefined;
  return value as AndromedaErrorResponse;
};

const readBoundedBody = async (response: Response): Promise<Uint8Array> => {
  const contentLength = response.headers.get('content-length');
  if (contentLength !== null && /^\d+$/u.test(contentLength)
    && Number(contentLength) > MAX_ANDROMEDA_RESPONSE_BYTES) {
    await response.body?.cancel().catch(() => undefined);
    throw dependencyError('andromeda_response_size');
  }
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      size += value.byteLength;
      if (size > MAX_ANDROMEDA_RESPONSE_BYTES) {
        await reader.cancel().catch(() => undefined);
        throw dependencyError('andromeda_response_size');
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
  return bytes;
};

const parseJson = (bytes: Uint8Array, operation: string): unknown => {
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as unknown;
  } catch (cause) {
    throw dependencyError(operation, cause);
  }
};

const getSetCookieHeaders = (headers: Headers): string[] => {
  const nodeHeaders = headers as Headers & { getSetCookie?: () => string[] };
  if (typeof nodeHeaders.getSetCookie === 'function') return nodeHeaders.getSetCookie();
  const single = headers.get('set-cookie');
  return single === null ? [] : [single];
};

const profileCookieFromHeaders = (
  headers: Headers,
  cookieName: string,
  requireSecure: boolean,
): string | undefined => {
  const setCookies = getSetCookieHeaders(headers);
  if (setCookies.length > 20) throw dependencyError('andromeda_cookie_headers');
  const matches: string[] = [];
  for (const line of setCookies) {
    if (line.length > 4_096) throw dependencyError('andromeda_cookie_header_size');
    const [pair = '', ...attributeParts] = line.split(';');
    const separator = pair.indexOf('=');
    if (separator < 1) continue;
    const name = pair.slice(0, separator).trim();
    if (name !== cookieName) continue;
    const value = pair.slice(separator + 1).trim();
    const attributes = new Map(attributeParts.map((attribute) => {
      const [key = '', ...rest] = attribute.trim().split('=');
      return [key.toLowerCase(), rest.join('=').trim().toLowerCase()] as const;
    }));
    if (!PROFILE_COOKIE_PATTERN.test(value)
      || attributes.get('path') !== '/'
      || !attributes.has('httponly')
      || (requireSecure && !attributes.has('secure'))
      || (attributes.has('samesite') && !['lax', 'strict', 'none'].includes(attributes.get('samesite') ?? ''))) {
      throw dependencyError('andromeda_profile_cookie_invalid');
    }
    matches.push(value);
  }
  if (matches.length > 1) throw dependencyError('andromeda_profile_cookie_ambiguous');
  return matches[0];
};

const statusError = (status: number, hasSession: boolean, apiError?: AndromedaErrorResponse): AppError => {
  const code = apiError?.code;
  if (status === 409 || code === 'CONFLICT') {
    return new AppError(ERROR_CODES.SESSION_CONFLICT, 409, undefined, { operation: 'andromeda_revision_conflict' });
  }
  if (status === 404 && hasSession) {
    return new AppError(ERROR_CODES.SESSION_EXPIRED, 404, undefined, { operation: 'andromeda_query_session_missing' });
  }
  if (status === 429 || code === 'RATE_LIMITED') return new AppError(ERROR_CODES.RATE_LIMITED, 429);
  if (status === 401) return new AppError(ERROR_CODES.AUTH_REQUIRED, 401);
  if (status === 403) return new AppError(ERROR_CODES.FORBIDDEN, 403);
  if (status === 400 || status === 422) return new AppError(ERROR_CODES.VALIDATION_FAILED, status);
  return dependencyError(`andromeda_http_${status}`);
};

export class AndromedaApiClient {
  private readonly baseUrl: string;
  private readonly fetcher: typeof fetch;
  private readonly now: () => number;

  constructor(private readonly options: AndromedaApiClientOptions) {
    const normalized = normalizeAndromedaApiBaseUrl(options.baseUrl, options.environment);
    if (!normalized) throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'ANDROMEDA_API_BASE_URL' });
    if (!COOKIE_NAME_PATTERN.test(options.profileCookieName)) {
      throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'ANDROMEDA_PROFILE_COOKIE_NAME' });
    }
    if (!Number.isSafeInteger(options.timeoutMs) || options.timeoutMs < 250 || options.timeoutMs > 40_000) {
      throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'ANDROMEDA_API_TIMEOUT_MS' });
    }
    this.baseUrl = normalized;
    this.fetcher = options.fetcher ?? globalThis.fetch;
    this.now = options.now ?? Date.now;
  }

  async queryAssistant(
    body: AssistantQueryInput,
    profileCookie?: string,
    signal?: AbortSignal,
  ): Promise<AssistantQueryResult> {
    this.validateRequest(body, profileCookie);
    const endpoint = `${this.baseUrl}${ANDROMEDA_ASSISTANT_PATH}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs);
    const started = this.now();
    try {
      const response = await this.fetcher(endpoint, {
        method: 'POST',
        redirect: 'error',
        headers: {
          accept: 'application/json',
          'content-type': 'application/json',
          ...(profileCookie ? { cookie: `${this.options.profileCookieName}=${profileCookie}` } : {}),
        },
        body: JSON.stringify({
          text: body.text,
          ...(body.sessionId !== undefined ? { sessionId: body.sessionId } : {}),
          ...(body.expectedRevision !== undefined ? { expectedRevision: body.expectedRevision } : {}),
        } satisfies AssistantQueryInput),
        signal: signal ? AbortSignal.any([signal, controller.signal]) : controller.signal,
      });
      const bytes = await readBoundedBody(response);
      const payload = parseJson(bytes, 'andromeda_json');
      if (!response.ok) {
        const apiError = parseErrorResponse(payload);
        const mapped = statusError(response.status, body.sessionId != null, apiError);
        this.options.logger?.warn({
          operation: 'andromeda_assistant_query',
          status: response.status,
          errorCode: apiError?.code ?? 'unrecognized',
          durationMs: Math.max(0, this.now() - started),
        });
        throw mapped;
      }
      if (response.status !== 200 || response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase() !== 'application/json') {
        throw dependencyError('andromeda_response_contract');
      }
      const result = parseAssistantResult(payload);
      const rotatedCookie = profileCookieFromHeaders(
        response.headers,
        this.options.profileCookieName,
        this.options.profileCookieSecure,
      );
      this.options.logger?.debug({
        operation: 'andromeda_assistant_query',
        status: response.status,
        durationMs: Math.max(0, this.now() - started),
      });
      return Object.freeze({ result, ...(rotatedCookie ? { profileCookie: rotatedCookie } : {}) });
    } catch (cause) {
      const error = cause instanceof AppError
        ? cause
        : controller.signal.aborted && !signal?.aborted
          ? new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'andromeda_timeout' }, { cause })
          : dependencyError('andromeda_transport', cause);
      if (!(cause instanceof AppError)) {
        this.options.logger?.warn({
          operation: 'andromeda_assistant_query',
          errorCode: error.code,
          durationMs: Math.max(0, this.now() - started),
        });
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  async compareSummary(programIds: readonly string[], signal?: AbortSignal): Promise<ProgramComparisonSummary> {
    if (programIds.length < 2 || programIds.length > 3
      || new Set(programIds).size !== programIds.length
      || !programIds.every((id) => PROGRAM_ID_PATTERN.test(id))) {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'programIds' });
    }
    const endpoint = new URL(`${this.baseUrl}${ANDROMEDA_COMPARE_SUMMARY_PATH}`);
    endpoint.searchParams.set('programIds', programIds.join(','));
    endpoint.searchParams.set('scope', 'all');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs);
    const started = this.now();
    try {
      const response = await this.fetcher(endpoint, {
        method: 'GET',
        redirect: 'error',
        headers: { accept: 'application/json' },
        signal: signal ? AbortSignal.any([signal, controller.signal]) : controller.signal,
      });
      const payload = parseJson(await readBoundedBody(response), 'andromeda_comparison_json');
      if (!response.ok) throw statusError(response.status, false, parseErrorResponse(payload));
      if (response.status !== 200
        || response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase() !== 'application/json'
        || !isRecord(payload)
        || !Array.isArray(payload['programs']) || payload['programs'].length !== programIds.length
        || !payload['programs'].every((overview) => isRecord(overview)
          && isRecord(overview['program'])
          && typeof overview['program']['id'] === 'string'
          && typeof overview['program']['code'] === 'string'
          && typeof overview['program']['name'] === 'string'
          && Array.isArray(overview['areaBreakdown'])
          && Array.isArray(overview['sourceGaps']))
        || !Array.isArray(payload['keyDifferences']) || payload['keyDifferences'].length > 128
        || !payload['keyDifferences'].every((difference) => isRecord(difference)
          && typeof difference['label'] === 'string' && typeof difference['dimension'] === 'string')
        || !Array.isArray(payload['tradeoffs']) || payload['tradeoffs'].length > 128
        || !Array.isArray(payload['sourceGaps']) || payload['sourceGaps'].length > 32) {
        throw dependencyError('andromeda_comparison_contract');
      }
      this.options.logger?.debug({
        operation: 'andromeda_compare_summary',
        status: response.status,
        durationMs: Math.max(0, this.now() - started),
        programCount: programIds.length,
      });
      return payload as ProgramComparisonSummary;
    } catch (cause) {
      const error = cause instanceof AppError
        ? cause
        : controller.signal.aborted && !signal?.aborted
          ? new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'andromeda_timeout' }, { cause })
          : dependencyError('andromeda_compare_transport', cause);
      if (!(cause instanceof AppError)) {
        this.options.logger?.warn({
          operation: 'andromeda_compare_summary',
          errorCode: error.code,
          durationMs: Math.max(0, this.now() - started),
        });
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  private validateRequest(body: AssistantQueryInput, profileCookie?: string): void {
    if (!body || typeof body.text !== 'string'
      || body.text.trim().length === 0
      || [...body.text].length > MAX_ASSISTANT_TEXT_CODEPOINTS
      || Buffer.byteLength(body.text, 'utf8') > MAX_ASSISTANT_TEXT_BYTES) {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'text' });
    }
    if (body.sessionId != null && !SESSION_ID_PATTERN.test(body.sessionId)) {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'sessionId' });
    }
    if (body.expectedRevision != null
      && (!Number.isSafeInteger(body.expectedRevision) || body.expectedRevision < 1)) {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'expectedRevision' });
    }
    if (profileCookie !== undefined && !PROFILE_COOKIE_PATTERN.test(profileCookie)) {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'profileCookie' });
    }
  }
}
