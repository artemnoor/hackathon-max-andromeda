// API types — derived from the Andromeda OpenAPI contract (API.md / openapi.json).
// Mock fixtures in src/lib/mock conform to these shapes.

import type { components } from "./generated";

export type Provenance = {
  kind?: string | null;
  url?: string | null;
  sourceKind?: string | null;
  sourceUrl?: string | null;
  capturedAt?: string | null;
  contentSha256?: string | null;
  locator?: string | null;
  sourceName?: string | null;
  universityId?: string | null;
  runId?: string | null;
  field?: string | null;
  recordKey?: string | null;
  inferred?: boolean;
};

export type SourceGapReference = {
  code: string;
  severity: "blocking" | "degradable" | "informational";
  message: string;
  sourceUrl?: string | null;
  field?: string | null;
  recordKey?: string | null;
  canContinue: boolean;
};

export type ProgramSummary = {
  id: string;
  directionId: string;
  code: string;
  name: string;
  educationYear: string;
  studyPlanUrl?: string | null;
  sourceUrl?: string | null;
  universityId?: string | null;
  universityName?: string | null;
  provenance?: Provenance[];
  sourceGaps?: SourceGapReference[];
};

export type ProgramListResponse = { items: ProgramSummary[] };

export type ProgramResponse = { program: ProgramSummary };

export type DisciplineArea = {
  code: string;
  name: string;
  description?: string | null;
  weight: string;
};

export type Discipline = {
  id: string;
  name: string;
  normalizedName: string;
  areaWeights: DisciplineArea[];
  primaryArea: string;
};

export type CurriculumItem = {
  id: string;
  discipline: Discipline;
  sourceName: string;
  hours: number;
  semester?: number | null;
  credits?: string | null;
  assessmentTypes?: string[] | null;
  sourcePosition?: number | null;
};

export type CurriculumResponse = {
  program: ProgramSummary;
  curriculumId: string;
  educationYear: string;
  sourceUrl?: string | null;
  capturedAt: string;
  items: CurriculumItem[];
  provenance?: Provenance[];
  sourceGaps?: SourceGapReference[];
};

export type ExamRequirement = {
  subject: string;
  sourceName?: string | null;
  minimumScore?: number | null;
  isChoice?: boolean | null;
  isRequired?: boolean | null;
  provenance?: Provenance | null;
};

export type QuotaResponse = {
  quotaType: string;
  sourceName?: string | null;
  places?: number | null;
  provenance?: Provenance | null;
};

export type CompetitionType =
  | "general"
  | "special_quota"
  | "separate_quota"
  | "targeted"
  | "bvi"
  | "other";

export type PassingScore = {
  scoreType?: string | null;
  competitionType?: CompetitionType | null;
  status: string;
  score?: string | null;
  provenance?: Provenance | null;
};

export type TuitionCost = {
  amount: string;
  currency: string;
  academicYear?: string | null;
  period?: string | null;
  studyForm?: string | null;
  isDiscounted?: boolean | null;
  provenance?: Provenance | null;
};

export type AdmissionOffering = {
  id: string;
  admissionYear: number;
  studyForm: string;
  fundingType: string;
  scope: "program" | "direction";
  places?: number | null;
  exams: ExamRequirement[];
  quotas: QuotaResponse[];
  passingScores: PassingScore[];
  tuition: TuitionCost[];
  provenance: Provenance[];
};

export type ProgramAdmissionsResponse = {
  program: ProgramSummary;
  programId: string;
  offerings: AdmissionOffering[];
};

export type AdmissionFitMetric = {
  value: number | null;
  status: string;
};

export type AdmissionFitBreakdown = {
  minimumReadiness: AdmissionFitMetric;
  passingReadiness: AdmissionFitMetric;
  dataCompleteness: AdmissionFitMetric;
};

export type AdmissionFitResponse = {
  status: "realistic" | "borderline" | "unlikely" | "insufficient_data";
  score: number;
  applicantTotalScore: string | null;
  dataQuality: string;
  breakdown: AdmissionFitBreakdown;
  reasons: string[];
  antiReasons: string[];
  dataGaps: string[];
};

export type AdmissionFitRequest = {
  version?: number;
  offeringId: string;
  applicant: {
    version: number;
    scores: { subject: string; score: number }[];
  };
};

export type ComparisonScope = "all" | "semester";

