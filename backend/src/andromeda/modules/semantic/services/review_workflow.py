"""Explicit proposal/review/publish workflow for semantic mappings."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from collections.abc import Iterable

from ..contracts.public import SemanticClassificationMethod, SemanticFeatureValue, SemanticReviewStatus
from ..contracts.review import SemanticReviewQueueItem
from ..contracts.review_artifacts import (
    ReviewedSemanticArtifact,
    SemanticMappingProposal,
    SemanticProposalState,
    SemanticReviewAction,
)


class SemanticReviewWorkflow:
    """Keep human review as a required state transition before activation."""

    def propose(
        self,
        queue_item: SemanticReviewQueueItem,
        *,
        feature_id: str,
        feature: SemanticFeatureValue,
        tool_version: str,
    ) -> SemanticMappingProposal:
        if feature.feature_id != feature_id:
            raise ValueError("proposal feature id does not match semantic value")
        reviewed_feature = feature.model_copy(
            update={
                "classification_method": SemanticClassificationMethod.JEV,
                "review_status": SemanticReviewStatus.UNREVIEWED,
            }
        )
        proposal_hash = _hash(
            {
                "queue_id": queue_item.queue_id,
                "feature_id": feature_id,
                "feature": reviewed_feature.model_dump(mode="json"),
                "source_hash": queue_item.source_hash,
            }
        )
        proposal_id = "semantic-proposal:" + hashlib.sha256(proposal_hash.encode("utf-8")).hexdigest()[:32]
        return SemanticMappingProposal(
            proposal_id=proposal_id,
            queue_id=queue_item.queue_id,
            discipline_id=queue_item.discipline_id,
            curriculum_item_id=queue_item.curriculum_item_id,
            feature_id=feature_id,
            feature=reviewed_feature,
            source_hash=queue_item.source_hash,
            semantic_version=queue_item.semantic_version,
            classifier_version=queue_item.classifier_version,
            proposal_hash=proposal_hash,
            tool_version=tool_version,
        )

    def review(
        self,
        proposal: SemanticMappingProposal,
        action: SemanticReviewAction,
        *,
        reviewer: str,
        current_source_hash: str | None,
        now: datetime | None = None,
    ) -> SemanticMappingProposal:
        if proposal.source_hash != current_source_hash:
            raise ValueError("stale semantic proposal source hash")
        if action is SemanticReviewAction.ACCEPT:
            state = SemanticProposalState.ACCEPTED
        elif action is SemanticReviewAction.REJECT:
            state = SemanticProposalState.REJECTED
        else:
            state = SemanticProposalState.REWOUND
        return proposal.model_copy(
            update={
                "state": state,
                "reviewer": reviewer,
                "reviewed_at": now or datetime.now(UTC),
            }
        )

    def publish(
        self,
        proposals: Iterable[SemanticMappingProposal],
        *,
        artifact_id: str,
        semantic_version: str,
        classifier_version: str,
        diff_report_present: bool,
        now: datetime | None = None,
    ) -> ReviewedSemanticArtifact:
        proposals_tuple = tuple(proposals)
        if not diff_report_present:
            raise ValueError("semantic artifact diff report is required")
        if any(proposal.state is SemanticProposalState.PENDING for proposal in proposals_tuple):
            raise ValueError("unreviewed semantic proposals cannot be published")
        accepted = tuple(
            proposal.model_copy(
                update={
                    "feature": proposal.feature.model_copy(update={"review_status": SemanticReviewStatus.REVIEWED}),
                }
            )
            for proposal in proposals_tuple
            if proposal.state is SemanticProposalState.ACCEPTED
        )
        return ReviewedSemanticArtifact(
            artifact_id=artifact_id,
            semantic_version=semantic_version,
            classifier_version=classifier_version,
            mappings=accepted,
            generated_at=now or datetime.now(UTC),
            source_proposal_hash=_hash(tuple(proposal.proposal_hash for proposal in proposals_tuple)),
        )


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["SemanticReviewWorkflow"]
