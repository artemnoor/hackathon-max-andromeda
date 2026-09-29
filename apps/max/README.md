# Hackathon MAX Andromeda

MAX Bot is a transport for Andromeda's existing Public API v1. Incoming free text, including example-button prompts, goes through \`POST /api/v1/assistant/query\`; question interpretation, clarification, admission logic, policy resolution, evidence and response modes stay in the Andromeda backend.

\`\`\`text
MAX Bot ──┐
MAX Mini App ──┼── HTTP / Public API v1 ── Andromeda backend
Web ──────┘                                ├── PostgreSQL and domain services
                                           ├── deterministic policy/admission logic
                                           └── Jev / optional backend verbalization
\`\`\`

The MAX SDK is confined to \`src/max/platform\`. Bot HTTP types come from the generated client in \`src/andromeda/generated/public-api.ts\`, whose canonical source is \`services/andromeda/openapi.json\`. MAX does not import backend Python, database, Jev or LLM code.

## Working Bot behavior

- \`/start\` and \`/help\` show four fixed message prompts: find a program, compare programs, ask about admission, or ask about rules and benefits.
- Every ordinary text message uses the same assistant API operation. Clarification options become bounded message buttons; other answers are rendered from typed response text, status, evidence summaries and action labels.
- Long replies are split at UTF-8 code-point boundaries. Internal response \`data\` and \`metadata\` are never sent to MAX.
- A server-side Redis mapping stores only the opaque Andromeda guest profile cookie, QuerySession ID/revision and activity time. MAX user IDs are hashed into Redis keys and are never treated as Andromeda identities.
- MAX does not collect profile fields implicitly, link accounts, make admissions decisions, or call Jev/DeepSeek directly.
- The Mini App remains a static, authenticated-launch shell. It does not yet present Andromeda product data or use the Public API.

## Local development

Use Node.js 22 or newer. Copy [\`.env.example\`](.env.example) to \`.env\`, set \`MAX_BOT_TOKEN\`, and set \`ANDROMEDA_API_BASE_URL\` to a reachable local or HTTPS Andromeda Public API v1 server. Start Redis and Andromeda using their development instructions, then run:

\`\`\`powershell
npm ci
npm run dev:bot
npm run dev:miniapp
\`\`\`

The Bot uses MAX polling in development by default; protected deployments use webhook and TLS Redis. The four message prompts need no scenario-specific routes. DeepSeek verbalization is optional and configured only on the Andromeda backend; without its feature flag/key, deterministic response text remains available.

For repo-wide checks and the fixture-backed stack, use the root [monorepo guide](../../README.md). For security boundaries see [security](docs/security.md); for test commands see [testing](docs/testing.md), and for hosted configuration see [deployment](docs/deployment.md).

Never commit \`.env\`, MAX tokens, guest cookies, update bodies or applicant data.
