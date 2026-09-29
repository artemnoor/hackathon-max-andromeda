/*
 * Live adapter for the attached Next.js UI.
 *
 * The backend remains the source of truth.  This module only translates the
 * generated FastAPI contract into the view-models used by the imported UI;
 * there are no catalogue, admissions, profile, or event fixtures in this path.
 */

import type { components, paths } from "./generated";
import { normalizeDecisionContext, normalizeDecisionSuggestions } from "./types";
import type {
  AdmissionFitRequest,
  AdmissionFitResponse,
  AdmissionOffering,
  AssistantQueryInput,
  AssistantQueryResponse,
  DecisionConstraintsUpdateRequest,
  DecisionContextData,
  DecisionMutationResponse,
  DecisionRevisionRequest,
  DecisionSuggestionsData,
  ShortlistRole,
  AuthSession,
  CampusPoint,
  CampusPointDetailResponse,
  CampusPointEventsResponse,
  CampusRecommendationsResponse,
  ComparisonResponse,
  ComparisonSummaryResponse,
  CurriculumResponse,
  Discipline,
  DisciplineArea,
  EventDetailResponse,
  EventItem,
  EventListResponse,
  IngestionRetryRequest,
  IngestionRunDetail,
  IngestionRunDetailResponse,
  IngestionRunListResponse,
  IngestionRunStatus,
  IngestionRunSummary,
  PersonalRouteResponse,
  PersonalRouteStep,
  ProgramSummary,
  ProgramAdmissionsResponse,
  ProgramListResponse,
  ProgramResponse,
  ProftestPreviewResponse,
  ProftestSessionAnswerRequest,
  ProftestSessionResponse,
  ProftestResultsResponse,
  ProftestSubmissionRequest,
  QuestionnaireResponse,
  Recommendation,
  RecommendationsResponse,
  Provenance,
  SourceGapReference,
  UserProfile,
  UserProfileSnapshot,
  UniversityAdminRole,
  UniversityAudienceMode,
  UniversityCatalog,
  UniversityCatalogLinks,
  UniversityCategory,
  UniversityCategoryKind,
  UniversityDiscovery,
  UniversityEvent,
  UniversityEventListResponse,
  UniversityEventStatus,
  UniversityMembership,
  UniversityUnit,
  UniversityUnitType,
} from "./types";

type ApiProgramList = paths["/programs"]["get"]["responses"][200]["content"]["application/json"];
type ApiProgram = paths["/programs/{id}"]["get"]["responses"][200]["content"]["application/json"];
type ApiCurriculum = paths["/programs/{id}/curriculum"]["get"]["responses"][200]["content"]["application/json"];
type ApiAdmissions = paths["/programs/{id}/admissions"]["get"]["responses"][200]["content"]["application/json"];
type ApiAdmissionFit = paths["/programs/{id}/admission-fit"]["post"]["responses"][200]["content"]["application/json"];
type ApiAdmissionFitRequest = NonNullable<paths["/programs/{id}/admission-fit"]["post"]["requestBody"]>["content"]["application/json"];
type ApiComparison = paths["/compare"]["get"]["responses"][200]["content"]["application/json"];
type ApiComparisonSummary = paths["/compare/summary"]["get"]["responses"][200]["content"]["application/json"];
type ApiDisciplineAreas = paths["/discipline-areas"]["get"]["responses"][200]["content"]["application/json"];
type ApiQuestions = paths["/proftest/questions"]["get"]["responses"][200]["content"]["application/json"];
type ApiPreview = paths["/proftest/preview"]["post"]["responses"][200]["content"]["application/json"];
type ApiResults = paths["/proftest/results"]["post"]["responses"][200]["content"]["application/json"];
type ApiProftestSession = paths["/proftest/sessions"]["post"]["responses"][200]["content"]["application/json"];
type ApiProftestSessionAnswer = components["schemas"]["ProftestSessionAnswerRequest"];
type ApiProftestSessionPatch = NonNullable<paths["/proftest/sessions/current"]["patch"]["requestBody"]>["content"]["application/json"];
type ApiProftestSessionNext = NonNullable<paths["/proftest/sessions/current/next"]["post"]["requestBody"]>["content"]["application/json"];
type ApiProftestAnalytics = NonNullable<paths["/proftest/analytics"]["post"]["requestBody"]>["content"]["application/json"];
type ApiProfile = paths["/proftest/profile"]["get"]["responses"][200]["content"]["application/json"];
type ApiCreateProfileRequest = NonNullable<paths["/proftest/profile"]["post"]["requestBody"]>["content"]["application/json"];
type ApiCreateProfile = paths["/proftest/profile"]["post"]["responses"][201]["content"]["application/json"];
type ApiUpdateProfileRequest = NonNullable<paths["/proftest/profile"]["put"]["requestBody"]>["content"]["application/json"];
type ApiUpdateProfile = paths["/proftest/profile"]["put"]["responses"][200]["content"]["application/json"];
type ApiRecommendationRequest = NonNullable<paths["/recommendations"]["post"]["requestBody"]>["content"]["application/json"];
type ApiRecommendationResponse = paths["/recommendations"]["post"]["responses"][200]["content"]["application/json"];
type ApiRecommendations = paths["/recommendations/current"]["get"]["responses"][200]["content"]["application/json"];
type ApiDecisionContext = paths["/decision/context"]["get"]["responses"][200]["content"]["application/json"];
type ApiDecisionSuggestions = paths["/decision/suggestions"]["get"]["responses"][200]["content"]["application/json"];
type ApiDecisionMutation = paths["/decision/constraints"]["put"]["responses"][200]["content"]["application/json"];
type ApiDecisionConstraintsUpdate = NonNullable<paths["/decision/constraints"]["put"]["requestBody"]>["content"]["application/json"];
type ApiDecisionProgramCommand = NonNullable<paths["/decision/considered"]["post"]["requestBody"]>["content"]["application/json"];
type ApiDecisionShortlistCommand = NonNullable<paths["/decision/shortlist"]["post"]["requestBody"]>["content"]["application/json"];
type ApiDecisionShortlistRole = NonNullable<paths["/decision/shortlist/{program_id}"]["patch"]["requestBody"]>["content"]["application/json"];
type ApiDecisionRevision = NonNullable<paths["/decision/shortlist/{program_id}"]["delete"]["requestBody"]>["content"]["application/json"];
type ApiDecisionAcceptSuggestion = NonNullable<paths["/decision/suggestions/{program_id}/accept"]["post"]["requestBody"]>["content"]["application/json"];
type ApiDecisionAnalytics = NonNullable<paths["/decision/analytics"]["post"]["requestBody"]>["content"]["application/json"];
type ApiDecisionAnalyticsResponse = paths["/decision/analytics"]["post"]["responses"][200]["content"]["application/json"];
type ApiFinalChoiceRequest = NonNullable<paths["/decision/final-choice"]["post"]["requestBody"]>["content"]["application/json"];
type ApiFinalChoiceMutation = paths["/decision/final-choice"]["post"]["responses"][200]["content"]["application/json"];
type ApiFinalChoiceReopen = NonNullable<paths["/decision/final-choice"]["delete"]["requestBody"]>["content"]["application/json"];
type ApiEvents = paths["/events"]["get"]["responses"][200]["content"]["application/json"];
type ApiEvent = paths["/events/{id}"]["get"]["responses"][200]["content"]["application/json"];
type ApiPoint = paths["/campus/points/{id}"]["get"]["responses"][200]["content"]["application/json"];
type ApiPointEvents = paths["/campus/points/{id}/events"]["get"]["responses"][200]["content"]["application/json"];
type ApiCampusRecommendations = paths["/campus/recommendations"]["get"]["responses"][200]["content"]["application/json"];
type ApiRoute = paths["/personal-route"]["get"]["responses"][200]["content"]["application/json"];
type ApiRuns = paths["/ops/ingestion/runs"]["get"]["responses"][200]["content"]["application/json"];
type ApiRun = paths["/ops/ingestion/runs/{id}"]["get"]["responses"][200]["content"]["application/json"];
type ApiRetry = paths["/ops/ingestion/runs/retry"]["post"]["responses"][200]["content"]["application/json"];
type ApiSession = paths["/auth/session"]["get"]["responses"][200]["content"]["application/json"];
type ApiAuthSession = paths["/auth/login"]["post"]["responses"][200]["content"]["application/json"];
type ApiImportedAuthSession = paths["/auth/decision/import-guest"]["post"]["responses"][200]["content"]["application/json"];
type ApiAuthState = paths["/auth/logout"]["post"]["responses"][200]["content"]["application/json"];
type ApiRegisterRequest = NonNullable<paths["/auth/register"]["post"]["requestBody"]>["content"]["application/json"];
type ApiLoginRequest = NonNullable<paths["/auth/login"]["post"]["requestBody"]>["content"]["application/json"];
type ApiEventsQuery = NonNullable<paths["/events"]["get"]["parameters"]["query"]>;
type ApiCampusPointEventsQuery = NonNullable<paths["/campus/points/{id}/events"]["get"]["parameters"]["query"]>;
type ApiSourceAttribution = components["schemas"]["SourceAttributionResponse"];
type ApiAdmissionProvenance = components["schemas"]["AdmissionProvenanceResponse"];
type ApiEventProvenance = components["schemas"]["EventProvenanceResponse"];
type ApiCampusProvenance = components["schemas"]["CampusProvenanceResponse"];
type ApiProvenance = ApiSourceAttribution | ApiAdmissionProvenance | ApiEventProvenance | ApiCampusProvenance;
type ApiSourceGap = components["schemas"]["SourceGapReferenceResponse"];
type ApiProgramSummary = components["schemas"]["ProgramSummaryResponse"];
type ApiDiscipline = components["schemas"]["DisciplineResponse"];
type ApiCurriculumItem = components["schemas"]["CurriculumItemResponse"];
type ApiAdmissionOffering = components["schemas"]["AdmissionOfferingResponse"];
type ApiExamRequirement = components["schemas"]["ExamRequirementResponse"];
type ApiQuota = components["schemas"]["QuotaResponse"];
type ApiPassingScore = components["schemas"]["PassingScoreResponse"];
type ApiTuition = components["schemas"]["TuitionCostResponse"];
type ApiAdmissionFitReason = components["schemas"]["AdmissionFitReasonResponse"];
type ApiRecommendationReason = components["schemas"]["ReasonResponse"];
type ApiRecommendationMetric = components["schemas"]["EvidenceMetricResponse"];
type ApiRecommendationEvidence = components["schemas"]["RecommendationEvidenceResponse"];
type ApiEventPayload = components["schemas"]["EventResponse"];
type ApiUniversityMemberships = paths["/university-admin/memberships"]["get"]["responses"][200]["content"]["application/json"];
type ApiUniversities = paths["/universities"]["get"]["responses"][200]["content"]["application/json"];
type ApiUniversityCatalog = paths["/universities/{university_id}/catalog"]["get"]["responses"][200]["content"]["application/json"];
type ApiUniversityUnits = paths["/university-admin/universities/{university_id}/units"]["get"]["responses"][200]["content"]["application/json"];
type ApiUniversityUnit = paths["/university-admin/universities/{university_id}/units/{unit_id}"]["patch"]["responses"][200]["content"]["application/json"];
type ApiUniversityCategories = paths["/university-admin/universities/{university_id}/categories"]["get"]["responses"][200]["content"]["application/json"];
type ApiUniversityCategory = paths["/university-admin/universities/{university_id}/categories/{category_id}"]["patch"]["responses"][200]["content"]["application/json"];
type ApiUniversityProgramEditorial = paths["/university-admin/universities/{university_id}/programs/{program_id}"]["patch"]["responses"][200]["content"]["application/json"];
type ApiUniversityDisciplineEditorial = paths["/university-admin/universities/{university_id}/disciplines/{discipline_id}"]["patch"]["responses"][200]["content"]["application/json"];
type ApiUniversityAdminEvents = paths["/university-admin/universities/{university_id}/events"]["get"]["responses"][200]["content"]["application/json"];
type ApiUniversityAdminEvent = paths["/university-admin/universities/{university_id}/events/{event_id}"]["get"]["responses"][200]["content"]["application/json"];
type ApiUniversityPublicEvents = paths["/universities/{university_id}/events"]["get"]["responses"][200]["content"]["application/json"];
type ApiKnowledgeReviewQueue = paths["/ops/knowledge/review-queue"]["get"]["responses"][200]["content"]["application/json"];
type ApiKnowledgeReviewDecisionRequest = NonNullable<paths["/ops/knowledge/review-actions"]["post"]["requestBody"]>["content"]["application/json"];
type ApiKnowledgeReviewDecision = paths["/ops/knowledge/review-actions"]["post"]["responses"][200]["content"]["application/json"];
type ApiKnowledgeReviewPreviewRequest = NonNullable<paths["/ops/knowledge/review-preview"]["post"]["requestBody"]>["content"]["application/json"];
type ApiKnowledgeReviewPreview = paths["/ops/knowledge/review-preview"]["post"]["responses"][200]["content"]["application/json"];

