# Semantic and catalog analytics

Andromeda separates four kinds of information:

1. official source facts in canonical entities;
2. derived semantic signals for disciplines and curriculum items;
3. deterministic program projections and analytics results;
4. explicit user choices and conversation state.

Semantic signals do not replace source facts. They are versioned, rebuildable
derived data and can be `available`, `unknown` or `unavailable`. Missing data
is never converted to numeric zero.

## Data flow

```text
source snapshot → raw/normalize/validate → canonical entities
  → semantic enrichment → ProgramProjection/ProgramMetric/evidence
  → typed QuerySpec → AnalyticsResult → ResponsePlan
```

The canonical layer remains the source of truth. Semantic and projection rows
carry taxonomy/classifier/projection versions, source hashes, ingest run IDs,
provenance and source gaps. `backend/scripts/rebuild_semantics.py` rebuilds
one university from a completed canonical ingest run; `--dry-run` prints a
content-light input hash and counts before writing anything.

## Broad areas versus semantic features

`DisciplineAreaCode` and `DisciplineAreaWeight` remain the broad academic
composition taxonomy. Their weights may form a distribution across areas.
`SemanticFeature` is independent and non-exclusive: a discipline or item can
have mathematics, programming, AI and practical signals at the same time.

Reusable discipline defaults are stored separately from context-specific
`CurriculumItemSemanticFeature` values. An item-level value can therefore
override the meaning of a same-named discipline in another curriculum. Every
value records method, confidence, review status, definition/classifier
versions, evidence and provenance. The deterministic rule classifier is the
default; model-assisted classification is an adapter and never a canonical
ingestion dependency.

## Metrics and query contract

`MetricRegistry` is the allow-list for supported metrics, entities,
aggregations, units, basis and missing-data policy. Examples include
`math_share`, `programming_share`, `ai_share`, `physics_share`,
`math_first_year_share`, `first_programming_semester`, `total_hours` and
admission metrics. A caller supplies a typed `QuerySpec`; raw SQL, arbitrary
metric names and unbounded limits are rejected.

Each `AnalyticsResult` exposes status, population, included/missing counts,
coverage, confidence, basis, semantic/classifier versions, provenance,
source gaps and metric explanations. Grouped averages use all eligible
materialized projections in the requested scope, not a representative
program.

## Rebuild and rollback

The safe operator order is:

```text
Alembic schema → semantic registry → semantic enrichment
→ program projections → typed analytics read path
```

The rebuild command is idempotent for the same ingest/taxonomy/classifier
versions. It skips unchanged item source hashes and refreshes only affected
projections. Use `--retry-of-run-id` when retrying a failed derived run. A
failed derived run leaves canonical data committed; disable the new derived
read path or keep the last-good projection version, then retry. An Alembic
downgrade is a schema operation and is not the production rollback mechanism
for canonical data.

## Jev and transport seams

`DecisionModelPort` is provider-neutral. `RuleBasedDecisionModel` is the
deterministic implementation used by default. `JevDecisionModelAdapter`
validates bounded typed output, allow-listed actions/templates/metrics,
timeouts, retries, output size and circuit state before falling back. It does
not execute SQL or write canonical data.

`ResponsePlan` and `ResponseEnvelope` are channel-neutral. Web and future
Public API v1 clients receive the same result/evidence contract; they do not
recalculate metrics or make business decisions. See [the integration seams](architecture/integration-seams.md).

## Separate source-backed policy ontology

The curriculum `SemanticFeature` vocabulary and `SemanticReviewWorkflow` remain
specific to curriculum meaning and classifier artifacts. The source-backed
`knowledge`/`policy` modules have different objects and lifecycle: source
claims, immutable rule revisions, exact-revision human approval, temporal
applicability and a deterministic `ResolutionTrace`. They reuse the semantic
workflow's review and provenance principles, but do not reuse curriculum
taxonomy tables, classifiers or semantic publish as the policy approval gate.
The runtime boundary and capabilities are described in the [Knowledge and
Policy architecture](architecture/knowledge-policy.md). Missing applicant
impact/domain calculations remain typed unavailable states; the policy module
does not implement a second admission-benefit evaluator.

## Operator checks

```powershell
python backend/scripts/rebuild_semantics.py --university university:bmstu --dry-run
python backend/scripts/profile_analytics.py --database-url $env:ANDROMEDA_POSTGRES_TEST_URL --out $env:TEMP/andromeda-analytics-profile.json
python backend/scripts/profile_queries.py --database-url $env:ANDROMEDA_POSTGRES_TEST_URL --out $env:TEMP/andromeda-query-profile.json
```

The profiles report bounded counts/timing/plans and redact the database target;
they do not include source bodies, credentials, cookies or raw user text.
