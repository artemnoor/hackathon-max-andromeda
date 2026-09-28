[← PostgreSQL](postgresql.md) · [Back to README](../README.md)

# Тестирование

## Canonical targets

Из корня репозитория новый разработчик или AI agent может начать с:

```powershell
python scripts/andromeda.py fast
python scripts/andromeda.py production-smoke
python scripts/andromeda.py full
```

Для release checkpoint дополнительно запускается:

```powershell
python scripts/release_evidence.py --require-clean
```

Команда пишет secret-free metadata и завершается с ошибкой на dirty
worktree; сама по себе она не повышает release status.

Отдельные `backend`, `backend-coverage`, `frontend`,
`frontend-coverage`, `ingestion`, `postgres`, `playwright`,
`migrations`, `deployment`, `security` и `release-evidence` targets описаны в
[test matrix](test-matrix.md). Coverage — диагностический отчёт; критические
правила и обязательные слои перечислены там же.

## Backend

### Knowledge and policy

The source-backed policy regression path is checked with deterministic unit,
repository, ingestion, review/API, response-envelope, architecture and Jev-gate
tests:

```powershell
cd backend
python -m pytest -q tests/unit tests/modules/conversation/test_policy_query.py tests/modules/conversation/test_policy_presentation.py tests/modules/presentation/test_knowledge_response.py tests/infrastructure/test_knowledge_candidate_repository.py tests/infrastructure/test_knowledge_provenance_report.py tests/infrastructure/test_knowledge_review_repository.py tests/infrastructure/test_knowledge_review_auth.py tests/infrastructure/test_knowledge_source_repository.py tests/infrastructure/test_admission_policy_repository.py tests/infrastructure/test_admission_cycle_repository.py tests/infrastructure/test_policy_dependency_refresh.py tests/ingestion/test_knowledge_source_discovery.py tests/ingestion/test_fetch_security.py tests/api/test_knowledge_ops.py tests/api/test_assistant_query.py tests/evaluation/test_jev_knowledge_policy_gate.py tests/infrastructure/test_alembic_migrations.py tests/architecture/test_module_boundaries.py
```

This covers rumor/proposal vs effective state, 2027/2028 cycle applicability,
scope/exception/conflict/supersession, last-good source snapshots, duplicate
claims, what-if no-write behavior, exact-hash approval, `ResolutionTrace`, and
bounded repository hydration. The vertical assistant test uses a typed domain
owner read boundary; an applicant-specific benefit result remains delegated to
the separate existing `admission_benefits` evaluator tests. PostgreSQL-specific
constraints and query plans require the disposable PostgreSQL target below;
SQLite tests do not stand in for those guarantees.

The policy Jev gate is explicitly off and has no registered policy operation.
Future matching operations require an independently labeled 500-case golden
corpus and approved per-operation thresholds; no Stage 2 calibration lock is
changed by this feature.

Multi-university HSE gate:

```powershell
python -m pytest -q tests/ingestion/test_hse_parser.py tests/integration/test_hse_full_ingestion.py
```

Проверяются official fixture metadata, HSE parser → canonical → persistence, admissions/curricula, repeat ingestion и coexistence с BMSTU при одинаковом direction code.

```powershell
cd backend
python -m pytest -q
python -m mypy
```

Тесты покрывают module contracts, parser → canonical boundary, dynamic BMSTU catalog identity, DB constraints, atomic repositories, API и полный backend vertical slice. Отдельные проверки гарантируют наличие всех 22 областей, положительные deterministic vectors BMSTU taxonomy, сумму каждого вектора `1.0000`, сохранение area weights в SQLite и агрегацию содержания по часам/ЗЕТ. Каждый ingestion run сохраняет в quality metadata версию taxonomy, source hashes, coverage, unresolved/fallback counts, конфликтные и дублированные ключи, area usage и affected programs. Поддерживается committed regression corpus для всех 22 областей и известных unknowns; неподтверждённый исторический live-аудит на 2 582 дисциплины больше не является product claim.

