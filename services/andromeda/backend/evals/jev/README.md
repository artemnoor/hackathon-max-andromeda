# Jev evaluation artifacts

This directory is evaluation-only. Nothing under `backend/evals` is imported by
the application composition root or by production API routes.

`decision-cases.v1.jsonl` is a synthetic, versioned corpus. It contains no
production profiles, credentials, cookies, or source snapshots. `train`, `dev`,
and `heldout` splits are kept immutable for a calibration run. The labels are
the expected bounded decisions, not factual catalog answers.

The optional System One adapter is invoked only by an explicit evaluation
command. Its report stores case IDs, typed metadata, usage and sanitized
structured output; it does not store raw state or provider debug transcripts.

The offline ecosystem report does not call Jev, System One, or jevQL and reports
those paths as not-run. It does not inspect whether provider credentials happen
to exist in the environment; live smoke/evaluation is a separate explicit run.

The calibration scripts are Andromeda-owned exporters/loaders around the
upstream jevcal APIs. Calibration, threshold selection and ECE are not
reimplemented locally. The committed
`config/jev/locks/decisions.v1.lock.json` is a raw upstream jevcal lock with a
hash/version sidecar; the current fixture artifact is intentionally not
production-calibrated and does not enable runtime Jev.

Useful offline checks from `backend/`:

```text
uv run --locked --extra evaluation --extra dev python scripts/jevcal_export.py --output .tmp/jevcal-rows.jsonl --questions-output .tmp/jevcal-questions.yaml --check
uv run --locked --extra evaluation --extra dev python scripts/jevcal_calibrate.py --source fixture --check
uv run --locked --extra evaluation --extra dev python scripts/evaluate_jev_ecosystem.py --output .tmp/jev-report.json --check
```

`jev-align` uses the pinned upstream `ClimbSession` for uncertainty
acquisition and GEPA optimization. Andromeda's semantic review workflow still
requires a human accept/reject decision before a versioned semantic artifact
can be published. System One remains benchmark-only. Production calibration
requires an external, sufficiently sized corpus; fixture sample counts are
not accuracy or ECE evidence.

## Knowledge/policy operation gate

`manifests/knowledge-policy-gates.v1.json` records the current operation
decision and minimum gates for any future knowledge/policy operation. There
are currently no registered policy-specific Jev operations. Do not infer one
from the existence of `KnowledgeRelationKind` or a stored candidate relation:
the exact relation review target/action seam is not implemented yet.

The existing `resolve_olympiad_profile` definition is reused only for bounded
Olympiad/profile identity selection. Its v2 golden cases are labeled from the
source-backed BMSTU fixture pipeline before provider capture; its observations
are stored in a separate file and never become labels. No operation-specific
calibration lock is checked in for this definition, and the capability is
disabled by default, so the manifest marks it ineligible for production use.
The unrelated decision and next-action locks do not calibrate this operation.

Before registering a future operation, the owning module must freeze a
versioned golden corpus and independently authored labels before any model
run. Inputs must be deterministically narrowed, candidate IDs must come from
the owner registry, evidence spans must be capped, and ambiguous cases must
have an unresolved gold label. A matching operation used for production
staging or canonical decisions needs at least 500 deterministic synthetic
golden cases. Include ambiguity, missing targets, adversarial prompts,
paraphrases, typos and non-matches. Record definition, prompt, model, provider,
corpus and label hashes plus adjudication reasons.

Evaluation reports must include false match, false no-match and unresolved
recall. Relation operations also measure hallucinated relations and wrong
relation types; scope/override/temporal outputs are prohibited from Jev and
remain deterministic, while end-to-end applicability errors must be measured
in the regression suite. Set operation-specific thresholds before rollout. A
missing, uncalibrated or regressed gate leaves an operation off or shadow-only;
predictions cannot write canonical claims, relations or policy. The
dependency-free manifest/corpus contract check is
`python -m pytest tests/evaluation/test_jev_knowledge_policy_gate.py`.

Knowledge/policy rollout is currently `off`: there is no policy-specific
operation and no exact relation-review consumer. No shadow or assisted
capability is configured. When a reviewed operation is eventually added,
audit only the operation/definition, candidate-set hash, prompt/provider/model
and lock identities, timing/fallback outcome, reviewer outcome and timestamp.
Do not persist raw source text or applicant profile data in model audit.
