from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    ChangeEvent,
    ChangeEventKind,
    ChangeEventReviewState,
    Claim,
    ClaimedPolicyStage,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimProposition,
    ClaimReviewState,
    ClaimRevisionRef,
    ClaimSubjectKind,
    ClaimValueDecimal,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    SourceReliabilityTier,
    TemporalInterval,
    change_event_id_for_claims,
    claim_id_for_source_assertion,
)
from andromeda.modules.knowledge.domain.change_event import (
    transition_change_event_review,
)
from andromeda.modules.knowledge.domain.claim import transition_claim_review

PUBLISHED = datetime(2027, 12, 1, tzinfo=UTC)
CAPTURED = datetime(2027, 12, 15, tzinfo=UTC)
RECORDED = datetime(2027, 12, 15, 0, 2, tzinfo=UTC)
OBSERVATION_ID = "source-observation:" + "a" * 32
SOURCE_ID = "source:ministry-admission"
SNAPSHOT_HASH = "b" * 64
ASSERTION = "The ministry proposed a new minimum exam score."


def _evidence(
    *,
    observation_id: str = OBSERVATION_ID,
    source_id: str = SOURCE_ID,
    snapshot_hash: str = SNAPSHOT_HASH,
) -> EvidenceRef:
    return EvidenceRef(
        source_id=source_id,
        source_observation_id=observation_id,
        snapshot_sha256=snapshot_hash,
        source_url="https://official.example/admission/order.pdf",
        locator=EvidenceLocator(
            page=2, section="Minimum scores", field="minimum_score"
        ),
    )


def _claim(
    *,
    review_state: ClaimReviewState = ClaimReviewState.NEEDS_REVIEW,
    stage: ClaimedPolicyStage = ClaimedPolicyStage.PROPOSAL,
    effective_time: TemporalInterval | None = None,
    method: ClaimExtractionMethod = ClaimExtractionMethod.DETERMINISTIC_PARSER,
    confidence: Decimal | None = None,
) -> Claim:
    digest = hashlib.sha256(ASSERTION.encode("utf-8")).hexdigest()
    return Claim(
        claim_id=claim_id_for_source_assertion(
            OBSERVATION_ID, 120, 120 + len(ASSERTION), digest
        ),
        clock=BitemporalRevision(
            revision=1,
            valid_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
            recorded_at=RECORDED,
        ),
        source_observation_id=OBSERVATION_ID,
        text_start_offset=120,
        text_end_offset=120 + len(ASSERTION),
        assertion_text=ASSERTION,
        assertion_text_sha256=digest,
        proposition=ClaimProposition(
            predicate="admission.minimum_ege_score",
            subject_kind=ClaimSubjectKind.EXAM,
            subject_id="subject:mathematics",
            value=ClaimValueDecimal(kind="decimal", value=Decimal(80)),
            unit="score",
        ),
        claimed_stage=stage,
        review_state=review_state,
        source_milestones=SourceMilestones(
            published_at=PUBLISHED,
            effective_time=effective_time,
            captured_at=CAPTURED,
        ),
        extraction_method=method,
        extractor_id="ministry_pdf_rules",
        extractor_version="v1",
        extraction_confidence=confidence,
        evidence=(
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                evidence=_evidence(),
            ),
        ),
    )


def test_claim_keeps_policy_stage_review_state_and_source_reliability_separate() -> (
    None
):
    claim = _claim()

    assert claim.claimed_stage is ClaimedPolicyStage.PROPOSAL
    assert claim.review_state is ClaimReviewState.NEEDS_REVIEW
    assert SourceReliabilityTier.OFFICIAL_ISSUER.value == "official_issuer"
    assert not hasattr(claim, "reliability_tier")
    assert claim.source_milestones.published_at == PUBLISHED
    assert claim.source_milestones.captured_at == CAPTURED
    assert claim.clock.recorded_at == RECORDED
    assert claim.source_milestones.effective_time is None


