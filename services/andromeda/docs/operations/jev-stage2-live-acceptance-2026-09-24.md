# Jev Stage 2: live acceptance и границы готовности

Дата проверки: 2026-09-24

Ветка: `feature/jev-ecosystem-stage-2`

Репозиторий: `artemnoor/andromeda`

## Короткий итог

Stage 2 сохраняет прежний принцип: Jev предлагает ограниченное typed-решение, а Andromeda проверяет его калибровкой, схемой и allow-list; факты и расчёты остаются у детерминированных доменных сервисов. В этой проверке были выполнены настоящие вызовы официального TypeSafe Python SDK к TypeSafe-compatible Polza endpoint. Для нескольких операций собраны отдельные observation datasets. Проверка выявила несовпадение словаря intent у provider registry с доменным контрактом, а также отличие фактического ответа SDK для Noul от формы, которую предполагал адаптер; оба случая покрыты исправлениями и регрессионными тестами.

Это **не означает, что все Jev operations готовы к production**. Только `choose_next_action` уже имеет ранее утверждённый production calibration lock и активный runtime callsite. Для Olympiad/profile resolution получены сильные численные результаты на синтетических фразах, построенных из официальных BMSTU candidate records, но отсутствует независимая human review и достаточно разнообразный пользовательский корпус. Поэтому его новый числовой calibration candidate **не оставлен в runtime lock directory и не включён**. При обычной конфигурации resolver остаётся deterministic/fail-closed.

## Как работает существующий путь

```text
Запрос / состояние диалога
        ↓
Зарегистрированная operation и Question Registry
        ↓
ограниченный typed input + allow-list вариантов
        ↓
TypeSafe SDK → Polza-compatible endpoint → Jev
        ↓
сырой choice / probabilities / model identity / usage
        ↓
jevcal.runtime.Cascade: версия, hash, model, threshold и applicability
        ↓
schema + allow-list validation
   ↙ принято                 ↘ отклонено / ошибка
typed bounded decision       существующий deterministic fallback
        ↓
детерминированные Andromeda services и source-backed data
```

Модель не получает SQL и не выдаёт canonical факт. Для олимпиадного resolver сначала выполняется детерминированное сужение кандидатов; Jev может выбирать только среди переданных canonical IDs и `unresolved`. Даже успешное разрешение имени не означает льготу: право, программа, предмет подтверждения и срок действия читаются из source-backed admission rules и проверяются `AdmissionBenefitEvaluator`.

## Операции и фактическая готовность

Точность ниже — доля совпадений Jev с заданной меткой на сохранённом capture corpus. Это не оценка на реальном пользовательском трафике. «Покрытие вероятностей» — доля capture-ответов, для которых exporter смог сохранить полный набор вероятностей по допустимым вариантам; capture прерывается, если распределение неполное или ответ не входит в allow-list.

| Операция | Live observations | Held-out | Совпадения всего / held-out | Покрытие probabilities | Jevcal threshold / ECE | Фактическое runtime состояние |
|---|---:|---:|---:|---:|---|---|
| `choose_next_action` (`next-action.v1`) | 120 | 56 | 120/120; 56/56 | 100% | `0.64` / `0.0439167` | **Production-calibrated и wired** существующим runtime. Артефакт и его manifest не изменялись в этой работе. |
| `resolve_intent` (`intent.v1`) | 25 | 14 | 21/25 (84%); 12/14 (85.71%) | 100% | нет: выборка меньше production minimum | Evaluation only. Typed provider-boundary mapping исправлен; продуктовый intent остаётся deterministic. |
| `resolve_metric` (`metric.v1`) | 24 | 12 | 24/24 (100%); 12/12 (100%) | 100% | нет: выборка меньше production minimum | Evaluation only. Результат не включает аналитический расчёт; его всё равно выполняют MetricRegistry/AnalyticsEngine. |
| `choose_presentation` (`presentation.v1`) | 10 | 6 | 5/10 (50%); 4/6 (66.67%) | 100% | нет: малая выборка и недостаточное качество | Jev не включать; остаётся deterministic-only. |
| `resolve_olympiad_profile` (`olympiad-profile-resolution.v1`) | 120 | 62 | 120/120; 62/62 | 100% | upstream candidate: `0.99` / ECE `0.0001667` | Bounded runtime adapter есть, но **не включён**: capture синтетический, независимой human review нет. Candidate lock удалён из runtime lock directory; требуется новый reviewed corpus перед production lock. |
| `classify_semantic_features` (Noul) | 1 отдельный live probe; не calibration corpus | — | Не оценивается | Недостаточно данных | нет | Только диагностический/evaluation сигнал. Никакого semantic значения в canonical storage из него не создаётся. |
| `jevQL` | Нет live provider query в этой приёмке | — | — | — | — | Проверяются существующие offline contracts и composition wiring; не оценивался как LLM factual decision. Materialized metrics остаются предпочтительным путём. |
| `jev-tree` | Нет live selection benchmark в этой приёмке | — | — | — | — | Существующий bounded adapter; не менялся и не объявляется live-validated здесь. Малые candidate sets не должны отправляться в дерево. |
| System One Adapter | Не используется как production decision path | — | — | — | — | Eval/benchmark boundary; не заменяет официальный TypeSafe SDK production transport. |

