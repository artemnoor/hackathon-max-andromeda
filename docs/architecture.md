# Monorepo architecture

## Runtime boundary

```text
MAX Bot ───────┐
MAX Mini App ──┼── HTTP / Public API v1 ── Andromeda backend
Web ───────────┘                             modular monolith
```

The repository contains two runtime applications, not two business backends. `apps/max` adapts MAX updates and Mini App launch data to channel-neutral behavior. `services/andromeda` owns the Public API, PostgreSQL, canonical education data, query sessions, admission and policy decisions, source provenance, and optional AI adapters.

MAX Bot uses only `POST /api/v1/assistant/query`. Its TypeScript wire types are generated from [`services/andromeda/openapi.json`](../services/andromeda/openapi.json), the canonical Public API v1 contract. The frontend's full-application OpenAPI snapshot is not a MAX contract. Internal `/ops`, university-admin and knowledge-review routes stay outside the public client boundary.

## Ownership and identity

- Andromeda owns `QuerySession` state and its PostgreSQL persistence. The Bot carries only its ID and expected revision between turns.
- MAX transport state stores the opaque Andromeda guest-profile cookie, session ID/revision and activity time in Redis. It stores no transcript or applicant profile.
- A MAX platform user ID is transient input used only to derive a one-way hashed Redis state key. It is not sent to Andromeda or used as Andromeda identity or authorization.
- MAX renders typed assistant text, status, evidence summaries and action labels. It does not interpret policy, calculate admission results, inspect response data/metadata, or call Jev/LLM providers.
- The Mini App frontend is a JavaScript single-page app built with Vite and served by the Node.js/TypeScript MAX host. It currently includes the source-backed catalog, program details and curricula, comparison of 2–4 programs, admission checks, and navigation for profile, shortlist, ProfTest, recommendations, personal route, news/events, olympiads and admission rules. See [`apps/max/README.md`](../apps/max/README.md) for which views use API data and which remain local or empty.
- Public catalog reads can be previewed in an ordinary browser. Requests that use a personal server profile validate signed MAX launch data on the server.
- The Mini App keeps applicant-entered profile fields, exam scores, shortlist and progress in browser `localStorage`. These values are not MAX account identity; EGE scores are not currently synchronized to Andromeda.

## AI boundary

Deterministic Andromeda services decide applicability and domain outcomes. Jev remains an optional bounded resolver under Andromeda's existing registry and calibration gates. An optional backend presentation adapter may naturalize an already typed source-backed response; its output is validated and falls back to deterministic wording. An outside-coverage response is explicitly unverified. Neither MAX transport nor an LLM can write canonical facts or policy.

## Verification boundary

The disposable E2E Compose project exercises PostgreSQL fixture ingestion, Redis-backed MAX session mapping, and real HTTP calls to the Public API. It uses isolated project names, dynamically selected loopback ports, and project-scoped cleanup. Regular `stack down` preserves the developer's named volumes; E2E cleanup removes only its own temporary volumes.
