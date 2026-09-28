# Development

## Prerequisites

- Node.js 22 or newer and npm.
- Docker Compose for local Redis-backed runtime and Redis integration tests.
- Chromium installed by Playwright for browser checks.

Create a local environment file with `Copy-Item .env.example .env`, then set `MAX_BOT_TOKEN`. For local Compose, Redis is created inside the Compose network; do not point the container at `localhost` for Redis.

## Run

```powershell
npm ci
npm run dev:bot
npm run dev:miniapp
```

Those commands run separate processes. To run the complete local stack, use `docker compose up --build`. The Mini App shell is served on port 8787. The Bot uses polling unless configured otherwise. Runtime commands remain neutral and do not call Andromeda.

## Change workflow

Keep MAX SDK calls inside `src/max/platform`. Keep shared config/errors/logging/state independent of application product logic. Do not add a backend route or use MAX profile fields as an Andromeda identity. See [architecture](architecture.md) and [security](security.md).
