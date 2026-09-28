# Knowledge and policy operations

Status: current bounded implementation; source coverage and approval staffing
are deployment responsibilities, not pre-seeded product data.

## Ownership and default state

- A `source_steward` approves versioned source registry revisions and allowlists.
- An authenticated `policy_steward` reviews exact policy revisions. University
  editors may submit scoped candidates but cannot approve them.
- The deployment operator owns the external schedule, credentials, PostgreSQL
  health and run alerts.
- The knowledge-source registry and reviewer allowlists can be empty. An empty
  registry is a valid cold start and means no source coverage is claimed.
- Polling creates observations, immutable snapshots, claims and pending review
  work only. It cannot approve or activate a policy revision.
- `ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED` defaults to `false`; policy
  queries return `outside_coverage` until an operator explicitly enables the
  read path after review. Source polling and reviewer endpoints have separate
  authorization and do not depend on this assistant flag.
- Jev policy operations, shadow predictions and assisted selection remain off.
  No Stage 2 calibration lock or rollout flag is changed by this feature.

## Bounded source polling

The poller is a one-shot command. A deployment scheduler may invoke it on an
operator-approved cadence; Andromeda does not start an implicit crawler or
background scheduler.

```powershell
python backend/scripts/discover_knowledge_sources.py --max-sources 100 --log-level INFO
```

The command reads only enabled, approved registry revisions and returns a
redacted run summary. Do not pass user-supplied URLs or credentials. Follow the
API's source registration workflow and allowlist controls to provision a
source. The command's `canonicalProjectionChanged` result must remain false.

| Boundary | Enforced limit | Behavior at the boundary |
|---|---:|---|
| Enabled registry | 500 sources | Repository rejects a larger registry read |
| Sources per invocation | 100 | Due sources beyond the batch are deferred |
| Minimum poll interval | 300 seconds | Registry contract and database constraint reject a shorter interval |
| Fetch attempt | 30 seconds per request; 90 seconds total by default | Retry is bounded; total fetch budget is enforced |
| HTTP retry | 2 retries by default; exponential delay 0.8–8 seconds; `Retry-After` capped at 10 seconds | Failure is recorded and retried later |
| Redirects | 5 by default | Every hop must pass HTTPS, host/path allowlist and public-IP checks |
| Response body | 30,000,000 bytes by default | Truncated bodies are rejected as source captures |
| HTML decode | 30,000,000 bytes | Only the bounded decoded prefix reaches the parser |
| PDF parse | 500 pages; 100,000 characters per page; 2,000,000 characters total | Over-budget documents become review/extraction failures |
| Plain text / extracted HTML | 2,000,000 characters | Excess content is not staged beyond the parser cap |
| Claims staged per poll | 500 | Contract and persistence constraint bound extraction output |
| Source poll retries | 10 attempts; backoff capped at 86,400 seconds | The latest successful snapshot hash is retained on failure |

An unchanged hash creates a new observation but does not create duplicate
claims. A changed hash stages candidates; it never retires a claim by absence.
A 404 records the source as removed while retaining the last successful
snapshot for audit. An unavailable source retains its last-good hash and makes
freshness explicit.

## Review and activation

1. Inspect the source health and poll-attempt outcome before examining claims.
2. Review the exact captured snapshot, evidence locator and typed assertion.
3. Compare candidate diff, any conflict diagnostics, scope, source lifecycle
   statement and proposed admission-cycle mapping.
4. Preview both resolver traces and domain-owner impact. Incomplete impact,
   an unresolved resolver conflict, a persisted open policy conflict, stale
   preview hash, or missing evidence must block approval.
5. Approve or reject the exact content hash as an authenticated human. A later
   edit creates a new pending revision and requires a new preview and decision.

The `EffectivePolicyResolver` reads only revisions with an explicit approved
ledger event bound to that exact hash. Do not infer approval from source
reliability, accepted claim status, an `ACTIVE` domain rule, Jev output, or a
successful parser run. Domain calculations remain in the existing owner module
(including `admission_benefits`).

