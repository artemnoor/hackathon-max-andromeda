# Knowledge and policy architecture decisions

Status: implemented bounded architecture on the Stage 2 baseline, reviewed
2026-09-26. This document describes runtime contracts and operational defaults;
it does not assert that a reviewer account, production source observation, or
broad source coverage already exists.

## Baseline and constraints

Implementation starts from the clean Stage 2 code baseline
`1f5777c892c2daf2f6f11a405bc19268b7dc0c88`. The implementation worktree adds
only the plan artifact commit `8fab087de2e438d8239d64b14290aab5fc345e45` before
runtime work. Alembic head at that baseline is
`0038_admission_offering_scope_and_exam_choices`; schema work remains additive
and must recheck the deployed head before each migration phase.

Andromeda remains one modular monolith, one backend, and one PostgreSQL
database. No policy service, staging service, graph database, Kafka, or second
assistant is introduced. Existing domain modules continue to own their
canonical facts and calculations. A missing source or unresolved interpretation
stays unknown, insufficient, or review-required; it is never converted to a
negative fact.

## Module ownership

Add two logical subject modules only:

| Module | Owns | Does not own |
|---|---|---|
| `knowledge` | Versioned allow-listed source registry; source observations and discovery health; claims and change candidates; review queue/workflow; evidence links and semantic diff proposals | Existing immutable raw snapshot persistence, domain canonical facts, effective policy selection, domain eligibility calculations |
| `policy` | Typed rule selector/revision contracts; immutable approval ledger; temporal/scope/precedence resolution; mandatory `ResolutionTrace`; policy dependencies and candidate impact projections | Source acquisition/parsing, review UI, BVI/100-point/confirmation/achievement calculations, user conversation state |

`knowledge` calls the existing ingestion capture and source-snapshot seam. The
existing `ingestion`/infrastructure adapters remain owners of raw capture and
snapshot persistence; they do not acquire claims or policy meaning. Canonical
admission facts stay in `admissions` and `admission_benefits`; curriculum
semantics stay in `semantic`; conversation state stays in `conversation`.
`change_intelligence` and a general `review` module are not created. The
existing semantic review workflow is reused for its review invariants, not as
the owner of policy approvals.

Dependency direction is through public typed contracts and repository ports:

```text
knowledge → ingestion capture/snapshot ports
knowledge → entity_resolution and registered Jev suggestion ports (optional)
policy → admissions cycle read contract
policy → domain-owner selector contracts (including admission_benefits)
conversation → knowledge/policy read contracts
composition/infrastructure → concrete repositories, adapters, and wiring
```

Subject modules do not import FastAPI, SQLAlchemy, concrete Jev SDKs, or
university parsers. PostgreSQL models remain in `andromeda.infrastructure`.

## Canonicalization and approval

The shared `Claim` is an assertion made by a source, not a universal fact row.
Claims may be grouped, contradicted, clarified, or linked to an existing
domain-owned fact. They remain candidate evidence until a domain owner accepts
the exact normalized revision. There is no catch-all canonical `facts` table.

Source reliability, policy lifecycle, and human approval are separate axes:

1. Reliability classifies the publisher/evidence (`primary_normative`,
   `official_issuer`, `official_university`, and later secondary tiers).
2. Policy lifecycle describes what the document says (`proposal`, `adopted`,
   `published`, `effective`, `future_effective`, `superseded`, and other typed
   terminal or unresolved states).
3. Approval records whether a human approved this exact immutable normalized
   revision. Official publication does not imply adoption, effectiveness, or
   approval.

The candidate model stores these axes without collapsing them.
`SourceReliabilityTier` remains on the approved source-registry revision and is
looked up through the capture observation; a `Claim` has no trust field.
`ClaimedPolicyStage` captures only what that source assertion says (for
example, `proposal` or `future_effective`), while `ClaimReviewState` says
whether that exact assertion still needs a human decision. An accepted source
assertion is not an approved policy revision and does not enter effective
resolution.

