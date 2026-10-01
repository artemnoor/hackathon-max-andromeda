# Query flow

The typed path for an analytical question is:

```text
natural language
  → deterministic parser and registered typed policy-query path
  → entity/metric resolution
  → QuerySession slot merge
  → DecisionPolicyPort
  → typed QuerySpec
  → QuerySpec validation + MetricRegistry
  → AnalyticsExecutor + repositories
  → AnalyticsResult + evidence
  → ResponsePolicyPort
  → ResponseEnvelope
```

`QuerySpec` contains entity, metrics, scope, canonical filters, aggregation,
sort and a bounded limit. It cannot carry SQL. Unsupported metrics,
aggregations and ambiguous entities are typed errors/states.

Admission questions use the same conversation state but compile to the existing
`BatchAdmissionFitRequest`; they do not create a second admission system.
Missing subject scores produce `ASK_FOR_EXAMS`; missing university scope
produces `ASK_FOR_UNIVERSITY_SCOPE`. Query sessions are owner-bound, persisted
with optimistic revisions and expire after the configured TTL.

Evidence can be followed from `AnalyticsResult` to projection metric, semantic
item feature, curriculum item, source link and captured source snapshot. The
channel receives the explainable envelope, not ORM objects or raw source bodies.

## Source-backed policy questions

Policy questions use the existing conversation session, `DecisionPolicyPort`,
`/assistant/query`, and `ResponseEnvelope`. There is no second assistant
backend. The current path handles registered claim predicates, source-stage
questions, explicit cycle applicability, historical/as-known-at lookup, and
two-cycle comparison. Unsupported topics are marked outside coverage; missing
source assertions are not reported as negative facts.

```text
user question
  → existing conversation parser + typed QuerySession context
  → canonical entity and admission-cycle resolution
  → knowledge claim/change lookup
  → approved-only deterministic Effective Rule Resolver
  → applicability + mandatory structured ResolutionTrace + evidence
  → for admission benefits: exact complete owner revisions + explicit applicant facts
  → existing AdmissionDecisionService + typed result, or fail-closed missing-data codes
  → existing ResponseEnvelope
  → channel-neutral Public API v1 → Web / MAX Bot
```

The resolver reads only an explicitly human-approved exact revision and returns
a structured trace with considered/filtered rules and precedence decisions.
Unresolved conflict, cycle mapping, valid time or scope blocks effective rules.
For admission-benefit impact, `QuerySession` can retain a typed applicant
context for its configured TTL. The owner adapter checks that the exact hashes
selected by policy equal the complete active rules for the target program and
that source coverage is complete, then delegates to the existing
`AdmissionDecisionService`. It requires explicit completeness declarations for
the applicant-fact dimensions relevant to the selected rules. Missing facts,
partial owner coverage, mixed domain owners or unsupported owners return
structured blocked/unavailable states; absence never becomes a negative
eligibility result. Other domain owners remain unavailable until their own
typed evaluator bridge is composed. The existing `admission_benefits`
evaluator remains the sole benefit calculator. Jev knowledge/policy operations
are not registered. The optional verbalizer seam can only choose a validated
ordering of typed response sections; the default response is deterministic
and no freeform LLM provider is wired.
