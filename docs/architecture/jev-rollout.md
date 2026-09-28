# Jev rollout and security gate

## Current release state

Andromeda ships with deterministic decision and analytics behavior. `JEV_*`,
`JEVQL_*` and `JEV_TREE_*` capabilities are disabled by default. The official
TypeSafe Python SDK is an optional `jev` extra; it is not imported by the core
composition unless a validated capability is explicitly enabled.

The current production calibration artifact
`next-action.typesafe-jev.v2.lock.json` covers only `next-action.v1` using
`next-action-definition.v2`; it does not enable Jev intent, metric, semantic,
presentation, or admission-profile decisions. It was built from 120 live
provider responses to a synthetic typed-state corpus (56 held out) using
upstream `jevcal` 0.1.0. The measured accuracy was 100% on the captured corpus
and held-out split, with 100% held-out coverage; upstream selected threshold
`0.64` (measure `top_prob`). A first v1 instruction set scored 75% and was
superseded; its artifacts are retained only as audit evidence. These results
are limited evidence for this definition, typed-state corpus, provider route,
and observed model version `jev-1.13.0`, not a claim that all Jev operations or
natural-language understanding are production-calibrated.

The runtime still validates schema, action availability, and state applicability
after the upstream confidence gate. Unsupported actions fall back to the
deterministic policy. The production lock is bound to the registry hash and
observed model version, so definition/model changes fail closed. The fixture
lock remains fixture-only. System One Adapter and jev-align remain
evaluation/development tools.

## Enablement gates

Before enabling `JEV_ENABLED=true`, all of the following must be available:

- a rotated `TYPESAFE_API_KEY` (or the `JEV_API_KEY` alias) in a secret manager;
- allow-listed TypeSafe-compatible provider health and observed model version
  (the validated Polza route is `https://polza.ai/api`);
- a current Question Registry and production-ready calibration lock;
- a current production lock with per-definition held-out evidence; runtime
  confidence acceptance is delegated to upstream `jevcal.runtime.Cascade`;
- bounded timeout/retry/concurrency and a tested deterministic rollback;
- security/license/package review and an owner for provider spend and outages.

`JEV_SHADOW_ENABLED=true` may run without changing the deterministic response,
but still requires provider credentials and health. A provider error, invalid
schema, missing lock or unavailable optional package returns deterministic
behavior and a safe capability reason.

## Data and security boundary

Canonical source facts and PostgreSQL calculations remain authoritative. Jev
receives sanitized, bounded state and registered typed questions. Model output
is untrusted: it is schema-validated, restricted to allow-listed actions,
metrics, templates and canonical candidate IDs, and never becomes SQL,
repository code, an endpoint or an explicit user fact.

The TypeSafe transport logs only operation/definition/provider metadata,
latency, bounded usage and fallback reason. Session IDs are hashed in shadow
telemetry; cookies, API keys, raw profiles and unrestricted user text are not
logged. Endpoint values are environment-controlled and allow-listed, never
copied from user input.

## Optional runtimes

The common analytics path reads materialized projections and the MetricRegistry.
jevQL is considered only for an explicitly registered, bounded semantic
predicate that materialized metrics cannot answer; unavailable rows stay
unknown rather than becoming false. The upstream Python SDK owns both embedded
and shared jevQL transports. jev-tree is a Node 22 isolated bridge
used only after deterministic narrowing and a candidate threshold above 255;
ordinary program comparisons do not call it.

## Rollback

1. Set `JEV_ENABLED=false`, `JEV_SHADOW_ENABLED=false`, `JEVQL_ENABLED=false`
   and `JEV_TREE_ENABLED=false`.
2. Restart the backend and verify the deterministic capability report.
3. Keep canonical ingestion, semantic projections and analytics available.
4. Re-run the assistant/admission/analytics smoke scenarios and inspect safe
   fallback telemetry.

No database migration is required for this stage. The existing Alembic head
and canonical source schema remain unchanged.
