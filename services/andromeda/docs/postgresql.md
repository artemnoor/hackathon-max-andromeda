[← Конфигурация](configuration.md) · [Back to README](../README.md) · [Тестирование →](testing.md)

# PostgreSQL для development и staging

Development и staging Andromeda используют PostgreSQL через единый `ANDROMEDA_DATABASE_URL`. Compose поднимает два независимых target: `andromeda_dev` на `5432` и `andromeda_staging` на `5433`. SQLite остаётся только быстрым test fallback.

## Development

Требования: Docker Desktop, Python dependencies и Poppler для live/PDF ingestion.

```powershell
Copy-Item .env.development.example .env.development
docker compose --env-file .env.development -f ops/postgres/docker-compose.yml --profile development up -d postgres-dev
$env:ANDROMEDA_ENV = "development"
$env:ANDROMEDA_DATABASE_URL = "postgresql+psycopg://andromeda:change-me@127.0.0.1:5432/andromeda_dev"
python -m alembic upgrade head
python backend/scripts/run_andromeda_ingestion.py --university all --mode fixture --database-url $env:ANDROMEDA_DATABASE_URL
```

Для полного локального flow после ingestion:

```powershell
python backend/scripts/run_andromeda_demo.py --mode fixture --database-url $env:ANDROMEDA_DATABASE_URL
```

Откройте `http://127.0.0.1:8000/docs` и `http://127.0.0.1:3000/`. Demo runner использует тот же URL для migration, ingestion, API и `frontend-next`.

## Staging

Staging target намеренно отделён именем базы, портом и volume:

```powershell
Copy-Item .env.staging.example .env.staging
docker compose --env-file .env.staging -f ops/postgres/docker-compose.yml --profile staging up -d postgres-staging
$env:ANDROMEDA_ENV = "staging"
$env:ANDROMEDA_DATABASE_URL = "postgresql+psycopg://andromeda:change-me@127.0.0.1:5433/andromeda_staging"
python -m alembic upgrade head
python backend/scripts/run_andromeda_ingestion.py --university all --mode fixture --database-url $env:ANDROMEDA_DATABASE_URL
```

Для настоящего remote staging замените host, credentials и database name только во внешнем secret-managed environment. Не коммитьте `.env.staging`.

## Migrations и ingestion update

Alembic берёт URL из `ANDROMEDA_DATABASE_URL` (с временным fallback на deprecated `BMSTU_DATABASE_URL`), поэтому API, runner и migration command не могут случайно писать в разные базы:

```powershell
$env:ANDROMEDA_ENV = "development"
$env:ANDROMEDA_DATABASE_URL = "postgresql+psycopg://andromeda:change-me@127.0.0.1:5432/andromeda_dev"
python -m alembic current
python -m alembic upgrade head
python backend/scripts/run_andromeda_ingestion.py --university all --mode live --database-url $env:ANDROMEDA_DATABASE_URL
```

Повторный ingest того же source snapshot идемпотентен. Новые данные добавляются, изменяемые поля canonical projection обновляются, устаревшие позиции затронутого curriculum удаляются атомарно, raw history сохраняется. Identity conflict или source contract error откатывает всю транзакцию.

В текущем Stage 2-based implementation миграции идут одной additive chain:
`0038_admission_offering_scope_and_exam_choices` →
`0054_claim_predicate_lookup_index` (current code head, 2026-09-26). Перед
каждым rollout проверьте реальный database head через `python -m alembic
current` и кодовую историю через `python -m alembic heads` / `history`; не
предполагайте, что production DB уже на code head. Новые таблицы знания,
approval ledger и projections используют существующие `source_snapshots` и
`ingest_runs`; миграции не заменяют их отдельным store.

У generic policy нет автоматического backfill approval из legacy benefit
`ACTIVE` строк. Перед adoption существующей базы используйте
`python backend/scripts/report_knowledge_provenance.py`: команда только читает
источники и показывает восстанавливаемые ссылки/пробелы, но не меняет историю.
См. [knowledge-policy operations runbook](operations/knowledge-policy-runbook.md).

После `0010_admission_passing_route` старые passing-score rows backfill-ятся как `competition_type=general`, `status=numeric`; BVI хранится с `score=NULL`. Повторный live sync не меняет `AdmissionOffering.id`, не создаёт duplicate route/status children и атомарно удаляет устаревшие children только после полной валидной projection.

## Troubleshooting

- `requires a PostgreSQL ANDROMEDA_DATABASE_URL` — задан `ANDROMEDA_ENV=development|staging`, но URL не PostgreSQL.
- `No module named psycopg` — повторите `python -m pip install -e "backend[dev]"`.
- `connection refused` — дождитесь compose healthcheck: `docker compose ... ps`.
- `password authentication failed` — проверьте пароль и URL encoding; не вставляйте пароль в logs.
- migration failure — проверьте `python -m alembic current`, не обходите Alembic `create_all()` в staging.
- parser/source failure — это source contract failure; не подменяйте БД прямым импортом fixture/ORM.

`LOG_LEVEL=DEBUG` показывает только stage, dialect, counters и redacted target. Password, signed URL, PDF body и полный payload не логируются.

## See Also

- [Конфигурация](configuration.md) — все env-переменные и defaults.
- [Быстрый старт](getting-started.md) — установка и полный flow.
- [Тестирование](testing.md) — SQLite/PostgreSQL test matrix и CI.