Before an existing database is adopted for this policy flow, inventory legacy
source links with the report-only command:

```powershell
python backend/scripts/report_knowledge_provenance.py
```

The command reports snapshot/run linkage, field-level document locators and
exact admissions-owner hashes. It issues only `SELECT`s and never repairs
rows. Stage 2 admission-benefit rows already carry immutable snapshot hashes,
source-run attribution and parser locators; the new source registry does not
establish historical source trust or policy approval. Any missing field needs
source-owner review, while unavailable source identity, old legal dates and
system-time history remain unknown.

For a conflict, missing cycle, unknown scope, incomplete provenance, stale
domain-owner revision, or unavailable owner calculation, leave the result
blocked/indeterminate and use the structured `ResolutionTrace` to identify the
reason. Do not resolve by timestamp or database row order.

### Persisted conflict review capability

Conflict-group creation and human resolution are disabled/not yet enabled in
this rollout. The review queue can show conflict participants already present
in persistence, and the approval service checks persisted open policy conflicts,
but production ingestion does not create conflict groups and the review API has
no conflict-resolution action. A missing conflict row is not evidence that
there is no disagreement. Resolver/assistant ambiguity remains fail-closed;
operators must not mark a conflict resolved through direct database edits.

## Security and logs

- Source URLs must be HTTPS on port 443 and match the approved host and path
  allowlist. Credentials in URLs, private/reserved IPs, unregistered adapters,
  unsafe redirects and arbitrary Python adapter names are rejected.
- Manual source URLs are validated against a registered allowlist; they are not
  dereferenced by the manual submission endpoint.
- Raw bodies, applicant profiles, cookies, tokens and secrets must not be
  logged. Logs may include source IDs, counts, bounded failure codes and a
  short hash prefix; URLs must be redacted of query and fragment data.
- Review endpoints require authenticated account capabilities. University
  scope does not grant central policy approval.
- The rule selector is a closed typed AST. It has no `eval`, `exec`, SQL or
  arbitrary provider code path.

## Database and performance checks

Current persistence uses relational IDs, foreign keys, unique/check
constraints and btree indexes for source observations/poll attempts, policy
scope/lifecycle, recorded/effective time, target relations, claim identity and
review state. Bounded selector/extraction payloads may use JSONB; query keys and
temporal fields stay relational. There are no GIN/range indexes or graph
materializations pending representative evidence.

Before changing limits or indexes, point the read-only profile at a sanitized
PostgreSQL database at the current Alembic head:

```powershell
$env:ANDROMEDA_POSTGRES_TEST_URL = "postgresql+psycopg://<redacted>"
python backend/scripts/profile_queries.py --out $env:TEMP/andromeda-query-profile.json
```

The profile records `EXPLAIN (FORMAT JSON)` and one bounded timing sample for
catalog, admissions, analytics, source registry and policy revision scans. It
does not use `ANALYZE`, mutate data or output query parameters. Keep the
redacted JSON artifact with the release evidence. SQLite repository tests
guard semantics and query-count bounds, but do not establish PostgreSQL plans,
lock behavior or production latency.

## Recovery and stop conditions

- On repeated source failure, inspect `failure_code`, `retry_count`,
  `next_retry_at` and the retained last-successful hash. Fix the registry or
  adapter, then let the bounded retry cadence recover; do not clear history.
- On candidate parser changes, the same unchanged snapshot can be reparsed by
  the versioned parser. Compare the new candidate set before review.
- On refresh failures, retry the immutable refresh request after inspecting
  typed blockers. A failed refresh must not expose stale derived policy as
  current.
- Stop activation if an approved resolver trace differs from the reviewed
  preview, if the exact owner hash changed, if any required source is stale, or
  if impact output is truncated/incomplete.
- Roll back the user read path by setting
  `ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED=false`; separately clear the
  relevant reviewer/steward capability allowlists to stop new human writes.
  Additive schema and audit history remain; do not delete snapshots, approval
  events or projection attempts.
