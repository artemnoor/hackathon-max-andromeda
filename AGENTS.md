# Repository instructions

This repository contains two separately owned applications. Read this file first, then read the closest `AGENTS.md`, README and relevant architecture/API docs before changing a subsystem.

## Ownership and boundaries

- `apps/max/` owns MAX protocol adapters, Bot/Mini App presentation, and MAX-specific state. It may call Andromeda only over HTTP Public API v1. Public API DTOs must come from the generated client under `apps/max`; never hand-copy backend schemas.
- `services/andromeda/` owns the modular-monolith backend, canonical data, policy/domain decisions, PostgreSQL persistence, ingestion, Jev runtime and the Web application. Follow `services/andromeda/AGENTS.md` and its architecture rules for changes there.
- `services/andromeda/openapi.json` is the canonical client-facing Public API v1 contract. The separate `services/andromeda/frontend-next/openapi.json` is the full application contract and must not be used by MAX.
- Shared Git history and a single local stack do not authorize cross-runtime imports. MAX must not import Python, SQLAlchemy, database drivers, Jev SDKs or internal FastAPI modules.

## Required workflow

Use `context → analysis → plan → implementation → tests → verification`. Check branch/status/history first. Preserve unrelated local or ignored data. Add tests for changed behavior and run the narrow checks before broader gates. For API changes, verify canonical OpenAPI and generated-client drift. Do not claim provider/live validation based on a stub.

## Security and operations

- Keep MAX platform IDs distinct from Andromeda account identity and authorization. Validate MAX init data on the server.
- Do not log prompts, applicant context, raw MAX updates/init data, cookies, provider keys or tokens.
- Keep AI providers optional; deterministic backend decisions remain authoritative. Jev calibration gates and provider boundaries must not be bypassed.
- Use fixture-backed local validation by default. Never make live university scraping or paid provider access a required CI dependency.
- Do not commit `.env`, `.ai-factory`, generated runtime artifacts, nested `.git` directories or submodules.

## Git

Do not rewrite published history, force-push, reset the user's work, or stage unrelated files. Check the staged path list before every commit. Keep imported Andromeda provenance current in `UPSTREAM_ANDROMEDA.md`.
