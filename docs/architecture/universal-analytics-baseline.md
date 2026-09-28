# Universal Analytics Compatibility Baseline

Дата baseline: 2026-09-21
Ветка: `feature/university-admin-control`
Статус: baseline для additive implementation; runtime behavior не изменяется этим документом.

## Границы baseline

Рабочее дерево на момент baseline было dirty. Вне scope этой реализации остаются:

- существующие изменения university-admin в backend/frontend/docs;
- Alembic revisions `0023_uni_admin`, `0024_uni_catalog`, `0025_uni_events` и их тесты;
- `proftest-spike/` и прочие pre-existing untracked artifacts.

Analytics migrations должны продолжить подтверждённую линейную цепочку и не переписывать эти файлы.

## Database baseline

Команды выполнялись из `backend/`:

```text
alembic heads
0025_uni_events (head)

alembic current
Rev: 0025_uni_events (head)
Parent: 0024_uni_catalog
```

История перед analytics начинается с `0022_ingestion_concurrency → 0023_uni_admin → 0024_uni_catalog → 0025_uni_events`. Короткие revision ID удерживают значения в пределах PostgreSQL `alembic_version.version_num` (`varchar(32)`).

## API baseline

`create_app("sqlite://...").openapi()` на baseline возвращал 71 path и 219 schemas. Обязательные public route families:

| Surface | Existing routes |
|---|---|
| Catalog | `/universities`, `/programs`, `/programs/{id}`, `/programs/{id}/curriculum`, `/discipline-areas` |
| Comparison | `/compare`, `/compare/summary` |
| Admissions | `/programs/{id}/admissions`, `/programs/{id}/admission-fit` |
| Decisions | `/decision/context`, `/decision/suggestions`, `/decision/analytics`, shortlist/final-choice/refinement routes |
| Profile | `/proftest/*`, `/recommendations`, `/recommendations/current` |
| Events/campus | `/events`, `/campus/*`, `/personal-route` |
| Operations/auth | `/ops/*`, `/auth/*`, `/health/*` |
| University admin | `/university-admin/*`, `/ops/university-admin/*`, `/universities/{university_id}/catalog`, `/universities/{university_id}/events` |

The exact generated OpenAPI document remains the contract artifact at `frontend-next/openapi.json`; generation and drift checks are performed by the existing scripts.

## Public contract baseline

The following imports and semantics are compatibility obligations:

- `ProgramFingerprint` and `ProfileScope` from `proftest.contracts.public`;
- `ComparisonRequest` and `ComparisonSummaryRequest`;
- admission offerings and `AdmissionFitRequest`/`BatchAdmissionFitRequest`;
- owner-bound `DecisionContext`;
- `SourceAttribution`, source gaps, canonical IDs, and strict `ContractModel` validation.

`ProgramFingerprint` remains the current recommendation/decision input until the analytics projection compatibility adapter is implemented.

## Architecture baseline

`backend/tests/architecture/test_module_boundaries.py` currently covers all subject modules and public-contract/repository-port cross-module imports. `test_analytics_boundaries.py` adds a forward guard for `semantic`, `analytics`, `entity_resolution`, `conversation`, and `presentation`: these modules must not import FastAPI, SQLAlchemy, infrastructure, ingestion, Jev, MAX, or composition.

## Verification snapshot

Observed before implementation:

```text
python -m pytest tests/architecture/test_module_boundaries.py -q
5 passed

python -m pytest tests/modules/comparison tests/modules/recommendations -q
36 passed

python -m pytest tests/modules/proftest tests/modules/decision tests/modules/admission_fit -q
114 passed

python -m pytest tests/ingestion tests/api -q
177 passed, 6 warnings

npm run test:unit
6 test files, 24 tests passed
```

The full comparison/recommendations/proftest/decision/admission-fit/ingestion/API/frontend suites remain the regression gate. These commands establish the historical green baseline; their results must be captured again after each implementation checkpoint, and pre-existing failures must be separated from failures introduced by analytics.

## Rollback reference

Task 1 introduces only tests and this baseline document. If it is reverted, no canonical schema or runtime behavior is lost. Later tasks must preserve this route/import/database baseline and add only backwards-compatible seams unless a breaking change is explicitly documented and tested.
