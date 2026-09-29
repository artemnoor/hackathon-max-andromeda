# Andromeda upstream snapshot

- Source repository: `https://github.com/artemnoor/andromeda`
- Imported source commit: `e8118b611220320f17ab60e936455680441e004d`
- Source commit date: 2026-09-28
- Snapshot import date: 2026-09-29
- Strategy: copy the tracked working tree at the pinned source commit into `services/andromeda/`; no Git submodule and no nested Git metadata.
- Excluded from the snapshot: `.git/`, all `.ai-factory/` planning artifacts, and the upstream root `.github/` workflows (the monorepo owns its CI orchestration).
- Canonical Public API v1 snapshot at import: `services/andromeda/openapi.json`
- Canonical OpenAPI SHA-256 at import: `440c74bd4206e0e011866c7112f57b28059c6f59a66ec8695a588f0025769c44`

## Updating the snapshot

1. Fetch and inspect an exact upstream commit; record its SHA and review the source diff before copying.
2. Import tracked source files under `services/andromeda/`, excluding `.git/`, `.ai-factory/`, upstream root CI, secrets and generated runtime artifacts. Do not overwrite monorepo root files or `apps/max/`.
3. Update this provenance record and regenerate the Public API client if the canonical contract changed.
4. Run the Andromeda component gate, MAX gate, contract drift checks, architecture-boundary checks and monorepo CI before merging.
5. Keep the upstream repository unchanged. Resolve source/monorepo conflicts explicitly; do not use an unreviewed force sync.
