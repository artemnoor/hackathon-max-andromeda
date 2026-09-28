# Education Policy Knowledge: pre-merge architecture and code-quality audit

**Branch:** codex/andromeda-education-policy-knowledge

**Audit starting HEAD:** b2f8218d61fcbc29ac98659b917e3ffc6f48792e

**Baseline / merge base:** feature/jev-ecosystem-stage-2 at 1f5777c892c2daf2f6f11a405bc19268b7dc0c88

**PR:** #3, open; pre-audit baseline CI was green
**Scope:** full branch diff plus architecture, repositories, policy resolution, assistant, API, discovery, Jev, migrations, security, performance and tests. Findings were recorded before fixes; this report includes remediation and verification results.

## Executive summary

The implementation follows the accepted modular-monolith architecture. It introduces two logical contexts, knowledge and policy, and reuses Stage 2 ingestion snapshots/fetch protections, Jev runtime/calibration, admissions and admission-benefits owners, conversation, entity resolution, and presentation. No second benefit calculator, Jev client/registry, or assistant backend was added.

The implementation diff is 257 files, +63,826/-8,918. Generated OpenAPI and frontend client output account for much of the churn; raw LOC is not evidence of overengineering. Most large files have one identifiable persistence, orchestration, or projection responsibility.

No Critical or High findings were observed. The audit moved policy authority/scope/cycle semantics out of the SQLAlchemy repository, added database-enforced participant uniqueness with migration 0056, reused one approved policy snapshot, and made precedence trace-limit exhaustion fail closed with a typed blocker. This final pass attached the exact immutable approval event to every considered approved revision in `ResolutionTrace v3` and moved approval readiness checks behind the existing policy approval command service. Persisted conflict-group creation/resolution is explicitly disabled in this rollout; resolver/assistant conflict handling remains fail-closed and the read-only API no longer implies that a complete conflict-review workflow is available.

The route still constructs a typed review preview, while the existing policy approval command service now owns and revalidates approval preconditions. AssistantService is large, yet its policy branch is cohesive and delegates final benefit calculations; do not split it solely due to file length.

## Diff breakdown

Branch diff against the stated baseline:

- 257 files changed; 63,826 insertions and 8,918 deletions.
- Runtime source across backend/src, frontend-next/src, the then-separate client package and scripts: 101 files, +18,840/-210 (historical audit scope).
- Tests: 46 files, +10,623/-63.
- Alembic migrations: 17 files, +2,256/-0.
- Contracts/schemas: 47 files, +7,077/-29.
- Docs/plans: 31 files, +5,255/-14.
- Evaluation/generated artifacts: 4 files, +19,228/-8,596.
- Other configuration/assets: 11 files, +547/-6.

The generated/evaluation category includes frontend-next/openapi.json (+15,775/-8,218) and frontend-next/src/lib/generated.ts (+3,331/-378), plus Jev gate/evaluation metadata. This is generated contract churn, not hand-written runtime complexity.

### Top 20 files by added lines

| Rank | File | Added |
|---:|---|---:|
| 1 | frontend-next/openapi.json | 15,775 |
| 2 | frontend-next/src/lib/generated.ts | 3,331 |
| 3 | .ai-factory/plans/feature-andromeda-education-policy-knowledge/index.md | 2,648 |
| 4 | backend/tests/infrastructure/test_knowledge_candidate_repository.py | 1,902 |
| 5 | backend/src/andromeda/infrastructure/repositories/policy.py | 1,000 |
| 6 | backend/src/andromeda/infrastructure/repositories/knowledge_candidates.py | 869 |
| 7 | backend/tests/unit/test_policy_applicability.py | 851 |
| 8 | backend/src/andromeda/infrastructure/repositories/knowledge_conflicts.py | 771 |
| 9 | backend/src/andromeda/modules/conversation/services/policy_presentation.py | 703 |
| 10 | backend/src/andromeda/modules/conversation/services/assistant.py | 651 |
| 11 | backend/src/andromeda/api/routes/knowledge_review.py | 595 |
| 12 | backend/src/andromeda/modules/presentation/services/knowledge_response.py | 564 |
| 13 | backend/src/andromeda/modules/policy/services/applicability_resolver.py | 549 |
| 14 | backend/src/andromeda/infrastructure/repositories/knowledge_source_repository.py | 544 |
| 15 | backend/tests/unit/test_knowledge_review.py | 537 |
| 16 | backend/src/andromeda/modules/knowledge/services/manual_source_commands.py | 510 |
| 17 | backend/tests/unit/test_knowledge_manual_commands.py | 489 |
| 18 | docs/architecture/knowledge-policy.md | 486 |
| 19 | backend/src/andromeda/modules/knowledge/contracts/conflicts.py | 480 |
| 20 | frontend-next/src/features/knowledge-review/knowledge-review-page.tsx | 476 |

