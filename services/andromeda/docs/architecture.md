[← Быстрый старт](getting-started.md) · [Back to README](../README.md) · [API →](api.md)

# Архитектура

Проект остаётся modular monolith: один backend, одна инфраструктура и явные границы предметных модулей. Микросервисы, Kafka, CQRS и отдельный deployment-модуль в текущий scope не входят. Source-backed knowledge/policy vertical реализован как ограниченный внутренний workflow; доступ к источникам, human approval и продуктовый rollout остаются закрыты до назначения операторов и пополнения проверенного корпуса. Фактическая модель описана в [Knowledge and Policy architecture](architecture/knowledge-policy.md).

## Canonical runtime surfaces

В репозитории действует одна ownership-схема. Backend runtime, canonical
contracts, repositories, migrations и BMSTU ingestion принадлежат
`backend/src/andromeda`. BMSTU-specific
capture/parser helpers после миграции находятся внутри
`andromeda/ingestion/universities/bmstu`.

Единственным production web runtime является `frontend-next`. Он собирается в
Next standalone и запускается deployment-описаниями из `deploy/yc`; API
доступен через same-origin `/api` в production и через явно заданный
`NEXT_PUBLIC_API_BASE_URL` в local demo. Исторический exploratory Spike
retired и не является runtime/package частью проекта.

Public API v1 is the stable boundary for Web and future external clients,
including MAX Bot and Mini App. It aliases existing FastAPI handlers; clients
do not own domain logic or access internal operator routes.

OpenAPI экспортируется backend script и генерирует единственный client в
`frontend-next`. Production proftest находится в
`andromeda.modules.proftest`; история retired Spike описана только в
`docs/archive/proftest-spike.md`.

## Поток данных

```text
official university source
  → ingestion registry / universities/{adapter}
  → raw DTO → normalization → canonical contracts
  → universities / programs / curricula / disciplines
  → infrastructure repositories → PostgreSQL (development/staging) or SQLite (tests)
  → FastAPI/OpenAPI → TypeScript frontend
```

## Decision-centered application layer

`decision` — единственный реализованный bounded orchestration-модуль вокруг
пользовательского выбора в текущем runtime. Он не дублирует scoring, admissions
или comparison и не импортирует ORM, FastAPI, ingestion или private service
implementations.
Вместо этого он читает typed public contracts существующих модулей и сохраняет
owner-bound `DecisionContext`:

```text
catalog / compare / admission / proftest / saved choice
                  ↓
          DecisionContext + revision
                  ↓
  explicit constraints + considered programs + shortlist
                  ↓
       candidate suggestions: Admission Fit → constraint outcomes → Content Fit → trade-offs
                  ↓
       explicit user add/remove/restore/role commands
```

В aggregate входят только известные пользователю данные: admissions
constraints, considered canonical program IDs, active/removed shortlist entries,
roles (`primary`/`alternative`) и explicit exclusions. Profile preferences не
копируются в `decision_contexts`: `UserProfile` остаётся владельцем
предпочтений, а DecisionContext получает его read-only projection и revision.
Suggestions, candidate partitions, Admission Fit outcomes, typed constraint
applicability, Content Fit evidence,
refinement question и source gaps никогда не становятся implicit user choice.

Каждая mutation проверяет optional `expectedRevision` и возвращает новую
revision; конфликт даёт `409`, а не last-write-wins. Read/recalculation не
удаляет shortlist. Server-side decision analytics записывает authoritative
shortlist sizes после committed transition, client-side view events только
наблюдают интерфейс и не влияют на domain behaviour.

Для профиля содержания application flow продолжается так:

```text
programs / curricula / disciplines public readers
  → proftest catalog adapter
  → ProgramFingerprint
  → UserProfile
  → recommendations scoring/ranking/explanations
  → canonical /proftest/sessions/* → /recommendations
  → generated frontend types
```

После завершения профтеста application flow сохраняет финальный профиль через отдельный persistence port:

```text
POST /proftest/sessions/current/complete
  → UserProfilePersistenceService
  → UserProfileRepository
  → user_profiles (session hash + JSON snapshot + revision/TTL)
  → GET /proftest/profile | GET /recommendations/current
```

