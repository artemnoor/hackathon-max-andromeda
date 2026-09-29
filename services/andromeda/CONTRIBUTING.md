# Contributing

1. Install backend dev dependencies and frontend dependencies from the getting-started guide.
2. Keep domain modules independent of FastAPI, SQLAlchemy and university-specific parsers.
3. Add a new university through `SourceAdapter`, the ingestion registry, official raw fixtures and canonical/provenance tests.
4. Never edit an applied Alembic revision. Add a new migration and test upgrade from the previous schema.
5. After API contract changes export OpenAPI, regenerate `frontend-next` types and run API drift checks.
6. Run focused tests while working, then the full backend, mypy, frontend unit/lint/build and relevant browser/PostgreSQL checks.

PR checklist: source-backed facts only, no secrets or fake fixtures, optimistic revisions preserved, source gaps explicit, migrations reversible where possible, tests and documentation updated.
