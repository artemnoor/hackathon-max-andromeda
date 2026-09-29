"""Typed source assertions and independent review/lifecycle axes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import NonEmptyText, SourceHash

from .evidence import EvidenceRef
from .sources import SourceObservationId
from .temporal import BitemporalRevision, SourceMilestones

ClaimId = Annotated[str, StringConstraints(pattern=r"^claim:[a-f0-9]{64}$")]
ClaimChangeEventId = Annotated[str, StringConstraints(pattern=r"^change-event:[a-f0-9]{64}$")]
ClaimPredicate = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,3}$",
    ),
]
ClaimExtractorId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,95}$")]
ClaimText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ClaimSubjectKind(StrEnum):
    UNKNOWN = "unknown"
    DOCUMENT = "document"
    UNIVERSITY = "university"
    ADMISSION_CYCLE = "admission_cycle"
    EDUCATION_LEVEL = "education_level"
    DIRECTION = "direction"
    PROGRAM = "program"
    EXAM = "exam"
    OLYMPIAD = "olympiad"
    OLYMPIAD_PROFILE = "olympiad_profile"
    INDIVIDUAL_ACHIEVEMENT = "individual_achievement"
    APPLICANT_CATEGORY = "applicant_category"


class ClaimValueText(ContractModel):
    kind: Literal["text"]
    value: NonEmptyText


class ClaimValueDecimal(ContractModel):
    kind: Literal["decimal"]
    value: Decimal = Field(strict=True, max_digits=16, decimal_places=6)


class ClaimValueBoolean(ContractModel):
    kind: Literal["boolean"]
    value: bool


class ClaimValueDate(ContractModel):
    kind: Literal["date"]
    value: date


class ClaimValueDateTime(ContractModel):
    kind: Literal["datetime"]
    value: datetime

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime claim values must be timezone-aware")
        return value.astimezone(UTC)


class ClaimValueIdentifier(ContractModel):
    kind: Literal["identifier"]
    value: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*:[^\s]{1,255}$")]


ClaimValue: TypeAlias = Annotated[
    ClaimValueText
    | ClaimValueDecimal
    | ClaimValueBoolean
    | ClaimValueDate
    | ClaimValueDateTime
    | ClaimValueIdentifier,
    Field(discriminator="kind"),
]


class ClaimProposition(ContractModel):
    """A bounded typed proposition, not a rule or executable expression."""

    predicate: ClaimPredicate
    subject_kind: ClaimSubjectKind
    subject_id: str | None = Field(default=None, min_length=1, max_length=320)
    value: ClaimValue
    unit: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("subject_id")
    @classmethod
    def validate_subject_id(cls, value: str | None) -> str | None:
        if value is not None and (":" not in value or any(char.isspace() for char in value)):
            raise ValueError("subject_id must be a canonical-looking namespaced identifier")
        return value


class ClaimedPolicyStage(StrEnum):
    """What the source asserts about a proposal or norm, not resolver state."""

    RUMOR = "rumor"
    HYPOTHESIS = "hypothesis"
    ANNOUNCED = "announced"
    PROPOSAL = "proposal"
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    ADOPTED = "adopted"
    PUBLISHED = "published"
    FUTURE_EFFECTIVE = "future_effective"
    EFFECTIVE = "effective"
    SUPERSEDED = "superseded"
    REPEALED = "repealed"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ClaimReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED_AS_SOURCE_ASSERTION = "accepted_as_source_assertion"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    DUPLICATE = "duplicate"


class ClaimExtractionMethod(StrEnum):
    STRUCTURED_DOCUMENT = "structured_document"
    DETERMINISTIC_PARSER = "deterministic_parser"
    MANUAL = "manual"
    JEV_SUGGESTION = "jev_suggestion"


class ClaimEvidenceRelationship(StrEnum):
    ORIGINATES_FROM = "originates_from"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"


class ClaimEvidenceLink(ContractModel):
    relationship: ClaimEvidenceRelationship
    evidence: EvidenceRef


class Claim(ContractModel):
    claim_id: ClaimId
    clock: BitemporalRevision
    source_observation_id: SourceObservationId
    text_start_offset: int = Field(strict=True, ge=0, le=10_000_000)
    text_end_offset: int = Field(strict=True, ge=1, le=10_000_000)
    assertion_text: ClaimText
    assertion_text_sha256: SourceHash
    proposition: ClaimProposition | None = None
    claimed_stage: ClaimedPolicyStage
    review_state: ClaimReviewState = ClaimReviewState.NEEDS_REVIEW
    source_milestones: SourceMilestones
    extraction_method: ClaimExtractionMethod
    extractor_id: ClaimExtractorId
    extractor_version: str = Field(min_length=1, max_length=64)
    extraction_confidence: Decimal | None = Field(
        default=None, strict=True, ge=Decimal(0), le=Decimal(1), max_digits=5, decimal_places=4
    )
    evidence: tuple[ClaimEvidenceLink, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_assertion(self) -> Claim:
        if self.text_start_offset >= self.text_end_offset:
            raise ValueError("claim text offsets must satisfy start < end")
        expected_hash = hashlib.sha256(self.assertion_text.encode("utf-8")).hexdigest()
        if self.assertion_text_sha256 != expected_hash:
            raise ValueError("assertion_text_sha256 does not match assertion_text")
        if self.claim_id != claim_id_for_source_assertion(
            self.source_observation_id,
            self.text_start_offset,
            self.text_end_offset,
            expected_hash,
        ):
            raise ValueError("claim_id does not match its source observation and text span")
        originating = tuple(
            link for link in self.evidence
            if link.relationship is ClaimEvidenceRelationship.ORIGINATES_FROM
        )
        if len(originating) != 1:
            raise ValueError("a source claim must have exactly one originating evidence link")
        if originating[0].evidence.source_observation_id != self.source_observation_id:
            raise ValueError("originating evidence must match the claim source observation")
        if self.source_milestones.captured_at is None:
            raise ValueError("claim source milestones must preserve captured_at")
        if self.clock.recorded_at < self.source_milestones.captured_at:
            raise ValueError("claim recorded_at cannot precede source capture")
        if self.claimed_stage in {
            ClaimedPolicyStage.FUTURE_EFFECTIVE,
            ClaimedPolicyStage.EFFECTIVE,
            ClaimedPolicyStage.SUPERSEDED,
            ClaimedPolicyStage.REPEALED,
        } and (
            self.source_milestones.effective_time is None
            or self.source_milestones.effective_time.start is None
        ):
            raise ValueError("this claimed policy stage requires a source-backed effective time")
        effective_start = self.source_milestones.effective_time.start if self.source_milestones.effective_time else None
        if effective_start is not None:
            if (
                self.claimed_stage is ClaimedPolicyStage.FUTURE_EFFECTIVE
                and effective_start <= self.clock.recorded_at
            ):
                raise ValueError("future_effective must start after the claim was recorded")
            if self.claimed_stage in {
                ClaimedPolicyStage.EFFECTIVE,
                ClaimedPolicyStage.SUPERSEDED,
                ClaimedPolicyStage.REPEALED,
            } and effective_start > self.clock.recorded_at:
                raise ValueError("effective policy stages cannot precede their source effective time")
        evidence_keys = tuple(
            (
                link.evidence.source_observation_id,
                str(link.evidence.source_url),
                link.evidence.locator.model_dump_json(),
            )
            for link in self.evidence
        )
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("claim evidence links must be unique")
        if (
            self.extraction_method is ClaimExtractionMethod.JEV_SUGGESTION
            and self.extraction_confidence is None
        ):
            raise ValueError("Jev claims require an extraction confidence")
        return self


class ChangeEventKind(StrEnum):
    HYPOTHESIS_REPORTED = "hypothesis_reported"
    ANNOUNCEMENT_PUBLISHED = "announcement_published"
    PROPOSAL_PUBLISHED = "proposal_published"
    DRAFT_PUBLISHED = "draft_published"
    DECISION_ADOPTED = "decision_adopted"
    DOCUMENT_PUBLISHED = "document_published"
    RULE_EFFECTIVE = "rule_effective"
    RULE_AMENDED = "rule_amended"
    RULE_SUPERSEDED = "rule_superseded"
    RULE_REPEALED = "rule_repealed"
    PROPOSAL_WITHDRAWN = "proposal_withdrawn"
    PROPOSAL_REJECTED = "proposal_rejected"
    UNKNOWN = "unknown"


class ChangeEventReviewState(StrEnum):
    NEEDS_REVIEW = "needs_review"
    ACCEPTED_AS_SOURCE_EVENT = "accepted_as_source_event"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    DUPLICATE = "duplicate"


class ClaimRevisionRef(ContractModel):
    claim_id: ClaimId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)


class ChangeEvent(ContractModel):
    change_event_id: ClaimChangeEventId
    clock: BitemporalRevision
    primary_source_observation_id: SourceObservationId
    event_kind: ChangeEventKind
    review_state: ChangeEventReviewState = ChangeEventReviewState.NEEDS_REVIEW
    source_milestones: SourceMilestones
    claims: tuple[ClaimRevisionRef, ...] = Field(min_length=1, max_length=128)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_event_evidence_and_time(self) -> ChangeEvent:
        if self.source_milestones.captured_at is None:
            raise ValueError("change event milestones must preserve captured_at")
        if self.clock.recorded_at < self.source_milestones.captured_at:
            raise ValueError("change event recorded_at cannot precede source capture")
        keys = tuple((item.claim_id, item.revision) for item in self.claims)
        if len(keys) != len(set(keys)):
            raise ValueError("change event claim references must be unique")
        evidence_keys = tuple(
            (item.source_observation_id, str(item.source_url), item.locator.model_dump_json())
            for item in self.evidence
        )
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("change event evidence references must be unique")
        if not any(
            item.source_observation_id == self.primary_source_observation_id
            for item in self.evidence
        ):
            raise ValueError("primary change event source observation must appear in its evidence")
        if self.change_event_id != change_event_id_for_claims(self.event_kind, self.claims):
            raise ValueError("change_event_id does not match its kind and claim references")
        if not _event_has_expected_milestone(self):
            raise ValueError("change event kind requires a matching source milestone")
        return self


def claim_id_for_source_assertion(
    source_observation_id: SourceObservationId,
    text_start_offset: int,
    text_end_offset: int,
    assertion_text_sha256: SourceHash,
) -> ClaimId:
    identity = {
        "assertion_text_sha256": assertion_text_sha256,
        "source_observation_id": source_observation_id,
        "text_end_offset": text_end_offset,
        "text_start_offset": text_start_offset,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"claim:{digest}"


def change_event_id_for_claims(
    event_kind: ChangeEventKind,
    claims: tuple[ClaimRevisionRef, ...],
) -> ClaimChangeEventId:
    claim_refs = sorted((item.claim_id, item.revision) for item in claims)
    payload = json.dumps(
        {"claims": claim_refs, "event_kind": event_kind.value},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"change-event:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _event_has_expected_milestone(event: ChangeEvent) -> bool:
    milestones = event.source_milestones
    if event.event_kind is ChangeEventKind.ANNOUNCEMENT_PUBLISHED:
        return milestones.announced_at is not None
    if event.event_kind in {
        ChangeEventKind.PROPOSAL_PUBLISHED,
        ChangeEventKind.DRAFT_PUBLISHED,
        ChangeEventKind.DOCUMENT_PUBLISHED,
    }:
        return milestones.published_at is not None
    if event.event_kind is ChangeEventKind.DECISION_ADOPTED:
        return milestones.adopted_at is not None
    if event.event_kind is ChangeEventKind.RULE_EFFECTIVE:
        return milestones.effective_time is not None and milestones.effective_time.start is not None
    if event.event_kind in {
        ChangeEventKind.RULE_AMENDED,
        ChangeEventKind.RULE_SUPERSEDED,
        ChangeEventKind.RULE_REPEALED,
    }:
        return milestones.effective_time is not None or milestones.adopted_at is not None
    if event.event_kind in {
        ChangeEventKind.PROPOSAL_WITHDRAWN,
        ChangeEventKind.PROPOSAL_REJECTED,
    }:
        return milestones.published_at is not None or milestones.announced_at is not None
    return True


__all__ = [
    "ChangeEvent",
    "ChangeEventKind",
    "ChangeEventReviewState",
    "Claim",
    "ClaimChangeEventId",
    "ClaimEvidenceLink",
    "ClaimEvidenceRelationship",
    "ClaimExtractionMethod",
    "ClaimId",
    "ClaimPredicate",
    "ClaimProposition",
    "ClaimReviewState",
    "ClaimRevisionRef",
    "ClaimSubjectKind",
    "ClaimText",
    "ClaimValue",
    "ClaimValueBoolean",
    "ClaimValueDate",
    "ClaimValueDateTime",
    "ClaimValueDecimal",
    "ClaimValueIdentifier",
    "ClaimValueText",
    "ClaimedPolicyStage",
    "change_event_id_for_claims",
    "claim_id_for_source_assertion",
]