def test_claim_requires_exact_text_hash_offsets_and_originating_evidence() -> None:
    claim = _claim()
    bad_hash = claim.model_dump(mode="python") | {"assertion_text_sha256": "0" * 64}
    with pytest.raises(ValidationError, match="does not match assertion_text"):
        Claim.model_validate(bad_hash)

    missing_origin = claim.model_dump(mode="python") | {
        "evidence": (
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship.SUPPORTS, evidence=_evidence()
            ),
        )
    }
    with pytest.raises(ValidationError, match="exactly one originating"):
        Claim.model_validate(missing_origin)


def test_effective_claim_stage_requires_explicit_effective_time() -> None:
    with pytest.raises(
        ValidationError, match="requires a source-backed effective time"
    ):
        _claim(stage=ClaimedPolicyStage.EFFECTIVE)

    effective = _claim(
        stage=ClaimedPolicyStage.FUTURE_EFFECTIVE,
        effective_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
    )
    assert effective.claimed_stage is ClaimedPolicyStage.FUTURE_EFFECTIVE


def test_jev_claims_require_confidence_and_stay_pending_until_reviewed() -> None:
    with pytest.raises(ValidationError, match="require an extraction confidence"):
        _claim(method=ClaimExtractionMethod.JEV_SUGGESTION)

    suggestion = _claim(
        method=ClaimExtractionMethod.JEV_SUGGESTION,
        confidence=Decimal("0.95"),
    )
    assert suggestion.review_state is ClaimReviewState.NEEDS_REVIEW


def test_claim_and_change_event_review_transitions_are_explicit_and_terminal() -> None:
    assert (
        transition_claim_review(
            ClaimReviewState.NEEDS_REVIEW,
            ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION,
        )
        is ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION
    )
    assert (
        transition_change_event_review(
            ChangeEventReviewState.NEEDS_REVIEW,
            ChangeEventReviewState.ACCEPTED_AS_SOURCE_EVENT,
        )
        is ChangeEventReviewState.ACCEPTED_AS_SOURCE_EVENT
    )

    with pytest.raises(ValueError, match="unsupported claim review transition"):
        transition_claim_review(
            ClaimReviewState.REJECTED, ClaimReviewState.NEEDS_REVIEW
        )
    with pytest.raises(ValueError, match="unsupported change-event review transition"):
        transition_change_event_review(
            ChangeEventReviewState.REJECTED, ChangeEventReviewState.NEEDS_REVIEW
        )


def test_change_event_requires_claims_evidence_and_kind_specific_milestone() -> None:
    claim = _claim()
    claim_ref = ClaimRevisionRef(claim_id=claim.claim_id, revision=claim.clock.revision)
    evidence = _evidence()
    with pytest.raises(ValidationError, match="requires a matching source milestone"):
        ChangeEvent(
            change_event_id=change_event_id_for_claims(
                ChangeEventKind.PROPOSAL_PUBLISHED, (claim_ref,)
            ),
            clock=BitemporalRevision(revision=1, recorded_at=RECORDED),
            primary_source_observation_id=OBSERVATION_ID,
            event_kind=ChangeEventKind.PROPOSAL_PUBLISHED,
            source_milestones=SourceMilestones(captured_at=CAPTURED),
            claims=(claim_ref,),
            evidence=(evidence,),
        )

    event = ChangeEvent(
        change_event_id=change_event_id_for_claims(
            ChangeEventKind.PROPOSAL_PUBLISHED, (claim_ref,)
        ),
        clock=BitemporalRevision(revision=1, recorded_at=RECORDED),
        primary_source_observation_id=OBSERVATION_ID,
        event_kind=ChangeEventKind.PROPOSAL_PUBLISHED,
        source_milestones=SourceMilestones(
            published_at=PUBLISHED, captured_at=CAPTURED
        ),
        claims=(claim_ref,),
        evidence=(evidence,),
    )
    assert event.review_state.value == "needs_review"
    assert event.event_kind is ChangeEventKind.PROPOSAL_PUBLISHED
