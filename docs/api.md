[← Архитектура](architecture.md) · [Back to README](../README.md) · [Admissions →](admissions.md)

# API

FastAPI-приложение `andromeda.api.main` обслуживает один backend. `/docs`, `/redoc` и runtime `/openapi.json` описывают полную поверхность FastAPI, включая operator/admin operations. Для внешних пользовательских клиентов каноническим является корневой файл [`openapi.json`](../openapi.json): это Public API v1, обслуживаемый теми же handlers по `/api/v1/...`. Старые unversioned public routes сохранены для совместимости.

`frontend-next/openapi.json` — generated full-app snapshot, нужный существующей Web админке и её внутренним типам. Это не альтернативная спецификация Public API. Из Public API генерируются `frontend-next/src/lib/public-api.generated.ts` и узкий `public-api-client.ts`; внутренний Web adapter отдельно использует `generated.ts`.

## Public API v1

MAX Bot, MAX Mini App, Web и другие transport-клиенты обращаются только к `/api/v1`. Они не вызывают `/ops/*`, `/university-admin/*` или knowledge-review API. Версионированные операции — aliases существующих endpoint handlers: backend, application services, repository и domain logic остаются общими.

| Группа | Public API v1 operations |
|---|---|
| Health | `GET /api/v1/health/live` |
| Вузы и каталог | `GET /api/v1/universities`; `GET /api/v1/universities/{university_id}/catalog`; `GET /api/v1/universities/{university_id}/events`; `GET /api/v1/universities/{university_id}/events/{event_id}` |
| Программы и поступление | `GET /api/v1/programs`; `GET /api/v1/programs/{id}`; `GET /api/v1/programs/{id}/curriculum`; `GET /api/v1/programs/{id}/admissions`; `POST /api/v1/programs/{id}/admission-fit`; `GET /api/v1/programs/{program_id}/admission-benefits`; `POST /api/v1/programs/{program_id}/admission-eligibility`; `GET /api/v1/universities/{university_id}/admission-benefits`; `GET /api/v1/admission-benefits/olympiads/{olympiad_id}/programs` |
| Сравнение и аналитика | `GET /api/v1/compare`; `GET /api/v1/compare/summary`; `POST /api/v1/analytics/query`; `POST /api/v1/assistant/query` |
| DecisionContext | `GET /api/v1/decision/context`; `GET /api/v1/decision/suggestions`; `POST /api/v1/decision/analytics`; `POST /api/v1/decision/considered`; `PUT /api/v1/decision/constraints`; `POST /api/v1/decision/refinement/answer`; `POST /api/v1/decision/shortlist`; `PATCH`/`DELETE /api/v1/decision/shortlist/{program_id}`; `POST`/`DELETE /api/v1/decision/final-choice`; `POST`/`DELETE /api/v1/decision/programs/{program_id}/exclude`; `POST /api/v1/decision/programs/{program_id}/restore`; `POST /api/v1/decision/suggestions/{program_id}/accept`; `POST /api/v1/decision/suggestions/{program_id}/reject` |
| Профиль и рекомендации | `POST /api/v1/proftest/sessions`; `GET`/`PATCH /api/v1/proftest/sessions/current`; `POST /api/v1/proftest/sessions/current/next`; `POST /api/v1/proftest/sessions/current/complete`; `POST /api/v1/proftest/analytics`; `GET`/`POST`/`PUT /api/v1/proftest/profile`; `POST /api/v1/recommendations`; `GET /api/v1/recommendations/current` |
| Events, campus and taxonomy | `GET /api/v1/events`; `GET /api/v1/events/{id}`; `GET /api/v1/campus/points`; `GET /api/v1/campus/points/{id}`; `GET /api/v1/campus/points/{id}/events`; `GET /api/v1/campus/recommendations`; `GET /api/v1/discipline-areas`; `GET /api/v1/personal-route` |
| Account | `POST /api/v1/auth/register`; `POST /api/v1/auth/login`; `POST /api/v1/auth/logout`; `GET /api/v1/auth/session`; `POST /api/v1/auth/decision/import-guest` |

Итого в Public API v1 опубликовано 58 method/path operations. Не входят три
deprecated assessment compatibility handlers: GET /proftest/questions,
POST /proftest/preview и POST /proftest/results. Они остаются в полном
unversioned FastAPI API для старых клиентов; новые клиенты используют
version-pinned /proftest/sessions и /proftest/profile. Ops, review и
university-admin handlers также остаются только в полной внутренней схеме.

**Authentication and sessions.** Public API preserves the current HttpOnly cookie boundary. The optional guest profile cookie defaults to `andromeda_profile_session`; the optional account cookie defaults to `andromeda_auth_session`. Deployments can configure their names with `ANDROMEDA_PROFILE_COOKIE_NAME` and `ANDROMEDA_AUTH_COOKIE_NAME`. Missing guest cookies can be issued by the backend; browser clients must use credentialed requests (`credentials: include`). The OpenAPI marks optional cookies as optional; `POST /api/v1/auth/decision/import-guest` requires an account cookie. Future platform adapters use the same Andromeda session cookies; external platform user IDs are not Andromeda identity tokens.