Адаптивный flow v2 сохраняет состояние до завершения и не меняет владельца
ranking:

```text
POST /proftest/sessions
  → ProftestSessionService
  → versioned questionnaire + ProfileBuilder
  → ProftestAnswerSessionRepository
  → proftest_answer_sessions (owner, answers, cursor, revision, expiry)
  → next question / AdaptiveQuestionSelector
  → complete → UserProfileRepository + recommendations
```

`ProftestSessionService` владеет переходами `draft → completed|expired` и
проверкой branch/question IDs. `AdaptiveQuestionSelector` получает только
typed `ProgramFingerprint` reads через `ProftestCatalogService`; matching и
ranking остаются внутри `RecommendationService`. Поэтому session API не
знает о SQLAlchemy, BMSTU parser или frontend mechanics. При изменении
раннего ответа adaptive answers инвалидируются через
`stale_question_ids`, а source gap/insufficient spread возвращается как
явная причина остановки, без выдуманных workload-сигналов.

`/proftest/questions`, `/proftest/preview` и `/proftest/results` остаются
deprecated compatibility adapters для уже выпущенных клиентов. Они делегируют
общие profile-builder/recommendation services и не содержат отдельного scoring
или ranking path; удалить их можно после одного release cycle без calls.

Anonymous identity — это случайный HttpOnly cookie, а в domain/infrastructure boundary передаётся только typed `ProfileScope` с SHA-256 hash. `UserProfile` не содержит storage metadata; revision и timestamps находятся в `UserProfileSnapshot`. Admission Fit остаётся отдельным score и не влияет на Content Fit.

Auth identity follows the same boundary: `modules/auth` publishes typed `Account` and application ports; infrastructure stores Argon2 password hashes and opaque session-token hashes in `accounts`/`auth_sessions`. The API alone reads the raw HttpOnly cookie. `ProfileScope` may carry a canonical `AccountId` in addition to the anonymous session hash, so the existing proftest/recommendations/personal-route flows restore account-owned profiles without adding `account_id` to `UserProfile`. Binding is explicit and non-merging: account profile wins when both owners have a profile, while the anonymous row remains isolated.

Университетские события и campus points используют общий canonical venue boundary:

```text
events ingestion / campus ingestion
  → Event + Venue + CampusPoint canonical contracts
  → infrastructure repositories
  → /events и /campus/* FastAPI contracts
  → список/карточка события или физической точки
```

`campus` отдаёт map-agnostic spatial data: название и canonical ID точки, тип (корпус, зона, место события, вход или другая категория), адрес, известные координаты, university/department/program links, events в точке, время событий и поля карточки. Эти данные предназначены для UI и будущего внешнего map-модуля. Внутри Andromeda не задаются визуальная раскладка объектов, 2D/3D-визуализация, связи, маршруты, route optimizer или библиотека карт.

Ingestion quality для operator-инструментов использует существующий `ingest_runs` и отдельный read-only `admin_ops` module:

```text
ingestion lifecycle
  → ingest_runs (running → completed|failed + bounded counters)
  → admin_ops reader/service + typed retry executor port
  → protected GET /ops/ingestion/runs[/{id}] and POST /ops/ingestion/runs/retry
```

Run создаётся до capture и атомарной projection transaction, а failure обновляет только безопасный audit status и generic error message после rollback. `admin_ops` не читает raw snapshot bodies или `RawSourceRecord.payload_json`, не знает ORM/parser и получает retry через typed executor port. Infrastructure связывает этот port с существующим BMSTU adapter/repository; retry ограничен фиксированными профилями и не принимает URL/команды. `#ops` UI не является обычной навигацией и не реализует correction, CMS, Auth/RBAC, карту или пользовательское scoring.

University-owned content использует отдельный `university_admin` bounded module,
а не `admin_ops`. Он владеет membership `owner/editor/viewer`, редакционными
подразделениями и категориями, overlay для канонических программ/предметов и
событиями вуза. Канонические source projections не изменяются:

