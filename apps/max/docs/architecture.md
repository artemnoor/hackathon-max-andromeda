# Architecture

## Runtime boundary

\`\`\`text
MAX User
  ├─ Bot ──→ MAX transport/application adapter ──┐
  ├─ Mini App ─→ MAX Bridge and static host ─────┤
  └─ Web ────────────────────────────────────────┤
                                                  ↓ HTTP
                                      Andromeda Public API v1
                                                  ↓
                                    Andromeda modular monolith
                              PostgreSQL / domain services / Jev
\`\`\`

The Bot calls only POST /api/v1/assistant/query. Its request and response DTO types are generated from the canonical Public API OpenAPI file at services/andromeda/openapi.json. There is one assistant flow and one backend; MAX adds no alternate query, admission or policy engine.

The start message opens a free-text conversation; there are no fixed task scenarios. Every turn uses the same QuerySession and Public API operation. When a Polza API key is configured, the backend model interprets natural-language intent and phrases, then formulates clarifications from the typed missing slots. Andromeda resolves those phrases against canonical university/program data and performs deterministic calculations. A model may choose an alternative only from a bounded list of actual catalog entries. It cannot create missing institutions, programs, scores, evidence or results. If provider access is unavailable, deterministic parsing and explicit missing-data handling remain as a fail-safe.

Buttons are limited to finite typed choices or actual catalog candidates returned by Andromeda; other clarification is free text. An unrecognized follow-up after a completed result starts a new query rather than repeating the previous result.

Admission university-scope choices are typed into the conversation state. Choosing one or several named universities leads to a follow-up asking for their names; choosing “Любые вузы” selects the available catalog directly.

The MAX SDK is accessed only in src/max/platform. src/max owns update normalization, assistant interaction, response rendering, callbacks and deep links. Supported read-only response actions are represented as allowlisted callbacks; clicking one issues a fixed follow-up prompt through the existing AssistantInteraction and QuerySession. Unsupported mutations and unavailable surfaces are omitted. src/shared owns configuration, safe errors, redacting logs and bounded transport state. Subject behavior does not import SDK types.

Every completed assistant result is also rendered as a downloadable PDF attachment in MAX. The report renderer consumes only the typed Public API v1 response: comparison rows, admission outcomes, policy facts, evidence and source references. It formats those values and does not calculate eligibility or generate new facts. Clarification turns remain normal chat questions and do not produce empty reports. The PDF embeds locally packaged Noto Sans TrueType fonts covering Latin and Cyrillic, so Russian text renders in the Bot runtime without an external font service.

## Identity and conversation state

The MAX platform user ID is not an Andromeda account ID, role, session or authorization grant. It is used transiently to derive a hashed Redis state key. The Bot sends only the user-authored text, current Andromeda QuerySession ID and expected revision; it never derives applicant context from MAX profile fields.

Redis stores an opaque Andromeda guest profile cookie together with the QuerySession ID, revision and last activity time. It does not store message history or MAX identity. Andromeda remains the owner of QuerySession persistence in PostgreSQL. Per-user Redis leases serialize Bot turns before an expected-revision request.

Jev resolution, deterministic decisions, domain benefit calculations, source provenance and optional DeepSeek verbalization remain inside Andromeda. The MAX renderer uses typed response text/status/evidence and approved action callbacks; it does not expose response data or metadata blobs.

## Transport lifecycle

Polling processes updates sequentially and advances the marker only after the batch succeeds. Webhook handling authenticates a bounded request and acknowledges only after processing completes. Startup checks the current MAX webhook subscription and does not delete a conflicting subscription. Shutdown does not mutate remote MAX subscription state.

Redis is the production shared state owner for rate counters, update leases/completion, one-time deep-link references and assistant conversation mappings. Process memory state is bounded and available only in explicit development/test composition. Protected runtime requires Redis over TLS.

## Mini App boundary

The Mini App frontend is a JavaScript single-page app built by Vite and served by the Node.js/TypeScript host. The host enforces an explicit static-file allowlist, response-size bound, origin allowlist and CSP. Signed MAX launch data is sent in the same-origin `X-Max-Init-Data` header and validated server-side for protected requests; it is not put in a URL or browser storage. Public catalog reads can run in an ordinary browser preview without a MAX launch.

The host maps an explicit allowlist of catalog, curriculum, admissions, comparison, profile, recommendation, events and admission-benefit requests to Andromeda Public API v1. Admission-fit requests are also forwarded to the backend, which owns the decision. The host does not use the MAX platform user ID as an Andromeda identity or link MAX accounts.

The frontend persists profile fields, exam scores, shortlist, comparison selection and progress in browser `localStorage`. This state is local to that browser. EGE scores entered in the Mini App are not synchronized to the Andromeda profile, and recommendations use the server-side profile. The personal-route view is calculated from local progress. News combines API events with curated, source-linked items; the bundled olympiad list is currently empty.

## Deliberately absent

- MAX-specific admission, policy or eligibility calculations; admission-fit decisions are requested from Andromeda.
- Direct Bot or Mini App imports of Python, SQLAlchemy, PostgreSQL, Jev or LLM provider code.
- MAX-account linking or implicit applicant-profile collection.
- Server-side synchronization of Mini App EGE scores, shortlist and progress.
- A second conversation backend, transcript store, queue, database or microservice.
- A Mini App assistant or MAX notifications connected to the Bot.
