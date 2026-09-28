from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from andromeda.modules.knowledge.contracts.public import (
    SourceIdentity,
    SourceJurisdiction,
    SourceObservation,
)
from andromeda.modules.knowledge.services.candidate_normalizer import (
    normalize_policy_claim_candidates,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
SOURCE_ID = "source:bmstu-admission"
URL = "https://priem.bmstu.ru/admission/rules.html"
BODY = "В проекте новых правил изменится минимальный балл ЕГЭ для поступления в университет."
BODY_HASH = hashlib.sha256(BODY.encode("utf-8")).hexdigest()


def _identity() -> SourceIdentity:
    return SourceIdentity(
        source_id=SOURCE_ID,
        issuer_id="issuer:bmstu",
        jurisdiction=SourceJurisdiction.UNIVERSITY,
        identity_key="admission-rules",
        display_name="BMSTU admission rules",
        created_at=NOW,
    )


def _observation() -> SourceObservation:
    return SourceObservation(
        source_observation_id="source-observation:" + "a" * 32,
        source_id=SOURCE_ID,
        registry_revision=1,
        idempotency_key="b" * 64,
        ingest_run_id="ingest:" + "c" * 32,
        snapshot_sha256=BODY_HASH,
        requested_url=URL,
        final_url=URL,
        status_code=200,
        content_type="text/html",
        response_class="success",
        access_mode="http",
        truncated=False,
        captured_at=NOW,
        observed_at=NOW,
    )


def test_normalizer_emits_bounded_review_only_claims_with_source_span_and_no_inferred_rule() -> None:
    claim = normalize_policy_claim_candidates(
        f"Navigation\n{BODY}\n{BODY}",
        source=_identity(),
        observation=_observation(),
        recorded_at=NOW,
    )[0]

    assert claim.assertion_text == BODY
    assert claim.claimed_stage.value == "proposal"
    assert claim.review_state.value == "needs_review"
    assert claim.proposition is None
    assert claim.source_milestones.effective_time is None
    assert claim.source_milestones.published_at is None
    assert claim.evidence[0].evidence.snapshot_sha256 == BODY_HASH
    assert claim.text_start_offset < claim.text_end_offset


def test_reliability_does_not_change_claimed_policy_stage_and_empty_text_is_allowed() -> None:
    claim = normalize_policy_claim_candidates(
        "Возможно, новое правило ЕГЭ начнет действовать с 2028 года.",
        source=_identity(),
        observation=_observation(),
        recorded_at=NOW,
    )[0]
    assert claim.claimed_stage.value == "hypothesis"

    assert (
        normalize_policy_claim_candidates(
            "Техническая информация.\nТелефон: 123; график работы: понедельник-пятница.",
            source=_identity(),
            observation=_observation(),
            recorded_at=NOW,
        )
        == ()
    )
