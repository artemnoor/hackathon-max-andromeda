import { createLogger } from '../shared/logger.js';
import { backendApi } from '../api/client.js';

const logger = createLogger('repository');
const remoteProgramCache = new Map();
let completeRemoteCatalog = null;

export function normalizeRemoteProgram(record) {
  if (!record || typeof record !== 'object') return record;
  record = record.program && typeof record.program === 'object' ? record.program : record;
  const examRequirements = Array.isArray(record.exams) ? record.exams : (record.examRequirements || []);
  const exams = Array.isArray(record.exams)
    ? record.exams.map((exam) => (typeof exam.subject === 'string' ? exam.subject : exam.subject?.name || exam.subject?.label) || exam.subjectName || exam.subjectLabel || exam.sourceName || exam.label || exam.subjectId || exam.name).filter(Boolean).join(' · ')
    : String(record.exams || '');
  const curriculum = Array.isArray(record.curriculum) ? record.curriculum.map((row) => Array.isArray(row) ? row : [
    row.discipline?.name || row.courseName || row.name || row.sourceName || '', row.discipline?.primaryArea || row.area || row.category || '', row.semester ?? null,
    row.hours ?? 0, row.assessment || row.assessmentTypes?.join?.(', ') || '', true,
  ]) : [];
  const sources = Array.isArray(record.provenance) ? record.provenance : (record.sourceAttributions || []);
  const source = sources.find((item) => item?.url || item?.sourceUrl);
  const provenance = Array.isArray(record.provenance) ? { status: source?.inferred ? 'inferred' : 'source-linked', sourceTitle: source?.sourceName || source?.kind || null, sourceUrl: source?.url || source?.sourceUrl || record.sourceUrl || null, checkedAt: source?.capturedAt || null, note: record.sourceGaps?.length ? 'Источник API содержит пробелы для части сведений.' : '' } : record.provenance;
  return {
    ...record,
    id: String(record.id),
    code: String(record.code || record.programCode || record.id),
    title: String(record.title || record.name || 'Программа без названия'),
    name: String(record.name || record.title || 'Программа без названия'),
    university: String(record.university || record.universityName || 'Вуз не указан'),
    universityName: String(record.university || record.universityName || ''),
    sourceBacked: true,
    sourceAttributions: sources,
    provenance: provenance || { status: 'source-linked', sourceUrl: record.sourceUrl || null },
    dept: String(record.dept || record.department || ''),
    areas: Array.isArray(record.areas) ? record.areas : [],
    exams,
    examRequirements,
    passing: record.passing ?? record.minimumScore ?? record.admission?.passingScore ?? null,
    budget: record.budget ?? record.budgetPlaces ?? null,
    cost: record.cost ?? record.tuitionPerYear ?? null,
    format: record.format ?? null,
    durationYears: record.durationYears ?? null,
    vuc: record.vuc ?? record.conditions?.vuc ?? 'unknown',
    benefits: record.benefits ?? record.conditions?.benefits ?? 'unknown',
    curriculum,
    fit: Array.isArray(record.fit) ? record.fit : [],
    description: String(record.description || ''),
  };
}

export function cacheRemotePrograms(records = [], { replace = false, complete = false } = {}) {
  if (replace) remoteProgramCache.clear();
  for (const record of records) {
    const program = normalizeRemoteProgram(record);
    if (program?.id) remoteProgramCache.set(String(program.id), program);
  }
  if (complete || completeRemoteCatalog !== null) completeRemoteCatalog = [...remoteProgramCache.values()];
}

export function getAvailablePrograms() {
  return [...(completeRemoteCatalog || remoteProgramCache.values())];
}

async function listPrograms(filters = {}) {
  const remote = await backendApi.listPrograms(filters);
  const records = (remote?.items || remote || []).map(normalizeRemoteProgram);
  const hasFilters = Object.values(filters).some((value) => value !== '' && value !== null && value !== undefined);
  cacheRemotePrograms(records, { replace: !hasFilters, complete: !hasFilters });
  logger.debug('listPrograms.complete', { resultCount: records.length, source: 'public_api_v1' });
  return records;
}

async function getProgram(id) {
  const program = remoteProgramCache.get(String(id)) || normalizeRemoteProgram(await backendApi.getProgram(id));
  if (program?.id) cacheRemotePrograms([program]);
  logger.debug('getProgram.complete', { programId: id, found: Boolean(program) });
  return program;
}

export function getProgramById(id) {
  return remoteProgramCache.get(String(id));
}

async function getRecommendations() {
  const response = await backendApi.getRecommendations({ limit: 10 });
  const recommendations = (response?.items || response?.recommendations || []).map((item) => remoteProgramCache.get(String(item.programId || item.program?.id))).filter(Boolean);
  logger.debug('getRecommendations.complete', { resultCount: recommendations.length, source: 'public_api_v1' });
  return recommendations;
}

async function getCompare(ids) {
  if (ids.length !== 2) return [];
  return backendApi.compare(ids);
}

export const catalogRepository = Object.freeze({ listPrograms, getProgram, getRecommendations, getCompare });
