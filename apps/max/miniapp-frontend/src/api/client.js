/** MAX host proxy for Andromeda Public API v1. The page never calls the backend directly. */
const launchProof = () => {
  const value = globalThis.WebApp?.initData;
  return typeof value === 'string' ? value : '';
};

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'HTTP_ERROR' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export const isBackendConfigured = true;

let launchVerification;

async function request(path, { method = 'GET', body, authenticated = true } = {}) {
  const proof = launchProof();
  if (authenticated && !proof) throw new ApiError('Откройте Mini App из MAX.', { status: 401, code: 'AUTH_REQUIRED' });
  const response = await fetch(path, {
    method,
    headers: { Accept: 'application/json', ...(proof ? { 'X-Max-Init-Data': proof } : {}), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    credentials: 'omit', cache: 'no-store', redirect: 'error',
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload?.error || {};
    throw new ApiError(error.message || 'Данные сейчас недоступны. Попробуйте позже.', { status: response.status, code: error.code || 'HTTP_ERROR' });
  }
  return payload;
}

export async function apiRequest(path, options = {}) {
  launchVerification ||= request('/api/max/session').catch((error) => { launchVerification = null; throw error; });
  await launchVerification;
  return request(path, options);
}

const publicApiRequest = (path) => request(path, { authenticated: false });

const queryString = (query = {}) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  const result = params.toString();
  return result ? `?${result}` : '';
};

export const backendApi = Object.freeze({
  listPrograms: (query = {}) => publicApiRequest(`/api/max/catalog/programs${queryString({ universityId: query.universityId })}`),
  listUniversities: () => publicApiRequest('/api/max/catalog/universities'),
  getProgram: (id) => publicApiRequest(`/api/max/catalog/programs/${encodeURIComponent(id)}`),
  getCurriculum: (id) => publicApiRequest(`/api/max/catalog/programs/${encodeURIComponent(id)}/curriculum`),
  getAdmissions: (id) => publicApiRequest(`/api/max/catalog/programs/${encodeURIComponent(id)}/admissions`),
  getBenefits: (id, year) => publicApiRequest(`/api/max/data/programs/${encodeURIComponent(id)}/admission-benefits${queryString({ year })}`),
  compare: (ids) => publicApiRequest(`/api/max/catalog/compare?programIds=${encodeURIComponent(ids.join(','))}`),
  getRecommendations: (query = {}) => apiRequest(`/api/max/data/recommendations${queryString(query.limit ? { limit: query.limit } : {})}`),
  getProfile: () => apiRequest('/api/max/data/profile'),
  getPersonalRoute: (query = {}) => apiRequest(`/api/max/data/personal-route${queryString(query)}`),
  listNews: (query = {}) => (query.recommended ? apiRequest(`/api/max/data/events${queryString(query)}`) : publicApiRequest(`/api/max/data/events${queryString(query)}`)),
  evaluateAdmission: async (input) => {
    const exams = (input.exams || []).filter((exam) => exam.status === 'taken' && Number.isFinite(Number(exam.score)))
      .map((exam) => ({ subject: String(exam.subjectId), score: Number(exam.score) }));
    if (!exams.length) throw new ApiError('Укажите баллы хотя бы по одному сданному предмету ЕГЭ.', { status: 400, code: 'VALIDATION_FAILED' });
    const programsResponse = await backendApi.listPrograms();
    const programs = programsResponse?.items || [];
    const records = [];
    for (const id of (input.programIds || []).slice(0, 20)) {
      const program = programs.find((item) => item.id === id);
      if (!program) continue;
      const admissions = await backendApi.getAdmissions(id);
      const offerings = (admissions?.offerings || []).filter((item) => item.admissionYear === input.admissionYear).slice(0, 5);
      for (const offering of offerings) {
        const result = await apiRequest(`/api/max/data/programs/${encodeURIComponent(id)}/admission-fit`, {
          method: 'POST',
          body: { version: 1, offeringId: offering.id, applicant: { version: 1, scores: exams } },
        });
        records.push({
          ...result,
          programCode: program.code,
          explanation: [...(result.reasons || []).map((item) => item.message), ...(result.dataGaps || []).map((item) => item.message)].join(' '),
          sourceUrl: result.reasons?.flatMap((item) => item.provenance || []).find((item) => item.sourceUrl)?.sourceUrl,
        });
      }
    }
    return { results: records };
  },
});