### New bounded contexts and reused modules

Only new bounded contexts are backend/src/andromeda/modules/knowledge and backend/src/andromeda/modules/policy. Existing extensions reuse admission_benefits, admissions, admission_fit, conversation, entity_resolution, presentation, ingestion, university_admin, repositories and composition. Jev Stage 2 runtime, QuestionRegistry, TypeSafe adapter, DecisionModelPort, jevcal and evaluation locks remain the only Jev stack.

No KnowledgeCore, DataStaging, second assistant backend, second Jev abstraction, or second benefit evaluator was introduced.

## Critical findings

None found.

## High findings

None found.

The persisted conflict workflow gap is medium and non-blocking because conflict review is not an enabled capability in this rollout. The docs now state that limitation, and the API exposes existing conflict participants only as diagnostic metadata.

## Medium findings

M1, M2, M5 and M6 were fixed as described above. M3 is explicitly disabled for this rollout; M4 and the approval-event provenance gap are fixed in this final pass.

### M1 — Policy relation semantics lived in a SQLAlchemy repository — FIXED

- **File/symbol:** backend/src/andromeda/infrastructure/repositories/policy.py; SqlAlchemyPolicyRuleRepository._validate_rule_relations and _validate_requires_acyclic, approximately lines 334–448.
- **Why:** repository code interprets family boundaries, authority levels, scope specificity, authorized exceptions, override/supersession/amendment precedence, and dependency cycle semantics. These decisions belong in policy domain/application services. The repository also validates selector ASTs already validated by PolicyApprovalCommandService.submit.
- **Pre-merge:** fixed in this audit.
- **Remediation:** moved typed authority/scope/family and bounded REQUIRES-cycle validation to `policy.domain.relations.validate_policy_relations`, called by the existing `PolicyApprovalCommandService`. It reuses existing `list_approved_revisions` and `get_revision` ports; no new repository contract was needed. Repository retains exact target lookup, evidence integrity, SQL and immutable writes. Current behavior and bounds are preserved.

### M2 — Migration 0055 participant uniqueness was not enforced for nullable typed rows — FIXED

- **File/symbol:** backend/alembic/versions/0055_knowledge_schema_alignment.py, uq_knowledge_conflict_participant_exact_ref; backend/src/andromeda/infrastructure/database/models/knowledge_conflicts.py, KnowledgeConflictParticipantModel.__table_args__.
- **Why:** the unique key includes unused nullable columns for each participant kind. PostgreSQL and SQLite treat NULLs as distinct under a normal unique index, so duplicate typed references can persist despite the index name. The Pydantic contract currently rejects duplicates before normal repository writes, but the DB constraint does not independently protect the invariant it claims to enforce.
- **Pre-merge:** fixed in this audit.
- **Remediation:** migration 0056 replaces the catch-all index with three kind-specific unique partial indexes for claim, change-event, and policy participants. SQLAlchemy metadata uses matching PostgreSQL/SQLite predicates; repository tests verify duplicate policy participant insertion is rejected by the database.

### M3 — Persisted knowledge conflict workflow has no production writer/reviewer path

- **File/symbol:** backend/src/andromeda/infrastructure/repositories/knowledge_conflicts.py, append_conflict_group/append_conflict_event; backend/src/andromeda/api/routes/knowledge_review.py, queue/actions.
- **Evidence:** repository-wide search finds append methods only in the repository port/adapter and infrastructure tests. The API renders groups and uses them as approval guards, but no application command, ingestion path or route creates/resolves them.
- **Why:** the conflict tables and response model imply a functioning review workflow but are inert in production. Direct same-subject contradictory accepted claims still yield INDETERMINATE in AssistantService._source_claim_answer_status, and policy precedence also fails closed, so this does not currently demonstrate fabricated answers. It does mean persisted claim/change conflict review, resolution audit and conflict-based approval blocking are not connected.
- **Final decision:** not enabled/not-yet-enabled capability; not a merge blocker for the current rollout.
- **Remediation:** architecture, operations and API docs now state that persisted conflict groups are diagnostic/read-only when present, no production writer or reviewer resolution action exists, and an absent row is not evidence of no conflict. Existing resolver/assistant ambiguity continues to fail closed. No new workflow was added.

