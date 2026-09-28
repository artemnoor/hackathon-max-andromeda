# Andromeda backend

Backend Andromeda — единый modular monolith для ingestion официальных данных
МГТУ им. Н.Э. Баумана, canonical projection и FastAPI/OpenAPI API.

## Быстрый запуск

Из корня репозитория:

```powershell
python -m pip install uv
uv sync --project backend --locked --extra dev --extra browser
python scripts/andromeda.py production-smoke
python backend/scripts/run_andromeda_demo.py --mode fixture --check
```

Без `--check` runner оставляет FastAPI и canonical `frontend-next` запущенными:

- API: `http://127.0.0.1:8000/docs`;
- UI: `http://127.0.0.1:3000/`;
- OpenAPI: `http://127.0.0.1:8000/openapi.json`.

Fixture mode использует только проверенные снимки официальных BMSTU sources.
Live mode обращается к официальному каталогу и связанным публичным
study-plan/admission resources, сохраняет provenance/source hashes и
останавливается с source gap или contract error вместо выдумывания данных.

## Canonical ingestion pipeline

```text
official BMSTU catalog/API
  → directions and profiles discovered dynamically
  → detail pages and linked study plans
  → admissions/order sources
  → typed raw DTOs with provenance
  → normalization and 22-area discipline classification
  → atomic canonical projection
  → PostgreSQL (development/staging) or SQLite (tests)
  → FastAPI/OpenAPI
```

Для полного поддерживаемого каталога не передавайте список программ:

```powershell
python backend/scripts/run_andromeda_bmstu.py --mode live --database-url $env:ANDROMEDA_DATABASE_URL --log-level INFO
```

Runner сам обходит catalog pagination, находит направления и программы,
разрешает detail pages, скачивает доступные study plans и связывает admissions
с canonical `program_id`. Ограниченный выбор программ допускается только как
диагностический input; production ingestion использует dynamic discovery.

Для backend-only fixture run:

```powershell
python backend/scripts/run_andromeda_bmstu.py --mode fixture --database-url sqlite:///./data/andromeda-demo.db --log-level INFO
```

Runner применяет `alembic upgrade head` до ingestion. Повторный запуск
одного source snapshot идемпотентен: canonical IDs и source provenance не
дублируются, а изменившаяся projection обновляется атомарно.

## Admissions semantics

Admissions строятся только из официальных detail/order sources. Для каждой
доступной комбинации года, формы, финансирования и конкурсного маршрута
сохраняются места, экзамены, минимумы, observed passing score, квоты,
стоимость и provenance, если факт опубликован.

- numeric passing score — минимум суммы баллов среди опубликованных
  зачисленных строк;
- targeted/separate/special quota и other — отдельные route-aware facts;
- `bvi` — отдельный status с `score=null`, отображается как «БВИ»;
- отсутствие факта — `source_gap`, а не ноль и не догадка.

## Storage and source artifacts

`ANDROMEDA_DATABASE_URL` — canonical target для API, Alembic и ingestion.
`BMSTU_DATABASE_URL` остаётся только deprecated fallback на один migration
cycle. Raw
snapshots immutable и связаны с content SHA-256; canonical tables обновляются
в одной projection transaction. SQLite предназначен для tests/local smoke,
development и staging используют PostgreSQL.

Poppler `pdftotext` нужен для текстового разбора study-plan PDF. CI
устанавливает и проверяет его до backend tests.

Перед live/fixture ingestion можно проверить parser capabilities без сети:

```powershell
python backend/scripts/preflight.py --profile bmstu --profile hse
```

Direct Python dependencies are resolved from `backend/uv.lock` with
`uv sync --locked`; Playwright/Chromium остаются optional browser fallback.

## Проверки

```powershell
python scripts/andromeda.py fast
python scripts/andromeda.py backend
python scripts/andromeda.py frontend
python scripts/andromeda.py production-smoke
```

Для browser E2E сначала запустите demo runner без `--check`, затем выполните
`python scripts/andromeda.py playwright`. CI выполняет тот же canonical Next
flow для SQLite fixture и PostgreSQL 16 service. Backend coverage и migration
artifacts создаются через `backend-coverage` и `migrations` targets.

## Границы

Предметные модули не знают об ORM, FastAPI или university-specific parser.
BMSTU adapter владеет source capture, PDF/HTML parsing, mappings и
provenance; API только связывает public contracts с HTTP. Events и campus
не заполняются fixture-данными в live production, если полноценный
официальный live source недоступен.