export type ComparisonRow = {
  discipline: string;
  semester?: number | null;
  hoursA?: number | null;
  hoursB?: number | null;
  creditsA?: string | null;
  creditsB?: string | null;
  presentA: boolean;
  presentB: boolean;
  deltaHours?: number | null;
  deltaCredits?: string | null;
};

export type ComparisonTotals = {
  totalHours: number;
  totalCredits: string;
};

export type AreaBreakdownItem = { code: string; name: string; share: string };

export type ComparisonResponse = {
  programA: ProgramSummary;
  programB: ProgramSummary;
  scope: ComparisonScope;
  semester?: number | null;
  rows: ComparisonRow[];
  totalsA: ComparisonTotals;
  totalsB: ComparisonTotals;
  areaBreakdownA?: AreaBreakdownItem[] | null;
  areaBreakdownB?: AreaBreakdownItem[] | null;
  provenance?: Provenance[];
  sourceGapDetails?: SourceGapReference[];
};

export type ComparisonSummaryResponse = components["schemas"]["ComparisonSummaryResponse"];
export type ComparisonProgramOverview = components["schemas"]["ComparisonProgramOverviewResponse"];
export type ComparisonKeyDifference = components["schemas"]["KeyDifferenceResponse"];
export type ComparisonTradeoff = components["schemas"]["TradeoffResponse"];
export type ComparisonSourceGap = components["schemas"]["ComparisonSourceGapResponse"];
export type ComparisonEvidence = components["schemas"]["ComparisonEvidenceResponse"];

export type QuestionBlock = components["schemas"]["QuestionBlock"];

export type QuestionOption = { id: string; label: string };

export type Question = {
  id: string;
  block: QuestionBlock;
  prompt: string;
  options: QuestionOption[];
  required: boolean;
  adaptive: boolean;
  multiSelect: boolean;
  maxSelected: number;
  stage?: string | null;
  componentType: components["schemas"]["QuestionComponentType"];
  order: number;
  helperText?: string | null;
  declaredDimensions: string[];
  allowUncertain: boolean;
  allowSkip: boolean;
};

export type QuestionnaireResponse = { version: number; questionSetVersion: string; questions: Question[] };

export type ProftestAnswer = {
  questionId: string;
  optionIds: string[];
  intensity?: string;
};

export type ProftestAdaptiveAnswer = {
  questionId: string;
  optionId: string;
  dimension: string;
};

export type ProftestSubmissionRequest = {
  answers: ProftestAnswer[];
  adaptiveAnswers: ProftestAdaptiveAnswer[];
};

export type ProftestSessionAnswerRequest = components["schemas"]["ProftestSessionAnswerRequest"];
export type ProftestSessionResponse = {
  sessionId: string;
  questionSetVersion: string;
  status: "draft" | "completed" | "expired" | "abandoned";
  cursor: number;
  interactionCount: number;
  revision: number;
  currentQuestion: Question | null;
  staleQuestionIds: string[];
  progress: { stage: string; stageIndex: number; stageCount: number; answerCount: number; minRemaining: number; maxRemaining: number };
  adaptive: components["schemas"]["AdaptiveSelectionResponse"] | null;
  preliminary: components["schemas"]["PreliminaryProfileResponse"] | null;
  results: ProftestResultsResponse | null;
  /** Revision of the persisted UserProfile produced by completion, if known. */
  profileRevision?: number | null;
};
export type ProftestAnalyticsEventRequest = components["schemas"]["ProftestAnalyticsEventRequest"];

export type WeightedArea = { code: string; name: string; weight: string };

export type UserProfile = {
  interests: string[];
  activityPreferences: string[];
  antiInterests: string[];
  preferredSubjectWeights: WeightedArea[];
  preferredActivityWeights: WeightedArea[];
  negativeWeights: WeightedArea[];
  confidence: string;
  adaptiveAnswers: { dimension: string; value: string }[];
  confidenceByDimension?: { dimension: string; value: string }[];
};

export type UserProfileSnapshot = {
  profile: UserProfile;
  revision: string;
  createdAt: string;
  updatedAt: string;
  expiresAt?: string | null;
};

/**
 * Decision data is deliberately kept separate from profile/recommendation
 * view models. The generated OpenAPI types remain the source of truth for
 * the wire shape; these aliases give screens a stable vocabulary for the
 * explicit user-owned state and the derived system state.
 */