### M4 — Policy approval business gates are in the FastAPI route

- **File/symbol:** backend/src/andromeda/api/routes/knowledge_review.py, apply_knowledge_review_action, approximately lines 135–225.
- **Why:** the route previously enforced hypothetical-preview fingerprint, resolved applicability, complete domain impact and open-conflict checks before calling the policy approval command. These are approval rules rather than transport validation.
- **Final decision:** fixed. `PolicyApprovalCommandService.decide` now requires and revalidates the typed preview, compares exact target revision/hash and fingerprint, requires a resolved candidate trace and complete domain-owner impact, and checks persisted open conflicts through a typed port. The route constructs the preview and maps the request; the approval invariants are not route-only.
- **Scope:** no general route/application refactor was made. Reject decisions retain their existing path; no new review subsystem was introduced.

### M5 — Successful policy resolution loaded the full approved snapshot twice — FIXED

- **File/symbol:** backend/src/andromeda/modules/policy/services/effective_rule_resolver.py, resolve; EffectiveRuleCandidateResolver.resolve.
- **Why:** candidate resolution reads the full approved snapshot (up to 500 rows), then successful resolution performs another full scan to recover revisions for precedence. This doubles bounded reads and can make trace candidates and precedence inputs originate from separate query statements. Both use a fixed as_known_at and rows are append-only, limiting correctness risk, but the repeated query is avoidable.
- **Pre-merge:** fixed in this audit.
- **Remediation:** `EffectivePolicyResolver.resolve` reads the approved snapshot once at one normalized `as_known_at` and passes the same immutable tuple to candidate filtering and precedence. No cache or broader query was added.

### M6 — Precedence could exceed its trace decision limit — FIXED

- **File/symbol:** `policy/domain/precedence.py::resolve_policy_precedence`, `PolicyPrecedenceResult`, and `ResolutionTrace`.
- **Why:** pairwise precedence is quadratic. At 101 candidates in one family, 5,050 comparisons exceeded the typed 5,000-decision bound and raised validation failure instead of returning a trace. This violated boundedness and fail-closed behavior.
- **Pre-merge:** fixed in this audit.
- **Remediation:** stop before adding decision 5,001, return an explicitly truncated `indeterminate` precedence result with no effective rules, and propagate `precedence_decision_limit` as a typed trace blocker. A 101-candidate regression verifies the hard bound and deterministic trace ID. The additive blocker was synchronized to the generated frontend client through the standard OpenAPI generator.

## Low findings

### L1 — Similar semantic-diff helpers in two owner adapters

- **Files/symbols:** infrastructure/repositories/admission_policy.py (_semantic_fields/_flatten/_field_change) and infrastructure/repositories/admission_benefit_policy.py (same-shaped helpers).
- **Why:** both produce field-level source-backed deltas, but admissions has collection identity handling and benefits has a different provenance/identity shape. A shared generic diff framework is not justified by two uses.
- **Pre-merge:** no. Keep separate unless another owner establishes stable shared semantics.

### L2 — Large assistant/presentation files are not by themselves god objects

- **Files/symbols:** modules/conversation/services/assistant.py (972 current lines; policy path mainly _handle_policy_query and _evaluate_admission_benefit_impact), policy_presentation.py, presentation/services/knowledge_response.py.
- **Why:** policy context lookup, temporal mode, resolver call, domain dispatch, response projection and general conversation share one application class. This is cohesive but colocated with admission/analytics orchestration. Extracting a handler may help focused testing, but could add a layer without reducing coupling.
- **Pre-merge:** no. Keep current structure; revisit only if a second caller or materially simpler tests establish a boundary.

## Confirmed-good architecture decisions

