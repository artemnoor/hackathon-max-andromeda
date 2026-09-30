import type { components } from '../andromeda/generated/public-api.js';
import { AppError, ERROR_CODES } from '../shared/errors.js';

type ProgramList = components['schemas']['ProgramListResponse'];
type Program = components['schemas']['ProgramResponse'];
type Curriculum = components['schemas']['CurriculumResponse'];
type Admissions = components['schemas']['ProgramAdmissionsResponse'];
type Comparison = components['schemas']['ComparisonResponse'];

const ID = /^program:(?:[a-z0-9][a-z0-9-]{0,62}:)?[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}$/u;
const MAX_BYTES = 4 * 1024 * 1024;

const invalid = (): AppError => new AppError(ERROR_CODES.VALIDATION_FAILED, 400);

const decodeId = (encoded: string): string => {
  let value: string;
  try { value = decodeURIComponent(encoded); } catch { throw invalid(); }
  if (!ID.test(value)) throw invalid();
  return value;
};

/** Only these read-only Public API v1 operations can be requested by the Mini App. */
export const catalogPublicPath = (url: URL, method = 'GET'): string | undefined => {
  const pathname = url.pathname;
  if (method === 'POST') {
    if (url.search) throw invalid();
    const fit = /^\/api\/max\/data\/programs\/([^/]+)\/admission-fit$/u.exec(pathname);
    if (!fit) return undefined;
    return `/api/v1/programs/${encodeURIComponent(decodeId(fit[1] ?? ''))}/admission-fit`;
  }
  if (method !== 'GET') return undefined;
  if (pathname === '/api/max/catalog/programs') {
    if ([...url.searchParams.keys()].some((key) => key !== 'universityId')) throw invalid();
    const universityId = url.searchParams.get('universityId');
    if (universityId && !/^university:[a-z0-9-]{1,80}$/u.test(universityId)) throw invalid();
    return `/api/v1/programs${universityId ? `?universityId=${encodeURIComponent(universityId)}` : ''}`;
  }
  if (pathname === '/api/max/catalog/universities') {
    if (url.search) throw invalid();
    return '/api/v1/universities';
  }
  if (pathname === '/api/max/catalog/compare') {
    if ([...url.searchParams.keys()].some((key) => key !== 'programIds')) throw invalid();
    const ids = (url.searchParams.get('programIds') ?? '').split(',').map(decodeId);
    if (ids.length !== 2 || ids[0] === ids[1]) throw invalid();
    return `/api/v1/compare?programIds=${encodeURIComponent(ids.join(','))}`;
  }
  if (pathname === '/api/max/data/profile' || pathname === '/api/max/data/proftest/questions') {
    if (url.search) throw invalid();
    return pathname.endsWith('/profile') ? '/api/v1/proftest/profile' : '/api/v1/proftest/questions';
  }
  if (pathname === '/api/max/data/recommendations' || pathname === '/api/max/data/personal-route') {
    if ([...url.searchParams.keys()].some((key) => key !== 'limit')) throw invalid();
    const limit = url.searchParams.get('limit');
    if (limit && (!/^\d{1,2}$/u.test(limit) || Number(limit) < 1 || Number(limit) > 20)) throw invalid();
    const endpoint = pathname.endsWith('/recommendations') ? 'recommendations/current' : 'personal-route';
    return `/api/v1/${endpoint}${limit ? `?limit=${limit}` : ''}`;
  }
  if (pathname === '/api/max/data/events') {
    const allowed = new Set(['from', 'to', 'kind', 'format', 'universityId', 'departmentId', 'programId', 'recommended', 'limit']);
    if ([...url.searchParams.keys()].some((key) => !allowed.has(key))) throw invalid();
    const limit = url.searchParams.get('limit');
    if (limit && (!/^\d{1,3}$/u.test(limit) || Number(limit) < 1 || Number(limit) > 100)) throw invalid();
    return `/api/v1/events${url.search}`;
  }
  const benefits = /^\/api\/max\/data\/programs\/([^/]+)\/admission-benefits$/u.exec(pathname);
  if (benefits) {
    if ([...url.searchParams.keys()].some((key) => !['year', 'includeReview'].includes(key))) throw invalid();
    const id = decodeId(benefits[1] ?? '');
    const year = url.searchParams.get('year');
    if (!year || !/^\d{4}$/u.test(year) || Number(year) < 2000 || Number(year) > 2100) throw invalid();
    return `/api/v1/programs/${encodeURIComponent(id)}/admission-benefits?${url.searchParams.toString()}`;
  }
  const match = /^\/api\/max\/catalog\/programs\/([^/]+)(?:\/(curriculum|admissions))?$/u.exec(pathname);
  if (!match) return undefined;
  if (url.search) throw invalid();
  const id = decodeId(match[1] ?? '');
  return `/api/v1/programs/${encodeURIComponent(id)}${match[2] ? `/${match[2]}` : ''}`;
};

/** Public catalog data can be read in an ordinary browser; personal data stays MAX-authenticated. */
export const catalogPathRequiresLaunch = (url: URL, method = 'GET'): boolean => {
  if (method !== 'GET') return true;
  return url.pathname === '/api/max/data/profile'
    || url.pathname === '/api/max/data/recommendations'
    || url.pathname === '/api/max/data/personal-route'
    || (url.pathname === '/api/max/data/events' && url.searchParams.get('recommended') === 'true');
};

type CatalogPayload = ProgramList | Program | Curriculum | Admissions | Comparison
  | components['schemas']['UniversityDiscoveryListResponse']
  | components['schemas']['EventListResponse']
  | components['schemas']['RecommendationsResponse']
  | components['schemas']['UserProfileSnapshotResponse']
  | components['schemas']['PersonalRouteResponse']
  | Record<string, unknown>
  | components['schemas']['AdmissionBenefitRuleListResponse'];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

export const fetchCatalogPayload = async (
  baseUrl: string,
  publicPath: string,
  timeoutMs: number,
  fetcher: typeof fetch = fetch,
  profileCookie?: string,
  method = 'GET',
  body?: string,
): Promise<Readonly<{ payload: CatalogPayload; setCookie?: string }>> => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(new URL(publicPath, `${baseUrl.replace(/\/$/u, '')}/`), {
      method,
      headers: { accept: 'application/json', ...(body ? { 'content-type': 'application/json' } : {}), ...(profileCookie ? { cookie: profileCookie } : {}) },
      ...(body ? { body } : {}),
      redirect: 'error',
      signal: controller.signal,
    });
    if (!response.ok) {
      if (response.status === 404) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 404, 'Программа не найдена.');
      throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
    }
    const length = Number(response.headers.get('content-length'));
    if (Number.isFinite(length) && length > MAX_BYTES) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
    const reader = response.body?.getReader();
    if (!reader) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
    const parts: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!value) continue;
        size += value.byteLength;
        if (size > MAX_BYTES) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
        parts.push(value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
    let payload: unknown;
    try { payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as unknown; }
    catch { throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503); }
    if (!isRecord(payload)) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
    const setCookie = response.headers.get('set-cookie');
    return { payload: payload as CatalogPayload, ...(setCookie && setCookie.length <= 2048 ? { setCookie } : {}) };
  } catch (error) {
    if (error instanceof AppError) throw error;
    throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
  } finally { clearTimeout(timeout); }
};
