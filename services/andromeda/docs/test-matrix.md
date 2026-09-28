# Test matrix and critical business rules

This is the current test map for the MVP Production Level transition. It is a
navigation document, not a replacement for the tests. Coverage percentage is a
diagnostic signal; release quality is decided by the rule-to-test mapping and
the runnable smoke gates.

## Canonical entrypoints

Run from the repository root:

| Target | What it proves | External prerequisites |
|---|---|---|
| `python scripts/andromeda.py fast` | architecture, OpenAPI contract, typing, docs, deployment contract | backend environment, Node/npm |
| `python scripts/andromeda.py backend` | complete backend suite | locked backend environment, Poppler |
| `python scripts/andromeda.py backend-coverage` | backend suite plus XML/HTML/JUnit artifacts under `artifacts/coverage/backend` | locked backend environment |
| `python scripts/andromeda.py frontend` | unit tests, lint, production build | `npm ci` |
| `python scripts/andromeda.py frontend-coverage` | frontend unit coverage under `frontend-next/coverage` | `npm ci`, V8 coverage provider |
| `python scripts/andromeda.py ingestion` | disposable BMSTU/HSE fixture ingestion | locked backend environment, Poppler |
| `python scripts/andromeda.py postgres` | PostgreSQL repository, migration, and API semantics | disposable `ANDROMEDA_POSTGRES_TEST_URL` |
| `python scripts/andromeda.py playwright` | browser flows against a running demo | Chromium and `PLAYWRIGHT_BASE_URL` |
| `python scripts/andromeda.py openapi` | canonical public/full OpenAPI and generated-client drift | backend and npm environments |
| `python scripts/andromeda.py data-api` | DATA-API schema and operation references against canonical Public OpenAPI | locked backend environment |
| `python scripts/andromeda.py docs` | documentation links and paths | Python |
| `python scripts/andromeda.py deployment` | backend/frontend Docker and proxy contract | Python |
| `python scripts/andromeda.py migrations` | migration tests plus empty-database upgrade/drift check | locked backend environment |
| `python scripts/andromeda.py production-smoke` | disposable fixture API, frontend, OG, admissions, events/campus smoke | Poppler, Node/npm, free local ports |
| `python scripts/andromeda.py release-evidence` | secret-free commit/lock/corpus metadata and 16-item exit template | Git |
| `python scripts/andromeda.py full` | all local gates that do not require live university sources or a pre-existing PostgreSQL service | all local prerequisites |

The CI workflow keeps PostgreSQL, browser, dependency, coverage and
full-stack jobs isolated so a failure identifies its layer. Live university
source health is intentionally a scheduled, read-only operational workflow.

## Critical rule matrix

