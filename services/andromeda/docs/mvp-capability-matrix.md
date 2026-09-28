# Andromeda MVP capability truth matrix

**Snapshot:** 2026-09-19
**Branch:** feature/andromeda-mvp-production-level
**Baseline commit:** 4088116
**Purpose:** source-backed capability and evidence baseline for the transition
from Tracer Bullet / Private Alpha foundation to MVP Production Level.

This document describes the repository state at the snapshot above. It is not
itself a release approval. A capability is not considered complete merely
because an endpoint exists or because it returns a typed not_available state.
The row must connect a user entrypoint, public contract, application owner,
repository/data source, response state, and rendered outcome.

## Status and evidence rules

| Status | Meaning in this matrix |
| --- | --- |
| CONFIRMED | The primary path is implemented in the current source and has meaningful contract, integration, or vertical evidence. |
| PARTIALLY CONFIRMED | A real path works, but a product-visible gap, incomplete state model, or missing end-to-end evidence remains. |
| INTENTIONAL | The capability is deliberately outside the current MVP scope; it must not be presented as implemented. |
| FUTURE RISK | The current path is acceptable at the supported scope but lacks evidence or safeguards needed before wider exposure. |
| UNVERIFIED | The repository contains a plausible path, but the required runtime/source/deployment evidence has not been demonstrated. |

Evidence is classified separately:

- Code path: current symbols and module boundaries.
- Contract: OpenAPI schema, generated frontend types, or typed public
  contract.
- Test evidence: an existing named test that proves the stated behavior.
- Runtime evidence: a fixture, PostgreSQL, live-source, browser, or
  deployment run. Fixture/CI evidence does not prove live-source or deployment
  readiness.

## Current product and data scope

- The production web runtime is frontend-next; its browser API boundary is
  frontend-next/src/lib/api.ts, with types generated from
  frontend-next/src/lib/generated.ts and frontend-next/openapi.json.
- Backend route ownership is registered by
  backend/src/andromeda/api/main.py:create_app: programs, admissions,
  admission fit, comparison, proftest, recommendations, decision, events,
  campus, personal route, admin/ops, auth, analytics, and health.
- BMSTU and HSE have adapter namespaces and fixture/integration evidence:
  backend/src/andromeda/ingestion/universities/{bmstu,hse} and
  backend/tests/integration/test_{bmstu,hse}_full_ingestion.py. Repeatable
  live-source operation and a clean production deployment remain separate
  unverified claims.
- Content Fit, Admission Fit, Career Fit, and Workload Readiness are separate
  dimensions. Career Fit and validated personal Workload Readiness are
  intentionally outside the current MVP; workload evidence is not the same
  thing as Workload Readiness.
- DecisionContext owns explicit constraints, considered programs, shortlist
  entries, roles, exclusions, revision, and final choice. Suggestions and
  profile-derived scores remain derived data and must not silently mutate that
  choice.

## Five-flow capability matrix

