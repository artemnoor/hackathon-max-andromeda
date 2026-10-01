# Hackathon MAX Andromeda

MAX Bot is a transport for Andromeda's existing Public API v1. Incoming free text, including example-button prompts, goes through `POST /api/v1/assistant/query`; question interpretation, clarification, admission logic, policy resolution, evidence and response modes stay in the Andromeda backend.

```text
MAX Bot ──┐
MAX Mini App ──┼── HTTP / Public API v1 ── Andromeda backend
Web ──────┘                                ├── PostgreSQL and domain services
                                           ├── deterministic policy/admission logic
                                           └── Jev / optional backend verbalization
```

The MAX SDK is confined to `src/max/platform`. Bot HTTP types come from the generated client in `src/andromeda/generated/public-api.ts`, whose canonical source is `services/andromeda/openapi.json`. MAX does not import backend Python, database, Jev or LLM code.

## Working Bot behavior

- `/start` clears the previous query session and opens a free-text conversation with one suggested comparison prompt. When `MINI_APP_PUBLIC_URL` is configured, `/start` and `/help` also show a native MAX button that opens the Mini App. The prompt is an example, not a separate scripted scenario flow.
- Every user message goes through the same `/api/v1/assistant/query` operation. When `POLZA_AI_API_KEY` is configured, the Polza/DeepSeek conversation provider interprets the request and writes a concise clarification based on typed missing fields; this does not depend on the prose-naturalization flag. Andromeda then resolves names against its real catalog and runs its existing deterministic services. AI may select an alternative only from a bounded list of real catalog entries; it cannot invent a program, score, source or result.
- Clarification buttons are used only for finite typed choices or real catalog entries. The user can always answer in free text. If the AI provider is unavailable, the backend uses its deterministic parser and clarification fallback; unavailable source data is reported as missing rather than simulated.
- If a completed request receives an unrecognized follow-up, the assistant starts a new query rather than repeating the old result. `/start` also clears the query session while preserving the anonymous profile cookie.
- Supported read-only response actions become callback buttons through that same assistant operation; unsupported mutations and unimplemented Mini App actions are omitted.
- In admission search, choosing a named-university scope is followed by a clear request to type one or more university names; “Любые вузы” explicitly searches the available catalog.
- Long replies are split at paragraph, sentence or whitespace boundaries within UTF-8 limits. Known evidence metrics use Russian labels; raw metric codes and internal metadata are not exposed verbatim to users.
- Every completed answer also gets a separate PDF attachment with its structured comparison/admission/policy details, missing-data notes and available source links. Clarification questions remain chat messages. The PDF repeats Andromeda's result and does not add facts or recalculate admission outcomes.
- A server-side Redis mapping stores only the opaque Andromeda guest profile cookie, QuerySession ID/revision and activity time. MAX user IDs are hashed into Redis keys and are never treated as Andromeda identities.
- MAX does not collect profile fields implicitly, link accounts, make admissions decisions, or call Jev/DeepSeek directly.
- The Mini App frontend is a JavaScript app built with Vite; its HTTP host is Node.js/TypeScript. `powershell` code fences in this documentation label command examples for Windows shells.
- Active Mini App sections include the API-backed program catalog and detail pages, curriculum, comparison of two to four programs, admission check, profile, shortlist, ProfTest, recommendations, personal route, news/events, olympiads and admission rules. The catalog has no demo-program fallback. The host maps an explicit set of requests to the canonical Public API v1.
- Public catalog requests can load in a browser preview without MAX launch data. The host validates signed launch data for personal/profile requests and admission-fit POSTs; the launch proof is sent in `X-Max-Init-Data`, not a URL.
- The Mini App stores applicant-entered fields, EGE scores, shortlist, comparison choices and progress in browser `localStorage`; these values are not linked to the MAX user ID. EGE scores are not currently synchronized to the Andromeda profile. Recommendations come from the server-side Public API profile, so browser-only entries do not personalize them. The personal route is calculated from browser-local progress. News combines API events with curated source-linked items; the bundled olympiad list is currently empty.

## Local development

Use Node.js 22 or newer. Copy [`.env.example`](.env.example) to `.env`, set `MAX_BOT_TOKEN`, and set `ANDROMEDA_API_BASE_URL` to a reachable local or HTTPS Andromeda Public API v1 server. Start Redis and Andromeda using their development instructions, then run:

```powershell
npm ci
npm run dev:bot
npm run dev:miniapp
```

The Bot uses MAX polling in development by default; protected deployments use webhook and TLS Redis. Set `POLZA_AI_API_KEY` in the root Compose `.env` to enable real conversation interpretation and, by default, constrained natural-language verbalization of structured results. Set `PRESENTATION_LLM_ENABLED=false` only to disable prose naturalization. Compose passes provider settings only to Andromeda. Without a provider key, deterministic parsing and domain behavior remain as a safe fallback; no catalog data or results are simulated.

For repo-wide checks and the fixture-backed stack, use the root [monorepo guide](../../README.md). For security boundaries see [security](docs/security.md); for test commands see [testing](docs/testing.md), and for hosted configuration see [deployment](docs/deployment.md).

Never commit `.env`, MAX tokens, guest cookies, update bodies or applicant data.
