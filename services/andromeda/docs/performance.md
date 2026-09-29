# Performance evidence

MVP performance work is evidence-driven. The repository keeps bounded limits
in public contracts and does not introduce a cache or a latency target without
a representative PostgreSQL measurement.

## PostgreSQL read profile

Against a disposable PostgreSQL database at the current Alembic head:

```powershell
$env:ANDROMEDA_POSTGRES_TEST_URL = "postgresql+psycopg://..."
python backend/scripts/profile_queries.py --out $env:TEMP/andromeda-query-profile.json
```

The diagnostic runs fixed, read-only `SELECT` statements for catalog,
curriculum, admissions, comparison, proftest catalog, events, campus and
admin runs. It records `EXPLAIN (FORMAT JSON)` and one bounded timing sample;
the database target is redacted. It does not run `ANALYZE`, mutate data, or
emit query parameters.

## Ingestion memory profile

The fixture parser profile records source bytes, canonical row counts and
`tracemalloc` peak for BMSTU or HSE without writing to the database:

```powershell
python backend/scripts/profile_ingestion_memory.py --university bmstu
python backend/scripts/profile_ingestion_memory.py --university hse
```

Runtime ingestion logs the same safe source-byte/count metrics together with
projection duration and run ID. Raw bodies, credentials and payload contents
are never logged.

## Current measured finding

`SqlAlchemyCurriculumRepository.get_for_program` previously selected
assessment rows once per curriculum item. The reader now loads all assessment
rows for the selected curriculum in one bounded query; the regression is
covered by `backend/tests/infrastructure/test_query_behavior.py`.

Future index or cache changes must attach a before/after profile artifact and
preserve completed-run/source-version invalidation semantics.

## Materialized analytics profile

Stable semantic values and program metrics are materialized after ingestion;
request-time analytics reads active projections and performs bounded typed
aggregation. The fixed grouped benchmark measures the real
`AnalyticsExecutor` path for “mean mathematics share by university” and
reports query count, population, coverage and duration without exposing rows:

```powershell
python backend/scripts/profile_analytics.py `
  --database-url $env:ANDROMEDA_POSTGRES_TEST_URL `
  --out $env:TEMP/andromeda-analytics-profile.json
```

`profile_queries.py` supplies the complementary read-only `EXPLAIN (FORMAT
JSON)` plans. The repository prefilters active projections and metric
thresholds in SQL and batch-hydrates metric/evidence rows. Analytics tests
guard against full-catalog Python rebuilds and N+1 evidence reads.

The fixed profile also includes the bounded policy revision scan and current
approved knowledge-source registry scan. The policy repository reads approval
events, source claims, evidence, relations and observations in bounded batches;
`backend/tests/infrastructure/test_knowledge_candidate_repository.py` guards
that three approved revisions are hydrated in a fixed six `SELECT`s instead of
one query per revision. A 500-revision batch is chunked at 400 composite keys
per query to remain below conservative SQLite bind-parameter limits. This is a
query-count guarantee, not a latency guarantee.

Knowledge capture and graph limits are recorded in the
[knowledge-policy operations runbook](operations/knowledge-policy-runbook.md).
No GIN/range index, materialized graph, or cache is enabled. Use a sanitized,
representative PostgreSQL database and save the profile artifact before adding
indexes or changing caps. PostgreSQL `EXPLAIN` is the DB-plan authority; SQLite
tests establish portable behavior and bounded query count only.

No universal latency SLA is claimed before a representative PostgreSQL
artifact exists. The benchmark artifact is versioned by metric registry and
projection schema; a regression is a release signal, not a reason to increase
limits or skip a case.