### Как читать результаты

- У `intent`, `metric` и `presentation` мало наблюдений для production calibration. Результат `24/24` на metric не заменяет широкую выборку: он лишь показывает, что на этих случаях operation сработала правильно.
- У Olympiad/profile resolution upstream Jevcal на сохранённых вероятностях подобрал `0.99` и численно получил 100% accepted accuracy на 62 held-out записях. Но строки сгенерированы из одного официального fixture-набора с фиксированными шаблонами: 11 известных профилей и `unresolved`, по 10 случаев на метку; пользовательские опечатки, реальные сокращения и независимая разметка не покрыты. Поэтому числовой результат не считается доказательством production-пригодности.
- Ранее созданный pilot corpus `olympiad-profile-resolution.v1` оставлен только как история capture. Его calibration lock и manifest удалены; pilot не является основой runtime policy.
- Production lock для нового Olympiad resolver в runtime config **не коммитится**, пока не появятся review и разнообразный corpus. Фича по умолчанию выключена (`JEV_ADMISSION_RESOLUTION_ENABLED=false`); без валидной конфигурации runtime сообщает disabled/fallback и не обязан останавливать приложение.

## Provider и версии

| Параметр | Зафиксированное значение |
|---|---|
| Endpoint host | `polza.ai` — TypeSafe-compatible route |
| Requested model | `typesafe/jev` |
| Observed model | `jev-1.13.0` |
| Python SDK | `typesafe-sdk 0.7.1` |
| Calibration package | `jevcal 0.1.0` |
| Upstream Jevcal source pin | `ae8f3144d69c9cb0e5e0a2c17f70b9d14714cb9f` |
| Authentication | Только существующая env/configuration boundary; секретов и значений ключей в отчёте нет |

Все live captures используют `official-typesafe-sdk-system-one` transport path. В observations записаны host, запрошенная и наблюдаемая модель, время, token usage, outcome, candidate IDs и probabilities. Содержимое пользовательских профилей и credentials в отчёт не переносились.

## Измеренная latency и объём

Процентили рассчитаны по сохранённым observation `latency_ms` методом nearest-rank для p95; это время одного provider operation в capture, не сквозной API SLA.

| Набор | p50 | p95 | Input tokens | Output tokens |
|---|---:|---:|---:|---:|
| `next-action.v2` baseline | 476 ms | 753 ms | 64,276 | 8,550 |
| `intent.v1` | 440 ms | 1,014 ms | 10,163 | 1,503 |
| `metric.v1` | 428 ms | 980 ms | 12,444 | 2,370 |
| `presentation.v1` | 439 ms | 1,081 ms | 3,999 | 542 |
| `olympiad-profile-resolution.v2` | 421 ms | 828 ms | 209,040 | 31,270 |

Это реальные результаты конкретных capture runs; они не обещают такую же latency при текущей нагрузке. В таблицах нет оценок timeout/fallback rate с production трафика: failure cases ниже — симулированные offline regressions.

## Olympiad/profile live vertical slice

Проверенный сценарий использовал существующий BMSTU 2026 fixture bundle и parser; это не новый ручной lookup:

