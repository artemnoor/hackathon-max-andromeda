# Universal Analytics Dependency Direction

Этот документ фиксирует boundary для последующих semantic/analytics/conversation/presentation изменений. Andromeda остаётся modular monolith: новые контексты получают отдельные contracts/services/repository ports, но не отдельные deployment units.

## Current production graph

```mermaid
flowchart LR
  sources[External sources] --> ingestion[University ingestion adapters]
  ingestion --> canonical[Canonical entities and repositories]
  canonical --> proftest[Proftest fingerprint]
  proftest --> recommendations[Recommendations]
  proftest --> comparison[Comparison and decision consumers]
  admissions[Admission facts] --> admissionfit[Admission Fit]
  admissionfit --> decision[Decision candidate pipeline]
  recommendations --> decision
  canonical --> api[FastAPI routes]
  decision --> api
  api --> public[Public API v1]
  public --> clients[Web / future MAX clients]
```

## Known direction risks

- `ProgramFingerprint` принадлежит `proftest`, хотя его данные переиспользуются recommendations и decision.
- Comparison и proftest имеют пересекающуюся workload/area aggregation логику.
- External clients must not own program resolution, session flow or decision rules.
- OG routes имеют presentation-specific fetching/rendering boundary.
- Runtime catalog fingerprint building не масштабируется на 5,000+ программ.

## Target graph

```mermaid
flowchart LR
  sources[External sources] --> ingestion[Ingestion adapters]
  ingestion --> canonical[Canonical storage]
  canonical --> semantic[Semantic enrichment]
  semantic --> projections[Persistent analytical projections]
  projections --> engine[Typed Analytics Engine]
  engine --> conversation[Conversation Engine]
  policy[DecisionPolicyPort: RuleBased or Jev adapter] --> conversation
  conversation --> policy
  conversation --> admission[Existing Admission Fit and Decision]
  engine --> response[ResponsePolicyPort]
  response --> envelope[ResponseEnvelope]
  envelope --> public[Public API v1]
  public --> clients[Web / future MAX clients]
```

## Enforced rules

1. Canonical entities remain the source of truth; semantic assignments, projections and caches are rebuildable derived data.
2. Subject modules import another subject only through `contracts.public` or `repository.ports`.
3. ORM, SQLAlchemy, FastAPI, ingestion adapters and channel SDKs stay outside subject modules.
4. Query inputs are typed `QuerySpec` values; neither Jev, LLM nor a channel can submit raw SQL.
5. Policies return typed decisions and response envelopes; clients render them without owning business logic.
6. Jev and MAX are optional adapters. Their absence must not disable deterministic implementations or analytics domain tests.