export type KnowledgeReviewQueue = ApiKnowledgeReviewQueue;
export type KnowledgeReviewTarget = components["schemas"]["ReviewTargetResponse"];
export type KnowledgeReviewAction = components["schemas"]["KnowledgeReviewAction"];
export type KnowledgeReviewPreviewContext = components["schemas"]["ReviewPolicyPreviewContext"];
export type KnowledgeReviewPolicyPreview = ApiKnowledgeReviewPreview["preview"];
export type KnowledgeReviewClaimPropositionRequest = components["schemas"]["ClaimPropositionRequest"];
type ApiUniversityPublicEvent = paths["/universities/{university_id}/events/{event_id}"]["get"]["responses"][200]["content"]["application/json"];
type ApiProvisionMembership = NonNullable<paths["/ops/university-admin/members"]["post"]["requestBody"]>["content"]["application/json"];
type ApiOwnerMembershipRequest = NonNullable<paths["/university-admin/universities/{university_id}/members"]["post"]["requestBody"]>["content"]["application/json"];
type ApiUnitRequest = NonNullable<paths["/university-admin/universities/{university_id}/units"]["post"]["requestBody"]>["content"]["application/json"];
type ApiUnitUpdateRequest = NonNullable<paths["/university-admin/universities/{university_id}/units/{unit_id}"]["patch"]["requestBody"]>["content"]["application/json"];
type ApiCategoryRequest = NonNullable<paths["/university-admin/universities/{university_id}/categories"]["post"]["requestBody"]>["content"]["application/json"];
type ApiCategoryUpdateRequest = NonNullable<paths["/university-admin/universities/{university_id}/categories/{category_id}"]["patch"]["requestBody"]>["content"]["application/json"];
type ApiCatalogLinksRequest = NonNullable<paths["/university-admin/universities/{university_id}/catalog-links"]["put"]["requestBody"]>["content"]["application/json"];
type ApiEditorialOverlayRequest = NonNullable<paths["/university-admin/universities/{university_id}/programs/{program_id}"]["patch"]["requestBody"]>["content"]["application/json"];
type ApiEventRequest = NonNullable<paths["/university-admin/universities/{university_id}/events"]["post"]["requestBody"]>["content"]["application/json"];
type ApiEventUpdateRequest = NonNullable<paths["/university-admin/universities/{university_id}/events/{event_id}"]["patch"]["requestBody"]>["content"]["application/json"];
type ApiAgendaRequest = NonNullable<paths["/university-admin/universities/{university_id}/events/{event_id}/agenda"]["put"]["requestBody"]>["content"]["application/json"];
type ApiCampusPointPayload = components["schemas"]["CampusPointResponse"] | components["schemas"]["CampusPointDetailResponse"];
type ApiRouteStepPayload = components["schemas"]["PersonalRouteStepResponse"];
type ApiAccountPayload = components["schemas"]["AccountResponse"];
type ApiProfileOutput = components["schemas"]["UserProfileResponse-Output"];

const CONFIGURED_API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api").replace(/\/$/, "");
const DEBUG_API_REQUESTS = process.env.NEXT_PUBLIC_DEBUG_API === "1";
export const API_REQUEST_TIMEOUT_MS = 45_000;

function getApiBaseUrl(): string {
  if (typeof window === "undefined") return CONFIGURED_API_BASE_URL;
  try {
    const url = new URL(CONFIGURED_API_BASE_URL);
    const localHosts = new Set(["localhost", "127.0.0.1"]);
    if (localHosts.has(url.hostname) && localHosts.has(window.location.hostname)) {
      url.hostname = window.location.hostname;
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return CONFIGURED_API_BASE_URL;
  }
}

type ApiErrorDetail = components["schemas"]["ErrorDetail"];
type ApiErrorPayload = components["schemas"]["ErrorResponse"];

function isErrorResponse(value: unknown): value is ApiErrorPayload {
  if (value === null || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.message === "string" && Array.isArray(candidate.details);
}

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly payload: ApiErrorPayload) {
    super(payload.message);
    this.name = "ApiError";
  }
}