`/assistant/query` keeps its owner-bound `QuerySession`, TTL, `session_id`/`revision` response fields and `sessionId`/`expectedRevision` request fields. The response field casing is the existing backend contract. The public request schema omits the legacy `interactive` flag because no current behavior consumes it; the old unversioned route keeps accepting its legacy DTO. `DecisionContext` and other revisioned mutations retain `expectedRevision`; stale revisions return HTTP `409` with `ErrorResponse`.

Errors use the existing `ErrorResponse` envelope for `400`, `401`, `403`, `404`, `409`, `422`, `429` and `500`. Rate-limited responses include `Retry-After` in seconds. `GET /universities` and `GET /programs` are currently unpaginated item collections. `GET /health/live` is a process liveness check; readiness/database detail is operational and excluded from Public API v1.

### Generate and verify OpenAPI and clients

After a backend contract change, refresh both checked-in snapshots and generated types:

```powershell
python backend/scripts/export_openapi.py --surface public-v1 --out openapi.json
python backend/scripts/export_openapi.py --surface full --out frontend-next/openapi.json
cd frontend-next
npm run generate-public-api
npm run generate-api
npm run check-public-api-drift
npm run check-api-drift
cd ..
python scripts/andromeda.py openapi
```

`openapi-typescript` generates both wire-type files; `openapi-fetch` powers the Public API client. Keep presentation/view models in the UI adapter, not as handwritten copies of public wire DTOs. `python scripts/andromeda.py openapi` exports fresh backend contracts to temporary files and checks both canonical snapshots and both generated clients. CI runs the same comparisons. FastAPI `/docs` remains the full application docs.

### DATA-API validation

[`DATA-API.yaml`](../DATA-API.yaml) points to the canonical public `openapi.json`. Its base URL is a reserved `.example` placeholder until an organizer-accessible HTTPS deployment URL is configured; validator PASS checks schema, deterministic check definitions and OpenAPI operation mapping, not live endpoint availability. Run the pinned official validator with:

```powershell
python scripts/andromeda.py data-api
```