A `Claim` is an immutable source-observation assertion with a bounded typed
proposition, exact text span/hash, extraction method/version, source
milestones, valid/system revision clock, and one originating `EvidenceRef`.
Additional evidence is linked with an explicit stance (`supports`,
`contradicts`, or `qualifies`); its own registry trust tier is not copied onto
the claim. Proposition values use a finite discriminated set (text, decimal,
boolean, date, datetime, identifier); values do not execute as a rule DSL.
`ChangeEvent` references exact claim revisions and source observations, and
requires the relevant published/announced/adopted/effective milestone for its
typed event kind. Exact source assertions are grouped by the versioned
`exact_assertion:v1` fingerprint into a review-only candidate cluster. Every
source claim, observation and evidence locator remains a separate immutable
record in that cluster; the grouping does not merge evidence or assert truth.
Near-duplicates are never auto-clustered. A missing source yields a source
availability diff, not a claim removal. Semantic candidate diffs compare exact
assertion fingerprints and may show field changes only where one typed subject
match is unambiguous; untyped wording changes stay as separate added/removed
candidates. No newest-row choice is made.

The candidate repository appends only `unreviewed`/`needs_review` claims and
`needs_review` events after validating observation IDs, snapshot hashes,
timestamps and evidence URLs against the capturing allowlist revision. The
audited review service appends exact-hash decisions for claims, change events
and policy revisions; accepting a source claim records only that source
assertion and does not activate policy. Policy submissions require accepted
source assertions, exact source evidence, a typed selector, an owner-rule
reference and temporal contract. `PENDING_SUBMITTED` is inserted atomically
with the exact immutable policy revision and provenance links. The operator
queue, actions and read-only preview are wired through the existing `knowledge`
review seam.

The policy applicability service loads only through the approved-revision read
port, returns no selection for a pending or stale hash, preserves unknown
context as indeterminate, and checks the exact owner revision through a typed
port. The resolver also requires an approved admission-cycle mapping, explicit
valid-time input, and the exact approval state known at the requested system
time. It emits a content-addressed structured `ResolutionTrace` for every
result, including blocked requests and empty approved-rule scans. An empty scan
is indeterminate, never a claim that no rule exists. Temporal matching yields
candidates with independently evaluated explicit scope.
`EffectivePolicyResolver` groups candidates by approved family and applies a
deterministic partial order: exact source-backed supersession, amendment,
override or authorized-exception edges; legal authority at equal scope; and
registered specificity at equal authority. Orthogonal scopes, unresolved
authority, equal-precedence rules and authority/scope crossings remain conflicts
or indeterminate. A lower-authority narrow exception can prevail only through
an exact approved `AUTHORIZED_EXCEPTION_TO` edge. SQL row order and newest
timestamp alone never decide precedence. The final resolver emits only exact
`DomainRuleRef` selections for the owning module or a blocked/conflict result.
Each considered approved revision carries a typed reference to the exact
immutable `PolicyApprovalEvent` (event ID, rule/revision/hash, sequence and
recorded time). The reference is validated against that revision and included
in the bounded `ResolutionTrace`; approval cannot be inherited by another
revision.

Policy selector AST v1 is an applicability filter only. Its closed operators
(`all`, `any`, `equals`, `in`, `exists`) use registered typed context fields,
bounded tree/list sizes and canonical values. The selected `DomainRuleRef`
points back to the owning module's exact revision. The AST has no effects,
formula language or domain-specific calculation operators. PostgreSQL stores
the bounded AST payload as JSONB (portable JSON in SQLite tests); lifecycle,
scope, owner reference, time fields, source claims, evidence locators and
approval history remain constrained relational data. Any invalid or unknown
stored AST fails closed when read back.

The `policy` module owns an append-only approval ledger keyed by canonical rule
revision ID and content hash. Persisting a rule candidate/revision also appends
`PENDING_SUBMITTED` in the same transaction. Only a human with the central
`policy.approve_revision` capability may append an approve, reject, or withdraw
event, with actor, reason, timestamp, and exact revision hash. State is derived
from the ledger; it is not a mutable status column. The resolver queries exact
approved revisions only. A newly edited revision is pending again. Candidate,
extracted claim, Jev suggestion, or legacy `ACTIVE` benefit status alone can
never enter effective resolution.

Exact references to source-backed admission-benefit records are content-addressed
because Stage 2 stores immutable source-hash keyed snapshots but has no owner
revision counter. New `policy-rule.v3` references carry the hash of the normalized
owner contract; canonical hashing normalizes decimals and UTC instants and omits
mutable ACTIVE/STALE review state. The policy table stores this hash in
`owner_revision_hash` (migration `0051`). No second benefit revision table is
introduced. The existing owner repository confirms exact active revisions, and
the existing admission-benefit evaluators remain the only calculators. Older
v1/v2 rows remain readable; a benefit reference without the exact owner hash is
unsupported and cannot resolve effectively.

