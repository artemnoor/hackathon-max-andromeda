# Admission Benefits architecture

## Ownership

```text
BMSTU official document index
  → BmstuAdmissionBenefitsCapture
  → RawAdmissionBenefitRecord / RawIndividualAchievementRecord
  → BMSTU parser + normalizer
  → AdmissionBenefitsSnapshot
  → SqlAlchemyAdmissionBenefitsRepository
  → AdmissionBenefitCatalogService / AdmissionBenefitEvaluator
  → FastAPI typed adapter
```

The domain module owns only university-agnostic contracts and deterministic policy evaluation:

- `modules/admission_benefits/contracts` — rules, applicants, provenance, statuses and results;
- `modules/admission_benefits/services` — scope, validity, confirmation, BVI/100 and individual-achievement evaluation;
- `ingestion/universities/bmstu/admission_benefits` — source discovery/capture and source-specific document classification;
- `infrastructure/database/models/admission_benefits.py` — persistence mapping only;
- `infrastructure/repositories/admission_benefits.py` — batch/reverse reads and atomic snapshot sync;
- `api/routes/admission_benefits.py` — thin HTTP adapter.

The domain does not import FastAPI, SQLAlchemy, ingestion adapters, Jev or an LLM. The legal result is deterministic over persisted canonical rules.

## Storage and revision semantics

Migrations `0034_admission_benefits` and `0035_admission_benefit_team_member` store normalized Olympiads, profiles, rules, scope/subject children, individual-achievement policies and rules. Migration `0038_admission_offering_scope_and_exam_choices` adds nullable source-backed campus and exam choice-group metadata without inventing missing values. Canonical parent identities include `source_snapshot_hash`, so a corrected official document does not overwrite the previous source fact. The repository marks superseded rows stale during a source-specific refresh and keeps their provenance.

Indexes cover university/year, Olympiad/profile, benefit type, scope targets and achievement code. Scope and confirmation children are loaded in batches for catalog, direction, program and reverse reads.

## Status model

```text
active          → eligible evaluation may use the rule
review_required → visible with evidence, never silently activated
conflict        → competing official/source interpretations need review
stale           → retained historical revision, not current active fact
```

Missing data is not zero. An unknown confirmation threshold, validity period or program scope produces an explicit review state/source gap.

## Separation from existing admissions

`AdmissionCompetitionType.BVI` and `PassingScoreStatus.BVI` remain historical admissions observations. `AdmissionBenefitRule(benefit_type=BVI)` is an applicant-right rule. `Admission Fit` can consume the existing admissions model, but it does not decide legal benefit eligibility and does not add Olympiad/ID values to the old formula implicitly.

`EffectiveCompetitiveScoreCalculator` consumes one selected source-backed `AdmissionOffering`, the applicant's raw subject scores, persisted exam requirements/choice cardinalities, deterministic benefit evaluation, and persisted individual-achievement policy. It reports the selected valid exam combination, score changes, ID breakdown, effective total, evidence, and source gaps. It does not sum unused EGE scores; it reports an insufficient result when offering or choice semantics are missing/ambiguous. BVI is reported as its own legal route, not as a general competitive score.

## Evidence path

```text
API response evidence
  → AdmissionBenefitRule.provenance
  → source_snapshot_hash + source_run_id
  → RawSourceSnapshot / raw record
  → official URL + page/table/row locator
```

The response can therefore explain which document revision and table row supported a result. Minimized fixtures are allowed in tests only when they retain the original official URL, exact source hash and stable locator.

## Failure and degraded behavior

Capture/parser failures are reported as source gaps and do not invalidate already persisted revisions. A partial refresh cannot claim complete current coverage. Unresolved direction/program identity remains review-only. If benefit data is unavailable, the existing admissions and Admission Fit endpoints remain usable and the benefit API returns an explicit not-found/insufficient-data response.

## Jev boundary

Jev may later resolve a user phrase to a canonical Olympiad/profile or select a follow-up question. It receives deterministic catalog/evaluation results. It must not calculate BVI, 100 points, confirmation thresholds, validity, scope applicability or individual-achievement points.

The optional admission-name selector uses a separate Question Registry artifact and calibration lock, is disabled by default, and may return only one ID from a bounded source-backed candidate set. Exact resolution and the legal evaluator remain deterministic. If the admission-resolution calibration lock is absent, incompatible, or rejected, the resolver preserves ambiguity and asks for clarification.