| User scenario | Status / product claim | Frontend entrypoint and rendering | HTTP and public contract | Application, repository, and data path | Evidence and remaining limitation |
| --- | --- | --- | --- | --- | --- |
| **1. Куда я могу поступить?** | PARTIALLY CONFIRMED and source-dependent. The system can classify configured candidates as realistic, borderline, unlikely, or insufficient-data; it is not a guarantee of admission or a complete live application search. | frontend-next/src/features/admission/admission-page.tsx: AdmissionPage renders score/constraint input and AdmissionOutcomes. frontend-next/src/features/program/program-page.tsx: AdmissionFitTab evaluates one selected offering with an explicit readiness/not-guarantee presentation and independent program/curriculum/admissions states. | GET /decision/context, GET /decision/suggestions, PUT /decision/constraints; GET /programs/{id}/admissions; POST /programs/{id}/admission-fit. Client functions are in frontend-next/src/lib/api.ts; schemas are generated from the exported OpenAPI contract. | backend/src/andromeda/api/routes/decision.py:get_suggestions → DecisionService / DecisionCandidatePipeline; selected-program path uses backend/src/andromeda/api/routes/admission_fit.py:calculate_program_admission_fit → AdmissionFitService → AdmissionFitDataReader. Readers are wired in backend/src/andromeda/api/dependencies/services.py to SqlAlchemyProgramRepository, SqlAlchemyAdmissionRepository, and SqlAlchemyAdmissionFitReader. Facts originate in canonical BMSTU/HSE ingestion projections. | backend/tests/modules/decision/test_candidates.py, backend/tests/api/test_admission_fit_api.py, backend/tests/integration/test_admission_fit_vertical_slice.py, and frontend-next/tests/admission-fit.spec.ts cover real, missing-source, validation, and browser-empty states. Remaining limitation is source freshness/live coverage; missing facts stay typed and visible. |
| **2. Что выбрать в конкретном вузе?** | CONFIRMED for the explicit choice core. Suggestions are derived and source-dependent; the user, not the recommender, owns the choice. | frontend-next/src/features/decision/decision-page.tsx and frontend-next/src/features/decision/decision-context.tsx load the context, render candidate partitions, and expose add/remove/restore/role/final-choice actions. Catalog/program cards use ProgramShortlistActions. | GET /decision/context, GET /decision/suggestions; mutations include PUT /decision/constraints, POST /decision/considered, POST /decision/shortlist, PATCH/DELETE /decision/shortlist/{program_id}, restore/exclude, accept/reject suggestion, and final-choice commands. All are mapped by typed functions in frontend-next/src/lib/api.ts. | backend/src/andromeda/api/routes/decision.py → DecisionService, DecisionCandidatePipeline, DecisionAnalyticsService; persistence is DecisionContextRepository through SqlAlchemyDecisionContextRepository. Candidate reads use public ProgramReader, profile projection, recommendations, and admission-fit boundaries. | backend/tests/api/test_decision_routes.py, backend/tests/modules/decision/test_decision_service.py, backend/tests/modules/decision/test_candidates.py, backend/tests/integration/test_no_linear_flow.py, and frontend-next/tests/decision-analytics.spec.ts cover context independence, revision conflicts, explicit transitions, and analytics isolation. The empty anonymous context is usable without a profile; 409 is rendered as a refresh/conflict state. Production-like source freshness and cross-device deployment evidence remain outside this row. |
| **3. Какие программы мне подходят?** | PARTIALLY CONFIRMED and source-dependent. Deterministic Content Fit, explanation, confidence-as-evidence-completeness, and a typed evidence envelope exist; Career Fit and Workload Readiness remain explicitly out of the ranking. | frontend-next/src/features/proftest/proftest-page.tsx completes the profile flow and renders profile dimensions, confidence, catalog completeness, source gaps, and per-recommendation evidence; frontend-next/src/features/recommendations/recommendations-page.tsx renders current suggestions, evidence, honest empty state, and service-failure state. frontend-next/src/app/page.tsx routes both views without making the test mandatory. | GET/POST /proftest/profile, POST /proftest/results, GET /recommendations/current, and GET /decision/suggestions; direct recommendation requests use POST /recommendations. Session completion also exposes `profileRevision` and evidence `questionSetVersion`. Client mapping is in frontend-next/src/lib/api.ts; recommendation/profile schemas are generated from OpenAPI. | Proftest session/profile services build UserProfile and ProgramFingerprint; CurrentRecommendationService delegates to RecommendationService, which reads through ProftestCatalogService and public program/curriculum/discipline readers. SQLAlchemy repositories provide the canonical projection. Ranking uses deterministic subject/activity/distinctive signals and anti-interest penalty; Career Fit and Workload Readiness do not feed the ranking. | backend/tests/integration/test_recommendations_catalog.py, backend/tests/api/test_recommendations_api.py, backend/tests/api/test_proftest_sessions_api.py, backend/tests/modules/proftest/test_proftest_projection.py, backend/tests/modules/recommendations/test_scoring.py, backend/tests/modules/recommendations/test_ranking.py, backend/tests/modules/recommendations/test_explanations.py, backend/tests/modules/recommendations/test_evidence.py, backend/tests/modules/recommendations/test_regression_corpus.py, backend/tests/integration/test_proftest_vertical_slice.py, frontend-next/tests/proftest-decision-integration.spec.ts, and frontend-next/tests/recommendations-states.spec.ts prove core and degraded paths. The corpus is a reviewable semantic regression set, not scientific outcome validation. |
| **4. Чем отличаются мои варианты?** | CONFIRMED for the supported comparison shape: summary-first 2–3 program selection plus A/B raw evidence, with source gaps preserved. The different cardinalities are an intentional contract, not a hidden product claim. | frontend-next/src/features/compare/compare-page.tsx loads programs, lets the user select candidates, renders summary/trade-offs and raw comparison tabs, preserves data during refresh, and offers retry. frontend-next/src/app/page.tsx owns the catalog load used by the compare view. | GET /compare/summary and GET /compare; client functions are getComparisonSummary and comparePrograms in frontend-next/src/lib/api.ts. Public contracts are ComparisonSummaryResponse and ComparisonResponse. | backend/src/andromeda/api/routes/compare.py → ComparisonSummaryService or CompareProgramsService → public ProgramReader, CurriculumReader, and DisciplineReader ports → SQLAlchemy repositories over canonical programs/curricula/disciplines. | backend/tests/api/test_compare_contract.py, backend/tests/modules/comparison/test_summary.py, backend/tests/vertical/test_increment_3.py, and frontend-next/tests/catalog-programs.spec.ts cover status rows, 2–3 program summary, A/B detail, retry, and source gaps. Raw detail remains deliberately A/B; expanding it is post-MVP scope. |
| **5. Короткий профориентационный старт** | CONFIRMED for the supported compact session flow. The adaptive test is bounded, deterministic, signal-evaluated, resumable, and does not silently mutate shortlist; product still labels it as a preference/profile aid, not a psychological diagnosis. | frontend-next/src/features/proftest/proftest-page.tsx:ProftestPage presents five core questions and up to four adaptive questions, persists only a validated session-scoped draft, resumes the server session, and renders results. | GET /proftest/sessions, GET /proftest/sessions/current, POST /proftest/sessions/current/next, PATCH /proftest/sessions/current, POST /proftest/sessions/current/complete; legacy `/proftest/questions`, `/preview`, and `/results` are deprecated compatibility adapters only. Profile/recommendation endpoints follow completion. Functions are typed in frontend-next/src/lib/api.ts. | backend/src/andromeda/api/routes/proftest.py → ProftestSessionService / ProftestService → versioned questionnaire, AdaptiveQuestionSelector, ProfileBuilder, UserProfilePersistenceService → SqlAlchemyProftestSessionRepository and SqlAlchemyUserProfileRepository over proftest_answer_sessions and user_profiles. stale_question_ids, revision, expiry, option membership, blocking source-gap stop, and completion state are server-side contracts. | backend/tests/api/test_proftest_sessions_api.py, backend/tests/infrastructure/test_proftest_sessions_repository.py, backend/tests/modules/proftest/test_adaptive.py, backend/tests/modules/proftest/test_session_policy.py, backend/tests/modules/proftest/test_questions.py, backend/tests/modules/proftest/test_user_profile.py, backend/tests/modules/proftest/test_signal_corpus.py, backend/tests/integration/test_proftest_vertical_slice.py, frontend-next/tests/proftest.spec.ts, and frontend-next/tests/proftest-decision-integration.spec.ts cover start, answer, adaptive handoff, completion, expiry/restart, reload, malformed draft, restore retry, and shortlist preservation. Remaining limitation is the bounded browser matrix, not the runtime contract. |

