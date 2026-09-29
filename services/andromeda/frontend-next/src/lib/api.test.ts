import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  ApiTimeoutError,
  API_REQUEST_TIMEOUT_MS,
  addDecisionShortlist,
  calculateAdmissionFit,
  comparePrograms,
  getCurriculum,
  getCurrentProftestSession,
  getCurrentRecommendations,
  getDecisionContext,
  getComparisonSummary,
  getProgram,
  getPrograms,
  getUniversityAdminEvents,
  getUniversityCatalog,
  getUniversityEvents,
  getUniversities,
  queryAssistant,
} from "./api";

const decisionContextPayload = {
  decisionId: "decision:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  state: {
    version: 1,
    admissionConstraints: null,
    choice: {
      consideredProgramIds: ["program:01"],
      shortlistEntries: [{
        programId: "program:01",
        role: "primary",
        state: "active",
        origin: "user",
        revision: 2,
        createdAt: "2026-09-17T10:00:00Z",
        updatedAt: "2026-09-17T10:00:00Z",
        removedAt: null,
      }],
      excludedProgramIds: [],
    },
    explicitPriorities: [],
    revision: 2,
    createdAt: "2026-09-17T10:00:00Z",
    updatedAt: "2026-09-17T10:00:00Z",
  },
  preferences: null,
  profileRevision: null,
  missingData: ["admission_constraints"],
  metadata: {
    decisionId: "decision:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    revision: 2,
    status: "active",
    createdAt: "2026-09-17T10:00:00Z",
    updatedAt: "2026-09-17T10:00:00Z",
    profileRevision: null,
  },
};