Миграция `0003_discipline_taxonomy` создаёт справочник областей и таблицы весов дисциплин. Fixture smoke прогоняет цепочку ingestion → repository → comparison → API на чистой и повторно используемой SQLite-базе. PostgreSQL integration tests используют Alembic, а не `Base.metadata.create_all()`, и проверяют migration chain, FK/unique/check constraints, idempotent rerun, projection update и rollback. Для full BMSTU ingestion повторный live run должен сохранить canonical counts без дублей и допускает только обновление provenance/curriculum metadata.

Admission Fit покрывается отдельным набором:

```powershell
cd backend
python -m pytest -q tests/modules/admission_fit tests/api/test_admission_fit_api.py tests/api/test_admission_fit_contract.py tests/integration/test_admission_fit_vertical_slice.py
```

Набор проверяет strict contracts, нормализацию и неоднозначность предметов, четыре статуса, minimum/passing/completeness breakdown, provenance-backed reasons, отсутствие влияния на recommendation ranking и synthetic personas. `test_admission_fit_vertical_slice.py` прогоняет BMSTU fixture parser → canonical admissions → SQLite repository → FastAPI endpoint. PostgreSQL smoke добавляется командой:

```powershell
$env:ANDROMEDA_POSTGRES_TEST_URL = "postgresql+psycopg://..."
python -m pytest -q tests/integration/test_postgresql_smoke.py tests/integration/test_storage_parity.py
```

Без PostgreSQL DSN smoke-тест явно `skipped`; CI передаёт disposable PostgreSQL URL.

Decision/Shortlist и отсутствие линейной зависимости проверяются отдельно:

```powershell
cd backend
python -m pytest -q tests/modules/decision tests/api/test_decision_routes.py tests/infrastructure/test_decision_analytics.py tests/integration/test_no_linear_flow.py
```

Набор проверяет owner-bound `DecisionContext`, optimistic revision, explicit
add/remove/restore/role transitions, отсутствие silent prune после изменения
ограничений, derived suggestions и batch Admission Fit. `test_no_linear_flow.py`
подтверждает, что свежий anonymous scope может открыть context, catalog,
comparison, admissions и Admission Fit без `UserProfile`, proftest или
Personal Route.

Для order-derived minima используйте focused набор:

```powershell
cd backend
python -m pytest -q tests/ingestion/test_bmstu_source_capture.py tests/ingestion/test_bmstu_orders_metadata.py tests/ingestion/test_bmstu_admission_orders_parser.py tests/ingestion/test_bmstu_admissions_normalizer.py tests/ingestion/test_bmstu_admissions_parser.py
python -m pytest -q tests/infrastructure/test_admissions_repository.py tests/infrastructure/test_alembic_migrations.py tests/api/test_andromeda_api.py
```

Проверяется migration `0010_admission_passing_route`, backfill старых numeric rows, route/BVI round-trip, deterministic minimum/provenance, API JSON и отсутствие `null балла` в UI. Public и full OpenAPI artifacts и generated clients проверяются перед frontend gates:

```powershell
cd ..
python scripts/andromeda.py openapi
cd frontend-next
npm run test:unit
npm run build
```

Повторяемый SQLite smoke полного runner:

```powershell
python backend/scripts/run_andromeda_ingestion.py --university all --mode fixture --database-url sqlite:///backend/data/andromeda-admission-ci.db --log-level INFO
python backend/scripts/run_andromeda_ingestion.py --university all --mode fixture --database-url sqlite:///backend/data/andromeda-admission-ci.db --log-level INFO
```