1. Парсер загрузил source-backed Olympiad/profile records из fixtures `backend/tests/ingestion/fixtures/bmstu/admission_benefits/`.
2. Для фразы без профиля детерминированный resolver оставил четыре кандидата. Ограниченный live selector был вызван с этими кандидатами и вернул `unresolved`; система запросила уточнение, а не выбрала произвольный профиль.
3. После уточнения `инфохимия` имя сопоставилось с canonical profile `olympiad-profile:bmstu-dffd82c346b3304135a3c9b3`.
4. Кандидат затем проверялся существующим детерминированным `AdmissionBenefitEvaluator`. Соответствующее source rule имеет `review_required`; итог также `review_required`, без предоставления пользователю неподтверждённого права.

Значит live Jev был использован для bounded ambiguity handling, но **не выдал юридический вывод**. Этот slice работал через существующий fixture-backed source reader; это не утверждение, что полный persisted PostgreSQL/API сценарий с активным production lock прошёл. Официальный пакет в текущих fixtures даёт 8 Olympiads, 11 profiles и 24 rules, но остаются review/stale/source gaps; покрытие admission benefits не объявляется полным.

## Исправления и границы данных

### Intent mapping

Registry использует labels `catalog_search` и `comparison`, тогда как внутренний typed contract — `analytics_query` и `compare_programs`. Ранее корректный ответ провайдера мог отвергаться schema validation и переходить в fallback. Исправление ограничено infrastructure adapter: labels сопоставляются в закрытый доменный словарь, evidence и исходные probabilities сохраняются. Неподдерживаемый `recommendation` безопасно превращается в `unknown`; Question Registry и его calibration hash не менялись.

### Noul evidence

Фактический TypeSafe SDK `0.7.1` не кладёт Noul-ответы в `SystemOneResponse.choices` как Choice answers: они находятся в `.answers`/`.nouls`. Transport adapter теперь сохраняет исходные per-feature Noul probabilities в raw evidence. При этом domain payload по-прежнему не заполняется этими числами: feature-intensity semantics требует отдельной валидации и не становится source fact.

## Fallback и fail-closed проверки

Следующее проверяется через unit/integration seams с fake transport/artifacts; это **не** live provider failures:

| Условие | Ожидаемое поведение | Проверка |
|---|---|---|
| timeout, auth error, provider 5xx | typed failure → deterministic fallback; не 500 из-за Jev | adapter tests |
| повторные provider failures | circuit открывается; лишние вызовы прекращаются | adapter tests |
| неверная/отсутствующая модель в health response | capability disabled/fallback | TypeSafe client tests |
| отсутствующий optional SDK | health check fail-closed | TypeSafe client tests |
| stale registry hash / истёкший artifact | calibration отвергается | Cascade tests |
| несовпадение модели или definition version | artifact не принимается | production lock contract tests |
| probability ниже calibrated gate | Jev choice отвергается, применяется fallback/unresolved | Cascade/adapter tests |
| canonical ID вне переданного candidate set | выбор запрещён, остаётся unresolved | adapter tests |
| admission resolution feature flag выключен / lock отсутствует | selector не подключается; resolver остаётся безопасным | runtime/config tests |

Приватные данные не нужны для profile resolution: transport получает только нормализуемую фразу и ограниченный список candidate labels/IDs. Любая правовая eligibility calculation после этого остаётся локальной и deterministic.

## Corpus, hashes и воспроизводимость

Observation/case файлы сохранены отдельно для каждой definition. SHA-256 текущих live inputs:

| Артефакт | SHA-256 |
|---|---|
| intent cases | `7221c710190d9054dbbb6ee0031bb06be93023007278d572fee961775cef109c` |
| intent observations | `e87d9d7786642b12688e220cab6c96de1cb9cec10e770b2d5189cce819e475cb` |
| metric cases | `b97e0ef17b660faddc4bd4e8b3c6ed505eef409c71fe4ba79381bdc4e3c27578` |
| metric observations | `d8733ee5ab514d6d6b8842732a332500f26592f6f4262e08323a3ee6ad044e21` |
| presentation cases | `5441725c03eb4f1544385e35b9d662def06bc804c23b5fa786a0f6363194877d` |
| presentation observations | `f4b223c7417bf7745d6aa82916fd7757c5bdcda4aacc164378a43906f4535e40` |
| Olympiad/profile v2 cases | `463ce7fc1a8519469e6532c34b74593344fa6d64b955a991cc0bfce7a031ef3d` |
| Olympiad/profile v2 observations | `8a203a99094b1492d62e5a8f0becca3861d37699185a49852fa9538eb3f14b42` |
| admission registry | `374edc8eb9fe050c7f1283534955b47a755825af9f2517438efc952012c384cf` |

