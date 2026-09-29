# Contributing

Read the repository and nearest component `AGENTS.md` before editing. MAX work belongs under `apps/max/`; Andromeda work belongs under `services/andromeda/`. Keep the HTTP Public API v1 boundary between them and generate MAX types from the canonical Public OpenAPI snapshot.

Run the narrowest relevant component checks first. Before opening a change, run the root contract/architecture checks and the component verification documented in each application's README. API changes also require OpenAPI snapshot and generated-client drift checks. Use deterministic fixture data in CI and local tests; report optional live-provider checks separately.

Keep commits scoped. Do not stage environment files, `.ai-factory/`, build output, test recordings with personal data, or unrelated workspace changes.
