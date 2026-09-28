from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    Claim,
    ClaimedPolicyStage,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimProposition,
    ClaimSubjectKind,
    ClaimValueDecimal,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    SourcePollAttempt,
    SourcePollOutcome,
    TemporalInterval,
    claim_id_for_source_assertion,
)
from andromeda.modules.knowledge.domain.claim_fingerprint import fingerprint_claim
from andromeda.modules.knowledge.services.candidate_diff import (
    diff_claim_sets,
    diff_source_attempt,
)

NOW = datetime(2027, 12, 15, 12, tzinfo=UTC)
EFFECTIVE = datetime(2028, 9, 1, tzinfo=UTC)


def _claim(
    source_suffix: str,
    *,
    text: str,
    value: Decimal | None,
    offset: int = 10,
    valid_from: datetime = EFFECTIVE,
    subject_id: str = "subject:mathematics",
    stage: ClaimedPolicyStage = ClaimedPolicyStage.PROPOSAL,
    source_id: str | None = None,
) -> Claim:
    observation_id = f"source-observation:{source_suffix * 32}"
    source_id = source_id or f"source:issuer-{source_suffix}"
    snapshot_hash = hashlib.sha256(source_suffix.encode()).hexdigest()
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    evidence = EvidenceRef(
        source_id=source_id,
        source_observation_id=observation_id,
        snapshot_sha256=snapshot_hash,
        source_url=f"https://issuer-{source_suffix}.example/admission/rules.pdf",
        locator=EvidenceLocator(page=2, section="minimum score"),
    )
    proposition = (
        ClaimProposition(
            predicate="admission.minimum_ege_score",
            subject_kind=ClaimSubjectKind.EXAM,
            subject_id=subject_id,
            value=ClaimValueDecimal(kind="decimal", value=value),
            unit="score",
        )
        if value is not None
        else None
    )
    return Claim(
        claim_id=claim_id_for_source_assertion(
            observation_id, offset, offset + len(text), text_hash
        ),
        clock=BitemporalRevision(
            revision=1,
            valid_time=TemporalInterval(start=valid_from),
            recorded_at=NOW,
        ),
        source_observation_id=observation_id,
        text_start_offset=offset,
        text_end_offset=offset + len(text),
        assertion_text=text,
        assertion_text_sha256=text_hash,
        proposition=proposition,
        claimed_stage=stage,
        source_milestones=SourceMilestones(
            captured_at=NOW,
            effective_time=TemporalInterval(start=EFFECTIVE),
        ),
        extraction_method=ClaimExtractionMethod.DETERMINISTIC_PARSER,
        extractor_id="official_text",
        extractor_version="v1",
        evidence=(
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                evidence=evidence,
            ),
        ),
    )


def test_exact_duplicate_claims_share_a_review_diff_and_keep_source_specific_refs() -> None:
    first = _claim("a", text="Минимальный балл ЕГЭ — 75.", value=Decimal(75))
    second = _claim("b", text="Минимальный  балл ЕГЭ — 75.", value=Decimal(75))

    assert fingerprint_claim(first) == fingerprint_claim(second)
    diff = diff_claim_sets((first,), (second,))
    assert len(diff.entries) == 1
    entry = diff.entries[0]
    assert entry.kind.value == "unchanged"
    assert entry.before[0].claim_id == first.claim_id
    assert entry.after[0].claim_id == second.claim_id
    assert first.source_observation_id != second.source_observation_id


def test_changed_typed_value_produces_a_field_diff_but_untyped_paraphrase_does_not_pair() -> None:
    previous = _claim("a", text="Минимальный балл ЕГЭ — 75.", value=Decimal(75))
    current = _claim("b", text="Минимальный балл ЕГЭ — 80.", value=Decimal(80))

    revised = diff_claim_sets((previous,), (current,))
    assert len(revised.entries) == 1
    assert revised.entries[0].kind.value == "revised"
    assert {change.path for change in revised.entries[0].changes} == {
        "assertion_text",
        "proposition.value",
    }
    value_change = next(
        change for change in revised.entries[0].changes if change.path == "proposition.value"
    )
    assert '"value":"75"' in (value_change.before or "")
    assert '"value":"80"' in (value_change.after or "")

    untyped_old = _claim("a", text="Предлагается изменить минимальный балл ЕГЭ.", value=None)
    untyped_new = _claim("b", text="Предлагается увеличить минимальный проходной балл ЕГЭ.", value=None)
    untyped_diff = diff_claim_sets((untyped_old,), (untyped_new,))
    assert {entry.kind.value for entry in untyped_diff.entries} == {"removed", "added"}