export type DecisionContextData = components["schemas"]["DecisionContextResponse"];
export type DecisionStateData = components["schemas"]["DecisionStateResponse"];
export type DecisionShortlistEntry = components["schemas"]["DecisionShortlistEntryResponse"];
export type DecisionSuggestion = components["schemas"]["DecisionSuggestionResponse"];
export type DecisionShortlistItem = components["schemas"]["DecisionShortlistItemResponse"];
export type DecisionSuggestionsData = components["schemas"]["DecisionSuggestionsResponse"];
export type DecisionMutationResponse = components["schemas"]["DecisionMutationResponse"];
export type DecisionConstraintsRequest = components["schemas"]["DecisionConstraintsRequest"];
export type DecisionConstraintsUpdateRequest = components["schemas"]["DecisionConstraintsUpdateRequest"];
export type DecisionProgramCommandRequest = components["schemas"]["DecisionProgramCommandRequest"];
export type DecisionShortlistCommandRequest = components["schemas"]["DecisionShortlistCommandRequest"];
export type DecisionShortlistRoleRequest = components["schemas"]["DecisionShortlistRoleRequest"];
export type DecisionRevisionRequest = components["schemas"]["DecisionRevisionRequest"];
export type ShortlistRole = components["schemas"]["ShortlistRole"];
export type DecisionPartition = DecisionSuggestion["partition"];

/**
 * Copy server arrays at the API boundary. In particular, null admission and
 * content fields stay null: the UI must be able to distinguish unknown data
 * from a measured zero.
 */
export function normalizeDecisionContext(value: DecisionContextData): DecisionContextData {
  return {
    ...value,
    state: {
      ...value.state,
      explicitPriorities: [...value.state.explicitPriorities],
      choice: {
        ...value.state.choice,
        consideredProgramIds: [...value.state.choice.consideredProgramIds],
        excludedProgramIds: [...value.state.choice.excludedProgramIds],
        shortlistEntries: value.state.choice.shortlistEntries.map((entry) => ({ ...entry })),
      },
    },
    missingData: [...value.missingData],
  };
}

export function normalizeDecisionSuggestions(value: DecisionSuggestionsData): DecisionSuggestionsData {
  return {
    ...value,
    activeShortlist: value.activeShortlist.map((item) => ({ ...item })),
    primaryCandidates: value.primaryCandidates.map((item) => ({ ...item })),
    alternativeCandidates: value.alternativeCandidates.map((item) => ({ ...item })),
    ineligibleCandidates: value.ineligibleCandidates.map((item) => ({ ...item })),
    insufficientDataCandidates: value.insufficientDataCandidates.map((item) => ({ ...item })),
    suggestions: value.suggestions.map((item) => ({ ...item })),
    sourceGaps: [...value.sourceGaps],
    missingData: [...value.missingData],
  };
}

export type ApiRevisionConflict = {
  status: 409;
  message: string;
};

export type ProftestPreviewResponse = {
  profile: UserProfile;
  adaptiveDecision: {
    dimension: string;
    decided: boolean;
    nextQuestion?: Question | null;
  };
  candidates: { programId: string; programName: string; contentFit: number }[];
};

export type MatchScoreBreakdown = {
  subjectFit: string;
  activityFit: string;
  distinctiveFit: string;
  antiPenalty: string;
  rawContentFit: string;
};

export type MatchScore = {
  programId: string;
  programCode: string;
  programName: string;
  breakdown: MatchScoreBreakdown;
};

export type FitReason = {
  area?: string | null;
  activity?: string | null;
  text: string;
  workload?: number | null;
  share?: string | null;
  sourceNames?: string[] | null;
  provenance?: Provenance[];
};

export type OptionalMetric = {
  status?: string | null;
  score?: number | null;
};

export type RecommendationEvidence = components["schemas"]["RecommendationEvidenceResponse"];

export type Recommendation = {
  programId: string;
  programCode: string;
  programName: string;
  contentFit: number;
  score: MatchScore;
  reasons: FitReason[];
  antiFitReasons: FitReason[];
  areaShare: { code: string; name: string; share: string }[];
  semesterDistribution: { semester: number; share: string }[];
  distinctiveSubjects: string[];
  admissionFit?: OptionalMetric | null;
  provenance: Provenance[];
  sourceGaps: SourceGapReference[];
  evidence: RecommendationEvidence;
};