- One modular monolith and one PostgreSQL database; only knowledge and policy were added as contexts.
- Generic policy stores typed selector/scope/temporal/precedence references and has no BVI/100-point/achievement-score effects.
- AdmissionBenefitsPolicyRuleReader confirms exact owner revisions and emits field diffs. Final applicant benefit evaluation calls the existing AdmissionBenefitPolicyEvaluator.
- admission_benefits remains the only owner calculating BVI, 100 points, Olympiad confirmation/validity and individual-achievement eligibility/points. Regression tests explicitly assert delegation.
- Effective resolution uses an approved-only reader. Pending revisions and hypothetical overlays are distinct; exact revision/hash and immutable approval event gate effective selection.
- Source reliability, claimed policy stage, approval and effective time remain separate.
- Missing cycle, validity, scope, evidence and contradictory assertions become blocked/indeterminate, not negative answers.
- ResolutionTrace is typed, content-addressed, deterministic and bounded; it carries per-rule temporal/lifecycle/scope/selector reasons, evidence, and the exact immutable approval-event reference for every considered approved revision. Bad revision/hash/event linkage fails closed as indeterminate. The trace is mandatory for resolved/conflict/no-match/blocked outcomes (approval-event provenance gap fixed).
- Discovery uses approved registry entries and existing Stage 2 Fetcher protections; each redirect is host-checked and route-validated, with HTTPS/public DNS/port/body/redirect/timeout/retry bounds.
- Discovery is one-shot, allowlisted and candidate-only. It has no arbitrary URL input, open crawl, approval write or activation path; source unavailability preserves last successful hash.
- No new Jev operation/client is registered. Candidate normalization is deterministic and review-only.
- Existing tests cover exact owner dispatch, pending/stale rejection, 2027-vs-2028 applicability, scope exceptions, precedence conflicts, read-only what-if, domain delegation, source safety, review authorization/stale hashes, and Jev fail-closed gates.

## Large-file analysis

| File | Current/added size | Assessment |
|---|---:|---|
| infrastructure/repositories/policy.py | ~900 lines after final pass | Revision/approval/evidence persistence adapter and mapping; approved revision plus event provenance is loaded in one bounded batched read. Authority/scope/precedence relation semantics have moved to policy domain. |
| infrastructure/repositories/knowledge_candidates.py | +869 lines | Claims/events/evidence/duplicate-cluster persistence share staging ownership; mostly SQL/mapping. |
| infrastructure/repositories/knowledge_conflicts.py | +771 lines | One conflict aggregate persistence adapter; production writer/reviewer path is intentionally disabled in this rollout (M3). |
| infrastructure/repositories/knowledge_source_repository.py | +544 lines | Registry, observations and poll health share source ownership; coherent mapping/query responsibilities. |
| infrastructure/repositories/admission_benefit_policy.py | 399 lines | Exact owner adapter and field diff; no benefit calculation. |
| infrastructure/repositories/admission_policy.py | 374 lines | Exact admissions owner adapter/diff; no Admission Fit calculation. |
| modules/conversation/services/assistant.py | 1,014 current lines | General orchestration plus cohesive policy branch; large, no automatic split justified. |
| composition/container.py | 923 current lines | Explicit typed factory/wiring surface; no subject business rules or service locator. |
| infrastructure/config/settings.py | 603 current lines | Consistently prefixed settings; rollout/Jev defaults fail closed. |
| api/routes/knowledge_review.py | ~600 current lines | Queue/evidence projection and request shaping; policy approval readiness is enforced by the application service (M4 fixed). |
| api/schemas/knowledge_ops.py, knowledge_review.py | 336/202 current lines | Typed bounded requests; no endpoint-per-table design. |

No mechanical file splitting is warranted. M1 and M4 were corrected; M3 remains an explicitly disabled workflow capability with fail-closed runtime behavior. The other large files are coherent for this scope.

## Repository boundary analysis

- knowledge_candidates.py mostly performs bounded SQL, row conversion, append-only/idempotency checks, exact source/evidence integrity and cluster persistence.
- knowledge_source_repository.py persists registry/observation/poll state and performs exact hash/identity checks and mapping.
- policy.py retains persistence mechanics; policy relation authority/scope/cycle semantics now belong to the application/domain layer (M1 fixed).
- knowledge_conflicts.py persists bounded conflict aggregates; its production writer/reviewer path remains unwired by rollout decision (M3 disabled). Existing participant reads are diagnostic/gating only. Its supersession validation coupling remains a follow-up review item, not part of this minimal merge hardening.
- admission_policy.py and admission_benefit_policy.py are owner integration adapters. They validate exact owner revisions, resolve provenance and compute typed field diffs; they do not calculate eligibility.
- No benefit arithmetic, Admission Fit, or policy precedence selection was found in SQL expressions.

## Assistant complexity analysis

AssistantService grew by 651 lines and is 1,014 lines total. Its policy branch handles claim lookup, historical/cycle mode selection, policy resolution, domain impact dispatch and response projection. It delegates benefit calculation and returns typed answer/envelope data.

