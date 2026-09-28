[Back to README](../README.md) · [Архитектура →](architecture.md)

# Быстрый старт

## Требования

- Python 3.11+;
- Node.js 22+ и npm;
- Poppler `pdftotext` для PDF учебных планов;
- Chromium для browser E2E-проверки.

## Установка

```powershell
python -m pip install uv
uv sync --project backend --locked --extra dev --extra browser
npm --prefix frontend-next ci
npx --prefix frontend-next playwright install chromium
npm --prefix frontend-next run build
npm --prefix frontend-next run check-api-drift
cd ..
```

Для обычного перехода от установки к проверяемому запуску используйте
`python scripts/andromeda.py production-smoke`; полная карта target-ов — в
[матрице тестирования](test-matrix.md). Повторную установку Chromium можно
не выполнять, если он уже установлен.

## Fixture-запуск

Из корня репозитория:

```powershell
python backend/scripts/run_andromeda_demo.py --mode fixture --check
```

Команда прогоняет captured sources через ingestion, Alembic, SQLite, FastAPI и canonical Next app, затем проверяет catalog, compare и admissions endpoints. Для ручного просмотра используйте ту же команду без `--check`.

Для generic ingestion:

```powershell
python backend/scripts/run_andromeda_ingestion.py --university bmstu --mode fixture
python backend/scripts/run_andromeda_ingestion.py --university hse --mode fixture
python backend/scripts/run_andromeda_ingestion.py --university all --mode fixture
```

Официальные raw fixtures находятся в `backend/tests/fixtures/tracer/raw` (BMSTU)
и `backend/tests/fixtures/hse/raw` (HSE). Название BMSTU fixture namespace
сохранено как совместимый raw-contract boundary; production live режим не
подменяется fixtures.

## Проверка результата

- UI: `http://127.0.0.1:3000/`;
- Swagger: `http://127.0.0.1:8000/docs`;
- OpenAPI: `http://127.0.0.1:8000/openapi.json`.

В UI откройте раздел «Программа», выберите одну из программ и дождитесь блока «Поступление». В нём отображаются текущие места и минимумы, исторические проходные баллы, а для платного набора — стоимость, если эти поля есть в captured BMSTU source. Ссылка «Источник» ведёт на официальный detail page.

Чтобы вручную проверить persistence профиля:

1. Откройте «Профиль содержания» и пройдите вопросы до TOP программ.
2. Обновите страницу. При сохранённой anonymous cookie появится пометка «Профиль восстановлен из Andromeda», а карточки рекомендаций загрузятся через API.
3. Для проверки server source of truth удалите локальный draft профтеста в DevTools и обновите страницу ещё раз. Незавершённый draft, напротив, должен восстанавливаться локально и не заменяться старым completed profile.
4. Технические endpoints доступны в Swagger: `GET /proftest/profile`, `POST /proftest/profile`, `PUT /proftest/profile` и `GET /recommendations/current?limit=10`.

Для live-источников:

```powershell
python backend/scripts/run_andromeda_demo.py --mode live
```

Live mode — explicit operational action: он обращается к официальным
источникам, поэтому не входит в deterministic PR/full локальный gate. Для
staging/production используется PostgreSQL и внутренний backend port `8020`;
локальный demo runner по умолчанию оставляет API на `8000`.

## PostgreSQL dev

Для обычного запуска поднимите отдельный development target:

```powershell
Copy-Item .env.development.example .env.development
docker compose --env-file .env.development -f ops/postgres/docker-compose.yml --profile development up -d postgres-dev
$env:ANDROMEDA_ENV = "development"
$env:ANDROMEDA_DATABASE_URL = "postgresql+psycopg://andromeda:change-me@127.0.0.1:5432/andromeda_dev"
python -m alembic upgrade head
python backend/scripts/run_andromeda_ingestion.py --university all --mode fixture --database-url $env:ANDROMEDA_DATABASE_URL
```

После ingestion запустите API и `frontend-next` отдельными процессами либо через demo runner с тем же `--database-url`. Для staging используйте `.env.staging.example`, профиль `staging`, порт `5433` и базу `andromeda_staging`. Подробности, refresh и troubleshooting — в [руководстве PostgreSQL](postgresql.md).

## See Also

- [Архитектура](architecture.md) — границы модулей и ingestion.
- [Тестирование](testing.md) — полный набор локальных проверок.