export type ProftestResultsResponse = {
  profile: UserProfile;
  recommendations: Recommendation[];
};

export type RecommendationsResponse = {
  profile: UserProfile;
  recommendations: Recommendation[];
};

export type AccountInfo = {
  id: string;
  email: string;
  displayName?: string | null;
  createdAt: string;
};

export type AuthSession = {
  authenticated: boolean;
  account: AccountInfo | null;
  decisionTransfer?: "bound" | "account_state_kept" | "no_anonymous_state" | "explicit_guest_import" | null;
};

export type EventKind =
  | "additional_education"
  | "open_day"
  | "lecture"
  | "competition"
  | "career"
  | "other";

export type EventFormat = "offline" | "online" | "hybrid";

export type EventVenue = {
  id?: string | null;
  name?: string | null;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
};

export type EventItem = {
  id: string;
  title: string;
  kind: EventKind;
  format: EventFormat;
  startsAt: string;
  endsAt?: string | null;
  description?: string | null;
  registrationUrl?: string | null;
  universityIds: string[];
  departmentIds: string[];
  programIds: string[];
  venue?: EventVenue | null;
  provenance: Provenance[];
};

export type EventListResponse = { items: EventItem[]; total: number };
export type EventDetailResponse = { event: EventItem };

export type UniversityAdminRole = "owner" | "editor" | "viewer";
export type MembershipStatus = "active" | "revoked";

export type UniversityMembership = {
  membershipId: string;
  accountId: string;
  universityId: string;
  universityName?: string | null;
  role: UniversityAdminRole;
  status: MembershipStatus;
  revision: number;
  createdAt: string;
  updatedAt: string;
  revokedAt?: string | null;
};

export type UniversityDiscovery = {
  id: string;
  name: string;
  city: string;
};

export type UniversityUnitType = "faculty" | "department";
export type EditorialStatus = "draft" | "published" | "archived";
export type EditorialVisibility = "visible" | "hidden";
export type UniversityCategoryKind = "subject" | "program" | "event" | "general";

export type UniversityUnit = {
  unitId: string;
  universityId: string;
  unitType: UniversityUnitType;
  parentUnitId?: string | null;
  slug: string;
  name: string;
  description?: string | null;
  status: EditorialStatus;
  sortOrder: number;
  revision: number;
};

export type UniversityCategory = {
  categoryId: string;
  universityId: string;
  slug: string;
  name: string;
  description?: string | null;
  categoryKind: UniversityCategoryKind;
  status: EditorialStatus;
  sortOrder: number;
  revision: number;
};

export type UniversityCatalogProgram = {
  programId: string;
  name: string;
  displayName?: string | null;
  publicSummary?: string | null;
  categoryIds: string[];
  unitIds: string[];
};

export type UniversityCatalogDiscipline = {
  disciplineId: string;
  name: string;
  displayName?: string | null;
  publicSummary?: string | null;
  categoryIds: string[];
  unitIds: string[];
};

export type UniversityCatalog = {
  universityId: string;
  universityName: string;
  city: string;
  officialSite: string;
  address: string;
  sourceState: string;
  units: UniversityUnit[];
  categories: UniversityCategory[];
  programs: UniversityCatalogProgram[];
  disciplines: UniversityCatalogDiscipline[];
};

export type UniversityTarget = { id: string; label: string };
export type UniversityAgendaItem = {
  itemId: string;
  eventId?: string;
  position: number;
  title: string;
  description?: string | null;
  startsAt?: string | null;
  endsAt?: string | null;
  locationLabel?: string | null;
  speakerLabel?: string | null;
  revision: number;
};

export type UniversityEventStatus = "draft" | "published" | "archived";
export type UniversityAudienceMode = "all_university" | "selected_units" | "selected_programs" | "unaffiliated";

export type UniversityEvent = {
  eventId: string;
  universityId: string;
  slug: string;
  title: string;
  kind: EventKind;
  format: EventFormat;
  startsAt: string;
  endsAt?: string | null;
  description?: string | null;
  registrationUrl?: string | null;
  venueId?: string | null;
  locationLabel?: string | null;
  locationAddress?: string | null;
  onlineUrl?: string | null;
  status?: UniversityEventStatus;
  audienceMode: UniversityAudienceMode;
  revision?: number;
  origin: "university_editorial";
  units: UniversityTarget[];
  programs: UniversityTarget[];
  categories: UniversityTarget[];
  agenda: UniversityAgendaItem[];
};