This is large but cohesive. Two focused assistant policy API tests are complemented by resolver/evaluator suites. Keep for this merge; only introduce PolicyQueryHandler if another caller or focused test boundary makes it demonstrably simpler.

## Migration audit

- Stage 2 head is 0038_admission_offering_scope_and_exam_choices.
- New chain is linear from 0039_knowledge_source_registry through 0056_exact_conflict_participant_uniqueness; one Alembic head.
- Tests cover fresh DB to head, clean Stage 2 head to current head with a preserved source_snapshots row, metadata drift, and refusal to destructively downgrade persisted owner/conflict/review history.
- No migration recreates existing Stage 2 feature tables; new knowledge/policy schema is additive.
- 0055 aligns actor/university column widths. Its nullable all-kind participant index was replaced by 0056 kind-specific unique partial indexes; model metadata and duplicate-insert tests match PostgreSQL/SQLite behavior (M2 fixed).
- `test_clean_stage2_head_upgrades_additively_to_one_current_head` inserts and preserves a Stage 2 snapshot. There is no full populated Stage 2 fixture with program/admission/benefit rows upgraded through 0039–0056; PostgreSQL CI evidence for the prior SHA upgraded an empty PostgreSQL 16 database. This is a coverage limitation, not a demonstrated data-loss problem.
- Local migration suite and Alembic fresh-database upgrade/drift gate passed after 0056. A populated Stage 2 production-like fixture upgrade and PostgreSQL run against this uncommitted worktree were not available locally; hosted PostgreSQL CI evidence applies to the prior audited SHA only.

## Security audit

- No arbitrary URL fetch: discovery reads versioned approved registry and a fixed adapter factory.
- Requested and redirected URLs are host/path checked; inherited Fetcher requires HTTPS/public DNS/standard port and bounds body, redirects, timeout and retry.
- Captures create candidates only. Source trust/lifecycle does not approve rules.
- Manual snapshot upload is bounded and never dereferences its submitted source URL.
- Reviewer and policy-steward identities/capabilities are separate; ops API key is not human identity.
- Policy submission/approval is capability-gated and approval events bind the exact revision hash and preview fingerprint.
- No arbitrary rule code, SQL from Jev/LLM, new Jev capability, or mandatory runtime LLM dependency was found.
- Raw assertions are returned as typed text; frontend uses React rendering. Active HTML elements are stripped during extraction.
- No new secret logging or unbounded response path found.
- .ai-factory/SECURITY.md is absent in this checkout; review used repository instructions, source and the security skill checklist.

## Performance audit

- Resolver corpus caps at 500 revisions; dependency traversal caps at 10,000 edges/1,000 nodes; discovery polls at most 100 sources/run; review queue at most 100; conflict evidence/event histories are bounded.
- Claim lookup is predicate/time bounded; migration 0054 adds a predicate/subject/recorded-time index.
- Successful resolver queries now reuse one immutable approved snapshot (M5 fixed).
- Source polling asks for latest attempt per registered revision; registry scan is capped at 500. At expected source count this is small; batch if registry grows.
- Queue row caps keep projection finite. Measure query count with 100 items before broad rollout.
- Precedence compares candidate pairs; work and trace are capped at 5,000 decisions. Limit exhaustion returns an explicit indeterminate result and stable blocker, verified with 101 same-family candidates (M6 fixed).
- No premature cache or graph database found.

## Test-quality audit

Tests cover exact hash approval, stale/pending rejection, three-valued selectors, temporal cohort differences, explicit scope and exceptions, unresolved precedence, read-only what-if, benefit evaluator delegation, source trust separation, no unreviewed Jev operation, source disappearance/no removal inference, review idempotency/capability/rollback, and migrations from Stage 2.

Coverage gaps:

- There is no end-to-end workflow for creating/resolving persisted conflict groups; this capability is not enabled in the current rollout (M3) and is documented rather than represented as shipped.
- Approval-event reference exactness is now covered for approved revisions, newer revision isolation, pending/rejected revisions, and event revision/hash mismatches.
- Max same-family stress case verifies the 5,000-decision trace bound and fail-closed state.
- Hosted CI must be checked against the final pushed HEAD; earlier CI evidence does not validate these final changes.

## Dead/duplicate code

