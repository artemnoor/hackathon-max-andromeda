# Universal educational analytics

Andromeda keeps canonical university data as its source of truth and adds two
rebuildable layers on top:

```text
official sources
  → ingestion → canonical entities
  → semantic enrichment → program projections
  → typed AnalyticsExecutor → QuerySpec result
  → ConversationEngine / ResponseEnvelope → Public API v1 → Web / MAX Bot
```

The canonical layer remains `University`, `Direction`, `Program`, `Curriculum`,
`CurriculumItem`, `Discipline`, admissions, provenance and source gaps. The
semantic layer is independent from the existing 22-code discipline taxonomy:
area weights describe academic composition, while semantic features describe
non-exclusive signals such as mathematics, programming, AI, theory and
practice. Item-level values override discipline defaults when the same name has
different meaning in different curricula.

`ProgramProjection` is the common analytical read model formerly represented
by the proftest fingerprint. The compatibility fingerprint import remains
available, but analytics owns projection building and persistence. Normal
queries read `program_projections` and `program_metrics`; they do not rebuild
curricula at request time.

Projection rebuilds consume the semantic run change-set. A no-op semantic run
does not reclassify or rebuild curriculum projections. Analytics results use a
bounded process-local LRU cache keyed by the typed query, registry version and
projection schema; affected program IDs invalidate matching entries after a
successful rebuild. The cache is an optimization only and can be cleared or
recreated without affecting canonical data.

## Module ownership

- `modules/semantic` owns versioned classification contracts, deterministic
  enrichment and semantic ports.
- `modules/analytics` owns projections, metric registry, basis selection,
  bounded `QuerySpec`, aggregation and explainable `AnalyticsResult`.
- `modules/entity_resolution` owns canonical entity/metric resolution and
  explicit ambiguity states.
- `modules/conversation` owns `QuerySession`, deterministic parsing,
  continuation and compilation into analytics/admission requests.
- `modules/presentation` owns `ResponsePolicyPort`, `ResponseEnvelope` and
  `ReportSpec`; channels only serialize or render these contracts.

`DecisionPolicyPort` and `ResponsePolicyPort` are the Jev seams. The current
implementations are deterministic and have no Jev/LLM imports. A future Jev
adapter receives typed state/capabilities and returns typed decisions; it
cannot emit SQL or bypass the metric registry.

## Public seams

- `POST /analytics/query` accepts a strict typed analytics request without NLP.
- `POST /assistant/query` accepts text plus optional `sessionId` and
  `expectedRevision`, and returns clarification or a complete envelope.
- Web uses `queryAssistant` and the `AssistantPage`; the current MAX Bot sends
  text to the same public `/assistant/query` operation and renders its typed
  envelope. The Mini App uses catalog and admission routes rather than the
  assistant operation.

All result values retain basis, coverage, confidence, quality status,
provenance, semantic/classifier versions and evidence references. Missing data
is represented as partial/insufficient/unavailable, never as zero.
