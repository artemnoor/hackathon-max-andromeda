# Andromeda: MVP Production Level evidence ledger

**Decision date:** 2026-09-19
**Repository baseline:** branch `feature/andromeda-mvp-production-level`,
release code checkpoint `b15dbe7`
**Current release decision:** **PROMOTED — MVP Production Level**

This ledger is a release-evidence document, not a runtime source of truth. It
records what the repository currently proves, what it does not prove, and the
follow-up verification still required for ongoing operation. `VERIFIED` means
the bounded MVP behavior has executable evidence in a clean checkout or a named
disposable deployment; it does not claim enterprise scale or completeness
outside the supported source scope.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `VERIFIED` | The stated behavior has executable, repeatable evidence in the repository or an explicitly named disposable environment. |
| `PARTIALLY VERIFIED` | A real implementation and some evidence exist, but a release-relevant path or state is still missing. |
| `UNVERIFIED` | The repository does not currently contain sufficient executable evidence. It must not be treated as green. |
| `INTENTIONAL` | A deliberate architecture or product-scope decision; it is not a defect to simplify away. |
| `FUTURE RISK` | Not a current MVP blocker, but requires a scale-triggered follow-up. |

## Evidence ledger

| Claim | Current status | Evidence | Missing evidence | Owner / next verification | Release impact |
| --- | --- | --- | --- | --- | --- |
| Five primary user flows have a truthful current-state map | `VERIFIED` | [capability matrix](mvp-capability-matrix.md), [vertical smoke](../backend/tests/vertical/test_mvp_production_flows.py::test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery), [current browser flow](../frontend-next/tests/mvp-production-flow.spec.ts), and clean deployment browser smoke | Production traffic metrics are operational follow-up, not a missing MVP contract | `MVP-093..095` complete | Required baseline satisfied |
| BMSTU and HSE ingestion is reproducible with stable canonical outcomes | `VERIFIED` | [baseline manifest](../backend/tests/fixtures/mvp/baseline_manifest.json), [baseline regression](../backend/tests/vertical/test_mvp_baseline_regression.py::test_fixture_source_manifest_is_stable), and [owner-attached live source-health evidence](release/mvp-production-level-evidence.md) on `b15dbe7`: BMSTU 134/134 curriculum+admission programmes; HSE 88.54% curriculum and 51.04% admission coverage; both degraded states have zero blocking gaps | Repeat scheduled runs, source-change handling, and third-university onboarding remain operational/post-MVP work; no completeness outside BMSTU/HSE is claimed | `MVP-021..024`, `MVP-095` closed | P0 satisfied for bounded scope |
| PostgreSQL migration and projection path works on a disposable database | `VERIFIED` | [PostgreSQL ingestion test](../backend/tests/integration/test_postgresql_ingestion.py::test_postgresql_ingest_is_repeatable_and_updates_projection), [profile persistence test](../backend/tests/integration/test_postgresql_user_profile.py::test_postgresql_persists_user_profile_through_repository_and_api), clean PostgreSQL 16 deployment, readiness head `0022_ingestion_concurrency`, backup/restore, and reversible migration check | Crash recovery under production load remains operational follow-up | `MVP-040..042`, `MVP-095` closed | P0 satisfied |
| Catalog, curriculum, admissions, comparison, and source-backed admission fit return stable business outcomes | `VERIFIED` | [baseline public read assertions](../backend/tests/vertical/test_mvp_baseline_regression.py::test_public_fixture_read_paths_keep_stable_business_outcomes), [production flow test](../backend/tests/vertical/test_mvp_production_flows.py::test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery), and clean deployment browser states | Live source freshness is represented as typed degraded data and is monitored by the source-health run | `MVP-051`, `MVP-071` complete | P0 satisfied |
| Recommendation ranking is deterministic and explainable for Content Fit | `VERIFIED` | [recommendation tests](../backend/tests/modules/recommendations), [versioned regression corpus](../backend/tests/fixtures/recommendations/regression-v1.json), [vertical smoke](../backend/tests/vertical/test_mvp_production_flows.py::test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery), and browser explanation rendering | Predictive accuracy is intentionally not claimed; future weight changes require a new reviewed corpus | `MVP-060..063` complete | P0 satisfied for bounded MVP policy |
| Admission Fit is an evidence-backed readiness assessment, not a probability claim | `VERIFIED` | [partial-data assertion](../backend/tests/vertical/test_mvp_production_flows.py::test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery), [Admission Fit docs](admission-fit.md), [browser validation](../frontend-next/tests/admission-fit.spec.ts), and clean deployment browser matrix | No probability or guaranteed-admission claim; source coverage remains explicit | `MVP-052` complete | P0 satisfied |
| Career Fit and validated Workload Readiness are public MVP capabilities | `INTENTIONAL` — out of scope | [product principles](product-principles.md), [capability matrix](mvp-capability-matrix.md) | No implementation is promised in the MVP claim | Product decision; do not promote without a new scoped plan | Must remain excluded from MVP claims |
| Adaptive proftest session path is compact, resumable, revision-bound, and persisted | `VERIFIED` | [production flow](../backend/tests/vertical/test_mvp_production_flows.py::test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery), [session API tests](../backend/tests/api/test_proftest_sessions_api.py), [expiry repository test](../backend/tests/infrastructure/test_proftest_sessions_repository.py::test_expired_draft_is_not_resumed_and_next_start_creates_a_new_session), [signal corpus](../backend/tests/fixtures/proftest/signal-corpus-v3.json), [handoff projection tests](../backend/tests/modules/proftest/test_proftest_projection.py), and clean deployment Chromium/mobile browser regression | Career Fit and validated Workload Readiness remain explicitly outside MVP | `MVP-095` closed | P0 satisfied |
| DecisionContext owns shortlist/final choice, optimistic revision, and explicit constraint outcomes | `VERIFIED` | [decision regression](../backend/tests/vertical/test_mvp_baseline_regression.py::test_decision_baseline_is_deterministic_and_revision_bound), [constraint API test](../backend/tests/api/test_decision_routes.py::test_decision_suggestions_report_source_backed_constraint_outcomes), [browser constraint smoke](../frontend-next/tests/admission-fit.spec.ts), and concurrency tests | Higher-load analytics capacity remains future measurement work; choice correctness is covered | `MVP-041` complete | P0 satisfied |
| Anonymous profile/auth isolation and guest-to-account transfer are implemented | `VERIFIED` | [vertical auth flow](../backend/tests/vertical/test_mvp_production_flows.py::test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery), [auth API tests](../backend/tests/api/test_auth_api.py), [request-control tests](../backend/tests/api/test_request_controls.py), and clean-origin browser smoke | Real deployment secrets and multi-region session operation remain deployment inputs/future operations | `MVP-095` closed | P0 satisfied |
| Admin/Ops ingestion run lifecycle is diagnosable and retryable | `VERIFIED` | [vertical failed→completed retry](../backend/tests/vertical/test_mvp_production_flows.py::test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery), [admin API tests](../backend/tests/api/test_admin_ops_api.py), configured ops browser tests, and source-health run IDs | Alert routing/retention remains operational follow-up | `MVP-023`, `MVP-082` complete | P0 satisfied |
| Structured request/run observability is sufficient for MVP operation | `VERIFIED` | [health/runtime route](../backend/src/andromeda/api/routes/health.py), [API tests](../backend/tests/api/test_andromeda_api.py), [request-control tests](../backend/tests/api/test_request_controls.py), and deployment health/run diagnostics | External alert retention policy remains operational follow-up | `MVP-095` closed | P0 satisfied |
| Taxonomy coverage and unknown classification are auditable | `VERIFIED` | [taxonomy classifier tests](../backend/tests/modules/test_discipline_classifier.py), [taxonomy metric tests](../backend/tests/ingestion/test_taxonomy_metrics.py), [regression corpus](../backend/tests/fixtures/taxonomy/discipline_classification.json), and current source-health metrics with versioned gaps/coverage | HSE unknown queue remains a visible degraded state and requires future operator review; it is not silently classified | `MVP-095` closed | P0 satisfied for bounded scope |
| CI proves clean-checkout backend/frontend/integration/browser quality | `VERIFIED` | [testing guide](testing.md), [test matrix](test-matrix.md), root `.github/workflows/monorepo-ci.yml`, canonical scripts under `../scripts/`, clean release metadata, and [successful upstream CI run](https://github.com/artemnoor/andromeda/actions/runs/35437883636) | Monorepo E2E now adds root Compose-backed MAX-to-Public-API coverage | `MVP-095` closed | P0 satisfied |
| Production-like deployment can be installed, migrated, smoked, rolled back, and restored | `VERIFIED` | [deployment documentation](deployment.md), [YC compose](../deploy/yc/compose.yaml), [deployment contract gate](../scripts/check_deployment_artifacts.py), clean `b15dbe7` images, Caddy smoke, fixture ingestion, backup/restore, and reversible migration evidence | A real production environment still requires deployment-owned secrets and traffic approval | `MVP-095` closed | P0 satisfied |
| Documentation and repository workflow describe the current source snapshot | `VERIFIED` | [README](../README.md), [architecture](architecture.md), [test matrix](test-matrix.md), root `AGENTS.md`, [release evidence](release/mvp-production-level-evidence.md), and `scripts/check_docs.py` | AI Factory plans/rules remain local ignored artifacts and are not part of this public runtime repository | `MVP-095` closed | P1 satisfied |
| Current performance is adequate without premature optimization | `FUTURE RISK` | [baseline regression](../backend/tests/vertical/test_mvp_baseline_regression.py), [query/repository tests](../backend/tests/infrastructure) | Production-like timings, query plans, N+1 and memory evidence | `MVP-043`; measure before optimizing | Not a blocker without evidence |

## Release decision

The repository is **MVP Production Level** for the bounded source-backed
BMSTU/HSE MVP. The release evidence proves runnable end-to-end flows,
diagnosable ingestion, clean-checkpoint CI, production-like deployment and
restore, and honest degraded data states. It does not broaden product claims
beyond the supported universities or implement Career Fit/validated Workload
Readiness. An unknown row is never treated as passed by assumption.

The release metadata command also records whether its `HEAD` is backed by a
clean worktree. `--require-clean` is the preflight for a release checkpoint;
it fails closed and does not promote the product by itself.

The complete tracer namespace disposition is recorded in the [MVP-012
migration checkpoint](archive/tracer-migration.md); it distinguishes retained
raw contracts/fixtures from executable compatibility wrappers and untracked
local artifacts.

## Decisions protected from scope drift

These are intentional and must survive all implementation phases:

- Keep the modular monolith, bounded contexts, domain/contracts/services/
  repository layering, typed Protocol ports, and architecture tests.
- Keep contract-first public APIs and generated frontend types.
- Keep Content Fit, Admission Fit, Career Fit, and Workload Readiness as
  distinct semantics; only the latter two remain explicitly out of MVP scope
  until separately implemented and validated.
- Keep `DecisionContext` as the owner of explicit shortlist/final choice;
  recommendations are derived suggestions and never silently prune choice.
- Keep anonymous opaque HttpOnly sessions, account precedence, and explicit
  guest-to-account transfer.
- Keep fail-closed behavior for blocking missing data, while exposing
  degradable and informational gaps where a safe result remains possible.
- Keep university-specific parsing and mapping inside ingestion adapters; do
  not leak source assumptions into university-independent domain core.
- Keep map-agnostic events/campus boundaries and document the current
  single-instance deployment boundary until scale requirements justify shared state.

## Verification protocol

For every later phase, update the current ledger row only after the named
command/test has run against the current code. Historical baseline artifacts
under `backend/tests/fixtures/mvp/` are immutable evidence; intentional
behavior changes require a new migration note and updated assertions rather
than rewriting the baseline silently.