University `owner`/`editor` roles may submit or correct university-scoped
candidates under existing `university_admin` authorization. Those roles cannot
approve policy. Central `policy_steward` is a distinct capability assigned to
an authenticated human account; no individual is presumed or seeded by this
ADR. Until an authorized account is provisioned, approval writes fail closed
and no new effective revision can be activated. Shared ops API keys and
automated poller identities are not human approvers.

The bounded review API is exposed at `/ops/knowledge/review-queue` and
`/ops/knowledge/review-actions`, with the read-only hypothetical preview at
`/ops/knowledge/review-preview`; reviewer and policy-steward allowlists remain
separate and empty by default. Its queue is a read model over the knowledge and
policy owner repositories. Claim/event decisions are exact-revision and
audited; an accepted claim records an assertion review outcome only. Policy
preview compares one exact pending revision with one approved snapshot and
returns both `ResolutionTrace`s, effective diff, domain-owner impact, evidence
and uncertainty. The preview is read-only. Approval re-computes and matches the
exact fingerprint, requires a resolved candidate, complete domain-owner impact,
evidence and no unresolved/truncated conflicts. The existing
`PolicyApprovalCommandService` enforces these conditions for every approval
caller and appends to the existing policy approval ledger. The fingerprint is
stored with that owner event. No
provisional or unreviewed revision can reach the approved-only resolver.
Claim edits append a pending revision and cannot change subject kind or
canonical identity; identity resolution is a separate action that checks an
exact ID against a supported typed catalog. The internal SPA route is
query-based and omitted from applicant navigation.

Persisted knowledge conflict review is not enabled in this rollout. The queue
may display existing conflict participants as diagnostic metadata, and policy
approval checks for persisted open conflicts, but there is no production
conflict-group writer or reviewer resolution action. Contradictory or otherwise
unresolved evidence remains fail-closed in the resolver/assistant. Do not
interpret an empty conflict list as proof that no conflict exists.

## Temporal foundation

The new contracts keep four clocks separate: source publication, source
announcement/adoption, capture, and Andromeda's immutable `recorded_at`.
Missing milestones stay absent. A source's stated `effective_time` is retained
separately from a normalized policy revision's `valid_time`; normalization
requires explicit evidence and review. Datetime bounds are timezone-aware UTC
instants and valid-time intervals use the half-open convention `[start, end)`.
An absent valid-time interval means unknown, and contract evaluation returns
`None` rather than treating it as always applicable.

Policy/claim revisions are append-only. `recorded_at` begins each system-time
version; an as-known-at lookup chooses the latest recorded revision no later
than the requested instant. Earlier rows are not rewritten to invent a
`system_to` value. A document published on Dec 1, captured on Dec 15, and
effective Sep 1, 2028 can therefore be represented with all three instants
distinct. Cycle/application windows use inclusive civil dates because the
official admission documents state calendar days; they are not silently
converted from admission years or academic-year labels.

`admissions` owns `AdmissionCycle`, keyed by university and admission year,
with a separately sourced `academic_year`, optional application/enrollment
date windows, lifecycle state, field-level `EvidenceRef`s, approval actor and
reason, and immutable revision time. A lookup at a date before the first
approved revision returns `BLOCKED_BY_MISSING_DATA`. It never maps
`admission_year=2028` to `academic_year=2028/29` unless a reviewed source says
so. The SQLAlchemy projection is stored in `admission_cycles` plus the
normalized `admission_cycle_evidence` links back to existing source
observations; no cycle calendar is seeded from a guess.

These contracts and tables participate in the implemented claims lifecycle,
policy resolver and assistant query path. Legal applicability is still
deterministic and evidence-bounded: missing validity or cycle mappings block
resolution rather than being inferred.

### Temporal query behavior

The assistant carries `valid_as_of` and `as_known_at` independently. An
explicit ISO date in a question about when a rule applied sets valid time; a
question about what Andromeda knew sets system/knowledge time. Date-only
knowledge cutoffs include the complete UTC day through `23:59:59.999999Z`;
“yesterday” uses the previous UTC calendar day. The response shows the actual
cutoff, so the date boundary is inspectable rather than implicit.

