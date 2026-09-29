# Monorepo development

## Prerequisites

- Python 3.11 and `uv` for Andromeda.
- Node.js 22 or newer and npm for MAX and the Andromeda Web frontend.
- Docker Engine with Docker Compose for the PostgreSQL/Redis fixture stack and full E2E command.
- Chromium installed through Playwright for browser tests.

Install the component dependencies from their own roots:

```powershell
uv sync --project services/andromeda/backend --locked --extra dev --extra browser
npm --prefix apps/max ci
npm --prefix services/andromeda/frontend-next ci
```

## Local verification

```powershell
python scripts/monorepo.py max
python scripts/monorepo.py andromeda
python scripts/monorepo.py contracts
python scripts/monorepo.py full
python scripts/monorepo.py e2e
```

`full` runs the deterministic MAX and Andromeda checks and validates the root Compose manifest; it does not start containers or require provider credentials. `e2e` starts a uniquely named disposable PostgreSQL/Redis/Andromeda fixture project, points MAX integration tests at its loopback API, runs both browser suites and always tears down that project's containers and temporary volumes. It never tears down a developer's regular `stack up` project.

The E2E HTTP scenarios require no MAX token or external AI key. They send fixed synthetic test updates through the MAX assistant interaction and generated Public API client. Running `npm run test:integration` without `MAX_E2E_ANDROMEDA_URL` skips the API scenarios; Redis integration runs only when `MAX_TEST_REDIS_URL` points to an unauthenticated loopback Redis database 1–15.

For an interactive development stack, copy `.env.example` to `.env` and run:

```powershell
python scripts/monorepo.py stack up --fixtures
python scripts/monorepo.py stack status
python scripts/monorepo.py stack down
```

The interactive stack uses named Postgres/Redis volumes and `stack down` preserves them. Pass `--volumes` only when intentionally deleting that local data. Add `--max` to `stack up` after configuring an operator-owned `MAX_BOT_TOKEN` to start Bot and Mini App processes.

## Public API and generated client

The canonical Public API v1 snapshot is `services/andromeda/openapi.json`. After changing a public backend contract, export it and regenerate the MAX client:

```powershell
python services/andromeda/backend/scripts/export_openapi.py --surface public-v1 --out services/andromeda/openapi.json
npm --prefix apps/max run generate:andromeda-client
npm --prefix apps/max run check:andromeda-client-drift
python scripts/monorepo.py contracts
```

`python scripts/monorepo.py contracts` verifies both Andromeda OpenAPI snapshots, the official DATA-API definition, generated Web clients and generated MAX client. FastAPI `/docs` remains the full application schema; do not use internal/admin routes in the Public API contract.

Never commit `.env`, API keys, MAX tokens, guest cookies, raw MAX updates, applicant profiles, generated runtime output, or local database files.