## Cross-flow state and contract audit

| State or claim | Current implementation | Truthful product interpretation |
| --- | --- | --- |
| Loading | Shared Loading components and route-level loading states cover catalog, decision, admission, program, recommendation, compare, and proftest. | Loading remains a runtime state, not a capability claim; each page has a bounded error/retry path. |
| API/network error | `frontend-next/src/lib/api.ts` has typed `ApiError`, timeout handling, safe JSON parsing, and typed response mapping; page-level states distinguish retryable service failure from valid absence. | Error UX is now explicit across the critical pages; future visual coverage can expand without changing the contract. |
| Empty valid result | Catalog, compare, admission, recommendation, program, and proftest expose distinct empty/profile-required/source-gap states. | Empty is valid only when the response explains whether it means no matching data, missing profile, or insufficient source evidence. |
| Partial/source gap | Backend contracts expose `sourceGaps`, missing-data partitions, provenance, and optional metrics; program/recommendation/compare pages preserve and render them. | Missing data remains visible and is not shown as zero, a probability, or a successful complete capability. |
| Stale/conflict | Proftest has revision and stale question IDs; DecisionContext handles `409` and reloads current state; compare refresh preserves prior data; API client preserves status/payload. | The domain model and current UI provide explicit recovery; wider concurrency/load testing remains a scale concern. |
| Placeholder/product wording | MVP-051 removed invented admission scores, probability-like wording, and the unsupported “no contraindications” fallback from the active UI. | This blocker is closed for the current frontend paths. Career Fit, Workload Readiness, and admission probability remain excluded from MVP claims; any future claim requires a separate validated contract and product slice. |

## Capability claim decisions