Case generation и capture командами не перезаписывают существующие observation files; provider-call budget ограничен максимумом инструмента, задаётся явно. Capturing требует настроенного ключа в окружении и сначала проверяет health/model identity. Ключ не следует помещать в аргументы процесса или историю команд.

Пример безопасного запуска из `backend/` (секрет предварительно должен быть установлен secret manager/session environment, не вставлен в исходник):

```powershell
uv run --locked --extra evaluation --extra dev python scripts/jev_operation_evaluation.py `
  --definition-id olympiad-profile-resolution.v1 `
  --registry config/jev/question-definitions.admission.v1.yaml `
  --generate-cases evals/jev/corpus/operation-captures/olympiad-profile-resolution.reviewed-cases.jsonl `
  --count 120
```

После независимой разметки и review cases, live capture запускается с `--cases <reviewed-cases>` и новым путём `--observations <new-observations>`. Не использовать текущие synthetic template labels как замену такому review. Для upstream compiler сначала проверяется команда из `python scripts/jevcal_calibrate.py --help`; калибровочный lock до review не записывать в активный runtime каталог.

## Проверки

### Выполненные локальные проверки

- Jev-focused набор: `82 passed` — TypeSafe transport, Jev adapter, `jevcal.runtime.Cascade`, runtime/settings, evaluation tooling, Jev ecosystem E2E, entity resolution и assistant query API.
- Изменённые Python-файлы: Ruff lint/format checks пройдены.
- Полный backend mypy из CI прошёл: `Success: no issues found in 571 source files`.
- `jevcal_calibrate.py --check` успешно провалидировал числовой Olympiad v2 candidate через upstream `jevcal` и admission registry до того, как candidate lock был удалён из runtime directory из-за отсутствия независимой corpus review.
- OpenAPI экспорт выполнен; документационная ссылка-проверка прошла: 120 Markdown файлов.
- Финальный полный backend CI-equivalent pytest с coverage завершился: `919 passed, 9 skipped` за 654.40 s; 339 предупреждений/deprecation/resource warnings, ошибок тестов нет.
- Архитектурные проверки: `35 passed`; Jev ecosystem offline contract subset: `61 passed`; ingestion preflight BMSTU + HSE: ready.
- Изменённые Python-файлы: `ruff check` и `ruff format --check` пройдены; общий OpenAPI export/client drift прошёл; frontend unit `25 passed`; frontend lint прошёл.
- Repository docs audit: 121 Markdown files; deployment artifact contract passed; `git diff --check` пройден.
- Hosted GitHub Actions: [run 35971052788](https://github.com/artemnoor/andromeda/actions/runs/35971052788) на SHA `7c232e0a46f9df593593a36419d011d361019b24` завершён с итогом **success**. Все jobs того исторического workflow были зелёные, включая backend, frontend, packaging, PostgreSQL, proftest и fullstack checks.
- План Phase 10 отмечает T32 завершённым после этой проверки. Текущий change к плану/report — только документационное обновление; его новый commit повторно проверяется hosted Actions отдельно, а финальная handoff указывает его SHA и результат.

Общий `ruff check src tests scripts evals` не является CI-командой и обнаружил многочисленные ранее существовавшие lint findings в широком дереве проекта; поэтому это не трактуется как регрессия данной работы. CI workflow выполняет полный backend pytest, архитектурный gate и mypy, но не запускает такой repo-wide Ruff command.

### Не подтверждено этой приёмкой

- независимая проверка разметки и реальный распределённый пользовательский corpus для новых operations;
- typo, сокращения и adversarial/OOD coverage у Olympiad resolver;
- production enablement `resolve_intent`, `resolve_metric`, `choose_presentation`, semantic classification или нового Olympiad lock;
- live provider failure-rate, retry-rate и production p95;
- live JevQL/jev-tree selection в этой приёмке;
- полноценный persisted PostgreSQL+API vertical с production-enabled новыми locks;
- полнота всех BMSTU admission rights: для части официальных правил есть review/stale/source gaps.

## Рекомендуемая следующая операционная ступень

1. Два человека независимо размечают разнообразные, непересекающиеся Olympiad/profile query families, включая короткие названия, официальные алиасы, неоднозначные фразы, опечатки и `unresolved`.
2. Проверяется candidate coverage, отсутствие leakage между train/held-out и точность expected canonical ID относительно официального captured source.
3. Новый live capture выполняется на reviewed corpus с зафиксированными provider/model versions; текущие observations остаются как отдельный pilot.
4. Upstream Jevcal повторно строит calibration, а `Cascade` проверяет lock; production lock публикуется только после независимого review, quality gates и end-to-end persisted source-backed eligibility test.
5. Разрешается feature flag только для этого узкого candidate-resolution use case. Само юридическое решение по-прежнему никогда не делегируется Jev.

## T30/T31 closeout — 2026-09-24

### T30 — Olympiad profile resolver: `BLOCKED_EXTERNAL_REVIEW`

Для этой проверки не был предоставлен независимый human-reviewed corpus и reviewer/adjudicator. Поэтому новый реалистичный corpus не объявляется reviewed, live profile-resolution capture повторно не запускался, новый Jevcal threshold/ECE не рассчитывался и production lock не создавался. Значения пилотного `olympiad-profile-resolution.v2` выше остаются только историческим synthetic/source-fixture pilot и не являются новыми метриками или production calibration evidence.

`JEV_ADMISSION_RESOLUTION_ENABLED` оставлен выключенным; активного admission resolver lock по-прежнему нет. Это намеренный fail-closed результат, а не успешное закрытие production acceptance. T30 остаётся незакрытым до независимой разметки и adjudication разнообразных формулировок, включая aliases, typos, ambiguity и unresolved cases.

### T31 — scenario and fallback acceptance

| Case | Result | Evidence and boundary |
|---|---|---|
| A — admission, 270 points | `LIVE_VERIFIED` for one shadow turn; full clarification flow `OFFLINE_VERIFIED` | Один запрос прошёл по `/assistant/query` через реальный TypeSafe SDK `choose_next_action` в shadow. HTTP 200, детерминированно запрошены баллы ЕГЭ. Следующие slots, scope, вопрос «бюджет/платное», defaults и complete admission result проверены API regression suite. Это не live admission decision от Jev. |
| B — math comparison | `OFFLINE_VERIFIED` for typed canonical programs; user aliases `ИУ5/ИУ7` safely unresolved | Два canonical BMSTU program IDs дали math comparison из persisted projections с непустым evidence, workload basis и metric values. Голые `ИУ5/ИУ7` не являются program IDs в текущем analytics contract и не имеют подтверждённой department-to-curriculum mapping; assistant просит уточнить программы, ничего не сопоставляет наугад. Intent/metric Jev остаются evaluation-only. |
| C — similar programs | `UNSUPPORTED`, safe clarification verified offline | Отдельная similarity capability отсутствует. `/assistant/query` просит уточнить metric; не возвращает список похожих программ, ID или similarity claims. |
| D — “Шаг в будущее / Инженерное дело” | `BLOCKED_EXTERNAL` for active Jev runtime; fallback `OFFLINE_VERIFIED` | Без human review/совместимого lock production selector выключен. Историческая v2 capture/replay выше — только `LIVE_EVALUATION` и отдельная deterministic source-rule evaluation, не active-runtime proof. Benefit и provenance определяет admission module. |
| E — BVI eligibility | `OFFLINE_VERIFIED` | Admission-benefit vertical tests подтверждают source-backed eligibility; historical BVI observation не даёт текущего права. |
| F — individual achievements | `OFFLINE_VERIFIED` | Appendix 6 fixture → parser/normalized policy → persistence/API/calculator проверено; points/caps берутся только из загруженной policy. |
| G — compare two programs | `OFFLINE_VERIFIED` | Canonical program IDs → QuerySession/compiler → analytics → response envelope; данные и evidence source-backed. Если названия программ не указаны, система уточняет, а не выбирает их сама. |
| H — “А где лучше?” | `OFFLINE_VERIFIED` | API возвращает clarification о metric; неподдержанный score/recommendation и выдуманные программы не выдаются. |

### LIVE VERIFIED

Live shadow observation от 2026-09-24: provider `polza` (`polza.ai`), requested model `typesafe/jev`, observed model `jev-1.13.0`, operation `choose_next_action`, latency `1031 ms`, usage `535` input / `73` output tokens. Запрос был синтетическим; credentials, provider body и персональные данные не сохранялись. Shadow вернул пользователю тот же deterministic result — clarification по ЕГЭ. Для этого smoke runtime был сконфигурирован только внутри временного процесса; постоянные flags, production lock и `next-action.v2` artifacts не менялись.

### OFFLINE VERIFIED

Live outage scenarios не имитировались как реальные: timeout/auth/5xx, unavailable SDK/model, schema/out-of-candidate, missing/stale/model-incompatible calibration, low probability и circuit-open проверены только offline fake/artifact tests. В том числе добавлен API-level fake timeout test: active shadow transport вызывается, а `/assistant/query` возвращает deterministic clarification с HTTP 200, не 500.

### Offline verification for closeout

- Targeted Jev/admission/analytics/assistant suite: `142 passed`, `31 warnings`.
- Command: `uv run --locked --extra dev --extra jev pytest -q tests/infrastructure/test_typesafe_client.py tests/infrastructure/test_jev_adapter.py tests/infrastructure/test_jevcal_cascade.py tests/infrastructure/test_jev_runtime.py tests/evaluation tests/e2e/test_jev_ecosystem_scenarios.py tests/api/test_assistant_query.py tests/api/test_analytics_api.py tests/api/test_admission_benefits_api.py tests/integration/test_analytics_engine.py tests/integration/test_andromeda_comparison.py tests/integration/test_bmstu_admission_benefits_ingestion.py tests/vertical/test_bmstu_admission_benefits_vertical_slice.py tests/modules/conversation/test_shadow_policy.py tests/modules/admission_benefits` (run from `backend/`).
- Ruff lint passed for the three changed Python test files. Formatting checks passed for the new E2E and shadow-policy test files; the pre-existing assistant API test file contains older formatting outside this change and is not a CI formatter target.
- `next-action.typesafe-jev.v2.lock.json` SHA-256 remains `1f881b527794f9c54aad6633f40e2d8bc92b8ddc56150c011844eb036f4d2ea4`; manifest SHA-256 remains `c09100f4f3c3c3b9d143436fa48665d7d87160178b81bc7c8c54f4aa94dc96a7`. No lock, registry, capture, or calibration artifact was changed or added.
- Added regressions prove shadow calls the model but returns the exact deterministic policy result, telemetry hashes session IDs and excludes query/profile sentinels, provider failure remains non-fatal at the API boundary, and unsupported/incomplete prompts do not fabricate program identities.

### NOT VERIFIED / BLOCKED EXTERNAL

- Independent human review/adjudication, a diverse reviewed Olympiad corpus and its new live capture/Jevcal calibration are unavailable; T30 remains open and the resolver remains disabled.
- Live provider outage/fallback rates, production p95, production-enabled Olympiad eligibility, and a live jevQL/jev-tree benchmark were not measured. Their failure behavior is covered only by offline fake/artifact tests where stated above.
- A natural-language `ИУ5/ИУ7` department-to-curriculum mapping and a similarity-search capability are unsupported; the assistant safely asks for clarification and returns no guessed program IDs.

### Operation disposition after T31

- `choose_next_action`: compatible calibrated artifact and composition path exist; one live shadow request passed. Jev influences no response in shadow. Runtime production activation still depends on explicit deployment flags/configuration.
- `resolve_olympiad_profile`: disabled; evaluation/pilot evidence only; production blocked on independent review and new calibration gates.
- `resolve_intent`, `resolve_metric`, `choose_presentation`, semantic classification: evaluation or deterministic product behavior only; no production callsite is enabled by this closeout.
- JevQL/jev-tree: existing adapters/wiring unchanged; no live selection benchmark is claimed.
- Admission rights, score calculation, semantic facts and analytics remain deterministic/source-backed; Jev is never legal eligibility or factual analytics authority.

T31's safety/available-path verification is complete. T30 remains open due to external review; T32 remains open until commit/push and hosted Actions are green for the exact final HEAD.