def test_exact_fingerprint_keeps_different_scope_stage_and_valid_period_separate() -> None:
    base = _claim("a", text="Для математики действует правило.", value=Decimal(75))
    different_scope = _claim(
        "b",
        text="Для математики действует правило.",
        value=Decimal(75),
        subject_id="subject:physics",
    )
    different_stage = _claim(
        "c",
        text="Для математики действует правило.",
        value=Decimal(75),
        stage=ClaimedPolicyStage.DRAFT,
    )
    different_time = _claim(
        "d",
        text="Для математики действует правило.",
        value=Decimal(75),
        valid_from=datetime(2029, 9, 1, tzinfo=UTC),
    )
    assert len(
        {
            fingerprint_claim(base),
            fingerprint_claim(different_scope),
            fingerprint_claim(different_stage),
            fingerprint_claim(different_time),
        }
    ) == 4
    temporal_diff = diff_claim_sets((base,), (different_time,))
    assert len(temporal_diff.entries) == 1
    assert temporal_diff.entries[0].kind.value == "revised"
    assert "valid_time.start" in {
        change.path for change in temporal_diff.entries[0].changes
    }


def test_source_diff_pairs_changed_snapshot_with_typed_candidate_value_change() -> None:
    before = SourcePollAttempt(
        attempt_id="poll-attempt:" + "a" * 32,
        source_id="source:issuer-a",
        registry_revision=1,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        outcome=SourcePollOutcome.NEW,
        parser_version="policy_text_lines:v1",
        snapshot_sha256="a" * 64,
        last_successful_snapshot_sha256="a" * 64,
        source_observation_id="source-observation:" + "a" * 32,
        retry_count=0,
        extracted_candidate_count=1,
    )
    after = SourcePollAttempt(
        attempt_id="poll-attempt:" + "b" * 32,
        source_id="source:issuer-a",
        registry_revision=1,
        started_at=NOW + timedelta(days=1),
        completed_at=NOW + timedelta(days=1, seconds=1),
        outcome=SourcePollOutcome.CHANGED,
        parser_version="policy_text_lines:v1",
        previous_snapshot_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        last_successful_snapshot_sha256="b" * 64,
        source_observation_id="source-observation:" + "b" * 32,
        retry_count=0,
        extracted_candidate_count=1,
    )
    diff = diff_source_attempt(
        before,
        after,
        before_claims=(
            _claim(
                "a",
                text="Минимальный балл ЕГЭ — 75.",
                value=Decimal(75),
                source_id="source:issuer-a",
            ),
        ),
        after_claims=(
            _claim(
                "b",
                text="Минимальный балл ЕГЭ — 80.",
                value=Decimal(80),
                source_id="source:issuer-a",
            ),
        ),
    )
    assert diff.current_attempt_outcome is SourcePollOutcome.CHANGED
    assert diff.previous_snapshot_sha256 == "a" * 64
    assert diff.snapshot_sha256 == "b" * 64
    assert diff.claim_diff is not None
    assert diff.claim_diff.entries[0].kind.value == "revised"


def test_source_unavailability_never_becomes_a_claim_removal_diff() -> None:
    current = SourcePollAttempt(
        attempt_id="poll-attempt:" + "c" * 32,
        source_id="source:issuer-a",
        registry_revision=1,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        outcome=SourcePollOutcome.REMOVED,
        parser_version="policy_text_lines:v1",
        previous_snapshot_sha256="a" * 64,
        last_successful_snapshot_sha256="a" * 64,
        retry_count=1,
        next_retry_at=NOW + timedelta(minutes=2),
        failure_code="http_404",
        extracted_candidate_count=0,
    )
    diff = diff_source_attempt(None, current)
    assert diff.current_attempt_outcome is SourcePollOutcome.REMOVED
    assert diff.claim_diff is None
    assert diff.last_successful_snapshot_sha256 == "a" * 64
