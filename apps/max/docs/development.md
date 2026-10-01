# Development

## Prerequisites

- Node.js 22 or newer and npm.
- A reachable Andromeda Public API v1 server.
- Redis for persistent conversation mappings, update leases and rate limits. MAX unit tests use the bounded memory adapter; Redis integration tests require MAX_TEST_REDIS_URL on a local test database.
- Chromium installed by Playwright for browser checks.

Copy .env.example to .env and set MAX_BOT_TOKEN for an actual Bot connection. ANDROMEDA_API_BASE_URL defaults to a local backend at http://127.0.0.1:8000. The Bot sends all ordinary text through the generated Public API v1 assistant contract. The MAX user ID is never sent as an Andromeda identity or applicant context.

## Run

```powershell
npm ci
npm run dev:bot
npm run dev:miniapp
```

Those commands run separate processes. Start the Andromeda backend and Redis according to the root monorepo and services/andromeda guides. The Mini App frontend is JavaScript built with Vite; the Node.js/TypeScript host serves it on port 8787 and reads the catalog from `ANDROMEDA_API_BASE_URL`. Public catalog reads work in browser preview without MAX launch data. Requests that use personal profile data require a valid signed launch. The Bot uses polling in development; protected deployments require webhook plus Redis TLS.

For deterministic tests, no MAX token or live AI provider is required:

```powershell
npm run verify
```

To exercise Redis Lua commands, set MAX_TEST_REDIS_URL to an unauthenticated loopback Redis database from 1 through 15 and run npm run test:integration. Never point this test variable at a shared or production Redis.

## Change workflow

Keep MAX SDK calls inside src/max/platform. Keep shared configuration, errors, logging and transport-state contracts channel-neutral. Keep Andromeda calls in the Public API HTTP client and use generated DTOs. Do not add backend routes, use MAX profile fields as an Andromeda identity, or calculate admission/policy results in the Bot. See architecture.md and security.md.