| Critical rule | Primary evidence | Boundary / integration evidence | User-visible evidence |
|---|---|---|---|
| Canonical IDs remain university-scoped | `backend/tests/ingestion/test_bmstu_adapter.py`, `backend/tests/ingestion/test_hse_parser.py` | `backend/tests/integration/test_bmstu_full_ingestion.py`, `backend/tests/integration/test_hse_full_ingestion.py` | catalog/program browser smoke |
| Taxonomy normalizes known, manual-override, and unknown disciplines deterministically | `backend/tests/modules/test_discipline_classifier.py`, `backend/tests/ingestion/test_taxonomy_overrides.py` | `backend/tests/ingestion/test_taxonomy_metrics.py`, `backend/tests/ingestion/test_quality_gate.py` | source-gap/provenance rendering in program and recommendation flows |
| Quality-gated ingestion never publishes a rejected projection | `backend/tests/ingestion/test_quality_gate.py` | `backend/tests/integration/test_ingestion_quality_projection.py`, `backend/tests/infrastructure/test_atomic_ingest.py` | Admin/Ops failed-run and retry smoke |
| Retry/recovery is idempotent and last-good data is preserved | `backend/tests/ingestion/test_retry_policy.py` | `backend/tests/infrastructure/test_ingestion_recovery.py`, `backend/tests/integration/test_postgresql_ingestion_concurrency.py` | `backend/tests/vertical/test_mvp_production_flows.py` |
| Content Fit ranking is deterministic and anti-interest aware | `backend/tests/modules/recommendations/test_ranking.py`, `test_scoring.py` | `backend/tests/modules/recommendations/test_regression_corpus.py`, `backend/tests/integration/test_recommendations_catalog.py` | `frontend-next/tests/recommendations-states.spec.ts`, proftest decision handoff |
| Recommendation explanation names evidence, uncertainty, and provenance | `backend/tests/modules/recommendations/test_explanations.py`, `test_evidence.py` | `backend/tests/api/test_recommendations_api.py` | recommendation and program partial-data states |
| Admission Fit is separate from Content Fit and is not a probability claim | `backend/tests/modules/admission_fit/`, `backend/tests/modules/decision/test_candidates.py` | `backend/tests/integration/test_admission_fit_vertical_slice.py` | `frontend-next/tests/admission-fit.spec.ts` |
| DecisionContext owns shortlist/final choice and never silently prunes it | `backend/tests/modules/decision/` | `backend/tests/api/test_decision_routes.py`, `tests/integration/test_no_linear_flow.py` | `frontend-next/tests/catalog-programs.spec.ts` |
| Optimistic revision and stale/conflict recovery are explicit | `backend/tests/api/test_decision_routes.py`, `backend/tests/modules/proftest/test_session_policy.py` | `backend/tests/integration/test_user_profile_persistence.py` | decision/proftest conflict states in browser tests |
| Adaptive proftest is bounded, resumable, and signal-useful | `backend/tests/modules/proftest/test_adaptive.py`, `test_signal_corpus.py` | `backend/tests/api/test_proftest_sessions_api.py`, `test_proftest_projection.py` | `frontend-next/tests/proftest.spec.ts`, `proftest-decision-integration.spec.ts` |
| Auth/profile scopes are isolated and guest transfer is deterministic | `backend/tests/modules/auth/test_authentication.py` | `backend/tests/api/test_auth_api.py`, `tests/integration/test_user_profile_persistence.py` | `frontend-next/tests/auth-guest.spec.ts` |
| HTTP contracts reject invalid enum/wire values and generated clients stay in sync | `backend/tests/api/test_openapi_jsonschema.py`, contract suites | `scripts/andromeda.py openapi`, `frontend-next/scripts/check-api-drift.mjs` | typed frontend API mapping tests |
| Security controls are present without leaking secrets | `backend/tests/api/test_security_headers.py`, `test_request_controls.py` | auth/admin/ingestion security suites, dependency audit | safe error/correlation UI states, `frontend-next/tests/ops-control-plane.spec.ts` |
| Health/readiness reports process and schema state accurately | `backend/tests/api/test_health.py` | empty-db Alembic gate and production smoke | deployment runbook checks |
| Policy candidates never become effective without exact human approval | `backend/tests/unit/test_policy_ast.py`, `backend/tests/unit/test_knowledge_review.py` | `backend/tests/infrastructure/test_knowledge_candidate_repository.py`, `backend/tests/infrastructure/test_knowledge_review_repository.py` | pending/approved state, trace and source evidence in `ResponseEnvelope.knowledge` |
| Temporal applicability, precedence and conflicts fail closed | `backend/tests/unit/test_policy_applicability.py`, `test_policy_dependencies.py`, `test_policy_what_if.py` | `backend/tests/infrastructure/test_admission_policy_repository.py`, `test_policy_dependency_refresh.py` | 2027/2028 cohort, university/direction exception and unresolved-conflict response |
| Source discovery is allowlisted, bounded and staging-only | `backend/tests/ingestion/test_fetch_security.py`, `test_knowledge_source_discovery.py` | `backend/tests/infrastructure/test_knowledge_source_repository.py`, `test_knowledge_candidate_repository.py` | last-good snapshot retained; no canonical rule on capture or extraction |
| Generic policy delegates benefit calculation to its domain owner | `backend/tests/infrastructure/test_admission_benefits_repository.py` | `backend/tests/infrastructure/test_admission_policy_repository.py` | exact selected rule trace; no second BVI/100-point/achievement calculator |
| Policy Jev stays off until independent evaluation and approval | `backend/tests/evaluation/test_jev_knowledge_policy_gate.py` | Stage 2 Question Registry/calibration lock regressions | no knowledge-policy callsite or canonical write from model prediction |
| Policy storage remains additive from the Stage 2 Alembic head | `backend/tests/infrastructure/test_alembic_migrations.py` | disposable PostgreSQL migration tests and source snapshot retention | existing catalog/admissions/benefit APIs continue serving their owner data |

## Test-layer disposition

- Architecture and compatibility tests remain: they protect public boundaries
  and the deliberate tracer-to-canonical migration.
- Semantic assertions are preferred over whole-response snapshots where
  timestamps, hashes, revisions, or source metadata are expected to change.
- Fixture manifests and regression corpora are versioned evidence. Updating a
  corpus requires a policy/taxonomy review; it is not a way to silence a
  failing assertion.
- Source-network probes are not part of deterministic PR tests. They are
  read-only and produce a safe artifact through `source-health.yml`.
- No global coverage threshold is used as a proxy for business correctness.
  Coverage reports expose untested code; the critical matrix above is the
  release gate for behavior.

## Safe artifacts

CI publishes backend JUnit/XML coverage, frontend V8 coverage, browser/demo
logs, and migration/OpenAPI smoke evidence. Reports must contain commit and
fixture identifiers where available, but never cookies, passwords, API keys,
raw source bodies, or personal profiles.