When a user asks about an admission cycle without naming a separate valid-time
date, the policy resolver uses the approved cycle's application-window start
at `00:00Z` as the comparison instant and includes that instant in each
`ResolutionTrace`. If the cycle or its application window is unavailable, the
result stays blocked. A two-cycle comparison uses one shared `as_known_at`
cutoff, resolves each cycle at its own approved application-window start, and
returns both traces plus the typed effective-policy diff. Historical queries
before the available immutable revision history return
`historical_state_unavailable`; they do not infer an empty or negative rule
state.

## Pilot and source allowlist

The first vertical is annual minimum EGE score requirements: discover the next
official federal order for the 2027/28 admission cycle, then compare it with
the corresponding official BMSTU admission rules/appendix as a narrower,
university-scoped candidate. `admissions` owns the source-backed mapping from
document validity to `admission_year=2027` and `academic_year=2027/28`. A rule
is not applied if that mapping is absent. Do not presume that the university
text is legally an exception merely because its number differs: source scope,
authority, exact document language, and applicability must validate; otherwise
leave the relation unresolved for review.

As of 2026-09-26 this is a future-source pilot definition, not a claim that the
2027/28 documents have been found or adopted. The published 2026/27 Minobrnauki
Order No. 881 is a known historical source-shape example only; it is not copied
forward into the future cycle. The existing BMSTU admission-document inventory
provides the known university source-index seam. The first benefit integration
slice follows this pilot and reads one existing `IndividualAchievementPolicy`
revision through `admission_benefits`; it does not move that policy or its
calculation into generic `policy`.

The versioned source registry starts with these exact official roots and
purpose-limited adapters:

| Registered source | Reliability | Allowed use |
|---|---|---|
| `publication.pravo.gov.ru/documents/block/foiv079` | `primary_normative` | Follow only issuer-matched Minobrnauki legal acts and their registered official document URLs |
| `minobrnauki.gov.ru/documents/` | `official_issuer` | Ministry document index and issuer announcements; proposals remain proposal claims |
| `api.www.bmstu.ru/page/admission-committee-documents` | `official_university` | Existing BMSTU admission rules and linked appendices; follow only registered links returned by this index |
| `priem.bmstu.ru` | `official_university` | Existing BMSTU order manifest where the registered adapter uses it |

The adapter may fetch HTTPS URLs only when both host and registered path/link
policy match, and it retains the existing ingestion protections for public DNS,
redirect revalidation, bounded body/redirect counts, MIME/PDF checks, retry,
and safe logging. The registry is versioned and changes require a source
steward capability plus audit. There is no open crawl, arbitrary URL input,
social-media polling, general news feed, or secondary-source poller in the
pilot. A secondary source may be attached manually as supporting evidence in a
later phase but cannot create an effective rule.