| Claim | Current status | Evidence / decision |
| --- | --- | --- |
| Catalog and program facts | CONFIRMED for canonical fixture-backed reads; source-dependent for freshness | GET /programs, GET /programs/{id}, GET /programs/{id}/curriculum; ProgramReader, CurriculumReader, canonical repositories; backend/tests/vertical/test_increment_1.py and test_increment_2.py. |
| Admissions facts | CONFIRMED for source-backed offerings and explicit gaps | GET /programs/{id}/admissions, AdmissionService, provenance-backed admission contracts; backend/tests/api/test_andromeda_api.py and admissions integration tests. Currentness/live repeatability is not implied. |
| Admission Fit | CONFIRMED for selected offering and Decision candidate partition; readiness is presented as a source-dependent assessment, not a probability or guarantee | AdmissionFitService, DecisionCandidatePipeline, strict status/reason/data-gap contracts, vertical/persona tests, and frontend-next/tests/admission-fit.spec.ts. No probability/guarantee claim is valid. |
| Content Fit | CONFIRMED deterministic ranking/explanation foundation | RecommendationService, scoring/ranking/explanation tests, canonical fingerprint reader, and the versioned `recommendations-regression.v1` corpus. Confidence/reliability is evidence completeness, not predictive accuracy; Career Fit and Workload Readiness remain out of scope. |
| Recommendation explanation/provenance | PARTIALLY CONFIRMED | Backend reason/source-gap contracts and RecommendationEvidence exist; the corpus proves source-backed reasons and explicit unknowns. Candidate-level/session handoff and broader browser rendering remain MVP-060..063/Phase 8 work. |
| Career Fit | INTENTIONAL out of MVP | README.md, docs/mvp.md, .ai-factory/DESCRIPTION.md, and typed optional-metric behavior exclude it from current capability claims. |
| Workload Readiness | INTENTIONAL out of MVP | Workload evidence may be displayed from curricula; no validated readiness score is part of the current ranking or public claim. |
| BMSTU/HSE coexistence | PARTIALLY CONFIRMED | Adapter namespaces, fixture integration tests, and 2026-09-19 read-only live source-health probes exist; both adapters were accepted as `degraded` with typed gaps, but release-owner repeatability/deployment evidence is not yet a release proof. |
| Anonymous → account continuity | CONFIRMED at contract/test level | Opaque HttpOnly scope, DecisionContext transfer, profile persistence, auth API and browser tests exist; deployment/security baseline remains later-phase work. |

## Existing evidence map

### Backend

- Architecture boundaries: backend/tests/architecture/test_module_boundaries.py.
- Contract/OpenAPI surfaces: backend/tests/contracts/,
  backend/tests/api/test_openapi_jsonschema.py, and
  backend/tests/api/test_andromeda_api.py.
- Decision/shortlist: backend/tests/api/test_decision_routes.py,
  backend/tests/modules/decision/, and
  backend/tests/integration/test_no_linear_flow.py.
- Admissions/admission fit:
  backend/tests/api/test_admission_fit_api.py,
  backend/tests/api/test_admission_fit_contract.py, and
  backend/tests/integration/test_admission_fit_vertical_slice.py.
- Recommendations/proftest:
  backend/tests/api/test_recommendations_api.py,
  backend/tests/integration/test_recommendations_catalog.py,
  backend/tests/api/test_proftest_sessions_api.py, and
  backend/tests/integration/test_proftest_vertical_slice.py.
- Comparison: backend/tests/api/test_compare_contract.py,
  backend/tests/modules/comparison/test_summary.py, and
  backend/tests/vertical/test_increment_3.py.
- BMSTU/HSE data: backend/tests/integration/test_bmstu_full_ingestion.py and
  backend/tests/integration/test_hse_full_ingestion.py.

### Frontend

The current browser inventory is:

- frontend-next/tests/catalog-programs.spec.ts;
- frontend-next/tests/decision-analytics.spec.ts;
- frontend-next/tests/proftest.spec.ts;
- frontend-next/tests/proftest-decision-integration.spec.ts;
- frontend-next/tests/legacy-flow-compat.spec.ts;
- frontend-next/tests/events-support-layer.spec.ts;
- frontend-next/tests/auth-guest.spec.ts.
- frontend-next/tests/admission-fit.spec.ts;
- frontend-next/tests/recommendations-states.spec.ts;
- frontend-next/tests/responsive-accessibility.spec.ts;
- frontend-next/tests/mvp-production-flow.spec.ts;
- frontend-next/tests/ops-control-plane.spec.ts (requires an explicit staging-like ops key).

`admissions.spec.ts` and `recommendations.spec.ts` are not separate files;
their current assertions live in `mvp-production-flow.spec.ts`,
`admission-fit.spec.ts`, `recommendations-states.spec.ts`, and the catalog
flow. The canonical test names above are the source of truth.

## Release interpretation

The repository already has a real modular product core and several confirmed
vertical slices. It is not yet justified to call the five-flow product
MVP Production Level until the deployment/release gate passes. The remaining
release evidence is operational rather than a missing domain shortcut:

1. fixture-backed deterministic evidence must be complemented by a clean
   production-like PostgreSQL deployment and rollback/restore drill;
2. CI must pass from a clean checkout with its new coverage, dependency,
   packaging, migration, and browser artifacts;
3. live source-health is an explicit read-only operational check and must be
   authorized and recorded separately from deterministic PR tests.

This matrix is the baseline for MVP-002–MVP-004. Later phases may update
current-state rows only with new evidence; they must not rewrite this snapshot
to hide a failed or skipped check.
