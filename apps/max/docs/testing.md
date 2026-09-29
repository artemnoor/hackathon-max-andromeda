# Testing and verification

Run the complete project gate:

```powershell
npm ci
npx playwright install chromium
npm run verify
```

`verify` runs lint, strict TypeScript checks, production build, unit tests, all HTTP/Webhook integration tests, Playwright browser tests, architecture and Mini App boundary checks, environment/Compose/docs/secret checks, aggregate Node coverage thresholds and npm dependency audit.

The Redis state integration test runs when `MAX_TEST_REDIS_URL` points to an unauthenticated loopback Redis database 1–15. The real Andromeda HTTP scenarios run when `MAX_E2E_ANDROMEDA_URL` points to a local fixture-backed Public API v1 server. Without those variables, only the corresponding external-service tests are skipped; the Mini App and Webhook integration tests still execute. Run `python scripts/monorepo.py e2e` from the repository root to start an isolated PostgreSQL/Redis/Andromeda fixture stack, run both integration suites and browser checks, and clean up the isolated resources.

GitHub Actions runs the same disposable monorepo E2E against the root Compose stack after component and contract jobs pass. It installs Chromium, starts fixture ingestion against PostgreSQL, and uses no MAX or AI-provider credential.

Browser tests use deterministic synthetic MAX `initData` signed with a fixture-only token. They verify preview behavior, same-origin header transport, no browser storage writes, and fail-closed invalid signatures. They do not contact MAX or Andromeda.