The 2026/27 order is cited only as a source-discovery/parser reference:
[Official publication, Minobrnauki Order No. 881](https://publication.pravo.gov.ru/Document/View/0001202512160004).
The current BMSTU source index and its parser are already documented in
[`admission-benefits.md`](admission-benefits.md) and
[`ingestion-adapters.md`](../ingestion-adapters.md).

## Bounded discovery operations

`knowledge` owns source-registry version, poll observations, per-source health,
last successful observation, content hash, retry/backoff outcome, and explicit
discovery gaps. Existing `ingestion` owns fetch/capture and immutable
`SourceSnapshot`/`IngestRun` persistence. `admin_ops` remains a reader/operator
seam for run status, not a second scheduler.

The first runnable seam is `backend/scripts/discover_knowledge_sources.py`.
It polls at most 100 due entries per invocation from a hard-coded registry of
versioned official-source adapters, reuses the immutable snapshot and ingest
run writer, parses bounded HTML/plain-text/PDF content, and only appends
`NEEDS_REVIEW` claims. Redirect targets must satisfy both the adapter host
policy and the exact registry path allowlist before a request is made. The
command has no URL input, does not run migrations, and cannot write canonical
policy. A 404 is recorded as a source-availability outcome, never as repeal.
The host-level systemd timer remains an operations rollout task; this code
provides the one-shot command only.

For the initial deployment, package discovery as a bounded one-shot command in
the existing backend artifact and invoke it daily at 01:17 UTC from a
`systemd` timer on the existing YC VM. The host timer runs
`docker compose run --rm --no-deps --entrypoint python backend -m <discovery-command>`
from the existing deployment directory. This reuses the backend image,
environment, network and PostgreSQL target; no long-lived worker or separate
deployment is added. The command must not run migrations or start an API server.
The deployment operator owns schedule health and retry operations; the source
steward owns registry contents. Use the existing bounded retry policy per
source, record a failed observation and next retry time, and never publish from
the poll command. `.github/workflows/source-health.yml` remains a scheduled
read-only availability probe and is not the production poller. If the timer or
source is unavailable, report a discovery gap and keep the last immutable
snapshot; do not infer removal or repeal from a failed fetch.

Human submissions use separate authenticated seams and still write only
staging/approval records. `POST /ops/knowledge/sources` is limited to the
configured source-steward account allowlist and always appends a disabled source
registry revision. `POST /ops/knowledge/sources/{source_id}/snapshots` accepts
a bounded PDF or UTF-8 text upload and validates its URL against the registered
allowlist; it never dereferences the submitted URL. University editors may
submit source-backed claims and metadata corrections only inside their exact
university membership scope. A correction appends a new `needs_review` claim
revision bound to the expected revision hash and preserves the source assertion
and evidence. University policy submissions must carry that same exact
university scope and go through the existing `PolicyApprovalCommandService`,
which writes its immutable pending approval event. The scoped authorizer permits
only submission and explicitly denies policy approval, so this path cannot
activate a rule. No manual route writes canonical facts or bypasses staging.

Initial health fields are `last_attempted_at`, `last_succeeded_at`, outcome,
consecutive failures, next retry, current/previous content hash, and latest
discovery gap. Deduplication uses canonical source identity plus content hash;
identical assertions from separate registered publishers create distinct
source claims and evidence observations linked to one exact review cluster when
versioned deterministic fingerprints agree. Discovery coverage is explicit per
registered source. A missing/unregistered source is a coverage gap, not
evidence of no change.

## Domain delegation and safe activation

Generic policy may select an approved domain-rule revision, resolve its
validity/scope/exception/supersession, and report dependencies. The final
meaning of a domain effect belongs to its existing evaluator. In particular,
`admission_benefits` alone calculates BVI, 100 points, Olympiad confirmation and
validity, special rights, and individual-achievement eligibility/points.
Generic policy must not have `grant_bvi`, `grant_100_points`, or
`set_achievement_points` effects. Its domain dispatch returns a typed
`AdmissionBenefitRuleId`/revision reference to the existing catalog/evaluator.
If future source semantics cannot be represented by that owner, stop and approve
a separate domain-owner contract and evaluation change before adoption.

Admissions facts follow the same ownership rule without replacing the current
read path. `admissions` owns `AdmissionOffering`, exam requirements, quotas,
passing scores and costs; `admission_fit` consumes those facts through its
existing deterministic fit service. Policy stores selector/scope/temporal and
precedence decisions, then points at an exact admissions owner revision. It
does not calculate exam eligibility, admission fit, quota eligibility or
competitive scores. A typed `AdmissionOfferingRevision` snapshot is appended
when the existing admissions ingestion synchronizes a normalized offering; its
owner reference binds `admission:offering:<sha256(offering_id)>`, a monotonic
revision number and a hash of the normalized source-backed payload. The current
mutable admissions tables and their public contracts remain the ordinary
catalog read path.

`AdmissionsPolicyRuleReader` only confirms the exact owner ID/revision/hash and
builds a semantic, field-level diff. It checks that both revisions match the
requested admission year, university and explicit program context, and resolves
all contributing provenance through an exact captured knowledge-source
observation. Missing or inferred evidence returns an unavailable/blocked
result. A changed exam fact may flow into the existing `admission_fit` service;
Olympiad and individual-achievement meanings continue to flow through the
existing `admission_benefits` evaluator. The policy-rule revision itself still
requires an explicit immutable approval event before the resolver can select
its exact owner reference.

Migration `0053_admission_offering_revisions` is additive and follows the
approval-preview migration. It creates immutable JSONB/JSON revision payloads
with relational identity, year, hash and recorded-time indexes; there is no
automatic historical backfill because current rows cannot establish prior
owner revision boundaries. Existing installations get exact owner history on
the next successful admissions source sync. Until then, policy lookup fails
closed for missing owner revisions while existing admissions, fit and benefit
queries continue on their current tables.

The same approval boundary applies to all future policy domains: only an exact
approved revision may be read by the `Effective Rule Resolver`; source capture,
parse, Jev classification, review preview, and what-if evaluation are
non-canonical. No approval state means no effective result. Discovery may run
before a human account is assigned because it is read-only with respect to
canonical policy; effective-policy activation remains disabled until that
capability is configured.

## Human decisions still required operationally

These are deployment assignments, not open schema decisions:

- provision at least one named authenticated account with the centrally
  governed `policy_steward` / `policy.approve_revision` capability and identify
  the legal/policy reviewer rota;
- provision a distinct `source_steward` and deployment operator responsible
  for registry and timer operations;
- confirm the 2027/28 official documents when published and approve the exact
  candidate scope/effective mapping before rule approval.

Until each assignment/evidence exists, the affected action is unavailable and
the API/assistant reports review-required or missing-data state. This does not
block building storage, discovery observations, candidate review, preview, or
deterministic resolver contracts; it blocks production activation of a rule
whose approval or source evidence is missing.

## Assistant rollout gate

`ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED` defaults to `false`. With the
flag off, the existing `/assistant/query` endpoint returns a typed
`outside_coverage` result for policy queries and does not read claims or invoke
the policy resolver. This gate is independent of Jev. Source registration,
review, and policy approval remain separately guarded by allowlists and
authenticated capabilities; source discovery is an explicitly scheduled
one-shot command rather than a background crawler.

## Reuse and verification

- Reuse Stage 2 `SourceAdapter`/`RawSourceSnapshot`, `SourceSnapshotModel`,
  content hash, `IngestRun`, idempotency/retry/heartbeat and official-host
  fetch policies; do not add a parallel snapshot store.
- Reuse `university_admin` membership/access for university-scoped submissions,
  and reuse account identity for policy audit. Do not equate university owner
  with central policy approver.
- Reuse `SemanticReviewWorkflow`'s hashed proposals, stale-source checks,
  reviewer/time and publish-after-review invariants where applicable. Its
  curriculum taxonomy and mappings remain in `semantic`; policy approval is a
  distinct exact-revision ledger.
- Reuse Stage 2 `DecisionModelPort`, `QuestionRegistry`, TypeSafe transport,
  calibration gates and Jev evaluation infrastructure only for future bounded
  semantic suggestions. They do not approve or activate policy.
- Reuse `admission_benefits` contracts, persistence and deterministic evaluator;
  no second benefit engine.

### Jev operation decision

The initial source-backed policy pilot does not need a new Jev operation.
`knowledge.services.candidate_normalizer` deterministically extracts exact
source spans and a provisional `ClaimedPolicyStage`; every extracted claim
remains `NEEDS_REVIEW`. The stage is a reported claim, not a determination of
legal status. Unknown wording stays unresolved for a human reviewer. This is
sufficient for the allow-listed document pilot and keeps source interpretation
separate from effective-rule resolution.

For Olympiad/profile identity only, reuse the existing
`resolve_olympiad_profile` Question Registry definition and
`JevAdmissionCandidateSelector`. Its input is already narrowed to persisted
candidate IDs; it returns one supplied ID or unresolved, and the selector
validates membership again. It is an entity-resolution aid owned by the
existing admissions/entity-resolution flow, not a policy classifier. Its
definition, evaluation artifact and calibration lock must not be reused to
classify claims, relations, legal status, rule type, scope or applicability.

There is currently no safe relation-suggestion consumer: the knowledge review
target and action contracts cover claim, change-event and policy-rule
revisions, but do not expose a relation revision as an exact auditable review
target. A relation classifier would therefore create suggestions the operator
cannot approve, reject or resolve in the existing review workflow. Do not
register or call that operation until a typed relation-review seam exists.

If later evidence shows a deterministic owner-module workflow cannot resolve a
specific bounded ambiguity, add a separate versioned operation only with an
owner-module typed request/result, capped evidence span, finite output enum or
pre-supplied canonical IDs, deterministic validation and its own independently
authored evaluation/calibration artifacts. Jev output remains a suggestion;
it cannot create canonical IDs, relations, claims or effective rules, and any
ambiguous candidate remains review-only. Relation suggestions additionally
require an exact, immutable relation-review action before operation
registration. No new operation or Jev capability is enabled by this decision.

Documentation check for this decision:
`rg -n "modules/(knowledge|policy)|modules/admission_benefits|DecisionModelPort" docs/architecture/knowledge-policy.md`.