export class ApiTimeoutError extends Error {
  constructor(public readonly path: string, public readonly timeoutMs: number) {
    super(`API request timed out after ${timeoutMs}ms`);
    this.name = "ApiTimeoutError";
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), API_REQUEST_TIMEOUT_MS);
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  const apiBaseUrl = getApiBaseUrl();

  if (DEBUG_API_REQUESTS) {
    console.debug("[FIX:catalog-api] request", { path });
  }

  try {
    const response = await fetch(getApiRequestUrl(path, apiBaseUrl), {
      ...init,
      credentials: "include",
      cache: "no-store",
      headers,
      signal: init.signal ?? controller.signal,
    });
    if (DEBUG_API_REQUESTS) {
      console.debug("[FIX:catalog-api] response", { path, status: response.status });
    }
    const text = await response.text();
    let payload: unknown = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = text;
    }
    if (!response.ok) {
      const errorPayload: ApiErrorPayload = isErrorResponse(payload)
        ? payload
        : { code: "INTERNAL_ERROR", message: `API request failed with ${response.status}`, details: [] as ApiErrorDetail[] };
      throw new ApiError(response.status, errorPayload);
    }
    return payload as T;
  } catch (error) {
    if (DEBUG_API_REQUESTS) {
      console.error("[FIX:catalog-api] request_failed", {
        path,
        message: error instanceof Error ? error.message : "unknown error",
      });
    }
    if (error instanceof DOMException ? error.name === "AbortError" : error instanceof Error && error.name === "AbortError") {
      if (!init.signal?.aborted) throw new ApiTimeoutError(path, API_REQUEST_TIMEOUT_MS);
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function _requestPath(apiBaseUrl: string, path: string): string {
  if (path.startsWith("/ops/") || path.startsWith("/university-admin/")) return path;
  if (path.startsWith("/api/v1/")) return path;

  const versionedPath = `/api/v1${path}`;
  const proxyBase = apiBaseUrl.endsWith("/api");
  return proxyBase ? versionedPath.slice("/api".length) : versionedPath;
}

export function getApiRequestUrl(path: string, apiBaseUrl = getApiBaseUrl()): string {
  return `${apiBaseUrl}${_requestPath(apiBaseUrl, path)}`;
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function mapProvenance(value: ApiProvenance | null | undefined): Provenance {
  if (!value) {
    return {
      kind: null,
      url: null,
      sourceKind: null,
      sourceUrl: null,
      capturedAt: null,
      contentSha256: null,
      locator: null,
      sourceName: null,
      universityId: null,
      runId: null,
      field: null,
      recordKey: null,
      inferred: false,
    };
  }
  const sourceKind = "sourceKind" in value ? value.sourceKind : value.kind;
  const sourceUrl = "sourceUrl" in value ? value.sourceUrl : value.url;
  const sourceName = "sourceName" in value ? value.sourceName : null;
  return {
    kind: "kind" in value ? value.kind : null,
    url: sourceUrl,
    sourceKind,
    sourceUrl,
    capturedAt: value.capturedAt,
    contentSha256: value.contentSha256,
    locator: value.locator ?? null,
    sourceName,
    universityId: value.universityId ?? null,
    runId: value.runId ?? null,
    field: value.field ?? null,
    recordKey: value.recordKey ?? null,
    inferred: value.inferred,
  };
}

function mapSourceGap(value: ApiSourceGap): SourceGapReference {
  return {
    code: value.code,
    severity: value.severity,
    message: value.message,
    sourceUrl: value.sourceUrl ?? null,
    field: value.field ?? null,
    recordKey: value.recordKey ?? null,
    canContinue: value.canContinue,
  };
}

function mapProgram(raw: ApiProgramSummary): ProgramSummary {
  return {
    id: raw.id,
    directionId: raw.directionId,
    code: raw.code,
    name: raw.name,
    educationYear: String(raw.educationYear),
    studyPlanUrl: raw.studyPlanUrl ?? null,
    sourceUrl: raw.sourceUrl ?? null,
    universityId: raw.universityId ?? null,
    universityName: raw.universityName ?? null,
    ...(raw.provenance ? { provenance: raw.provenance.map(mapProvenance) } : {}),
    ...(raw.sourceGaps ? { sourceGaps: raw.sourceGaps.map(mapSourceGap) } : {}),
  };
}

function mapDiscipline(raw: ApiDiscipline): Discipline {
  return {
    id: raw.id,
    name: raw.name,
    normalizedName: raw.normalizedName,
    primaryArea: raw.primaryArea,
    areaWeights: raw.areaWeights.map((area): DisciplineArea => ({
      code: area.code,
      name: area.name,
      description: area.description ?? null,
      weight: String(area.weight),
    })),
  };
}

function mapCurriculum(raw: ApiCurriculum): CurriculumResponse {
  return {
    program: mapProgram(raw.program),
    curriculumId: raw.curriculumId,
    educationYear: String(raw.educationYear),
    sourceUrl: raw.sourceUrl ?? null,
    capturedAt: raw.capturedAt,
    ...(raw.provenance ? { provenance: raw.provenance.map(mapProvenance) } : {}),
    ...(raw.sourceGaps ? { sourceGaps: raw.sourceGaps.map(mapSourceGap) } : {}),
    items: raw.items.map((item: ApiCurriculumItem) => ({
      id: item.id,
      discipline: mapDiscipline(item.discipline),
      sourceName: item.sourceName,
      hours: item.hours,
      semester: item.semester ?? null,
      credits: item.credits ?? null,
      assessmentTypes: item.assessmentTypes ?? null,
      sourcePosition: item.sourcePosition ?? null,
    })),
  };
}

function mapAdmissions(raw: ApiAdmissions): ProgramAdmissionsResponse {
  const offerings: AdmissionOffering[] = raw.offerings.map((offering: ApiAdmissionOffering) => ({
    id: offering.id,
    admissionYear: offering.admissionYear,
    studyForm: offering.studyForm ?? "unknown",
    fundingType: offering.fundingType ?? "unknown",
    scope: offering.scope,
    places: offering.places ?? null,
    exams: offering.exams.map((exam: ApiExamRequirement) => ({
      subject: exam.subject,
      sourceName: exam.sourceName ?? null,
      minimumScore: numberOrNull(exam.minimumScore),
      isChoice: exam.isChoice ?? false,
      isRequired: exam.isRequired ?? true,
      provenance: mapProvenance(exam.provenance),
    })),
    quotas: offering.quotas.map((quota: ApiQuota) => ({
      quotaType: quota.quotaType,
      sourceName: quota.sourceName ?? null,
      places: quota.places ?? null,
      provenance: mapProvenance(quota.provenance),
    })),
    passingScores: offering.passingScores.map((passing: ApiPassingScore) => ({
      scoreType: passing.scoreType,
      competitionType: passing.competitionType,
      status: passing.status,
      score: passing.score ?? null,
      provenance: mapProvenance(passing.provenance),
    })),
    tuition: offering.tuition.map((tuition: ApiTuition) => ({
      amount: tuition.amount,
      currency: tuition.currency,
      academicYear: tuition.academicYear ?? null,
      period: tuition.period ?? null,
      studyForm: tuition.studyForm ?? null,
      isDiscounted: tuition.isDiscounted ?? false,
      provenance: mapProvenance(tuition.provenance),
    })),
    provenance: (offering.provenance ?? []).map(mapProvenance),
  }));
  return { program: mapProgram(raw.program), programId: raw.programId, offerings };
}

function mapAdmissionFit(raw: ApiAdmissionFit): AdmissionFitResponse {
  const metric = (value: components["schemas"]["AdmissionFitMetricResponse"]) => ({
    value: numberOrNull(value.value),
    status: value.status,
  });
  const reason = (value: ApiAdmissionFitReason) => value.message;
  return {
    status: raw.status,
    score: raw.score,
    applicantTotalScore: raw.applicantTotalScore ?? null,
    dataQuality: raw.dataQuality,
    breakdown: {
      minimumReadiness: metric(raw.breakdown?.minimumReadiness),
      passingReadiness: metric(raw.breakdown?.passingReadiness),
      dataCompleteness: metric(raw.breakdown?.dataCompleteness),
    },
    reasons: raw.reasons.map(reason),
    antiReasons: raw.antiReasons.map(reason),
    dataGaps: raw.dataGaps.map(reason),
  };
}

function mapComparison(raw: ApiComparison): ComparisonResponse {
  return {
    programA: mapProgram(raw.programA),
    programB: mapProgram(raw.programB),
    scope: raw.scope,
    semester: raw.semester ?? null,
    rows: raw.rows.map((row) => ({
      discipline: row.discipline.name,
      semester: row.semester ?? null,
      hoursA: row.a?.hours ?? null,
      hoursB: row.b?.hours ?? null,
      creditsA: row.a?.credits ?? null,
      creditsB: row.b?.credits ?? null,
      presentA: row.a != null,
      presentB: row.b != null,
      deltaHours: row.hoursDelta ?? null,
      deltaCredits: row.creditsDelta ?? null,
    })),
    totalsA: { totalHours: raw.totalsA?.hours ?? 0, totalCredits: raw.totalsA?.credits ?? "0.0000" },
    totalsB: { totalHours: raw.totalsB?.hours ?? 0, totalCredits: raw.totalsB?.credits ?? "0.0000" },
    areaBreakdownA: raw.areaBreakdownA.map((item) => ({ code: item.area, name: item.name, share: item.share })),
    areaBreakdownB: raw.areaBreakdownB.map((item) => ({ code: item.area, name: item.name, share: item.share })),
    provenance: raw.provenance.map(mapProvenance),
    sourceGapDetails: raw.sourceGapDetails.map(mapSourceGap),
  };
}

function mapProfile(raw: ApiProfileOutput): UserProfile {
  const weights = (value: Record<string, string> | undefined) => Object.entries(value ?? {}).map(([code, weight]) => ({ code, name: code, weight }));
  return {
    interests: raw.interests ?? [],
    activityPreferences: raw.activityPreferences ?? [],
    antiInterests: (raw.antiInterests ?? []).map((item) => item.area),
    preferredSubjectWeights: weights(raw.preferredSubjectWeights),
    preferredActivityWeights: weights(raw.preferredActivityWeights),
    negativeWeights: weights(raw.negativeWeights),
    confidence: raw.confidence?.value ?? "0",
    confidenceByDimension: Object.entries(raw.confidenceByDimension ?? {}).map(([dimension, value]) => ({ dimension, value })),
    adaptiveAnswers: (raw.adaptiveAnswers ?? []).map((answer) => ({
      dimension: answer.dimension,
      value: answer.optionId,
    })),
  };
}

function mapProfileSnapshot(raw: ApiProfile): UserProfileSnapshot {
  return {
    profile: mapProfile(raw.profile ?? raw),
    revision: String(raw.revision ?? "0"),
    createdAt: raw.createdAt ?? new Date().toISOString(),
    updatedAt: raw.updatedAt ?? new Date().toISOString(),
    expiresAt: raw.expiresAt ?? null,
  };
}

function mapRecommendation(raw: components["schemas"]["RecommendationResponse"]): Recommendation {
  const mapShare = (value: Record<string, string>) => Object.entries(value).map(([code, share]) => ({ code, name: code, share }));
  const mapSemester = (value: Record<string, string>) => Object.entries(value).map(([semester, share]) => ({ semester: Number(semester), share }));
  const mapReason = (value: ApiRecommendationReason) => ({
    area: value.area ?? null,
    activity: value.activity ?? null,
    text: value.text,
    workload: numberOrNull(value.workload),
    share: value.share ?? null,
    sourceNames: value.sourceNames ?? [],
    provenance: value.provenance.map(mapProvenance),
  });
  const mapMetric = (value: ApiRecommendationMetric | undefined) => ({
    value: value?.value ?? null,
    status: value?.status ?? "not_available",
  });
  const mapEvidence = (value: ApiRecommendationEvidence | null | undefined) => ({
    profileConfidence: mapMetric(value?.profileConfidence),
    catalogCompleteness: mapMetric(value?.catalogCompleteness),
    sourceFreshness: {
      ...mapMetric(value?.sourceFreshness),
      latestCapturedAt: value?.sourceFreshness?.latestCapturedAt ?? null,
      runIds: value?.sourceFreshness?.runIds ?? [],
      snapshotConsistent: value?.sourceFreshness?.snapshotConsistent ?? null,
    },
    reliability: mapMetric(value?.reliability),
    signalsUsed: value?.signalsUsed ?? [],
    inferredSignals: value?.inferredSignals ?? [],
    missingData: (value?.missingData ?? []).map(mapSourceGap),
    policyVersion: value?.policyVersion ?? "content-fit.v1",
    taxonomyVersion: value?.taxonomyVersion ?? "taxonomy-22.v1",
    questionSetVersion: value?.questionSetVersion ?? null,
    profileRevision: value?.profileRevision ?? null,
    catalogRunIds: value?.catalogRunIds ?? [],
  });
  return {
    programId: raw.programId,
    programCode: raw.programCode,
    programName: raw.programName,
    contentFit: raw.contentFit,
    score: {
      programId: raw.score?.programId ?? raw.programId,
      programCode: raw.score?.programCode ?? raw.programCode,
      programName: raw.programName,
      breakdown: raw.score?.breakdown ?? {
        subjectFit: "0",
        activityFit: "0",
        distinctiveFit: "0",
        antiPenalty: "0",
        rawContentFit: String(raw.contentFit ?? 0),
      },
    },
    reasons: raw.reasons.map(mapReason),
    antiFitReasons: raw.antiFitReasons.map(mapReason),
    areaShare: mapShare(raw.areaShare),
    semesterDistribution: mapSemester(raw.semesterDistribution),
    distinctiveSubjects: raw.distinctiveSubjects,
    admissionFit: raw.admissionFit
      ? { status: raw.admissionFit.status ?? null, score: raw.admissionFit.value ?? null }
      : null,
    provenance: raw.provenance.map(mapProvenance),
    sourceGaps: raw.sourceGaps.map(mapSourceGap),
    evidence: mapEvidence(raw.evidence),
  };
}

function mapRecommendations(raw: ApiRecommendations): RecommendationsResponse {
  return {
    profile: mapProfile(raw.profile),
    recommendations: (raw.recommendations ?? []).map(mapRecommendation),
  };
}

function mapProftestSession(raw: ApiProftestSession): ProftestSessionResponse {
  const question = raw.currentQuestion;
  return {
    sessionId: raw.sessionId,
    questionSetVersion: raw.questionSetVersion,
    status: raw.status,
    cursor: raw.cursor,
    interactionCount: raw.interactionCount,
    revision: raw.revision,
    currentQuestion: question ? {
      id: question.id,
      block: question.block,
      prompt: question.prompt,
      options: question.options,
      required: question.required,
      adaptive: question.adaptive,
      multiSelect: question.multiSelect,
      maxSelected: question.maxSelected,
      stage: question.stage ?? null,
      componentType: question.componentType,
      order: question.order,
      helperText: question.helperText ?? null,
      declaredDimensions: question.declaredDimensions ?? [],
      allowUncertain: question.allowUncertain,
      allowSkip: question.allowSkip,
    } : null,
    staleQuestionIds: raw.staleQuestionIds ?? [],
    progress: raw.progress,
    adaptive: raw.adaptive ?? null,
    preliminary: raw.preliminary ?? null,
    results: raw.results ? mapRecommendations(raw.results) : null,
    profileRevision: raw.profileRevision ?? null,
  };
}

function mapEvent(raw: ApiEventPayload): EventItem {
  return {
    id: raw.id,
    title: raw.title,
    kind: raw.kind,
    format: raw.format,
    startsAt: raw.startsAt,
    endsAt: raw.endsAt ?? null,
    description: raw.description ?? null,
    registrationUrl: raw.registrationUrl ?? null,
    universityIds: raw.universityIds ?? [],
    departmentIds: raw.departmentIds ?? [],
    programIds: raw.programIds ?? [],
    venue: raw.venue ? {
      id: raw.venue.id,
      name: raw.venue.name,
      address: raw.venue.address ?? null,
      latitude: numberOrNull(raw.venue.latitude),
      longitude: numberOrNull(raw.venue.longitude),
    } : null,
    provenance: raw.provenance.map(mapProvenance),
  };
}

function mapUniversityMembership(raw: components["schemas"]["UniversityMembershipResponse"]): UniversityMembership {
  return {
    membershipId: raw.membershipId,
    accountId: raw.accountId,
    universityId: raw.universityId,
    universityName: raw.universityName ?? null,
    role: raw.role,
    status: raw.status,
    revision: raw.revision,
    createdAt: raw.createdAt,
    updatedAt: raw.updatedAt,
    revokedAt: raw.revokedAt ?? null,
  };
}

function mapUniversityUnit(raw: components["schemas"]["UniversityUnitResponse"]): UniversityUnit {
  return {
    unitId: raw.unitId,
    universityId: raw.universityId,
    unitType: raw.unitType,
    parentUnitId: raw.parentUnitId ?? null,
    slug: raw.slug,
    name: raw.name,
    description: raw.description ?? null,
    status: raw.status,
    sortOrder: raw.sortOrder,
    revision: raw.revision,
  };
}

function mapUniversityCategory(raw: components["schemas"]["UniversityCategoryResponse"]): UniversityCategory {
  return {
    categoryId: raw.categoryId,
    universityId: raw.universityId,
    slug: raw.slug,
    name: raw.name,
    description: raw.description ?? null,
    categoryKind: raw.categoryKind,
    status: raw.status,
    sortOrder: raw.sortOrder,
    revision: raw.revision,
  };
}

function mapUniversityEvent(raw: components["schemas"]["UniversityEditorialEventAdminResponse"] | components["schemas"]["UniversityEditorialEventPublicResponse"]): UniversityEvent {
  return {
    eventId: raw.eventId,
    universityId: raw.universityId,
    slug: raw.slug,
    title: raw.title,
    kind: raw.kind,
    format: raw.format,
    startsAt: raw.startsAt,
    endsAt: raw.endsAt ?? null,
    description: raw.description ?? null,
    registrationUrl: raw.registrationUrl ?? null,
    venueId: raw.venueId ?? null,
    locationLabel: raw.locationLabel ?? null,
    locationAddress: raw.locationAddress ?? null,
    onlineUrl: raw.onlineUrl ?? null,
    ...("status" in raw ? { status: raw.status, revision: raw.revision } : {}),
    audienceMode: raw.audienceMode,
    origin: raw.origin,
    units: raw.units.map((item) => ({ id: item.id, label: item.name })),
    programs: raw.programs.map((item) => ({ id: item.id, label: item.name })),
    categories: raw.categories.map((item) => ({ id: item.id, label: item.name })),
    agenda: raw.agenda.map((item) => ({
      itemId: item.itemId,
      position: item.position,
      title: item.title,
      description: item.description ?? null,
      startsAt: item.startsAt ?? null,
      endsAt: item.endsAt ?? null,
      locationLabel: item.locationLabel ?? null,
      speakerLabel: item.speakerLabel ?? null,
      revision: "revision" in item ? item.revision : 1,
    })),
  };
}

function mapUniversityCatalog(raw: ApiUniversityCatalog): UniversityCatalog {
  return {
    universityId: raw.universityId,
    universityName: raw.universityName,
    city: raw.city,
    officialSite: raw.officialSite,
    address: raw.address,
    sourceState: raw.sourceState,
    units: raw.units.map(mapUniversityUnit),
    categories: raw.categories.map(mapUniversityCategory),
    programs: raw.programs.map((item) => ({
      programId: item.programId,
      name: item.name,
      displayName: item.displayName ?? null,
      publicSummary: item.publicSummary ?? null,
      categoryIds: item.categoryIds,
      unitIds: item.unitIds,
    })),
    disciplines: raw.disciplines.map((item) => ({
      disciplineId: item.disciplineId,
      name: item.name,
      displayName: item.displayName ?? null,
      publicSummary: item.publicSummary ?? null,
      categoryIds: item.categoryIds,
      unitIds: item.unitIds,
    })),
  };
}

function mapPoint(raw: ApiCampusPointPayload): CampusPoint {
  return {
    id: raw.id,
    name: raw.name,
    pointType: raw.pointType,
    address: raw.address ?? null,
    latitude: numberOrNull(raw.latitude),
    longitude: numberOrNull(raw.longitude),
    universityIds: raw.universityIds ?? [],
    departmentIds: raw.departmentIds ?? [],
    programIds: raw.programIds ?? [],
    provenance: raw.provenance.map(mapProvenance),
  };
}

function mapRoute(raw: ApiRoute): PersonalRouteResponse {
  const recommendations = raw.recommendations.map(mapRecommendation);
  const steps: PersonalRouteStep[] = raw.steps.map((step: ApiRouteStepPayload) => {
    const point = step.point ? mapPoint(step.point) : null;
    return {
      position: step.position,
      kind: step.kind,
      reason: step.reason,
      programIds: step.programIds ?? [],
      recommendation: step.recommendation ? mapRecommendation(step.recommendation) : null,
      event: step.event ? mapEvent(step.event) : null,
      venue: point ? { id: point.id, name: point.name, address: point.address, latitude: point.latitude, longitude: point.longitude } : null,
      point,
      startsAt: step.startsAt ?? null,
    };
  });
  return { status: raw.status, summary: raw.summary, recommendations, steps };
}

function mapSession(raw: ApiAuthSession | ApiAuthState | ApiSession | ApiImportedAuthSession): AuthSession {
  const account = raw.account as ApiAccountPayload | null | undefined;
  return {
    authenticated: raw.authenticated,
    decisionTransfer: "decisionTransfer" in raw ? raw.decisionTransfer as AuthSession["decisionTransfer"] : null,
    account: account ? {
      id: account.accountId,
      email: account.email,
      displayName: null,
      createdAt: account.createdAt,
    } : null,
  };
}

function mapRun(raw: components["schemas"]["IngestionRunDetailResponse"]): IngestionRunDetail {
  return {
    id: raw.id,
    source: raw.sourceProfile ?? ((raw.sourceKinds ?? []).join(", ") || "bmstu_live"),
    status: raw.status,
    startedAt: raw.startedAt,
    finishedAt: raw.finishedAt ?? null,
    sourceCount: raw.sourceCount ?? 0,
    programCount: raw.programCount ?? 0,
    curriculumItemCount: raw.curriculumItemCount ?? 0,
    eventCount: raw.eventCount ?? 0,
    campusPointCount: raw.campusPointCount ?? 0,
    sourceGapCount: raw.sourceGapCount ?? 0,
    criticalGapCount: raw.criticalGapCount ?? 0,
    qualityStatus: raw.qualityStatus,
    driftStatus: raw.driftStatus,
    sourceProfile: raw.sourceProfile ?? null,
    universityId: raw.universityId ?? null,
    durationMs: raw.durationMs ?? null,
    projectionStatus: raw.projectionStatus,
    insertedCount: raw.insertedCount ?? 0,
    updatedCount: raw.updatedCount ?? 0,
    unchangedCount: raw.unchangedCount ?? 0,
    removedCount: raw.removedCount ?? 0,
    errorMessage: raw.errorMessage ?? null,
    errorCode: raw.errorCode ?? null,
    previousGoodRunId: raw.previousGoodRunId ?? null,
    sourceRevision: raw.sourceRevision ?? null,
    configurationVersion: raw.configurationVersion ?? null,
    retryOfRunId: raw.retryOfRunId ?? null,
    projectionTarget: raw.projectionTarget ?? null,
    heartbeatAt: raw.heartbeatAt ?? null,
    recoveryReason: raw.recoveryReason ?? null,
    sourceHashes: raw.sourceHashes ?? [],
    sourceKinds: raw.sourceKinds ?? [],
  };
}

function mapRunSummary(raw: components["schemas"]["IngestionRunSummaryResponse"]): IngestionRunSummary {
  return {
    id: raw.id,
    status: raw.status,
    startedAt: raw.startedAt,
    finishedAt: raw.finishedAt ?? null,
    source: raw.sourceProfile,
    sourceCount: raw.sourceCount,
    programCount: raw.programCount,
    curriculumItemCount: raw.curriculumItemCount,
    eventCount: raw.eventCount,
    campusPointCount: raw.campusPointCount,
    sourceGapCount: raw.sourceGapCount,
    criticalGapCount: raw.criticalGapCount,
    qualityStatus: raw.qualityStatus,
    driftStatus: raw.driftStatus,
    sourceProfile: raw.sourceProfile ?? null,
    universityId: raw.universityId ?? null,
    durationMs: raw.durationMs ?? null,
    projectionStatus: raw.projectionStatus,
  };
}

export function getPrograms(): Promise<ProgramListResponse> {
  return requestJson<ApiProgramList>("/programs").then((raw) => ({ items: raw.items.map(mapProgram) }));
}

export function getProgram(id: string): Promise<ProgramResponse> {
  return requestJson<ApiProgram>(`/programs/${encodeURIComponent(id)}`).then((raw) => ({ program: mapProgram(raw.program) }));
}

export function getCurriculum(id: string): Promise<CurriculumResponse> {
  return requestJson<ApiCurriculum>(`/programs/${encodeURIComponent(id)}/curriculum`).then(mapCurriculum);
}

export function getProgramAdmissions(id: string): Promise<ProgramAdmissionsResponse> {
  return requestJson<ApiAdmissions>(`/programs/${encodeURIComponent(id)}/admissions`).then(mapAdmissions);
}

export function calculateAdmissionFit(id: string, request: AdmissionFitRequest): Promise<AdmissionFitResponse> {
  const payload = request as ApiAdmissionFitRequest;
  return requestJson<ApiAdmissionFit>(`/programs/${encodeURIComponent(id)}/admission-fit`, {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(mapAdmissionFit);
}

export function comparePrograms(programIds: readonly [string, string], options: { scope?: "all" | "semester"; semester?: number } = {}): Promise<ComparisonResponse> {
  const params = new URLSearchParams({ programIds: programIds.join(","), scope: options.scope ?? "all" });
  if (options.semester !== undefined) params.set("semester", String(options.semester));
  return requestJson<ApiComparison>(`/compare?${params}`).then(mapComparison);
}

export function getDisciplineAreas(): Promise<{ items: DisciplineArea[] }> {
  return requestJson<ApiDisciplineAreas>("/discipline-areas").then((raw) => ({
    items: raw.items.map((item) => ({ code: item.code, name: item.name, description: item.description, weight: "1" })),
  }));
}

/** @deprecated Use startProftestSession and the version-pinned session API. */
export function getProftestQuestions(): Promise<QuestionnaireResponse> {
  return requestJson<ApiQuestions>("/proftest/questions");
}

/** @deprecated Use the session API; retained for one compatibility release. */
export function previewProftest(request: ProftestSubmissionRequest): Promise<ProftestPreviewResponse> {
  return requestJson<ApiPreview>("/proftest/preview", { method: "POST", body: JSON.stringify(request) }).then((raw) => ({
    profile: mapProfile(raw.profile),
    adaptiveDecision: {
      dimension: raw.adaptive.dimensions[0]?.code ?? "",
      decided: raw.adaptive.status === "skipped",
      nextQuestion: raw.question ?? null,
    },
    candidates: raw.candidates.map((candidate) => ({
      programId: candidate.programId,
      programName: candidate.programCode,
      contentFit: candidate.contentFit,
    })),
  }));
}

/** @deprecated Use completeProftestSession after the session flow. */
export function getProftestResults(request: ProftestSubmissionRequest): Promise<ProftestResultsResponse> {
  return requestJson<ApiResults>("/proftest/results", { method: "POST", body: JSON.stringify(request) }).then(mapRecommendations);
}

export function startProftestSession(): Promise<ProftestSessionResponse> {
  return requestJson<ApiProftestSession>("/proftest/sessions", { method: "POST", body: "{}" }).then(mapProftestSession);
}

export function getCurrentProftestSession(): Promise<ProftestSessionResponse> {
  return requestJson<ApiProftestSession>("/proftest/sessions/current").then(mapProftestSession);
}

export function nextProftestSession(answer: ProftestSessionAnswerRequest, expectedRevision: number): Promise<ProftestSessionResponse> {
  const request: ApiProftestSessionNext = { ...answer, expectedRevision };
  return requestJson<ApiProftestSession>("/proftest/sessions/current/next", { method: "POST", body: JSON.stringify(request) }).then(mapProftestSession);
}

export function saveProftestSession(answers: readonly ProftestSessionAnswerRequest[], expectedRevision: number): Promise<ProftestSessionResponse> {
  const request: ApiProftestSessionPatch = { answers: [...answers], expectedRevision };
  return requestJson<ApiProftestSession>("/proftest/sessions/current", { method: "PATCH", body: JSON.stringify(request) }).then(mapProftestSession);
}

export function completeProftestSession(): Promise<ProftestSessionResponse> {
  return requestJson<ApiProftestSession>("/proftest/sessions/current/complete", { method: "POST", body: "{}" }).then(mapProftestSession);
}

export function sendProftestAnalytics(request: ApiProftestAnalytics): Promise<{ accepted: number }> {
  return requestJson<{ accepted: number }>("/proftest/analytics", { method: "POST", body: JSON.stringify(request) });
}

export function getCurrentProfile(): Promise<UserProfileSnapshot> {
  return requestJson<ApiProfile>("/proftest/profile").then(mapProfileSnapshot);
}

export type CreateProfileRequest = ApiCreateProfileRequest;
export type UpdateProfileRequest = ApiUpdateProfileRequest;
export type RecommendationRequest = ApiRecommendationRequest;
export type CurrentProfileResponse = UserProfileSnapshot;

export function createCurrentProfile(request: CreateProfileRequest): Promise<CurrentProfileResponse> {
  return requestJson<ApiCreateProfile>("/proftest/profile", { method: "POST", body: JSON.stringify(request) }).then(mapProfileSnapshot);
}

export function updateCurrentProfile(request: UpdateProfileRequest): Promise<CurrentProfileResponse> {
  return requestJson<ApiUpdateProfile>("/proftest/profile", { method: "PUT", body: JSON.stringify(request) }).then(mapProfileSnapshot);
}

export function getRecommendations(request: RecommendationRequest): Promise<RecommendationsResponse> {
  return requestJson<ApiRecommendationResponse>("/recommendations", { method: "POST", body: JSON.stringify(request) }).then(mapRecommendations);
}

export function getCurrentRecommendations(limit = 10): Promise<RecommendationsResponse> {
  return requestJson<ApiRecommendations>(`/recommendations/current?limit=${encodeURIComponent(String(limit))}`).then(mapRecommendations);
}

export function getComparisonSummary(
  programIds: readonly string[],
  options: { scope?: "all" | "semester"; semester?: number } = {},
): Promise<ComparisonSummaryResponse> {
  const params = new URLSearchParams({ programIds: programIds.join(","), scope: options.scope ?? "all" });
  if (options.semester !== undefined) params.set("semester", String(options.semester));
  return requestJson<ApiComparisonSummary>(`/compare/summary?${params}`);
}

type ApiDecisionCommandResponse = ApiDecisionMutation;

function mapDecisionMutation(raw: ApiDecisionCommandResponse): DecisionMutationResponse {
  return { ...raw, context: normalizeDecisionContext(raw.context) };
}

function revisionBody(expectedRevision?: number | null): DecisionRevisionRequest {
  return expectedRevision === undefined ? {} : { expectedRevision };
}

export function getDecisionContext(): Promise<DecisionContextData> {
  return requestJson<ApiDecisionContext>("/decision/context").then(normalizeDecisionContext);
}

export function getDecisionSuggestions(): Promise<DecisionSuggestionsData> {
  return requestJson<ApiDecisionSuggestions>("/decision/suggestions").then(normalizeDecisionSuggestions);
}

export function updateDecisionConstraints(request: DecisionConstraintsUpdateRequest): Promise<DecisionMutationResponse> {
  const payload: ApiDecisionConstraintsUpdate = request;
  return requestJson<ApiDecisionCommandResponse>("/decision/constraints", {
    method: "PUT",
    body: JSON.stringify(payload),
  }).then(mapDecisionMutation);
}

export function markDecisionProgramConsidered(programId: string, expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  const payload: ApiDecisionProgramCommand = { version: 1, programId, expectedRevision };
  return requestJson<ApiDecisionCommandResponse>("/decision/considered", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(mapDecisionMutation);
}

export function addDecisionShortlist(
  programId: string,
  role: ShortlistRole = "primary",
  expectedRevision?: number | null,
): Promise<DecisionMutationResponse> {
  const payload: ApiDecisionShortlistCommand = { version: 1, programId, role, expectedRevision };
  return requestJson<ApiDecisionCommandResponse>("/decision/shortlist", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(mapDecisionMutation);
}

export function removeDecisionShortlist(programId: string, expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  return requestJson<ApiDecisionCommandResponse>(`/decision/shortlist/${encodeURIComponent(programId)}`, {
    method: "DELETE",
    body: JSON.stringify(revisionBody(expectedRevision)),
  }).then(mapDecisionMutation);
}

export function restoreDecisionShortlist(programId: string, expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  return requestJson<ApiDecisionCommandResponse>(`/decision/programs/${encodeURIComponent(programId)}/restore`, {
    method: "POST",
    body: JSON.stringify(revisionBody(expectedRevision)),
  }).then(mapDecisionMutation);
}

export function setDecisionShortlistRole(
  programId: string,
  role: ShortlistRole,
  expectedRevision?: number | null,
): Promise<DecisionMutationResponse> {
  const payload: ApiDecisionShortlistRole = { version: 1, role, expectedRevision };
  return requestJson<ApiDecisionCommandResponse>(`/decision/shortlist/${encodeURIComponent(programId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }).then(mapDecisionMutation);
}

export function excludeDecisionProgram(programId: string, expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  return requestJson<ApiDecisionCommandResponse>(`/decision/programs/${encodeURIComponent(programId)}/exclude`, {
    method: "POST",
    body: JSON.stringify(revisionBody(expectedRevision)),
  }).then(mapDecisionMutation);
}

export function restoreExcludedDecisionProgram(programId: string, expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  return requestJson<ApiDecisionCommandResponse>(`/decision/programs/${encodeURIComponent(programId)}/exclude`, {
    method: "DELETE",
    body: JSON.stringify(revisionBody(expectedRevision)),
  }).then(mapDecisionMutation);
}

export function acceptDecisionSuggestion(
  programId: string,
  role: ShortlistRole = "primary",
  expectedRevision?: number | null,
): Promise<DecisionMutationResponse> {
  const payload: ApiDecisionAcceptSuggestion = { version: 1, role, expectedRevision };
  return requestJson<ApiDecisionCommandResponse>(`/decision/suggestions/${encodeURIComponent(programId)}/accept`, {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(mapDecisionMutation);
}

export function rejectDecisionSuggestion(programId: string, expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  return requestJson<ApiDecisionCommandResponse>(`/decision/suggestions/${encodeURIComponent(programId)}/reject`, {
    method: "POST",
    body: JSON.stringify(revisionBody(expectedRevision)),
  }).then(mapDecisionMutation);
}

export function selectDecisionFinalChoice(programId: string, expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  const payload: ApiFinalChoiceRequest = { version: 1, programId, expectedRevision };
  return requestJson<ApiFinalChoiceMutation>("/decision/final-choice", {
    method: "POST",
    body: JSON.stringify(payload),
  }).then(mapDecisionMutation);
}

export function reopenDecisionFinalChoice(expectedRevision?: number | null): Promise<DecisionMutationResponse> {
  const payload: ApiFinalChoiceReopen = expectedRevision === undefined ? {} : { expectedRevision };
  return requestJson<ApiFinalChoiceMutation>("/decision/final-choice", {
    method: "DELETE",
    body: JSON.stringify(payload),
  }).then(mapDecisionMutation);
}

export type DecisionAnalyticsEventRequest = ApiDecisionAnalytics;

export function sendDecisionAnalytics(request: DecisionAnalyticsEventRequest): Promise<ApiDecisionAnalyticsResponse> {
  return requestJson<ApiDecisionAnalyticsResponse>("/decision/analytics", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export type EventQuery = {
  from?: string;
  to?: string;
  kind?: string;
  format?: string;
  universityId?: string;
  departmentId?: string;
  programId?: string;
  recommended?: boolean;
  limit?: number;
};

function queryString(options: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) if (value !== undefined) params.set(key, String(value));
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function getEvents(options: EventQuery = {}): Promise<EventListResponse> {
  return requestJson<ApiEvents>(`/events${queryString(options)}`).then((raw) => ({ items: raw.items.map(mapEvent), total: raw.total }));
}

export function getEvent(id: string): Promise<EventDetailResponse> {
  return requestJson<ApiEvent>(`/events/${encodeURIComponent(id)}`).then((raw) => ({ event: mapEvent(raw.event) }));
}

export function getCampusPoint(id: string): Promise<CampusPointDetailResponse> {
  return requestJson<ApiPoint>(`/campus/points/${encodeURIComponent(id)}`).then((raw) => ({ point: mapPoint(raw) }));
}

export type CampusPointEventsQuery = ApiCampusPointEventsQuery;

export function getCampusPointEvents(id: string, options: CampusPointEventsQuery = {}): Promise<CampusPointEventsResponse> {
  return requestJson<ApiPointEvents>(`/campus/points/${encodeURIComponent(id)}/events${queryString(options)}`).then((raw) => ({
    pointId: raw.pointId,
    items: raw.items.map(mapEvent),
    total: raw.total,
  }));
}

export function getCampusRecommendations(limit = 10): Promise<CampusRecommendationsResponse> {
  return requestJson<ApiCampusRecommendations>(`/campus/recommendations?limit=${encodeURIComponent(String(limit))}`).then((raw) => ({
    recommendedProgramIds: raw.recommendedProgramIds,
    recommendations: raw.recommendations.map(mapRecommendation),
    points: raw.points.map(mapPoint),
    events: raw.events.map(mapEvent),
    eventsWithoutPoint: raw.eventsWithoutPoint.map(mapEvent),
  }));
}

export function getPersonalRoute(limit = 10): Promise<PersonalRouteResponse> {
  return requestJson<ApiRoute>(`/personal-route?limit=${encodeURIComponent(String(limit))}`).then(mapRoute);
}

export function getAuthSession(): Promise<AuthSession> {
  return requestJson<ApiSession>("/auth/session").then(mapSession);
}

export function getKnowledgeReviewQueue(limit = 50): Promise<KnowledgeReviewQueue> {
  return requestJson<ApiKnowledgeReviewQueue>(`/ops/knowledge/review-queue?limit=${encodeURIComponent(String(limit))}`);
}

export function applyKnowledgeReviewAction(
  request: ApiKnowledgeReviewDecisionRequest,
): Promise<ApiKnowledgeReviewDecision> {
  return requestJson<ApiKnowledgeReviewDecision>("/ops/knowledge/review-actions", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function previewKnowledgeReviewPolicy(
  request: ApiKnowledgeReviewPreviewRequest,
): Promise<ApiKnowledgeReviewPreview> {
  return requestJson<ApiKnowledgeReviewPreview>("/ops/knowledge/review-preview", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export type RegisterRequest = ApiRegisterRequest;
export type LoginRequest = ApiLoginRequest;

export function registerAccount(request: RegisterRequest): Promise<AuthSession> {
  return requestJson<ApiAuthSession>("/auth/register", { method: "POST", body: JSON.stringify(request) }).then(mapSession);
}

export function loginAccount(request: LoginRequest): Promise<AuthSession> {
  return requestJson<ApiAuthSession>("/auth/login", { method: "POST", body: JSON.stringify(request) }).then(mapSession);
}

export function logoutAccount(): Promise<AuthSession> {
  return requestJson<ApiAuthState>("/auth/logout", { method: "POST" }).then(mapSession);
}

export function importGuestDecision(): Promise<AuthSession> {
  return requestJson<ApiImportedAuthSession>("/auth/decision/import-guest", { method: "POST" }).then(mapSession);
}

function opsHeaders(opsKey: string): HeadersInit {
  return { "X-Andromeda-Ops-Key": opsKey };
}

export function getIngestionRuns(options: { status?: IngestionRunStatus; limit?: number } = {}, opsKey: string): Promise<IngestionRunListResponse> {
  return requestJson<ApiRuns>(`/ops/ingestion/runs${queryString(options)}`, { headers: opsHeaders(opsKey) }).then((raw) => ({
    items: raw.items.map(mapRunSummary),
    total: raw.total,
  }));
}

export function getIngestionRun(id: string, opsKey: string): Promise<IngestionRunDetailResponse> {
  return requestJson<ApiRun>(`/ops/ingestion/runs/${encodeURIComponent(id)}`, { headers: opsHeaders(opsKey) }).then((raw) => ({ run: mapRun(raw.run) }));
}

export function retryIngestion(request: IngestionRetryRequest, opsKey: string): Promise<IngestionRunDetailResponse> {
  return requestJson<ApiRetry>("/ops/ingestion/runs/retry", {
    method: "POST",
    headers: opsHeaders(opsKey),
    body: JSON.stringify(request),
  }).then((raw) => ({ run: mapRun(raw.run) }));
}

export function queryAssistant(request: AssistantQueryInput): Promise<AssistantQueryResponse> {
  return requestJson<AssistantQueryResponse>("/assistant/query", {
    method: "POST",
    body: JSON.stringify({
      text: request.text,
      ...(request.sessionId ? { sessionId: request.sessionId } : {}),
      ...(request.expectedRevision ? { expectedRevision: request.expectedRevision } : {}),
    }),
  });
}

export type UniversityMembershipProvisionRequest = ApiProvisionMembership;
export type UniversityMembershipOwnerRequest = ApiOwnerMembershipRequest;
export type UniversityUnitRequest = ApiUnitRequest;
export type UniversityUnitUpdateRequest = ApiUnitUpdateRequest;
export type UniversityCategoryRequest = ApiCategoryRequest;
export type UniversityCategoryUpdateRequest = ApiCategoryUpdateRequest;
export type UniversityEditorialOverlayRequest = ApiEditorialOverlayRequest;
export type UniversityEventRequest = ApiEventRequest;
export type UniversityEventUpdateRequest = ApiEventUpdateRequest;
export type UniversityAgendaReplaceRequest = ApiAgendaRequest;

export function getUniversityMemberships(): Promise<UniversityMembership[]> {
  return requestJson<ApiUniversityMemberships>("/university-admin/memberships").then((raw) => raw.items.map(mapUniversityMembership));
}

export function getUniversityMembers(universityId: string): Promise<UniversityMembership[]> {
  return requestJson<components["schemas"]["UniversityMembershipListResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/members`).then((raw) => raw.items.map(mapUniversityMembership));
}

export function provisionUniversityMembership(request: UniversityMembershipProvisionRequest, opsKey: string): Promise<UniversityMembership> {
  return requestJson<components["schemas"]["UniversityMembershipResponse"]>("/ops/university-admin/members", {
    method: "POST",
    headers: opsHeaders(opsKey),
    body: JSON.stringify(request),
  }).then(mapUniversityMembership);
}

export function addUniversityMember(universityId: string, request: UniversityMembershipOwnerRequest): Promise<UniversityMembership> {
  return requestJson<components["schemas"]["UniversityMembershipResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/members`, {
    method: "POST",
    body: JSON.stringify(request),
  }).then(mapUniversityMembership);
}

export function revokeUniversityMember(universityId: string, membershipId: string, expectedRevision: number): Promise<UniversityMembership> {
  const query = new URLSearchParams({ expectedRevision: String(expectedRevision) });
  return requestJson<components["schemas"]["UniversityMembershipResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/members/${encodeURIComponent(membershipId)}?${query}`, {
    method: "DELETE",
  }).then(mapUniversityMembership);
}

export function getUniversities(): Promise<UniversityDiscovery[]> {
  return requestJson<ApiUniversities>("/universities").then((raw) => raw.items);
}

export function getUniversityCatalog(universityId: string): Promise<UniversityCatalog> {
  return requestJson<ApiUniversityCatalog>(`/universities/${encodeURIComponent(universityId)}/catalog`).then(mapUniversityCatalog);
}

export function getUniversityUnits(universityId: string): Promise<UniversityUnit[]> {
  return requestJson<ApiUniversityUnits>(`/university-admin/universities/${encodeURIComponent(universityId)}/units`).then((raw) => raw.items.map(mapUniversityUnit));
}

export function createUniversityUnit(universityId: string, request: UniversityUnitRequest): Promise<UniversityUnit> {
  return requestJson<components["schemas"]["UniversityUnitResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/units`, {
    method: "POST",
    body: JSON.stringify(request),
  }).then(mapUniversityUnit);
}

export function updateUniversityUnit(universityId: string, unitId: string, request: UniversityUnitUpdateRequest): Promise<UniversityUnit> {
  return requestJson<ApiUniversityUnit>(`/university-admin/universities/${encodeURIComponent(universityId)}/units/${encodeURIComponent(unitId)}`, {
    method: "PATCH",
    body: JSON.stringify(request),
  }).then(mapUniversityUnit);
}

export function archiveUniversityUnit(universityId: string, unitId: string, expectedRevision: number): Promise<UniversityUnit> {
  return requestJson<components["schemas"]["UniversityUnitResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/units/${encodeURIComponent(unitId)}?expectedRevision=${encodeURIComponent(String(expectedRevision))}`, {
    method: "DELETE",
  }).then(mapUniversityUnit);
}

export function getUniversityCategories(universityId: string): Promise<UniversityCategory[]> {
  return requestJson<ApiUniversityCategories>(`/university-admin/universities/${encodeURIComponent(universityId)}/categories`).then((raw) => raw.items.map(mapUniversityCategory));
}

export function createUniversityCategory(universityId: string, request: UniversityCategoryRequest): Promise<UniversityCategory> {
  return requestJson<components["schemas"]["UniversityCategoryResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/categories`, {
    method: "POST",
    body: JSON.stringify(request),
  }).then(mapUniversityCategory);
}

export function updateUniversityCategory(universityId: string, categoryId: string, request: UniversityCategoryUpdateRequest): Promise<UniversityCategory> {
  return requestJson<ApiUniversityCategory>(`/university-admin/universities/${encodeURIComponent(universityId)}/categories/${encodeURIComponent(categoryId)}`, {
    method: "PATCH",
    body: JSON.stringify(request),
  }).then(mapUniversityCategory);
}

export function archiveUniversityCategory(universityId: string, categoryId: string, expectedRevision: number): Promise<UniversityCategory> {
  return requestJson<components["schemas"]["UniversityCategoryResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/categories/${encodeURIComponent(categoryId)}?expectedRevision=${encodeURIComponent(String(expectedRevision))}`, {
    method: "DELETE",
  }).then(mapUniversityCategory);
}

export function replaceUniversityCatalogLinks(universityId: string, links: UniversityCatalogLinks): Promise<UniversityCatalogLinks> {
  const payload: ApiCatalogLinksRequest = links;
  return requestJson<components["schemas"]["UniversityCatalogLinksResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/catalog-links`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getUniversityProgramEditorial(universityId: string, programId: string): Promise<components["schemas"]["UniversityProgramEditorialResponse"]> {
  return requestJson<components["schemas"]["UniversityProgramEditorialResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/programs/${encodeURIComponent(programId)}`);
}

export function updateUniversityProgramEditorial(universityId: string, programId: string, request: UniversityEditorialOverlayRequest): Promise<components["schemas"]["UniversityProgramEditorialResponse"]> {
  return requestJson<ApiUniversityProgramEditorial>(`/university-admin/universities/${encodeURIComponent(universityId)}/programs/${encodeURIComponent(programId)}`, {
    method: "PATCH",
    body: JSON.stringify(request),
  });
}

export function getUniversityDisciplineEditorial(universityId: string, disciplineId: string): Promise<components["schemas"]["UniversityDisciplineEditorialResponse"]> {
  return requestJson<components["schemas"]["UniversityDisciplineEditorialResponse"]>(`/university-admin/universities/${encodeURIComponent(universityId)}/disciplines/${encodeURIComponent(disciplineId)}`);
}

export function updateUniversityDisciplineEditorial(universityId: string, disciplineId: string, request: UniversityEditorialOverlayRequest): Promise<components["schemas"]["UniversityDisciplineEditorialResponse"]> {
  return requestJson<ApiUniversityDisciplineEditorial>(`/university-admin/universities/${encodeURIComponent(universityId)}/disciplines/${encodeURIComponent(disciplineId)}`, {
    method: "PATCH",
    body: JSON.stringify(request),
  });
}

export function getUniversityAdminEvents(universityId: string, status?: UniversityEventStatus): Promise<UniversityEventListResponse> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return requestJson<ApiUniversityAdminEvents>(`/university-admin/universities/${encodeURIComponent(universityId)}/events${query}`).then((raw) => ({
    items: raw.items.map((item) => mapUniversityEvent(item)),
    total: raw.total,
  }));
}

export function getUniversityAdminEvent(universityId: string, eventId: string): Promise<UniversityEvent> {
  return requestJson<ApiUniversityAdminEvent>(`/university-admin/universities/${encodeURIComponent(universityId)}/events/${encodeURIComponent(eventId)}`).then((raw) => mapUniversityEvent(raw.event));
}

export function createUniversityEvent(universityId: string, request: UniversityEventRequest): Promise<UniversityEvent> {
  return requestJson<ApiUniversityAdminEvent>(`/university-admin/universities/${encodeURIComponent(universityId)}/events`, {
    method: "POST",
    body: JSON.stringify(request),
  }).then((raw) => mapUniversityEvent(raw.event));
}

export function updateUniversityEvent(universityId: string, eventId: string, request: UniversityEventUpdateRequest): Promise<UniversityEvent> {
  return requestJson<ApiUniversityAdminEvent>(`/university-admin/universities/${encodeURIComponent(universityId)}/events/${encodeURIComponent(eventId)}`, {
    method: "PATCH",
    body: JSON.stringify(request),
  }).then((raw) => mapUniversityEvent(raw.event));
}

export function publishUniversityEvent(universityId: string, eventId: string, expectedRevision: number): Promise<UniversityEvent> {
  return requestJson<ApiUniversityAdminEvent>(`/university-admin/universities/${encodeURIComponent(universityId)}/events/${encodeURIComponent(eventId)}/publish?expectedRevision=${encodeURIComponent(String(expectedRevision))}`, {
    method: "POST",
  }).then((raw) => mapUniversityEvent(raw.event));
}

export function archiveUniversityEvent(universityId: string, eventId: string, expectedRevision: number): Promise<UniversityEvent> {
  return requestJson<ApiUniversityAdminEvent>(`/university-admin/universities/${encodeURIComponent(universityId)}/events/${encodeURIComponent(eventId)}?expectedRevision=${encodeURIComponent(String(expectedRevision))}`, {
    method: "DELETE",
  }).then((raw) => mapUniversityEvent(raw.event));
}

export function replaceUniversityEventAgenda(universityId: string, eventId: string, request: UniversityAgendaReplaceRequest): Promise<UniversityEvent> {
  return requestJson<ApiUniversityAdminEvent>(`/university-admin/universities/${encodeURIComponent(universityId)}/events/${encodeURIComponent(eventId)}/agenda`, {
    method: "PUT",
    body: JSON.stringify(request),
  }).then((raw) => mapUniversityEvent(raw.event));
}

export function getUniversityEvents(
  universityId: string,
  options: { kind?: string; format?: string } = {},
): Promise<UniversityEventListResponse> {
  const query = queryString(options);
  return requestJson<ApiUniversityPublicEvents>(`/universities/${encodeURIComponent(universityId)}/events${query}`).then((raw) => ({
    items: raw.items.map((item) => mapUniversityEvent(item)),
    total: raw.total,
  }));
}

export function getUniversityEvent(universityId: string, eventId: string): Promise<UniversityEvent> {
  return requestJson<ApiUniversityPublicEvent>(`/universities/${encodeURIComponent(universityId)}/events/${encodeURIComponent(eventId)}`).then((raw) => mapUniversityEvent(raw.event));
}
