from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from andromeda.modules.knowledge.contracts.public import ClaimProposition
from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewAction,
    KnowledgeReviewTargetKind,
)
from andromeda.modules.policy.contracts.applicability import PolicyApplicabilityContext
from andromeda.modules.policy.contracts.what_if import PolicyHypotheticalPreview
from andromeda.shared.contracts.ids import EducationYear, UniversityId

from .common import ApiModel
from .knowledge_ops import ClaimPropositionRequest


class ReviewTargetResponse(ApiModel):
    kind: KnowledgeReviewTargetKind
    object_id: str
    revision: int = Field(ge=1)
    revision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReviewEvidenceResponse(ApiModel):
    source_id: str
    source_observation_id: str
    snapshot_sha256: str
    source_name: str | None = None
    reliability_tier: str | None = None
    source_url: str
    page: int | None = None
    table: str | None = None
    row: int | None = None
    section: str | None = None
    field: str | None = None
    record_key: str | None = None
    inferred: bool = False


class ReviewDiffEntryResponse(ApiModel):
    path: str
    kind: str
    before: str | None = None
    after: str | None = None
    reason_code: str


class ReviewActionHistoryResponse(ApiModel):
    action: str
    actor_account_id: str
    reason: str
    recorded_at: datetime
    result_revision: int
    result_hash: str
    policy_preview_fingerprint: str | None = None


class ReviewConflictParticipantResponse(ApiModel):
    kind: str
    object_id: str
    revision: int
    content_hash: str | None = None
    role: str
    evidence: tuple[ReviewEvidenceResponse, ...]


class ReviewConflictResponse(ApiModel):
    conflict_id: str
    kind: str
    state: str
    scope: str | None = None
    participants: tuple[ReviewConflictParticipantResponse, ...]


class ReviewQueueItemResponse(ApiModel):
    target: ReviewTargetResponse
    review_state: str
    created_at: datetime
    title: str
    assertion_text: str | None = None
    proposition: ClaimProposition | None = None
    extraction_method: str | None = None
    extractor: str | None = None
    confidence: Decimal | None = Field(default=None, ge=Decimal(0), le=Decimal(1))
    claimed_stage: str | None = None
    change_event_kind: str | None = None
    linked_claim_ids: tuple[str, ...] = ()
    related_assertions: tuple[str, ...] = ()
    policy_lifecycle: str | None = None
    policy_authority: str | None = None
    policy_scope: str | None = None
    domain_rule_id: str | None = None
    canonical_summary: str
    effective_from: datetime | None = None
    evidence: tuple[ReviewEvidenceResponse, ...] = ()
    diff: tuple[ReviewDiffEntryResponse, ...] = ()
    impact_status: Literal["not_required", "unavailable"] = "not_required"
    impact_reason: str | None = None
    conflicts: tuple[ReviewConflictResponse, ...] = ()
    conflicts_truncated: bool = False
    current_trace_id: str | None = None
    candidate_trace_id: str | None = None
    action_history: tuple[ReviewActionHistoryResponse, ...] = ()


class ReviewQueueResponse(ApiModel):
    items: tuple[ReviewQueueItemResponse, ...]
    truncated: bool


class ReviewDecisionRequest(ApiModel):
    target: ReviewTargetResponse
    action: KnowledgeReviewAction
    reason: str = Field(min_length=1, max_length=512)
    idempotency_key: str = Field(pattern=r"^review-idempotency:[a-f0-9]{64}$")
    policy_preview_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    policy_preview_context: ReviewPolicyPreviewContext | None = None
    edited_proposition: ClaimPropositionRequest | None = None
    canonical_subject_id: str | None = Field(default=None, min_length=1, max_length=320)
    related_target: ReviewTargetResponse | None = None

    @model_validator(mode="after")
    def payload_matches_review_action(self) -> ReviewDecisionRequest:
        policy_details = (
            self.policy_preview_context is not None,
            self.policy_preview_fingerprint is not None,
        )
        if self.target.kind is KnowledgeReviewTargetKind.POLICY_RULE:
            if self.action not in {KnowledgeReviewAction.APPROVE, KnowledgeReviewAction.REJECT}:
                raise ValueError("policy rules support only approve/reject review actions")
            if not all(policy_details):
                raise ValueError("policy decisions require the exact reviewer preview")
            if self.edited_proposition is not None or self.canonical_subject_id is not None:
                raise ValueError("policy decisions cannot include claim edit details")
        elif any(policy_details):
            raise ValueError("policy preview details apply only to policy-rule decisions")
        if self.action is KnowledgeReviewAction.EDIT:
            if self.target.kind is not KnowledgeReviewTargetKind.CLAIM:
                raise ValueError("candidate editing currently requires a source claim")
            if self.edited_proposition is None or self.canonical_subject_id is not None:
                raise ValueError("claim edit requires exactly one replacement proposition")
        elif self.action is KnowledgeReviewAction.RESOLVE_IDENTITY:
            if self.target.kind is not KnowledgeReviewTargetKind.CLAIM:
                raise ValueError("identity resolution requires a source claim")
            if self.canonical_subject_id is None or self.edited_proposition is not None:
                raise ValueError("identity resolution requires one exact canonical subject ID")
        elif self.edited_proposition is not None or self.canonical_subject_id is not None:
            raise ValueError("claim edit details apply only to edit or identity-resolution actions")
        return self


class ReviewPolicyPreviewContext(ApiModel):
    university_id: UniversityId
    admission_year: EducationYear
    applicability: PolicyApplicabilityContext = Field(
        default_factory=PolicyApplicabilityContext
    )
    valid_as_of: datetime


class ReviewPolicyPreviewRequest(ApiModel):
    target: ReviewTargetResponse
    context: ReviewPolicyPreviewContext


class ReviewPolicyPreviewResponse(ApiModel):
    preview: PolicyHypotheticalPreview


class ReviewDecisionResponse(ApiModel):
    event_id: str
    target: ReviewTargetResponse
    action: KnowledgeReviewAction
    status: str
    actor_account_id: str
    reason: str
    recorded_at: datetime
    result_revision: int
    result_hash: str
    policy_preview_fingerprint: str | None = None


__all__ = [
    "ReviewActionHistoryResponse",
    "ReviewConflictParticipantResponse",
    "ReviewConflictResponse",
    "ReviewDecisionRequest",
    "ReviewDecisionResponse",
    "ReviewDiffEntryResponse",
    "ReviewEvidenceResponse",
    "ReviewPolicyPreviewContext",
    "ReviewPolicyPreviewRequest",
    "ReviewPolicyPreviewResponse",
    "ReviewQueueItemResponse",
    "ReviewQueueResponse",
    "ReviewTargetResponse",
]
