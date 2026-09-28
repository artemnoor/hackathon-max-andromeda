# Testing and verification

Run the complete project gate:

```powershell
npm ci
npx playwright install chromium
npm run verify
```

`verify` runs lint, strict TypeScript checks, production build, unit tests, all HTTP/Webhook integration tests, Playwright browser tests, architecture and Mini App boundary checks, environment/Compose/docs/secret checks, aggregate Node coverage thresholds and npm dependency audit.

The Redis integration suite is run when `MAX_TEST_REDIS_URL` points to an unauthenticated loopback Redis database 1–15. Without it, only that Redis case is marked skipped; the Mini App and Webhook integration tests still execute. GitHub Actions provides a dedicated Redis service, installs Chromium, validates Compose and builds the Docker image.

Browser tests use deterministic synthetic MAX `initData` signed with a fixture-only token. They verify preview behavior, same-origin header transport, no browser storage writes, and fail-closed invalid signatures. They do not contact MAX or Andromeda.