- Conflict group/event append methods remain persistence seams used by infrastructure tests, not production capabilities in this rollout (M3 is documented disabled).
- No duplicate Jev client/registry/calibration adapter or admission-benefits evaluator found.
- No stale knowledge-policy compatibility wrapper or unused rollout flag found.
- Similar semantic diff helpers exist in the two domain owner adapters (L1); their identity rules differ, so a shared abstraction is not justified yet.

## Recommended minimal fixes

1. M1, M2, M5 and M6 remain fixed; migration 0056 and bounded-resolution regression tests are preserved.
2. M3 is disabled/not-yet-enabled. Architecture, operations and API docs explicitly describe read-only diagnostics, absence of a conflict writer/resolver API and fail-closed ambiguity. This is not a merge blocker for the current rollout.
3. M4 is fixed in the existing `PolicyApprovalCommandService`; exact preview, trace, impact and conflict preconditions are application-owned and covered by service/API regressions.
4. Approval-event trace provenance is implemented as typed exact-event metadata in `ResolutionTrace v3`, loaded from the existing ledger without a second store or repeated full snapshot read. Invalid event/revision/hash relationships fail closed.

## Overall assessment

Architecture remains coherent and reuses Stage 2, admissions and benefit seams. The targeted repository, database uniqueness, snapshot reuse, bounded trace, exact approval provenance and application-service approval gates are addressed. The branch does not claim a persisted conflict-review lifecycle in this rollout. No module split, mass rewrite, Jev expansion or unrelated product scope is justified by evidence.

## Verification and evidence

- `python scripts/andromeda.py full` completed successfully after updating trace fixtures: backend `1105 passed, 9 skipped`; backend coverage `1105 passed, 9 skipped` with 86% total coverage; frontend unit tests `28 passed`, ESLint and production build passed; frontend coverage `28 passed`; the then-separate client package had `16 passed` plus strict typing; BMSTU/HSE fixture ingestion passed; migration tests `28 passed`; empty SQLite `alembic upgrade head` and `alembic check` passed; production-like API/frontend fixture smoke returned `check: true`.
- Final `python scripts/andromeda.py fast` passed: architecture/OpenAPI contract tests `37 passed`, Mypy passed on 680 source files, generated OpenAPI client drift check passed, documentation link audit passed (145 Markdown files), and deployment artifact contract passed.
- Targeted policy/knowledge/admission-benefit regression set passed `76 tests`; the exact approval-event trace, stale/new revision isolation, pending/rejected filtering and hash/revision mismatch gates are included. Ruff passed on all touched backend source and tests. `git diff --check` passed.
- Alembic has one head, `0056_exact_conflict_participant_uniqueness`; history is a linear chain `0038_admission_offering_scope_and_exam_choices` → `0039` → `0056`. Migration tests passed fresh and Stage 2 additive upgrade coverage, model/schema drift and partial-index/uniqueness checks. No migration was added for approval-event references because the existing immutable ledger supplies the provenance.
- Jev offline/evaluation checks passed: `uv lock --check`; upstream Jev/evaluation/entity-resolution and module-boundary set `71 passed`; ecosystem report `--check`; jev-tree bridge smoke returned the expected bounded canonical candidate/hash. No Jev runtime operation or calibration lock changed.
- Local PostgreSQL integration was not runnable because `ANDROMEDA_POSTGRES_TEST_URL` is unset. The full local suite skipped nine environment-dependent PostgreSQL tests. Hosted PostgreSQL integration passed on the exact audit-fix code SHA `d65815a42fd4cfb4e41e0dd140a08e6ca2377bb0`.
- Local Playwright was not run independently; the production-like fixture API/frontend smoke passed. Hosted fullstack and canonical browser scenarios passed on that same code SHA.
- Hosted push and pull-request workflows both completed successfully on `d65815a42fd4cfb4e41e0dd140a08e6ca2377bb0`: backend (including architecture boundaries, strict typing and Alembic gates), frontend, PostgreSQL integration, fullstack/browser, Jev offline, the then-separate client suite, proftest integration, packaging, dependency audit and documentation. Runs: [push CI](https://github.com/artemnoor/andromeda/actions/runs/36282742853) and [PR CI](https://github.com/artemnoor/andromeda/actions/runs/36282744868). The PR merge state was `CLEAN` after both runs.
- The implementation commits are `9759a38` (`fix(policy): harden premerge policy resolution and approval trace`) and `d65815a` (`docs: close education policy premerge audit`), pushed to `codex/andromeda-education-policy-knowledge`. The only dirty worktree file is the pre-existing, untouched `frontend-next/next-env.d.ts`, excluded from staging.