The direct upstream validator invocation and its pinned GitVerse revision are documented in [testing](testing.md#public-api-openapi-and-data-api). Do not add credentials or cookies to the public check file.

## Программы

| Метод | Endpoint | Назначение |
|---|---|---|
| GET | `/programs` | Source-backed каталог программ для независимого выбора и shortlist |
| GET | `/programs/{id}` | Карточка программы |
| GET | `/programs/{id}/curriculum` | Позиции учебного плана |
| GET | `/programs/{id}/admissions` | Source-backed данные поступления |

`GET /programs/{id}/admissions` возвращает strict `ProgramAdmissionsResponse`: каноническую программу и offering-записи по годам, форме и типу финансирования. В offering доступны места, ЕГЭ и минимумы, проходные баллы, квоты и стоимость обучения — только если они опубликованы в доступном источнике. Каждая запись и дочерний показатель содержит provenance с URL, временем capture и хэшем источника. Поля без источника остаются пустыми; значения `0` не используются как замена неизвестности.

`DisciplineResponse` сохраняет `name`/`sourceName` и дополнительно отдаёт `areaWeights` — вектор областей с весами — и `primaryArea`. Каталог областей доступен через `GET /discipline-areas`; он содержит 22 стабильных кода, название, описание и позицию для сортировки.

## Универсальная аналитика и assistant query

| Метод | Endpoint | Назначение |
|---|---|---|
| POST | `/analytics/query` | Выполняет strict typed `QuerySpec` по materialized program projections без NLP и raw SQL |
| POST | `/assistant/query` | Принимает bounded текст, продолжает owner-bound `QuerySession` и возвращает clarification либо `ResponseEnvelope` |

`/analytics/query` принимает allow-listed `entity`, `metrics`, `scope`,
`filters`, `groupBy`, `aggregation`, `sort` и bounded `limit` (`1..100`).
Unsupported metric/aggregation, неоднозначная сущность, неканонический ID и
неподдержанный scope получают typed validation/contract error. Результат
содержит population, included/missing counts, coverage, confidence, basis,
metric explanations, provenance, source gaps и semantic/classifier versions.

`/assistant/query` не использует `DecisionContext` как память диалога:
assistant state хранится в owner-bound `query_sessions` с TTL и optimistic
revision. Explicit user facts, deterministic inference, profile projection и
policy defaults разделены в typed frame. Если данных недостаточно, endpoint
возвращает минимальный следующий вопрос; если их достаточно — компилирует
typed analytics/admission operation. Jev не обязателен: deterministic policy
остаётся рабочим fallback.

Registered source-backed policy questions also use `/assistant/query` and the
same `QuerySession`. Their `ResponseEnvelope.knowledge` section carries source
assertion status, reliability/lifecycle, effective-time and scope details,
uncertainty, evidence locators, semantic diff/trace and actionability. The
resolver reads only exact human-approved revisions. Missing source coverage,
cycle, scope or unresolved conflict stays typed unavailable/unknown. For an
applicant-specific admission-benefit impact check, the request may include
`applicant_admission_context`: typed facts plus the dimensions the applicant
confirmed complete. The owner-bound query session retains it only for its TTL.
The assistant forwards only exact approved benefit references; the benefit
owner verifies that the selected hashes cover the complete active rule set and
source coverage before calling the existing `AdmissionDecisionService`.
Missing/ambiguous program, incomplete owner coverage or unconfirmed applicant
facts produce typed missing-data codes; they never imply ineligibility. Mixed
domain owners and non-benefit owner calculations remain unavailable until their
own evaluator bridges are wired. Policy Jev operations are not registered. The
optional presentation port can reorder an allowlisted set of typed response
sections; no freeform LLM provider is wired, and the default response is
deterministic. Unsupported topics use an explicitly unverified
`outside_coverage` mode and do not enter canonical data. See the
[knowledge-policy runbook](operations/knowledge-policy-runbook.md).
The policy assistant rollout is independently controlled by
`ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED` and defaults to `false`; when
disabled, `/assistant/query` returns typed `outside_coverage` without reading
claims or resolving policies. This flag does not alter Jev settings.

При изменении assistant wire contract обновите оба OpenAPI snapshot и generated clients по инструкции в разделе [Generate and verify OpenAPI and clients](#generate-and-verify-openapi-and-clients), затем запустите `python scripts/andromeda.py openapi`.

## University admin, public catalog and editorial events

University console работает только в рамках account session и активной
membership. `GET /university-admin/memberships` возвращает доступные scopes;
роль `owner` управляет участниками, `owner/editor` меняют контент, `viewer`
читает его без mutation controls. Первого владельца добавляет только
ops-key-protected `POST /ops/university-admin/members`; email-домен не даёт
доступа автоматически.

| Метод | Endpoint | Назначение |
|---|---|---|
| GET | `/universities` | Безопасный список поддерживаемых вузов для public selector |
| GET | `/universities/{university_id}/catalog` | Published units/categories и видимые program/discipline overlays |
| GET/POST/PATCH/DELETE | `/university-admin/universities/{university_id}/units` | Faculty/department hierarchy с archive и revision |
| GET/POST/PATCH/DELETE | `/university-admin/universities/{university_id}/categories` | Editorial categories с archive и revision |
| PUT | `/university-admin/universities/{university_id}/catalog-links` | Связи unit/category с каноническими program/discipline IDs |
| PATCH | `/university-admin/universities/{university_id}/programs|disciplines/{id}` | Public name/summary/visibility overlay |
| GET/POST/PATCH/DELETE | `/university-admin/universities/{university_id}/events` | Draft/list/update/archive editorial events |
| POST/PUT | `/university-admin/universities/{university_id}/events/{id}/publish|agenda` | Публикация и замена упорядоченного плана |
| GET | `/universities/{university_id}/events[/{event_id}]` | Public published event feed/detail |

Editorial events хранятся отдельно от source `/events`. Они поддерживают
`kind=open_day` наряду с lecture/career/competition/other, описание,
регистрацию, venue/location, agenda и связи с факультетами, кафедрами,
программами и категориями. `all_university` означает весь вуз,
`selected_units/programs` ограничивает аудиторию, а `unaffiliated` означает
явное отсутствие факультетской/программной связи. Draft и archived не попадают
в public feed; stale selected targets скрываются, если больше не активны.
Все enum/datetime payloads проходят strict JSON boundary, а mutation требуют
`expectedRevision`; недостаточная роль даёт 403, неизвестный scope — 404.

### Manual knowledge submissions

Knowledge ops writes проходятся только через авторизованные application
commands. `POST /ops/knowledge/sources` доступен только явно настроенному
source steward; новая registry revision всегда создаётся с `enabled=false`.
`POST /ops/knowledge/sources/{source_id}/snapshots` принимает ограниченный PDF
или UTF-8 text upload, сверяет URL с allowlist и записывает immutable snapshot;
endpoint не скачивает переданный URL.

`POST /university-admin/universities/{university_id}/knowledge/claims` создаёт
source-backed claim в `needs_review`. `PUT
/university-admin/universities/{university_id}/knowledge/claims/{claim_id}/metadata`
добавляет metadata revision только для точного ожидаемого revision/hash и только
для ещё не разрешённого manual candidate в этом university scope; assertion и
evidence остаются неизменными. `POST
/university-admin/universities/{university_id}/knowledge/policy-rules` принимает
только policy revision с точным university scope и пишет начальное pending
событие через owner `PolicyApprovalCommandService`. University editor не может
одобрить или активировать эту revision. Все кандидаты остаются вне
`Effective Rule Resolver` до отдельного approval exact revision.

### Knowledge review queue

`GET /ops/knowledge/review-queue?limit=50` показывает ограниченную очередь
последних unresolved claim, change-event и policy revisions; `limit` ограничен
`1..100`. `POST /ops/knowledge/review-actions` записывает действие по exact
revision/hash с обязательной причиной и idempotency key. Для policy revision
сначала вызовите `POST /ops/knowledge/review-preview` с точной целью и явным
university/admission-year/valid-as-of контекстом. Endpoint возвращает approved
current trace, pending-candidate hypothetical trace, effective-policy diff,
domain-owner impact и evidence; состояние canonical policy не меняется.
Reviewer account IDs
задаются через `ANDROMEDA_KNOWLEDGE_REVIEWER_ACCOUNT_IDS`, policy-steward IDs —
отдельно через `ANDROMEDA_POLICY_STEWARD_ACCOUNT_IDS`; обе настройки пусты по
умолчанию. Actor берётся из текущей authenticated session, а не из request body.

Очередь показывает snapshot/evidence locator, надёжность источника, lifecycle,
scope, diff, conflict participants и неизменяемую историю. Эти оси не
объединяются в один статус. Подтверждение claim фиксирует source assertion,
но не активирует policy. Policy approve требует exact preview fingerprint,
повторно вычисленный сервером, resolved candidate trace, полный domain-owner
impact, evidence и отсутствие unresolved/truncated conflicts. Fingerprint
сохраняется в существующем policy approval event; отсутствие/неполный preview
блокирует approve и не трактуется как нулевое влияние. Claim edit создаёт новую
pending revision; identity resolution принимает только существующий exact ID
из поддержанного typed catalog и не может быть подменён общим edit. Внутренний
SPA экран открывается query route `/?view=knowledge-review` и не добавлен в
обычную навигацию.

Conflict participants в queue — read-only diagnostic metadata. В текущем
rollout нет API для создания persisted conflict groups или для их human
resolution; список участников не означает, что discovery уже записал все
противоречия. Resolver и assistant возвращают fail-closed uncertainty при
обнаруженном конфликте. Не используйте отсутствие conflict row как
подтверждение отсутствия разногласий.

## DecisionContext и shortlist

`DecisionContext` — owner-bound application state для пользовательского выбора.
Он сохраняется по anonymous HttpOnly session или authenticated account scope и
восстанавливается после reload. В нём хранятся только explicit данные:
admission constraints, рассмотренные canonical `programId`, shortlist entries с
ролями `primary`/`alternative`, explicit exclusions, revision и timestamps.
`UserProfile` остаётся владельцем предпочтений; в ответе DecisionContext это
read-only projection, а не копия profile JSON.

| Метод | Endpoint | Request | Ответ и side effect |
|---|---|---|---|
| GET | `/decision/context` | — | Текущий context, profile projection, `missingData` и metadata; read-only, при первом обращении создаётся owner-bound context. |
| GET | `/decision/suggestions` | — | Derived candidate set: до 3 primary и 2 alternative, active shortlist, ineligible/insufficient-data, reasons, Admission Fit, Content Fit, typed `constraintOutcomes`, trade-offs/source gaps и optional refinement question; shortlist не меняется. |
| POST | `/decision/refinement/answer` | `{questionId, optionId, expectedRevision}` | Проверяет текущий вопрос и revision, уточняет только derived profile/suggestions и возвращает новый профиль и candidate set; shortlist не меняется. |
| PUT | `/decision/constraints` | `{constraints, expectedRevision?}`; `constraints: null` — явная очистка | Сохраняет явно введённые admissions constraints и возвращает новую revision; не удаляет и не демотирует shortlist. |
| POST | `/decision/considered` | `{programId, expectedRevision?}` | Отмечает одну программу как рассмотренную после явного действия пользователя. |
| POST | `/decision/shortlist` | `{programId, role, expectedRevision?}` | Явно добавляет программу или восстанавливает её active state с ролью `primary`/`alternative`. |
| PATCH | `/decision/shortlist/{programId}` | `{role, expectedRevision?}` | Явно меняет роль active shortlist entry. |
| DELETE | `/decision/shortlist/{programId}` | `{expectedRevision?}` | Явно переводит сохранённую программу в removed state; запись не теряется. |
| POST | `/decision/programs/{programId}/restore` | `{expectedRevision?}` | Явно восстанавливает ранее removed shortlist entry. |
| POST | `/decision/programs/{programId}/exclude` | `{expectedRevision?}` | Явно исключает программу из system suggestions; это не удаляет другие сохранённые варианты. |
| DELETE | `/decision/programs/{programId}/exclude` | `{expectedRevision?}` | Возвращает программу в область system suggestions. |
| POST | `/decision/suggestions/{programId}/accept` | `{role?, expectedRevision?}` | Принимает конкретное system suggestion и добавляет его только по explicit команде. |
| POST | `/decision/suggestions/{programId}/reject` | `{expectedRevision?}` | Отклоняет конкретное system suggestion явно; сохранённые shortlist entries не меняются. |
| POST | `/decision/analytics` | allow-listed `eventId`, `eventType`, bounded payload | Принимает только view/interaction events; mutation facts генерирует сервер. Сбой analytics не меняет результат пользовательской команды. |

Все mutation responses содержат `decisionId`, `context` и `changed`. Если
`expectedRevision` устарел, API возвращает `409 CONFLICT`; это предотвращает
last-write-wins между вкладками. Unknown fields, non-canonical IDs и oversized
payloads получают `422`. Recalculation после ввода баллов может показать
`borderline` или `unlikely`, но не удаляет saved program автоматически.

Candidate pipeline внутри Decision Service разделяет факторы, а не собирает
магический общий score:

```text
hard constraints → batch Admission Fit → preference/Content Fit
→ separate risk, differences, missing data → small suggestions
```

Batch Admission Fit используется для candidate set внутри
`DecisionCandidatePipeline`; отдельный public endpoint одного варианта
`POST /programs/{id}/admission-fit` остаётся без изменений.

`constraintOutcomes` содержит отдельное typed-состояние для каждого явно
введённого условия: `applied` с `satisfied=true/false`, `not_applicable` или
`insufficient_data` с `sourceGaps`. Год, форма и финансирование сопоставляются
с тем же offering, который используется Admission Fit; максимальная стоимость
сравнивается только с опубликованной суммой в поддержанной валюте, а location —
только с canonical city университета. Неизвестный факт не считается совпадением
и не удаляет explicit shortlist.

## Сравнение

```text
GET /compare?programIds=<program-id-a>,<program-id-b>
GET /compare?programIds=<program-id-a>,<program-id-b>&scope=semester&semester=1
```

`ComparisonResponse` содержит `programA`, `programB`, `scope`, `rows`, `totalsA`, `totalsB` и `areaBreakdownA`/`areaBreakdownB`. Последние показывают агрегированный вектор содержания программы в выбранной области и режиме. Строка хранит `a`, `b`, статус и `hoursDelta`/`creditsDelta`; у дисциплин сохраняются исходные названия, семестры, формы контроля и area weights. Категории учебного плана не являются частью canonical contract.

Для финального shortlist доступен additive summary endpoint:

```text
GET /compare/summary?programIds=<program-id-a>,<program-id-b>
GET /compare/summary?programIds=<program-id-a>,<program-id-b>,<program-id-c>&scope=semester&semester=1
```

Он принимает 2–3 distinct canonical IDs и возвращает `programs`,
`keyDifferences`, `tradeoffs`, `admissionContext`, `contentDifferences`,
`sourceGaps` и typed `evidence`. В summary нет winner и искусственного общего
score: выводы разделяют trade-offs и ссылаются на raw area/totals/discipline
evidence. Legacy `/compare` с двумя программами остаётся полным drill-down
контрактом.

Доли и веса передаются как decimal-строки (`"0.4589"`), чтобы frontend не терял точность JSON number. Frontend types генерируются из OpenAPI, поэтому изменение этих полей проходит через drift gate.

Статусы:

- `both` — одинаковые дисциплина и workload;
- `different` — дисциплина есть в обеих программах, workload различается;
- `only_a` / `only_b` — позиция есть только с одной стороны.

## Ошибки

Ответ ошибки имеет strict-поля `code`, `message`, `details`. Основные коды: `VALIDATION_ERROR`, `UNAUTHORIZED`, `NOT_FOUND`, `CONFLICT`, `CONTRACT_ERROR`, `SOURCE_CONTRACT_ERROR`, `INTERNAL_ERROR`.

## Аутентификация и аккаунт

| Метод | Endpoint | Назначение |
|---|---|---|
| POST | `/auth/register` | Создаёт аккаунт, persistent server-side session и при наличии переносит текущий anonymous profile |
| POST | `/auth/login` | Проверяет credentials, создаёт новую session и восстанавливает account profile |
| POST | `/auth/logout` | Отзывает текущую session и очищает auth cookie |
| GET | `/auth/session` | Возвращает безопасное authenticated/unauthenticated состояние и public account |

`email` нормализуется к lowercase, пароль при регистрации должен содержать не менее 12 символов. Login использует одинаковую generic ошибку `Invalid email or password` для неизвестного email и неверного пароля. Raw password не хранится: backend использует Argon2id через `argon2-cffi`. Raw session token существует только в `HttpOnly` cookie; в `auth_sessions` хранится только его SHA-256 hash с expiry/revocation.

Auth cookie не читается frontend JavaScript и имеет `Path=/`, `HttpOnly`, `Max-Age`, `Secure` и настроенный `SameSite`. Для credentialed state-changing auth requests при наличии `Origin` API принимает только configured frontend origins.

## Профиль содержания

| Метод | Endpoint | Назначение |
|---|---|---|
| GET | `/proftest/questions` | **Deprecated compatibility**: versioned bank scenario-based вопросов без внутренних весов |
| POST | `/proftest/preview` | **Deprecated compatibility**: строит `UserProfile`, первичный ranking и adaptive selection |
| POST | `/proftest/results` | **Deprecated compatibility**: строит финальный профиль и TOP рекомендаций с fit/anti-fit evidence |
| GET | `/proftest/profile` | Читает current completed profile по account scope или anonymous session |
| POST | `/proftest/profile` | Создаёт current profile; повторное создание возвращает `409 CONFLICT` |
| PUT | `/proftest/profile` | Обновляет профиль по optimistic `expectedRevision` |

Эти compatibility POST endpoints принимают strict `answers` и optional `adaptiveAnswers`; они делегируют единственным `UserProfileBuilder` и `RecommendationService` и не являются вторым scoring path. Новые clients должны использовать session flow ниже. `UserProfile` строится до matching, а response содержит integer `contentFit`, breakdown компонентов, реальные workload/share и исходные названия отличительных дисциплин. Каждая рекомендация также содержит typed `evidence`: confidence профиля, completeness каталога, deterministic source-snapshot freshness, reliability, использованные/выведенные сигналы, версии policy/taxonomy и field-level missing data. `reliability` — это полнота и согласованность evidence, а не вероятность поступления или predictive accuracy. В этих Content Fit responses optional metrics (`workloadReadiness`, `careerFit`, `admissionFit`) возвращаются с `status: "not_available"` и не влияют на scoring. Отдельный endpoint Admission Fit описан ниже и также не меняет этот ranking.

При изменении profile/session wire contract обновите оба OpenAPI snapshot и generated clients по инструкции в разделе [Generate and verify OpenAPI and clients](#generate-and-verify-openapi-and-clients), затем запустите `python scripts/andromeda.py openapi`.

## Адаптивная сессия профтеста v3

Новый TestShell использует version-pinned session API и не отправляет legacy
`adaptiveAnswer`. Сессия принадлежит authenticated account либо anonymous
HttpOnly profile scope; frontend никогда не передаёт owner ID и хранит в
`localStorage` только незавершённый draft для быстрого восстановления UI.
Новые сессии используют immutable `proftest-v3`; уже сохранённые draft-сессии
с `proftest-v2` дочитываются своим вопросником и не переинтерпретируются.

| Метод | Endpoint | Request | Response/поведение |
|---|---|---|---|
| POST | `/proftest/sessions` | пустой JSON | Создаёт или возобновляет единственный draft владельца; новая сессия возвращает первый вопрос и `questionSetVersion=proftest-v3`. |
| GET | `/proftest/sessions/current` | — | Возвращает текущий draft или completed session с результатами; `404` означает, что у владельца нет сессии. |
| POST | `/proftest/sessions/current/next` | `questionId`, `optionIds`, `status`, optional `intensity`/`dimension`, `expectedRevision` | Валидирует вопрос pinned branch, сохраняет ответ, увеличивает revision и возвращает следующий вопрос либо честный adaptive stop. |
| PATCH | `/proftest/sessions/current` | `answers[]`, `expectedRevision` | Сохраняет исправление ранее отвеченного вопроса; зависимые adaptive IDs попадают в `staleQuestionIds`, а branch пересчитывается. |
| POST | `/proftest/sessions/current/complete` | пустой JSON | Проверяет обязательные ответы, атомарно сохраняет `UserProfile` и переводит сессию в `completed`; повторный вызов безопасен. |
| POST | `/proftest/analytics` | `{events: [...]}` | Принимает только allow-listed telemetry, дедуплицирует `eventId` и применяет retention; raw event read не является public API. |

`ProftestSessionResponse` содержит только public view: `sessionId`,
`questionSetVersion`, `status` (`draft`/`completed`/`expired`/`abandoned`),
`cursor`, `interactionCount`, `revision`, `currentQuestion`,
`staleQuestionIds`, `progress`, optional `preliminary`, `adaptive` и optional
`results`. `preliminary.topics` содержит максимум три `{code, label}` без
процентов, Content Fit, имён/ID программ и fingerprint data. После пятого
валидного core-ответа `adaptive` возвращается сразу; если уточнение остановлено,
он содержит `status=skipped` и `stopReason`, а `currentQuestion=null`.
Вопрос описывает `stage`, `componentType`, option metadata, `required`,
`allowUncertain`, `allowSkip`, `multiSelect`, лимит выбранных вариантов и
declared dimensions. Внутренние scoring deltas, owner key, cookie token,
ORM state и raw source payload в ответ не попадают.

Для `next` сервер принимает статусы `answered`, `uncertain` и `skipped`.
Проверяются принадлежность ID текущему versioned question set, допустимое
число option IDs, adaptive dimension и optimistic `expectedRevision`.
Старый revision получает `409 CONFLICT`; неизвестный вопрос, branch или
нарушение лимита — typed `422 VALIDATION_ERROR`. Это позволяет безопасно
повторять запрос после reload и не создавать две активные сессии на одного
владельца.

Analytics payload ограничен набором `stage`, `questionId`, `component`,
`device`, `durationMs`, `uncertainty`, `adaptiveCount`, `changed`,
`top3Changed` и `reason`; строковые значения ограничены, device принимает
только `mobile`/`desktop`/`unknown`, размер payload ограничен 2 KiB. Event
rows имеют уникальный `eventId` и expiry 180 дней. Infrastructure repository
предоставляет deterministic aggregates для operator use (completion rate,
uncertainty, changed answers, top-3 changes, adaptive count и median response
time), но не публикует профили или сырые ответы.

Legacy routes остаются только для уже выпущенных клиентов и помечены
`deprecated: true` в OpenAPI. Условие удаления: все tracked clients используют
session API, а за один полный release cycle нет обращений к compatibility
routes; до этого они сохраняют parity по profile/ranking contracts.

Public v1 client types генерируются из корневого `openapi.json` в
`frontend-next/src/lib/public-api.generated.ts`; Web internal/admin types
генерируются из `frontend-next/openapi.json` в
`frontend-next/src/lib/generated.ts`. Оба snapshots и оба generated outputs
проверяются drift gate.

### Политика v3

Core состоит ровно из пяти server-owned вопросов: `core_doing`,
`core_learning`, `core_result`, `core_task_mode`, `core_anti`. Они собирают
только deterministic subject/activity/anti-interest сигналы для Content Fit;
цель выбора, опыт, поступление, стоимость, город, формат и нагрузка не
добавляются в этот flow. Каждый выбранный multi-select option остаётся частью
одной отправки и не увеличивает `interactionCount` отдельно.

После core сервер ранжирует текущие canonical fingerprints через тот же
`RecommendationService`, но наружу отдаёт только topic chips. Adaptive branch
создаёт не более четырёх вопросов v3, исключает уже заданные вопросы и точные
dimensions, сохраняет bounded ranking history в `state_json` и использует
детерминированный tie-break. После минимум двух adaptive answers действует
early stop: неизменный TOP-3 с delta до `0` даёт `top_three_stable`, небольшой
delta до `3` — `low_ranking_impact`; четвёртый ответ всегда завершает branch.
Пустой/неполный catalog не маскируется вопросом: возвращается
`insufficient_candidates` или `source_gap`, после чего completion остаётся
идемпотентным.

`proftest-v2` сохраняется только для уже pinned sessions и старых clients;
его защитный budget остаётся широким. Unknown question-set version отклоняется
typed validation error, а не молча переключается на v3. Optional filtering,
admission-fit и logistics refinement находятся после результата и не меняют
Content Fit ranking.

## Recommendations

| Метод | Endpoint | Назначение |
|---|---|---|
| POST | `/recommendations` | Ранжирует реальные программы для готового `UserProfile` |
| GET | `/recommendations/current?limit=10` | Ранжирует программы для current persisted profile |

Request содержит `profile` и `limit` (`1..20`). Профиль — тот же strict public contract, который возвращает proftest. Ответ `RecommendationsResponse` содержит профиль и TOP программ с integer `contentFit`, breakdown (`subjectFit`, `activityFit`, `distinctiveFit`, `antiPenalty`), долями областей, распределением по семестрам, отличительными дисциплинами и evidence-backed `reasons`/`antiFitReasons`.

Пример минимального запроса:

```json
{
  "profile": {
    "version": 1,
    "interests": ["computer_science_data"],
    "activityPreferences": ["software_creation"],
    "antiInterests": [],
    "preferredSubjectWeights": {"computer_science_data": "1"},
    "preferredActivityWeights": {"software_creation": "1"},
    "negativeWeights": {},
    "confidence": {"value": "1", "answeredBase": 6, "answeredAdaptive": 0},
    "adaptiveAnswers": []
  },
  "limit": 10
}
```

`/recommendations` и `/proftest/results` используют один RecommendationService. Он не импортирует ORM или parser, а получает fingerprints через infrastructure adapter, который делегирует существующий `Program/Curriculum/Discipline` catalog path.

## Personal route

| Метод | Endpoint | Назначение |
|---|---|---|
| GET | `/personal-route?limit=10` | Возвращает необязательные support-материалы по current profile |

`GET /personal-route` — read-only compatibility/support orchestration поверх существующих `CurrentRecommendationService`, `EventService` и `CampusService`. Он не создаёт новую сущность профиля, программы, события или точки, не хранит отдельный route snapshot и не является частью `DecisionService`. `limit` ограничен диапазоном `1..20`. Его просмотр не меняет `DecisionContext` и не требует прохождения обязательной воронки; UI предлагает каталог, поступление и «Мой выбор», если profile ещё нет.

Ответ `PersonalRouteResponse` содержит `status`, `summary`, те же source-backed `recommendations` и typed support items `explore_program`, `compare_programs` и `attend_event`. `position` сохраняется для совместимости и детерминированного порядка выдачи, но не означает обязательную последовательность. Item программы ссылается на canonical `programId`, item события — на существующий `eventId`, `venueId` и, если точка известна, полную `CampusPointDetailResponse` с карточкой, coordinate/address и university/department/program links. Для онлайн-события `venueId` и `point` остаются `null`.

Без current profile endpoint возвращает стандартный `404 NOT_FOUND`; это source state, а не блокировка других entry points. Пустая рекомендационная выдача получает `status: "no_recommendations"`, а отсутствие будущих подходящих событий — `status: "no_events"` при сохранённых program items. События отфильтрованы по рекомендованным canonical program IDs, текущему времени и deterministic UTC ordering. Endpoint не возвращает geometry, directions, расстояния, карту или route optimizer.

Минимальный пример ответа:

```json
{
  "status": "ready",
      "summary": "Дополнительные материалы по рекомендациям; порядок действий выбираете вы",
  "recommendations": [],
  "steps": [
    {
      "position": 1,
      "kind": "explore_program",
      "reason": "При желании изучите программу с самым высоким Content Fit",
      "programIds": ["<program-id>"]
    },
    {
      "position": 3,
      "kind": "attend_event",
      "reason": "При желании посетите событие, связанное с программой",
      "programIds": ["<program-id>"],
      "eventId": "event:bmstu:dod-2026",
      "venueId": "venue:bmstu:main-campus",
      "startsAt": "2026-10-17T08:00:00Z"
    }
  ]
}
```

`frontend-next` генерирует `PersonalRouteResponse` из `/openapi.json`; для UI используется только логический план, без маршрутизации по карте.

`POST /proftest/results` сохраняет только финальный `UserProfile` (без `AnswerSet` и cookie token). До login/register профиль принадлежит anonymous scope. При register/login активный anonymous profile переносится к account, если account profile ещё отсутствует. Если существуют оба, account profile wins, anonymous row остаётся отдельной и не merge-ится. Account-owned row больше не доступен по anonymous cookie; новый authenticated session восстанавливает его по canonical account ID. Если профиля нет или его TTL истёк, API возвращает `NOT_FOUND`; устаревший `expectedRevision` и duplicate create возвращают `CONFLICT`. Session keys и auth tokens в БД представлены только hash-значениями.

## Admission Fit

| Метод | Endpoint | Назначение |
|---|---|---|
| POST | `/programs/{id}/admission-fit` | Считает отдельную оценку реалистичности поступления для выбранного offering |

Endpoint принимает баллы абитуриента и явный `offeringId` из `GET /programs/{id}/admissions`. Это не подбор программы и не прогноз зачисления: сервер сравнивает введённые значения только с source-backed минимумами и проходным баллом выбранного набора.

Минимальный strict-запрос:

```json
{
  "version": 1,
  "offeringId": "<offering-id-from-admissions>",
  "applicant": {
    "version": 1,
    "scores": [
      {"subject": "Математика", "score": 90},
      {"subject": "Русский язык", "score": 88},
      {"subject": "Информатика", "score": 92}
    ]
  }
}
```

Поле `offeringId` нужно брать из фактического ответа admissions: год, форма, финансирование и scope могут отличаться между программами и источниками. `score` каждого предмета находится в диапазоне `0..100`; неизвестное поле или дублирующийся после нормализации предмет возвращают `VALIDATION_ERROR`.

Ответ содержит `status`, целочисленный `score` `0..100`, `dataQuality`, три независимые метрики `breakdown`, а также `reasons`, `antiReasons` и `dataGaps`. Decimal-значения баллов и метрик сериализуются строками. У reason сохраняются предмет, введённый факт, reference score и provenance, когда они есть.

Статусы:

- `realistic` — обязательные предметы сопоставлены, известные минимумы не нарушены, а введённая сумма не ниже выбранного проходного ориентира; итоговый score не ниже 80;
- `borderline` — данные полные, но сумма ниже опубликованного проходного ориентира либо итоговый score находится в диапазоне 55–79;
- `unlikely` — нарушен известный минимум, сумма ниже 85% проходного ориентира или итоговый score ниже 55;
- `insufficient_data` — отсутствует обязательный балл или невозможно посчитать доступную метрику.

Ошибки `NOT_FOUND` означают неизвестную программу или offering. Отсутствие admission facts не маскируется нулевыми значениями: API возвращает успешный результат с `dataQuality`/`dataGaps`, а UI показывает, каких фактов не хватает.

## Admissions

Admission API — read-only application path. Route вызывает `AdmissionService`, service читает `ProgramReader` и `AdmissionReader`, а SQLAlchemy projection остаётся внутри infrastructure. BMSTU adapter преобразует detail-page `__NEXT_DATA__` в raw/canonical contracts и связывает записи с canonical `program_id`; HTTP schema не экспортирует ORM-модели.

## Admin/Ops: ingestion quality

Admin/Ops API — узкий контракт для operator-инструментов. Он выключен по умолчанию: доступ появляется только при непустом `ANDROMEDA_OPS_API_KEY`, переданном в заголовке `X-Andromeda-Ops-Key`. При выключенном API, отсутствующем или неверном ключе сервер возвращает одинаковый `404 NOT_FOUND`.

| Метод | Endpoint | Назначение |
|---|---|---|
| GET | `/ops/ingestion/runs?status=completed&limit=50` | Ограниченный список запусков ingestion, newest-first |
| GET | `/ops/ingestion/runs/{id}` | Детали одного запуска по canonical `ingest:<32 hex>` ID |
| POST | `/ops/ingestion/runs/retry` | Bounded повтор разрешённого ingestion profile (`bmstu_fixture` или staging-only `bmstu_live`) |

Ответ содержит lifecycle status, timestamps, source count/kind/hash metadata, counts canonical projection и безопасные error code/message для failed run. `limit` ограничен диапазоном `1..100`; `status` принимает только `running`, `completed` или `failed`. Retry не принимает URL, shell-команду, program IDs или raw payload: body содержит только allowlisted `source`. Одновременный retry отклоняется с `409 CONFLICT`; live profile разрешён только в staging и использует зафиксированные официальные источники adapter-а.

Операторский экран открывается только явным `/#ops`, отсутствует в обычной пользовательской навигации, держит введённый ключ только в памяти страницы и очищает поле после подключения. Он показывает loading/empty/error states, status filter, detail/counters/safe errors и просит подтверждение перед `bmstu_fixture` retry. Сырые тела snapshot, raw payload, credentials, cookies или traceback не возвращаются и не показываются; произвольное исправление данных, DELETE, arbitrary SQL, CMS и Auth/RBAC не входят в контракт.

Audit row создаётся до capture и projection transaction, поэтому failed ingestion сохраняет безопасный факт ошибки даже при полном rollback projection. Источник истины — существующий `ingest_runs`; новая сущность raw provenance не создаётся. Повтор использует тот же typed BMSTU adapter и атомарный canonical sync, поэтому остаётся идемпотентным в пределах возможностей существующей projection.

## See Also

- [Архитектура](architecture.md) — почему API не импортирует ORM.
- [Конфигурация](configuration.md) — адреса и переменные окружения.
- [Тестирование](testing.md) — OpenAPI drift и API integration.
