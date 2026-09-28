# Integration seams

## Stage 2 execution baseline

Stage 2 execution baseline for the source-backed policy plan is
`1f5777c892c2daf2f6f11a405bc19268b7dc0c88` on
`feature/jev-ecosystem-stage-2`. It contains the implemented Jev runtime and
current integration seams described below. Recheck the branch's current remote
head before later work. The earlier `feature/university-admin-control`
worktree was dirty during research and is not a runtime or implementation
baseline.

## Jev

Jev integration is optional infrastructure behind typed ports. The default
runtime is deterministic and must remain usable when every external provider
is unavailable. The production decision client is a TypeSafe-compatible
adapter; System One Adapter is evaluation-only and must not be used as the
production client.

Implemented now:

- `TypeSafeJevTransport` → `JevDecisionModelAdapter` → `DecisionModelPort`;
- `ModelBackedDecisionPolicy` and `ShadowDecisionPolicy` → `DecisionPolicyPort`;
- `JevQLAdapter` → `SemanticPredicatePort`;
- `JevTreeAdapter` → `HierarchicalSelectionPort`.

`SemanticClassifierPort` and `ResponsePolicyPort` remain deterministic in the
default composition; future provider adapters must use the same typed seam.

These adapters belong at the composition/integration boundary. Domain,
analytics, admissions and presentation contracts must not import a Jev SDK.
The deterministic implementations remain the testable default.

The shared Question Registry owns operation instructions, criteria, version,
input/output schema and calibration identity. Tool-specific settings stay in
their own validated configuration:

- jevcal: dataset splits, upstream calibration and lock generation;
- jev-align: upstream acquisition/GEPA, review, proposal and rewind settings;
- jevQL: engine mode, budgets, cache and SDK endpoint settings;
- jev-tree: candidate threshold, tree limits and Node runtime settings.

No model output may provide SQL, a repository handle, an endpoint, a template
name or a user fact. The only application-facing boundary is a typed
DecisionModelPort/semantic/resolution port. External responses are
schema-validated and failures fall back to deterministic behavior with a
typed reason.

### Upstream strategy

| Project | Strategy | Boundary |
|---|---|---|
| jevcal | DEV/EVAL_TOOL | Offline calibration and immutable lock artifacts |
| jev-align | DEV/EVAL_TOOL | Human-reviewed semantic proposals and versioned imports |
| System One Adapter | DEV/EVAL_TOOL | Baseline/evaluation reports only |
| jevQL | ISOLATED_OPTIONAL_RUNTIME, embedded-first | `Jevql()` private embedded engine, or `Jevql(url=..., token=...)` shared service |
| jev-tree | ISOLATED_OPTIONAL_RUNTIME | Node adapter only after deterministic narrowing and large-candidate threshold |
| awesome-jev | PATTERN_ONLY | Curated reference list, no runtime dependency |

The common analytics path is materialized metrics and deterministic SQL
aggregation. jevQL may run only for an explicitly registered,
non-materialized semantic predicate with bounded rows and evidence. jev-tree
must not be called for ordinary small candidate sets, including a comparison of
twenty programs.

Production flags are disabled by default. Enabling a provider requires a
validated definition, an immutable calibration lock, health/version checks,
bounded timeout/retry/rate budgets and a tested rollback path.

## State ownership

DecisionContext stores explicit user choices for shortlist/decision flows.
QuerySession stores conversation state, including explicit, inferred and
model-candidate origins. decision_analytics is operational/user-action
telemetry and is not catalog analytics or a source of domain truth.

## Knowledge and policy seams

The runtime contains logical `knowledge` and `policy` modules within the
modular monolith. `knowledge` owns versioned allowlisted registry revisions,
source observations, claims/change candidates, evidence links and review
actions. Raw immutable snapshots remain owned by the Stage 2 ingestion
repository. `policy` owns typed selector/rule revisions, the exact-hash
append-only approval ledger, effective resolution, typed dependencies,
`ResolutionTrace`, and rebuildable impact/diff projections. The detailed
contracts and persisted ownership are in the [Knowledge and Policy
architecture](knowledge-policy.md).

The resolver reads only exact revisions with an explicit human approval event.
The first pending event is written atomically with a candidate revision; a
later UI action is not required to enforce the gate. Source discovery,
deterministic extraction, candidate normalization, review preview and what-if
remain non-canonical. The source poller is a one-shot command over approved
sources, not an automatically scheduled open crawl.

Existing subject modules retain calculations. `policy` may select an exact
`DomainRuleRef` and explain scope/precedence; it does not calculate BVI,
100-point rights, confirmation, validity or individual-achievement points.
Those results stay with the existing `admission_benefits` evaluator.

The conversation and presentation modules route supported policy questions
through the existing `/assistant/query` and `ResponseEnvelope`. Current impact
requests return a typed domain-result-unavailable state when no owner
calculation bridge is wired. The optional verbalizer receives only safe typed
section references and the default path is deterministic.

Knowledge/policy Jev operations are not registered. Existing Stage 2 Jev ports
remain reusable if a future, separately evaluated bounded operation is
approved. Current calibration locks and feature flags are unchanged; no Jev
policy callsite is implied here.

## MAX

MAX should send an update to `POST /assistant/query`, preserve the returned
`session_id`/`revision`, and map `ResponseEnvelope` to text, image, PDF,
buttons or a Mini App. It should not implement NLP, entity resolution,
analytics, admission fit or response selection.

## Public client boundary

Web currently uses the channel-neutral backend and Public API v1. A future MAX
Bot or Mini App should call the same versioned contract; conversation state,
entity resolution and domain decisions remain server-owned.

The signed frontend `/og/*` renderer remains as a generic server-side image
rendering capability. It fetches the same Public API v1 data and verifies
HMAC-authenticated requests. It is not a public API operation and no current
MAX transport is implemented.

## Web and OG

The Web `queryAssistant` client and `AssistantPage` use the same endpoint.
Existing OG routes retain HMAC/timestamp validation and server-side cookie
forwarding. New generic renderers must consume envelope data and evidence; they
must not query canonical repositories or recalculate metrics.