```text
account session + university membership
  → university_admin access policy
  → units/categories/catalog overlays + editorial events
  → PostgreSQL tables 0023–0025
  → protected /university-admin/* commands
  → public /universities/{university_id}/catalog and /events
```

Событие вуза имеет lifecycle `draft → published → archived`, optimistic
`revision`, agenda и явный audience mode: `all_university`, selected units,
selected programs или `unaffiliated`. Public readers видят только published
записи, а revoked membership и недостаточная роль проверяются backend.
`FORBIDDEN` отображается как 403; неизвестный scope не перечисляет чужие
membership и возвращается как безопасный 404.

## Границы

## Universal analytics boundary

Универсальные содержательные вопросы проходят через отдельные bounded
contexts, не принадлежащие клиентскому transport-у или конкретной модели:

```text
ingestion → canonical storage → semantic → projections
          → analytics (QuerySpec) → conversation/policies
          → ResponseEnvelope → Public API v1 → Web / future MAX clients
```

`semantic`, `analytics`, `entity_resolution`, `conversation` и `presentation`
публикуют typed contracts и Protocol-порты. `ProgramFingerprint` сохранён как
совместимый импорт, но общая аналитическая projection теперь строится и
читается из materialized `program_projections`/`program_metrics`. Подробные
правила и версии находятся в [universal analytics](architecture/universal-analytics.md),
[semantic taxonomy](architecture/semantic-taxonomy.md),
[metric registry](architecture/metric-registry.md) и
[integration seams](architecture/integration-seams.md) и
[Jev ecosystem](architecture/jev-ecosystem.md) и
[Jev rollout/security gate](architecture/jev-rollout.md).

`POST /analytics/query` является прямым typed входом без NLP. `POST
/assistant/query` добавляет owner-bound `QuerySession`, deterministic parser,
`DecisionPolicyPort`, существующий Admission Fit и `ResponsePolicyPort`.
Отсутствие данных остаётся quality status, а evidence связывает metric с
curriculum item и source snapshot.

### Stage 2 Jev boundary and dependency direction

Stage 2 extends the existing analytics graph without introducing a second
backend:

    clean Stage 1 baseline
      → canonical storage
      → semantic enrichment
      → ProgramProjection / ProgramMetric
      → MetricRegistry / QuerySpec
      → deterministic AnalyticsExecutor
      → QueryFrame / QuerySession
      → DecisionModelPort
           ↘ deterministic default
           ↘ optional TypeSafe production adapter
           ↘ shadow evaluation
      → AnalyticsResult / ResponsePlan / ResponseEnvelope
      → Web / OG / future MAX clients

The normal factual path is deterministic and source-backed. A Jev adapter may
answer only bounded control questions such as intent, metric, next action,
presentation or a reviewed semantic candidate. It never calculates catalog
facts, emits SQL, writes canonical data or becomes the owner of user choices.

The following ownership rules are mandatory:

- DecisionContext remains explicit shortlist/decision state.
- QuerySession remains conversation memory with explicit/inferred/model origin.
- decision_analytics remains action telemetry and is not reused for catalog
  metrics.
- Question Registry owns shared instructions, criteria, definition version and
  input/output schema; jevcal, jev-align, jevQL and jev-tree keep their own
  technical configurations.
- common analytics reads materialized metrics first; jevQL is only an
  embedded-first optional semantic predicate for registered non-materialized
  questions.
- entity resolution uses exact/alias/context narrowing first; jev-tree is
  eligible only for a genuinely large unresolved candidate set, never for
ordinary comparisons of twenty programs.

### Source-backed knowledge and policy boundary

The runtime implements logical `knowledge` and `policy` modules inside the
same backend and PostgreSQL deployment. Together they provide versioned
source registry and observations, immutable snapshots through the existing
ingestion seam, source-backed claim/change candidates, exact revision approval
ledger, review queue/actions/preview, semantic diff, impact projection,
approved-only deterministic resolution with `ResolutionTrace`, and typed
assistant policy queries. Source acquisition remains an allowlisted one-shot
poller; it is not an open web crawler. These capabilities do not imply broad
source coverage or a populated production review rota. See the [Knowledge and
Policy architecture](architecture/knowledge-policy.md) and its [operations
runbook](operations/knowledge-policy-runbook.md).