describe("canonical API client", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("maps the catalog response without a fixture fallback", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{ id: "program:01", directionId: "01.03.02", code: "01.03.02-01", name: "Программа", educationYear: 2026, studyPlanUrl: null, sourceUrl: null }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(getPrograms()).resolves.toEqual({
      items: [{ id: "program:01", directionId: "01.03.02", code: "01.03.02-01", name: "Программа", educationYear: "2026", studyPlanUrl: null, sourceUrl: null, universityId: null, universityName: null }],
    });
    expect(fetch).toHaveBeenCalledWith("/api/v1/programs", expect.objectContaining({ credentials: "include", cache: "no-store" }));
  });

  it("preserves program provenance and curriculum source gaps through typed mappers", async () => {
    const program = {
      id: "program:01",
      directionId: "01.03.02",
      code: "01.03.02-01",
      name: "Программа",
      educationYear: 2026,
      studyPlanUrl: "https://example.test/plan.pdf",
      sourceUrl: "https://example.test/catalog",
      universityId: "university:test",
      universityName: "Тестовый университет",
      provenance: [{ kind: "bmstu_curriculum_document", url: "https://example.test/catalog", capturedAt: "2026-09-18T10:00:00Z", contentSha256: "a", inferred: false }],
      sourceGaps: [{ code: "passing_score_missing", severity: "degradable", message: "Проходной балл не опубликован", sourceUrl: null, field: "passing_score", recordKey: "program:01", canContinue: true }],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      const body = path.endsWith("/curriculum")
        ? {
            program,
            curriculumId: "curriculum:01",
            educationYear: 2026,
            sourceUrl: "https://example.test/plan.pdf",
            capturedAt: "2026-09-18T10:00:00Z",
            items: [],
            provenance: [{ kind: "bmstu_curriculum_document", url: "https://example.test/plan.pdf", capturedAt: "2026-09-18T10:00:00Z", contentSha256: "a", inferred: false }],
            sourceGaps: program.sourceGaps,
          }
        : { program };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProgram("program:01")).resolves.toMatchObject({
      program: { universityName: "Тестовый университет", sourceGaps: [{ code: "passing_score_missing", canContinue: true }] },
    });
    await expect(getCurriculum("program:01")).resolves.toMatchObject({
      provenance: [{ sourceUrl: "https://example.test/plan.pdf" }],
      sourceGaps: [{ message: "Проходной балл не опубликован" }],
    });
  });

  it("preserves comparison provenance and source-gap details", async () => {
    const baseProgram = { id: "program:01", directionId: "01.03.02", code: "01.03.02-01", name: "Программа", educationYear: 2026, studyPlanUrl: "https://example.test/plan.pdf", sourceUrl: "https://example.test/catalog", provenance: [], sourceGaps: [] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      programA: baseProgram,
      programB: { ...baseProgram, id: "program:02", code: "01.03.02-02" },
      scope: "all",
      semester: null,
      rows: [],
      totalsA: { hours: 1, credits: "1.0" },
      totalsB: { hours: 2, credits: "2.0" },
      areaBreakdownA: [],
      areaBreakdownB: [],
      provenance: [{ kind: "bmstu_curriculum_document", url: "https://example.test/plan.pdf", capturedAt: "2026-09-18T10:00:00Z", contentSha256: "a", inferred: false }],
      sourceGapDetails: [{ code: "curriculum_missing", severity: "degradable", message: "Нет плана", sourceUrl: null, field: "curriculum", recordKey: "program:02", canContinue: true }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(comparePrograms(["program:01", "program:02"])).resolves.toMatchObject({
      provenance: [{ sourceUrl: "https://example.test/plan.pdf" }],
      sourceGapDetails: [{ code: "curriculum_missing", severity: "degradable" }],
    });
  });

  it("keeps recommendation evidence, inferred provenance, and typed gaps", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      profile: { interests: [], activityPreferences: [], antiInterests: [], confidence: { value: "0.75" } },
      recommendations: [{
        programId: "program:01",
        programCode: "01.03.02-01",
        programName: "Программа",
        contentFit: 82,
        score: { programId: "program:01", programCode: "01.03.02-01", programName: "Программа", breakdown: { subjectFit: "0.8", activityFit: "0.7", distinctiveFit: "0.6", antiPenalty: "0", rawContentFit: "0.82" } },
        reasons: [{ kind: "fit", area: "computer_science_data", activity: null, text: "Совпадение", workload: "10", share: "0.5", sourceNames: ["Алгоритмы"], provenance: [{ kind: "bmstu_curriculum_document", url: "https://bmstu.ru/plan.pdf", capturedAt: "2026-09-18T10:00:00Z", contentSha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", field: "curriculum", recordKey: "program:01", inferred: false }] }],
        antiFitReasons: [],
        areaShare: { computer_science_data: "0.5" },
        semesterDistribution: { "1": "1" },
        distinctiveSubjects: ["Алгоритмы"],
        admissionFit: { status: "available", value: 75 },
        provenance: [{ kind: "bmstu_curriculum_document", url: "https://bmstu.ru/plan.pdf", capturedAt: "2026-09-18T10:00:00Z", contentSha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", universityId: "university:bmstu", runId: "ingest:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", field: "curriculum", recordKey: "program:01", inferred: false }],
        sourceGaps: [{ code: "passing_score_missing", severity: "degradable", message: "Проходной балл отсутствует", field: "passing_score", recordKey: "program:01", canContinue: true }],
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(getCurrentRecommendations()).resolves.toMatchObject({
      recommendations: [{
        provenance: [{ sourceKind: "bmstu_curriculum_document", sourceUrl: "https://bmstu.ru/plan.pdf", universityId: "university:bmstu", runId: "ingest:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", inferred: false }],
        sourceGaps: [{ code: "passing_score_missing", severity: "degradable", canContinue: true }],
        reasons: [{ provenance: [{ field: "curriculum", recordKey: "program:01" }] }],
      }],
    });
  });

  it("preserves admission metric status instead of turning unavailable data into zero", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      programId: "program:01",
      offeringId: "admission-offering:01",
      admissionYear: 2026,
      studyForm: "full_time",
      fundingType: "budget",
      status: "insufficient_data",
      score: 0,
      applicantTotalScore: null,
      dataQuality: "partial",
      breakdown: {
        minimumReadiness: { value: null, status: "not_available" },
        passingReadiness: { value: null, status: "not_available" },
        dataCompleteness: { value: "50.00", status: "partial" },
      },
      reasons: [],
      antiReasons: [],
      dataGaps: [{ kind: "data_gap", message: "Не указан обязательный предмет" }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(calculateAdmissionFit("program:01", {
      version: 1,
      offeringId: "admission-offering:01",
      applicant: { version: 1, scores: [] },
    })).resolves.toMatchObject({
      status: "insufficient_data",
      breakdown: {
        minimumReadiness: { value: null, status: "not_available" },
        dataCompleteness: { value: 50, status: "partial" },
      },
    });
  });

  it("exposes structured API errors to feature boundaries", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: "NOT_FOUND",
      message: "Профиль не найден",
      details: [],
    }), { status: 404, headers: { "Content-Type": "application/json" } })));

    await expect(getCurrentRecommendations()).rejects.toEqual(expect.objectContaining({
      constructor: ApiError,
      status: 404,
      payload: expect.objectContaining({ code: "NOT_FOUND" }),
    }));
  });

  it("turns an aborted fetch into a typed timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));

    const pending = getCurrentRecommendations();
    const assertion = expect(pending).rejects.toMatchObject({
      constructor: ApiTimeoutError,
      path: "/recommendations/current?limit=10",
      timeoutMs: API_REQUEST_TIMEOUT_MS,
    });
    await vi.advanceTimersByTimeAsync(API_REQUEST_TIMEOUT_MS);
    await assertion;
  });

  it("maps a stopped preliminary proftest response without numeric leakage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      sessionId: "proftest-session:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      questionSetVersion: "proftest-v3",
      status: "draft",
      cursor: 5,
      interactionCount: 5,
      revision: 6,
      currentQuestion: null,
      staleQuestionIds: [],
      progress: { stage: "clarification", stageIndex: 5, stageCount: 6, answerCount: 5, minRemaining: 0, maxRemaining: 4 },
      adaptive: { status: "skipped", reason: "stable", candidateCount: 4, topCandidateCount: 4, dimensions: [], askedQuestionIds: [], uncertainDimensions: [], adaptiveCount: 0, stopReason: "no_meaningful_question" },
      preliminary: { topics: [{ code: "area:computer_science_data", label: "Информатика и данные" }] },
      results: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(getCurrentProftestSession()).resolves.toEqual(expect.objectContaining({
      questionSetVersion: "proftest-v3",
      currentQuestion: null,
      preliminary: { topics: [{ code: "area:computer_science_data", label: "Информатика и данные" }] },
      adaptive: expect.objectContaining({ stopReason: "no_meaningful_question" }),
    }));
  });

  it("uses the generated decision route and preserves the explicit context shape", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(decisionContextPayload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));

    await expect(getDecisionContext()).resolves.toMatchObject({
      decisionId: decisionContextPayload.decisionId,
      state: { revision: 2, choice: { shortlistEntries: [{ programId: "program:01", state: "active" }] } },
      missingData: ["admission_constraints"],
    });
    expect(fetch).toHaveBeenCalledWith("/api/v1/decision/context", expect.objectContaining({
      credentials: "include",
      cache: "no-store",
    }));
  });

  it("sends an explicit shortlist command with the server revision", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      decisionId: decisionContextPayload.decisionId,
      context: decisionContextPayload,
      changed: true,
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await addDecisionShortlist("program:01", "alternative", 2);

    const [, init] = vi.mocked(fetch).mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(fetch).toHaveBeenCalledWith("/api/v1/decision/shortlist", expect.objectContaining({ method: "POST" }));
    expect(JSON.parse(String(init.body))).toEqual({
      version: 1,
      programId: "program:01",
      role: "alternative",
      expectedRevision: 2,
    });
  });

  it("keeps comparison summary selection separate from shortlist mutations", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      programs: [],
      scope: "all",
      semester: null,
      keyDifferences: [],
      tradeoffs: [],
      sourceGaps: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(getComparisonSummary(["program:01.03.02-01", "program:01.03.02-02", "program:01.03.02-03"])).resolves.toEqual(expect.objectContaining({ programs: [] }));
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/compare/summary?programIds=program%3A01.03.02-01%2Cprogram%3A01.03.02-02%2Cprogram%3A01.03.02-03&scope=all",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
  });

  it("loads university discovery, catalog and public editorial events through the generated contract", async () => {
    const university = { id: "university:test", name: "Тестовый университет", city: "Москва" };
    const catalog = {
      universityId: university.id,
      universityName: university.name,
      city: university.city,
      officialSite: "https://example.test",
      address: "Москва",
      sourceState: "complete",
      units: [{ unitId: "unit:test:faculty", universityId: university.id, unitType: "faculty", parentUnitId: null, slug: "faculty", name: "Факультет", description: null, status: "published", sortOrder: 0, revision: 1 }],
      categories: [],
      programs: [],
      disciplines: [],
    };
    const event = {
      eventId: "university-event:test:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      universityId: university.id,
      slug: "open-day",
      title: "День открытых дверей",
      kind: "open_day",
      format: "offline",
      startsAt: "2026-10-01T10:00:00Z",
      endsAt: null,
      description: "План мероприятия",
      registrationUrl: null,
      venueId: null,
      locationLabel: "Главный корпус",
      locationAddress: "Москва",
      onlineUrl: null,
      audienceMode: "all_university",
      origin: "university_editorial",
      units: [],
      programs: [],
      categories: [],
      agenda: [{ itemId: "agenda:1", position: 1, title: "Регистрация", description: null, startsAt: null, endsAt: null, locationLabel: null, speakerLabel: null }],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      const body = path === "/api/v1/universities"
        ? { items: [university] }
        : path.endsWith("/catalog")
          ? catalog
          : { items: [event], total: 1 };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getUniversities()).resolves.toEqual([university]);
    await expect(getUniversityCatalog(university.id)).resolves.toMatchObject({
      universityName: university.name,
      units: [{ unitId: "unit:test:faculty", name: "Факультет" }],
    });
    await expect(getUniversityEvents(university.id)).resolves.toMatchObject({
      total: 1,
      items: [{ eventId: event.eventId, title: event.title, agenda: [{ title: "Регистрация", revision: 1 }] }],
    });
    await expect(getUniversityAdminEvents(university.id, "draft")).resolves.toMatchObject({ total: 1 });
    expect(fetchMock).toHaveBeenCalledWith("/api/university-admin/universities/university%3Atest/events?status=draft", expect.objectContaining({ credentials: "include" }));
  });

  it("keeps university admin authorization errors typed for the console boundary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: "FORBIDDEN",
      message: "Недостаточно прав",
      details: [],
    }), { status: 403, headers: { "Content-Type": "application/json" } })));

    await expect(getUniversityAdminEvents("university:test")).rejects.toEqual(expect.objectContaining({
      constructor: ApiError,
      status: 403,
      payload: expect.objectContaining({ code: "FORBIDDEN" }),
    }));
  });

  it("keeps assistant session state in the channel-neutral web adapter", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      state: "needs_clarification",
      session_id: "query-session:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      revision: 2,
      question: "Какие баллы по предметам?",
      options: ["Русский язык"],
      missing_slots: ["exams"],
      response: null,
      query: null,
      admission_request: null,
      admission_requests: [],
      admission_result: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(queryAssistant({
      text: "Куда я прохожу с 270?",
      sessionId: "query-session:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      expectedRevision: 1,
    })).resolves.toMatchObject({ state: "needs_clarification", revision: 2 });
    const [, init] = vi.mocked(fetch).mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      text: "Куда я прохожу с 270?",
      sessionId: "query-session:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      expectedRevision: 1,
    });
  });
});