На live smoke runner динамически читает только официальный [orders manifest](https://priem.bmstu.ru/lists/orders.json) и сохраняет source gaps вместо нулевых или выдуманных баллов. В CI live сеть не требуется: используются sanitized source excerpts и injected fetchers.

Admin/Ops data-quality slice проверяется отдельным bounded read-only набором:

```powershell
cd backend
python -m pytest -q tests/modules/admin_ops tests/api/test_admin_ops_contract.py tests/api/test_admin_ops_api.py tests/infrastructure/test_admin_ops_repository.py tests/integration/test_admin_ops_vertical_slice.py tests/vertical/test_admin_ops_vertical_contract.py tests/infrastructure/test_atomic_ingest.py
python -m pytest -q tests/architecture/test_module_boundaries.py
python -m mypy
```

Проверки покрывают lifecycle `running → completed|failed`, сохранение failed audit после rollback, deterministic list/detail, bounded fixture retry, running conflict, staging-only live boundary, malformed audit data, explicit key guard, отсутствие raw source fields и OpenAPI operation IDs. Admin/Ops endpoint выключен без `ANDROMEDA_OPS_API_KEY`; ключ не попадает в логи или ответы. Browser check открывает только `/#ops`, проверяет safe detail, unavailable conflict notice, confirmation перед retry и wrong-key error state.

University admin/catalog/events slice проверяется так:

```powershell
cd backend
python -m pytest -q tests/modules/university_admin tests/api/test_university_admin_access.py tests/api/test_university_catalog_api.py tests/api/test_university_events_api.py tests/infrastructure/test_university_admin_repository.py tests/infrastructure/test_university_catalog_repository.py tests/infrastructure/test_university_catalog_query_count.py tests/infrastructure/test_university_events_repository.py tests/infrastructure/test_university_events_query_count.py tests/integration/test_university_event_projection.py tests/architecture/test_module_boundaries.py tests/infrastructure/test_alembic_migrations.py
python -m mypy src/andromeda
cd ..
python scripts/andromeda.py openapi
cd frontend-next
npx tsc --noEmit
npm run lint
npm run test:unit
npm run build
```

Focused checks cover ops-only first-owner provisioning, owner/editor/viewer
role matrix, cross-university denial, 401/403/404 semantics, draft/public/
archived event lifecycle, explicit audience modes, agenda, source/editorial
ID separation and bounded public reads. Public browser surfaces use the
existing anonymous demo flow: `/?view=university-catalog`, `/?view=events`
with a university selector and `/?view=university-admin` for an authenticated
membership. The browser never stores an ops key, password or auth token.

Personal Route проверяется отдельными contract/API и vertical tests как
совместимый optional support layer:

```powershell
cd backend
python -m pytest -q tests/modules/personal_route tests/api/test_personal_route_api.py tests/api/test_personal_route_contract.py tests/integration/test_personal_route_vertical_slice.py tests/vertical/test_personal_route_scope_guard.py
```

Набор проверяет deterministic plan ordering, current-profile isolation, recommendation-to-event filtering, canonical event/venue/point links, online events without a point, fixed-clock behavior for past events и отсутствие map/storage dependencies. Отдельно проверяется, что DecisionService не вызывает этот модуль и что отсутствие profile не закрывает каталог/сравнение/поступление. PostgreSQL job повторяет fixture → repository → profile → optional support read flow.

## Canonical Next frontend

```powershell
cd frontend-next
npm run build
npm run check-api-drift
npm run check-public-api-drift
npm run test:unit
npm run test:e2e
```

E2E-тест использует стабильные `data-testid`, сохраняет existing comparison coverage и проходит профтест до explainable recommendation на desktop/mobile. Отдельный browser scenario завершает тест, очищает local draft и проверяет восстановление профиля и current recommendations по cookie/API. `legacy-flow-compat.spec.ts` проверяет, что старый `flow` URL открывает нейтральный DecisionContext без mandatory funnel. `events-support-layer.spec.ts` проверяет optional personal route, source-backed event-to-program links и видимый source gap для события без связи; просмотр не меняет shortlist. Admission assertions находятся в `mvp-production-flow.spec.ts` и `admission-fit.spec.ts`; recommendation failure/empty assertions — в `recommendations-states.spec.ts`, responsive/accessibility smoke — в `responsive-accessibility.spec.ts`, а `ops-control-plane.spec.ts` дополнительно проверяет wrong-key recovery, configured ops access, подтверждённый fixture retry и безопасный run detail. Ops-сценарий запускается только при явно заданном `PLAYWRIGHT_OPS_API_KEY` поверх staging-like `ANDROMEDA_OPS_API_KEY`, чтобы локальный публичный demo не получал встроенный ключ. Перед ним должен работать fixture demo:

```powershell
python backend/scripts/run_andromeda_demo.py --mode fixture
```

## Public API OpenAPI and DATA-API

Корневой [`openapi.json`](../openapi.json) — canonical Public API v1 contract;
`frontend-next/openapi.json` содержит full-app/internal endpoints. Генерация и
drift workflow:

```powershell
python backend/scripts/export_openapi.py --surface public-v1 --out openapi.json
python backend/scripts/export_openapi.py --surface full --out frontend-next/openapi.json
cd frontend-next
npm run generate-public-api
npm run generate-api
cd ..
python scripts/andromeda.py openapi
```

Последняя команда сравнивает backend exports, оба checked-in snapshots и оба
generated clients. Официальный DATA-API validator vendored без изменений из
`stasnorman/example-data-api` commit
`8504a6d9b39e6f652bce689d96e88538d7541c6b`; запуск:

```powershell
python scripts/andromeda.py data-api
```

Прямая команда вызывает тот же upstream script/schema:

```powershell
uv run --project backend --locked --extra dev python scripts/data_api/validate_data_api.py DATA-API.yaml --schema scripts/data_api/DATA-API.schema.json --openapi openapi.json
```

Validator сверяет DATA-API 1.0 schema, переменные/check dependencies и
OpenAPI paths/methods; он не отправляет HTTP requests. В YAML оставлен
HTTPS `.example` base URL, который нужно заменить реальным deployed URL перед
live organizer-side проверкой. Validator и schema сохранены без изменений из
`stasnorman/example-data-api` commit
`8504a6d9b39e6f652bce689d96e88538d7541c6b`; upstream provenance и SHA-256
сохранены в [`scripts/data_api/UPSTREAM.md`](../scripts/data_api/UPSTREAM.md).

Recommendation tests дополнительно проверяют strict contracts и module boundary, неизменность детерминированного ranking, tie-break по коду, монотонный anti-interest penalty, evidence-backed explanations, пять synthetic personas, empty catalog и DB → catalog adapter → service → API путь. Versioned corpus `tests/fixtures/recommendations/regression-v1.json` и `tests/modules/recommendations/test_regression_corpus.py` добавляют replay-кейсы для `content-fit.v1`: top-level thematic fit, anti-interest exclusions, source-gap degradation, explicit unknown reasons, metamorphic axis isolation и stable tie-break. Corpus не утверждает predictive accuracy и должен обновляться только вместе с policy/taxonomy review.

Persistence-проверки включают strict `ProfileScope`/`UserProfileSnapshot`, anonymous cookie isolation, revision conflict, migration `0005_user_profiles`, repository transaction, SQLite migration → BMSTU ingestion → `POST /proftest/results` → `GET /proftest/profile` → `GET /recommendations/current` и PostgreSQL smoke. Auth-проверки дополнительно покрывают Argon2 hash, opaque/revocable sessions, cookie flags, trusted Origin, anonymous → account transfer, account-profile-wins conflict и cross-account isolation. Профиль не смешивается с Admission Fit и Content Fit ranking.

Session-driven adaptive proftest имеет focused backend gate:

```powershell
python -m pytest -q tests/api/test_proftest_sessions_api.py tests/modules/proftest
python -m mypy src/andromeda/modules/proftest src/andromeda/api
```

Он покрывает version-pinned вопросы v3/v2, ровно пять core submissions,
preliminary topics, 7/8/9-step adaptive personas и cap 4,
five-plus component mechanics,
uncertain/skipped answers, deterministic adaptive selection и stop reasons,
stale revision conflicts, early-answer invalidation, guest ownership,
completed session resume, atomic profile persistence, analytics replay,
bounded payload validation и expiry. Полный browser gate запускается через
fixture demo на отдельном порту, если стандартный локальный frontend занят:

```powershell
$env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1:3001"
python backend/scripts/run_andromeda_demo.py --mode fixture --api-port 8010 --frontend-port 3001
cd frontend-next
npx playwright test --workers=1
```

Для disposable compose smoke через локальный Caddy с self-signed TLS
используйте только явно заданный тестовый флаг:

```powershell
$env:PLAYWRIGHT_BASE_URL = "https://localhost:8443"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS = "1"
# For a compose smoke on a non-default HTTPS port, set the backend origin too:
$env:ANDROMEDA_FRONTEND_ORIGIN = "https://localhost:8443"
npx playwright test tests/catalog-programs.spec.ts --project=chromium
```

`PLAYWRIGHT_IGNORE_HTTPS_ERRORS` действует только в Playwright и не меняет
secure-cookie, Origin/CSRF или TLS policy backend.

Browser scenarios проверяют desktop/mobile completion, reload resume,
completed-result recovery, auth/guest menu, independent entry points и
существующие catalog/comparison/admissions/events/recommendations/support
contracts. В
двухпрограммном fixture adaptive selector может завершиться с
`insufficient_candidate_spread`; это явный source-backed gap, а не
синтетический adaptive вопрос.

Для signal-quality replay используется versioned fixture
`tests/fixtures/proftest/signal-corpus-v3.json`. Он проверяет, что v3 persona
answers дают только объявленные subject/activity/anti-interest axes,
uncertain answers не создают сигналы, а adaptive answer меняет измеримый
Content Fit axis. При blocking curriculum gaps selector останавливает
дополнительные вопросы с `stopReason=source_gap`; profile остаётся доступным,
но это не повышает evidence reliability.

`ProftestPage` хранит только validated answer draft с `questionSetVersion` и
`sessionId`; completed/expired session очищает draft. Restore/start/save/complete
ошибки имеют retry или безопасный restart, а `409` сначала перечитывает
authoritative session. Для проверки запускаются `proftest.spec.ts` на Chromium
desktop/mobile; malformed localStorage и временный restore failure входят в
browser regression.

После completion profile persistence является отдельным checkpoint handoff:
`test_proftest_projection.py` проверяет, что persisted `profileRevision` и
`proftest-v3` доходят до recommendation evidence, а отказ recommendation path
возвращает completed session с сохранённым профилем и `results=null`. API
регрессия проверяет те же поля в wire contract; `proftest-decision-integration.spec.ts`
проверяет видимость набора вопросов, ревизии, completeness/source gaps и
отсутствие автоматической мутации shortlist. Результаты не являются
психологическим диагнозом: confidence отображается как полнота профильного
сигнала, а source-backed evidence и missing data остаются отдельными.

Локальный gate canonical Next включает backend pytest/mypy, Next unit, lint,
build, OpenAPI drift и Playwright на desktop/mobile проектах. Browser suite
запускает одинаковые сценарии на desktop и mobile; число сценариев определяется
файлами в `frontend-next/tests`, а не фиксированным списком. PostgreSQL target
требует явный disposable `ANDROMEDA_POSTGRES_TEST_URL`; он не превращает
отсутствие сервиса в незаметный зелёный skip. CI job `postgresql-integration`
поднимает PostgreSQL 16 и выполняет cases с миграциями.

Для focused запуска:

```powershell
python -m pytest -q tests/api/test_auth_api.py tests/api/test_proftest_profile_api.py tests/integration/test_user_profile_persistence.py tests/infrastructure/test_user_profile_repository.py
```

Next unit-тесты проверяют API mapping/error/timeout contracts, а browser E2E
прогоняется на Chromium desktop и mobile projects.

## CI

GitHub Actions запускает backend tests/mypy/architecture/coverage, canonical
Next contract/unit/coverage/lint/build gates, fixture smoke и Chromium E2E.
Отдельные jobs проверяют migrations, PostgreSQL, proftest,
dependency audit, документацию и Docker packaging. `postgresql-integration`
поднимает disposable PostgreSQL 16 service, применяет Alembic к пустой базе,
прогоняет BMSTU fixture → API → `frontend-next` и выполняет PostgreSQL-backed
browser scenario. Poppler и браузер устанавливаются в CI jobs; live
source-health остаётся scheduled read-only workflow.

Перед отправкой изменений полный локальный gate повторяет существенные CI
границы:

```powershell
python scripts/andromeda.py fast
python scripts/andromeda.py backend-coverage
python scripts/andromeda.py frontend
python scripts/andromeda.py frontend-coverage
python scripts/andromeda.py production-smoke
```

Для migration parity используйте `python scripts/andromeda.py migrations`:
команда применяет текущий Alembic head (`0054_claim_predicate_lookup_index`)
к пустой SQLite-базе и запускает `alembic check`. Текущий implementation
сохраняет одну additive history от Stage 2 head `0038`; отдельный regression
поднимает базу с `0038`, сохраняет Stage 2 source snapshot и доводит её до
`0054`. PostgreSQL migration/rollback smoke остаётся отдельным disposable
target и не использует рабочую базу.

Analytics tests проверяют allowlist, bounded canonical IDs, отсутствие raw
profile/score/cookie/source body, owner isolation, idempotency и то, что отказ
telemetry не блокирует shortlist mutation. Browser events допускают только
safe view/interaction payload; authoritative shortlist size before/after
создаётся сервером.

Для локального PostgreSQL запуска используйте [руководство PostgreSQL](postgresql.md). Без test DSN PostgreSQL-only tests явно помечаются skipped; CI обязан передавать `ANDROMEDA_POSTGRES_TEST_URL`.

### Universal analytics acceptance corpus

The source-backed analytics slice has deterministic fixtures for metric
resolution and comparison, grouped mean by university, bounded ranking and
filtering, evidence/basis/coverage explanations, admission clarification with
no redundant questions, Jev unavailable/timeout/malformed-output fallback,
and ResponsePlan conformance for Web and future clients of Public API v1.

```powershell
python backend/scripts/evaluate_decision_model.py
python -m pytest -q tests/evaluation tests/modules/conversation tests/modules/presentation tests/infrastructure/test_jev_adapter.py
python -m pytest -q tests/integration/test_analytics_engine.py tests/api/test_analytics_api.py tests/api/test_assistant_query.py
```

The evaluation report contains aggregate accuracy and fallback counts; it does
not store raw user text. Jev shadow decisions are advisory until an empirical
promotion gate exists.

## See Also

- [API](api.md) — контракты, которые проверяются drift gate.
- [Быстрый старт](getting-started.md) — локальный fixture demo.
- [PostgreSQL](postgresql.md) — storage integration commands.
## Jev ecosystem offline gate

The upstream integration gate is offline by default and does not require
provider secrets. From `backend/` run:

```text
uv lock --check
uv run --locked --extra evaluation --extra jev --extra jevql --extra dev python -m pytest -q tests/evaluation tests/infrastructure/jevql tests/modules/entity_resolution tests/composition/test_jevql_wiring.py
npm ci --ignore-scripts                 # from backend/jev-tree-bridge
uv run --locked --extra evaluation --extra dev python scripts/evaluate_jev_ecosystem.py --output .tmp/jev-report.json --check
```

The offline report never invokes provider paths and marks them `not_run_offline`;
that is not a credential or service-health check and is not a production
calibration claim. The official TypeSafe client and System One benchmark are
opt-in; raw provider prompts, responses, cookies and keys are never committed.