Existing `ingestion` owns raw capture/snapshots, and subject modules retain
their canonical facts and calculations. In particular, `admission_benefits`
remains the only BVI, 100-point, confirmation, validity, and
individual-achievement evaluator. `policy` selects an approved exact domain
revision and explains the deterministic resolution; it does not calculate
benefit eligibility. Jev suggestion operations for knowledge/policy remain
unregistered and disabled. Source discovery cannot change canonical policy.

No module under modules/domain, modules/contracts or modules/services imports a
Jev SDK or an isolated runtime client. Infrastructure adapters depend inward on
typed ports, and AndromedaContainer is the only composition authority.

```text
backend/src/andromeda/
├── modules/{universities,programs,curricula,disciplines,comparison}/
├── modules/{semantic,analytics,entity_resolution,conversation,presentation}/
├── modules/{knowledge,policy}/
├── modules/decision/{domain,contracts,services,repository}/
├── modules/proftest/{domain,contracts,services,repository}/
├── modules/recommendations/{domain,contracts,services,repository}/
├── modules/admissions/{domain,contracts,services,repository}/
├── modules/admission_fit/{domain,contracts,services,repository}/
├── modules/events/{domain,contracts,services,repository}/
├── modules/campus/{domain,contracts,services,repository}/
├── modules/personal_route/{domain,contracts,services,repository}/
├── modules/admin_ops/{domain,contracts,services,repository}/
├── modules/university_admin/{domain,contracts,services,repository}/
├── ingestion/universities/bmstu/
├── infrastructure/{database,repositories,config,logging}/
├── api/{routes,schemas,dependencies}/
└── composition/
```

Предметные модули публикуют `contracts.public` и Protocol-порты. Cross-module imports разрешены только через `modules/<module>/contracts/public.py` и typed `modules/<module>/repository/ports.py`; concrete domain/services/repository internals остаются закрытыми. `comparison` получает программы, curricula и disciplines через reader-контракты. SQLAlchemy-модели и `Session` остаются внутри infrastructure.

`proftest` использует те же публичные reader-контракты через собственный typed catalog port; его domain/services не знают об ORM, HTTP schemas или BMSTU parser. `ProgramFingerprint` и `UserProfile` остаются application contracts, а API routes только связывают их с HTTP.

### Canonical composition root

`andromeda.composition.container.AndromedaContainer` — единственный активный
composition graph для API и generic ingestion runner. `create_app()` создаёт
один `Engine`, передаёт его вместе с теми же `Settings` в `build_container()`
и сохраняет root в `app.state.container`; API dependency providers только
делегируют ему создание readers, repositories и application services.
`app.state.engine` остаётся совместимым alias того же объекта для outer-layer
health/session boundaries, а не вторым engine. Subject modules не импортируют
composition root. Новые runtime entrypoints должны получать этот root, а не
собирать параллельный service graph или читать environment defaults повторно.

`recommendations` получает только публичные `UserProfile` и `ProgramFingerprint`, а для каталога использует `RecommendationCatalogReader`. Его scoring policy фиксирует Content Fit как сумму subject, activity и distinctive fit с отдельным anti-interest penalty. Отдельный `RecommendationEvidence` envelope переносит profile confidence, catalog completeness, source snapshot identity, reliability, signal usage, inferred activity mapping и typed source gaps; он не меняет ranking. `Career Fit`, `Admission Fit` и `Workload readiness` typed как `not_available` и не меняют score. Старые proftest matching/ranking/explanation paths остаются compatibility facades.

`admission_fit` — отдельный application/domain-модуль для оценки одного явно выбранного admission offering. Он публикует `ApplicantAdmissionProfile`, `AdmissionFitRequest` и `AdmissionFitResult`, а свой `AdmissionFitDataReader` получает snapshot через публичные `ProgramReader` и `AdmissionReader`. Внутри модуля нет SQLAlchemy, FastAPI, parser или recommendation imports:

```text
ProgramReader + AdmissionReader public contracts
  → AdmissionFitDataReader infrastructure adapter
  → AdmissionFitService
  → deterministic AdmissionFitScoringService
  → reasons / antiReasons / dataGaps + score/status
  → POST /programs/{id}/admission-fit
```

`Admission Fit` оценивает только реалистичность поступления по опубликованным admissions facts. Он не принимает `UserProfile`, `ProgramFingerprint` или Content Fit score и не вызывается из `RecommendationService`; поэтому его результат не меняет ranking рекомендаций.

`admissions` публикует `ProgramAdmissions`, offering и child contracts через `AdmissionReader`. Его service получает программу через `ProgramReader`, а не через ORM. Admission Fit в этот модуль не входит: slice только показывает source-backed факты поступления и сохраняет их provenance. Новые университеты подключают собственный ingestion adapter, не меняя этот application path.

`events` публикует event/venue contracts и фильтры для списков, карточек и recommendation-aware reads. `campus` публикует point contracts, point details, events-at-point и recommendation results; он не владеет картой и не вычисляет маршруты. Оба модуля используют canonical `UniversityId`, `DepartmentId`, `ProgramId` и `VenueId`, поэтому карта может запрашивать данные без дублирования university/program сущностей.

`personal_route` — совместимый read-only support slice для текущего пользователя,
а не часть DecisionService и не владелец shortlist. Его public contracts
описывают необязательные explainable suggestions, а Protocol-порты читают
существующие recommendation/event/campus contracts. Composition wiring собирает
`PersonalRouteService`; модуль не имеет ORM, миграций, ingestion, HTTP или map
dependency. Он не хранит собственную сущность выбора и не вызывается из
candidate pipeline. `attend_event` может быть online и тогда не содержит
venue/point; физическая близость, граф связей, directions и оптимизация
маршрута намеренно остаются за будущим независимым map-модулем. Просмотр
personal route/events не мутирует `DecisionContext`; программа добавляется в
shortlist только отдельной explicit-командой из UI.

Старые пути `proftest.services.ranking`, `proftest.services.matching` и `proftest.services.explanations` сохранены как точечные compatibility facades. Они не являются разрешением импортировать recommendation internals в новый runtime-код и перечислены в architecture test как единственные переходные aliases.

Исполняемый BMSTU runner теперь принадлежит `backend/scripts/run_andromeda_bmstu.py`,
а полный fixture/live demo — `backend/scripts/run_andromeda_demo.py`. Старые
`run_tracer_bullet.py` и `run_tracer_demo.py` оставлены на один migration cycle
как thin wrappers с parity tests; новые docs/CI/runtime paths не должны их
импортировать. `RawTracerBundle`, parser module `parser/tracer.py` и
`tests/fixtures/tracer/raw` — намеренно сохранённые raw-contract/fixture
идентификаторы, а не отдельный runtime.

BMSTU URL, catalog pagination, detail/API shape, public study-plan resolver, PDF parser, mappings и browser fallback находятся в BMSTU adapter. Live ingestion начинает с официального catalog API, обнаруживает все detail slugs/profiles и связывает curriculum/admissions по сохранённому source code и study-plan URL; ручной список программ не является production input. Добавление нового вуза должно создавать новый adapter без зависимости comparison от структуры сайта.

## Storage boundary

`ANDROMEDA_DATABASE_URL` — единый target для FastAPI, Alembic и generic ingestion runner; `BMSTU_DATABASE_URL` временно поддерживается как deprecated fallback. `SqlAlchemy*Repository` и `SqlAlchemyIngestionRepository` — infrastructure adapters; модули видят только public contracts и repository ports. Поэтому PostgreSQL не меняет comparison/proftest/recommendations и не требует переписывать их scoring или fingerprint logic.

University registry выполняет единый orchestration flow:

```text
UniversityAdapter registry
  → capture(mode=fixture|live)
  → parse(raw DTOs)
  → normalize + deterministic taxonomy
  → provenance/identity/sanity validation
  → atomic canonical persistence
```

