# Andromeda MAX Hackathon Monorepo

Единый standalone repository для MAX-хакатона: MAX transport живёт в `apps/max`, Andromeda — в `services/andromeda`. MAX обращается к backend только по HTTP через Public API v1 и использует сгенерированный из canonical OpenAPI контракт. Совместное хранение в Git не создаёт прямой import-зависимости между TypeScript transport и Python backend.

```text
MAX Bot ───────┐
MAX Mini App ──┼── HTTP / Public API v1 ── Andromeda modular monolith
Web ───────────┘                              ├── PostgreSQL
                                              ├── deterministic domain services
                                              └── bounded Jev / optional presentation
```

## Repository layout

- [`apps/max/`](apps/max/): MAX Bot, Mini App shell, transport state, tests and generated Public API client.
- [`services/andromeda/`](services/andromeda/): Python backend, PostgreSQL model/migrations, Web app, ingestion, canonical OpenAPI and DATA-API assets.
- [`UPSTREAM_ANDROMEDA.md`](UPSTREAM_ANDROMEDA.md): imported source SHA and reviewed snapshot-sync procedure.

MAX must not import Andromeda Python, database, Jev or provider internals. Backend business behavior remains behind `/api/v1/*`; MAX platform identifiers are not Andromeda identities or authorization.

## Local development

See [`apps/max/docs/development.md`](apps/max/docs/development.md) for MAX setup and [`services/andromeda/README.md`](services/andromeda/README.md) for backend prerequisites and fixture-backed operation. From the repository root, use:

```powershell
python scripts/monorepo.py max
python scripts/monorepo.py andromeda
python scripts/monorepo.py contracts
python scripts/monorepo.py full
python scripts/monorepo.py e2e
```

Use `python scripts/monorepo.py stack -d` to start the combined local stack after configuring the environment examples. `full` includes the root Compose configuration check; it does not silently start long-running services or require PostgreSQL/provider credentials.

Use fixture-backed data for deterministic local checks. Live university sources and paid AI providers are optional and are not substitutes for the deterministic test suite. Never commit `.env` files, tokens, cookies, MAX update payloads or applicant profiles.

## API contracts and licenses

The canonical Public API v1 contract is [`services/andromeda/openapi.json`](services/andromeda/openapi.json). MAX DTOs are generated from that file; update the backend export, generated client and drift evidence together. Internal `/ops` and review APIs are not MAX contracts. The MAX and Andromeda source trees retain their respective license notices in their package roots.
