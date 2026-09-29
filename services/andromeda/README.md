# Andromeda

> Stage: MVP Production Level — bounded, source-backed BMSTU/HSE MVP. See the
> [release evidence](docs/release/mvp-production-level-evidence.md) and [gate](docs/release/mvp-production-level-gate.md).

Andromeda — multi-university data-driven система поддержки выбора образовательной программы. Основной объект продукта — `DecisionContext` и пользовательский shortlist: система объединяет source-backed сведения о программах, содержании учебных планов и поступлении, а пользователь сам принимает финальное решение.

BMSTU — первый полноценный источник, HSE — второй. Новые университеты подключаются через adapters (`capture → parse → normalize → validate → persist`), без университетских ветвлений в доменных модулях. Пользователь может начать с каталога, сравнения, проверки поступления, профиля предпочтений или уже сохранённого выбора — профтест и линейный маршрут не обязательны.

Система разделяет факты и решения: `DecisionContext` хранит только явно подтверждённые пользователем ограничения и shortlist, а предложения, Admission Fit, Content Fit, trade-offs и source gaps остаются derived evidence. Andromeda никогда не удаляет сохранённую программу автоматически; последнее решение принимает пользователь. Гостевая anonymous HttpOnly-сессия работает сразу, аккаунт нужен только для переноса выбора между устройствами.

## Быстрый старт

```powershell
python -m pip install uv
uv sync --project backend --locked --extra dev --extra browser
npm --prefix frontend-next ci
python backend/scripts/run_andromeda_demo.py --mode fixture --check
```

После запуска API доступен на `http://127.0.0.1:8000/docs`, UI — на `http://127.0.0.1:3000/`. Для ручной работы уберите `--check`.

Для обычной dev-работы используйте PostgreSQL: инструкции находятся в [руководстве PostgreSQL](docs/postgresql.md). SQLite остаётся быстрым test fallback.

## Canonical verification

Команды не требуют знания внутреннего дерева тестов:

```powershell
python scripts/andromeda.py fast              # быстрые boundary/type/docs checks
python scripts/andromeda.py production-smoke # disposable fixture runtime smoke
python scripts/andromeda.py full              # локальные проверки без live source/PostgreSQL
```

`backend`, `frontend`, `postgres`, `playwright`, `migrations`,
`backend-coverage`, `frontend-coverage`, `deployment` и `security` являются
отдельными целевыми проверками. Полная карта, prerequisites и безопасные
артефакты находятся в [матрице тестирования](docs/test-matrix.md).

## Что уже работает

- Generic university ingestion (`--university bmstu|hse|all`) с provenance и fail-closed source selection.
- BMSTU и HSE fixture/live adapters с university-scoped canonical IDs.
- Изолированные модули universities, programs, curricula, disciplines, decision, comparison, proftest, recommendations, admissions и admission_fit.
- SQLAlchemy/Alembic с FK, unique/check constraints и Decimal без float-конверсии.
- FastAPI, stable Public API v1 и TypeScript-клиенты, generated из OpenAPI.
- Универсальный аналитический слой: versioned semantic features, materialized
  `ProgramProjection`, allow-listed `MetricRegistry`, typed `/analytics/query`
  и channel-neutral `/assistant/query`; deterministic fallback does not require optional Jev.
- Bounded source-backed knowledge/policy workflow: allowlisted one-shot source
  discovery, claim/change staging, exact-hash human approval, deterministic
  temporal/scope resolver with `ResolutionTrace`, review/impact preview and
  policy questions through the existing assistant (read path disabled by
  default behind `ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED`). Source coverage
  and reviewer staffing are explicit operations prerequisites; the generic
  policy layer does not replace admission-benefit calculations.
- Jev integration seam: shared Question Registry, official TypeSafe SDK adapter,
  deterministic fallback, shadow-only policy, calibration-lock gate and
  isolated jevQL/jev-tree optional runtimes. Все flags выключены по умолчанию;
  Jev не вычисляет факты и не генерирует SQL.
- University-owned admin: scoped owner/editor/viewer memberships, управление факультетами/кафедрами и категориями, public catalog overlays и отдельная афиша вузов с draft/publish/archive, audience targeting и agenda. В UI доступны «Вузы», публичный каталог/афиша и защищённая админка из личного кабинета.
- Persistent shortlist с ролями «основная/альтернатива», явными add/remove/restore и optimistic revision; raw A/B comparison и summary-first сравнение 2–3 программ.
- Профиль содержания: короткое ядро из пяти вопросов, preliminary topic chips, bounded adaptive refinement и реальные программы с объяснениями по учебному плану. Career Fit и персональный Workload Readiness не являются MVP capability; вместо них показываются source-backed Content Fit и workload evidence в сравнении.
- Persistence профиля: completed `UserProfile` хранится по anonymous HttpOnly session cookie и восстанавливается после перезагрузки UI.
- Recommendation vertical slice: готовый `UserProfile` → детерминированный Content Fit → reasons/anti-reasons по реальному fingerprint.
- Admissions vertical slice: реальные BMSTU данные поступления по canonical `program_id` — места, ЕГЭ и минимумы, квоты, проходные баллы, стоимость и форма обучения.
- Production scope ограничен source-backed BMSTU/HSE coverage и single-instance
  operational layout. Career Fit, validated Workload Readiness, ML ranking,
  отзывы, массовое университетское покрытие и guaranteed admission claims не
  входят в текущий MVP.