University-owned identities namespaced: `university:bmstu`, `university:hse`, `direction:{university}:{code}`, `program:{university}:{local-code}`, `curriculum:{university}:{program-local-code}-{year}`. Local code остаётся отдельным полем. Discipline остаётся global canonical concept по нормализованному названию, потому что это намеренная cross-university vocabulary boundary.

`user_profiles` хранит только сериализованный public `UserProfile` и nullable future `account_id`; raw session token, answers и ORM objects не являются публичными контрактами. LocalStorage во frontend используется только для незавершённого draft. Completed profile восстанавливается через API и cookie.

`decision_contexts` хранит один owner-bound `DecisionState` на логический выбор:
constraints, considered IDs, shortlist entries/roles/states, exclusions,
revision и timestamps. Он связан с тем же anonymous/account scope, но не
дублирует `UserProfile` или recommendation ranking. `decision_analytics_events`
хранит только bounded allow-listed events с owner hash/account binding,
idempotency key и TTL; analytics не используется как источник domain state.

`proftest_answer_sessions` хранит versioned answer state в server-side JSON вместе с
cursor, revision, status, owner key и expiry. `proftest_analytics_events`
хранит только allow-listed bounded telemetry с уникальным event ID и
retention. Anonymous owner представлен SHA-256 hash HttpOnly profile cookie;
account owner — canonical account ID. Partial unique index не допускает две
активные draft-сессии для одного owner, а completion обновляет session и
`user_profiles` в одной транзакции. Browser localStorage — лишь ускоренный
кэш draft и не источник истины.

`ANDROMEDA_ENV=development` и `ANDROMEDA_ENV=staging` fail fast с non-PostgreSQL URL. `ANDROMEDA_ENV=test` сохраняет SQLite для быстрых тестов. Raw source snapshots остаются immutable provenance, а canonical domain projection обновляется атомарной ingestion sync-транзакцией.

## Identity дисциплин

Исходное `source_name` сохраняется на каждой позиции. Canonical normalization ограничивается Unicode, casefold и пробелами. Fuzzy-сопоставление и автоматическое объединение неоднозначных названий не используются.

## Таксономия дисциплин Andromeda

Каждая дисциплина получает не единственный ярлык, а нормализованный вектор `area_weights`: веса по 22 верхнеуровневым областям Andromeda. Веса строго положительны, не дублируют область и в сумме дают `1.0000`. Поэтому междисциплинарные предметы не теряют вторичную область: например, машинное обучение хранится как компьютерные науки + математика.

Для BMSTU явные сопоставления находятся в `ingestion/universities/bmstu/mappings/discipline_areas.py`. Это часть university-specific ingestion adapter, а не core comparison. На входе сохраняется исходное название, затем adapter применяет точное сопоставление по нормализованному имени; прозрачные keyword rules остаются автоматическим сигналом, а unresolved outcome не маскируется под reviewed Universal. Каждый canonical snapshot carries typed classification outcomes с rule ID и taxonomy version; quality metadata сохраняет воспроизводимые coverage/unknown metrics, source hashes и affected programs. Исторический live-аудит на 2 582 дисциплины не считается доказательством текущего состояния и не используется как claim.

Распределение содержания программы считается в `comparison` по часам позиций учебного плана (при отсутствии часов используется ЗЕТ). Вектор предмета умножается на долю его нагрузки, после чего веса агрегируются по программе и выбранному семестру. Один предмет может влиять на несколько профилей, но исходная дисциплина и её workload остаются отдельной строкой сравнения.

## See Also

- [Knowledge and Policy architecture](architecture/knowledge-policy.md) — source discovery, immutable review and approved-only deterministic policy boundary.
- [Knowledge and policy operations](operations/knowledge-policy-runbook.md) — source polling, review, security and recovery limits.
- [API](api.md) — HTTP-контракты для frontend.
- [Конфигурация](configuration.md) — database и logging settings.
- [PostgreSQL](postgresql.md) — запуск storage targets и migrations.
- [Тестирование](testing.md) — архитектурные и интеграционные gates.