export type UniversityEventListResponse = { items: UniversityEvent[]; total: number };
export type UniversityCatalogLinks = {
  categoryPrograms: [string, string][];
  categoryDisciplines: [string, string][];
  unitPrograms: [string, string][];
  unitDisciplines: [string, string][];
};

export type CampusPoint = {
  id: string;
  name: string;
  pointType: string;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  universityIds: string[];
  departmentIds: string[];
  programIds: string[];
  provenance: Provenance[];
};

export type CampusPointDetailResponse = { point: CampusPoint };
export type CampusPointEventsResponse = { pointId: string; items: EventItem[]; total: number };
export type CampusRecommendationsResponse = {
  recommendedProgramIds: string[];
  recommendations: Recommendation[];
  points: CampusPoint[];
  events: EventItem[];
  eventsWithoutPoint: EventItem[];
};

export type PersonalRouteStatus = "ready" | "no_recommendations" | "no_events";

export type PersonalRouteStep = {
  position: number;
  kind: "explore_program" | "compare_programs" | "attend_event";
  reason: string;
  programIds: string[];
  recommendation?: Recommendation | null;
  event?: EventItem | null;
  venue?: EventVenue | null;
  point?: CampusPoint | null;
  startsAt?: string | null;
};

export type PersonalRouteResponse = {
  status: PersonalRouteStatus;
  summary: string;
  recommendations: Recommendation[];
  steps: PersonalRouteStep[];
};

export type IngestionRunStatus = "running" | "completed" | "failed";

export type IngestionRunSummary = {
  id: string;
  source?: string | null;
  status: IngestionRunStatus;
  startedAt: string;
  finishedAt?: string | null;
  sourceCount: number;
  programCount: number;
  curriculumItemCount: number;
  eventCount: number;
  campusPointCount: number;
  sourceGapCount: number;
  criticalGapCount: number;
  qualityStatus: "not_checked" | "passed" | "degraded" | "rejected";
  driftStatus: "not_checked" | "passed" | "rejected";
  sourceProfile?: string | null;
  universityId?: string | null;
  durationMs?: number | null;
  projectionStatus?: string | null;
};

export type IngestionRunDetail = IngestionRunSummary & {
  insertedCount: number;
  updatedCount: number;
  unchangedCount: number;
  removedCount: number;
  errorMessage?: string | null;
  errorCode?: string | null;
  previousGoodRunId?: string | null;
  sourceRevision?: string | null;
  configurationVersion?: string | null;
  retryOfRunId?: string | null;
  projectionTarget?: string | null;
  heartbeatAt?: string | null;
  recoveryReason?: string | null;
  sourceHashes: string[];
  sourceKinds: string[];
};

export type IngestionRunListResponse = { items: IngestionRunSummary[]; total: number };
export type IngestionRunDetailResponse = { run: IngestionRunDetail };
export type IngestionRetrySource = "bmstu_fixture" | "bmstu_live" | "hse_fixture" | "hse_live";
export type IngestionRetryRequest = {
  source: IngestionRetrySource;
  idempotencyKey?: string;
  retryOfRunId?: string;
};
export type AssistantQueryInput = {
  text: string;
  sessionId?: string;
  expectedRevision?: number;
};

export type AssistantResponseEnvelope = {
  response_type: "text" | "image" | "image_collection" | "pdf" | "mini_app";
  response_mode: components["schemas"]["ResponseMode"];
  text: string;
  template: string;
  data: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  evidence?: Array<Record<string, unknown>>;
  knowledge: components["schemas"]["KnowledgeResponseSection"] | null;
  plan?: {
    response_format: "text" | "image" | "image_collection" | "pdf" | "mini_app";
    template: string;
    text: string;
    data: Record<string, unknown>;
    actions: string[];
    result_reference: string | null;
    evidence_available: boolean;
    has_source_gaps: boolean;
  } | null;
};

export type AssistantQueryResponse = {
  state: "needs_clarification" | "complete" | "ambiguous";
  session_id: string;
  revision: number;
  question: string | null;
  options: string[];
  missing_slots: string[];
  response: AssistantResponseEnvelope | null;
  query: Record<string, unknown> | null;
  admission_request: Record<string, unknown> | null;
  admission_requests: Record<string, unknown>[];
  admission_result: Record<string, unknown> | null;
};