### Подбор и профиль содержания

Профиль предпочтений — один из способов уточнить `DecisionContext`, а не обязательный первый этап. В UI выберите «Подобрать». Canonical compact adaptive v3 использует version-pinned session API: `POST /proftest/sessions`, `GET /proftest/sessions/current`, `POST /proftest/sessions/current/next`, `PATCH /proftest/sessions/current` и `POST /proftest/sessions/current/complete`. Старые `/proftest/questions`, `/proftest/preview` и `/proftest/results` сохранены как явно deprecated compatibility adapters на один release cycle и не используются новым frontend flow. Финальный результат сохраняется в Andromeda по anonymous HttpOnly cookie; после reload UI использует `GET /proftest/profile` и `GET /recommendations/current`. Профиль обновляет предложения, но не меняет shortlist без явного действия пользователя. После изменения API обновите frontend-контракт:

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

`Content Fit` рассчитывается детерминированно по реальным часам/ЗЕТ и долям предметных областей. Отдельный `Admission Fit` показывает риск по source-backed admissions facts и не влияет на Content Fit или ranking рекомендаций.

### Данные поступления

В UI выберите «Поступление» или откройте карточку программы. `DecisionContext` может сохранить явно введённые баллы и ограничения, после чего Decision Service оценивает batch кандидатов как realistic/borderline/unlikely/insufficient-data. Исторический проходной балл не является гарантией. Данные проходят тот же BMSTU parser → canonical contracts → PostgreSQL/SQLite repository → FastAPI flow; отсутствующие официальные значения не заменяются нулями.

### Мой выбор

`Мой выбор` — основной пользовательский экран. Он показывает основные варианты, альтернативы, ранее сохранённые варианты, известные ограничения и missing data. Система может предложить до трёх основных кандидатов и двух альтернатив с причинами, рисками, content differences и source gaps, но добавление, удаление, восстановление, исключение и смена роли выполняются отдельными командами пользователя. Все изменения защищены `expectedRevision`; устаревшая запись получает `409 CONFLICT`.

Сравнение сначала показывает краткий вывод и trade-offs, затем Admission/Content Fit и только потом дисциплины, часы, ЗЕТ и другие raw evidence. События, campus и `personal-route` оставлены как необязательная поддержка выбора; они не образуют следующий обязательный шаг.

## Пример

```text
GET /compare?programIds=<program-id-a>,<program-id-b>&scope=semester&semester=1
```

Ответ содержит rows со статусами `both`, `different`, `only_a`, `only_b`, а также totals и blocks.

## Документация

| Гид | Содержание |
|---|---|
| [Быстрый старт](docs/getting-started.md) | Установка и первый запуск |
| [Архитектура](docs/architecture.md) | Модули и поток данных |
| [Universal analytics](docs/architecture/universal-analytics.md) | Semantic layer, projections, QuerySpec и integration seams |
| [Jev rollout](docs/architecture/jev-rollout.md) | Безопасные flags, production gates, shadow/fallback и rollback |
| [Semantic and catalog analytics](docs/semantic-analytics.md) | Версии семантики, metric registry, evidence, rebuild/rollback и Jev fallback |
| [Query flow](docs/architecture/query-flow.md) | Conversation state, analytics и admission compilation |
| [Knowledge and Policy](docs/architecture/knowledge-policy.md) | Source claims, approval, temporal resolution и impact |
| [Knowledge operations](docs/operations/knowledge-policy-runbook.md) | Polling, review, security, recovery и budgets |
| [Public API v1 и DATA-API](docs/api.md) | Canonical OpenAPI, transport boundary, generated clients и organizer validator |
| [Admissions](docs/admissions.md) | Данные поступления и source gaps |
| [Admission Fit](docs/admission-fit.md) | Отдельная оценка реалистичности поступления |
| [Принципы продукта](docs/product-principles.md) | Правила Decision Support и пользовательского выбора |
| [Конфигурация](docs/configuration.md) | Переменные окружения |
| [PostgreSQL](docs/postgresql.md) | Dev/staging, migrations и ingestion |
| [MVP](docs/mvp.md) | Scope и measurable Definition of Done |
| [Deployment](docs/deployment.md) | Staging, health checks, backups и rollback |
| [Тестирование](docs/testing.md) | Локальные и CI-проверки |

## License

MIT — см. [LICENSE](LICENSE).
