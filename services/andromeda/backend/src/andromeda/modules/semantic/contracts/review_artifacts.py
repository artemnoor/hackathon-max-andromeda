"""Versioned contracts for human-reviewed semantic proposals."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import CurriculumItemId, DisciplineId, SemanticFeatureId, SemanticVersion, SourceHash

from .public import SemanticFeatureValue


class SemanticReviewAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REWIND = "rewind"


class SemanticProposalState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REWOUND = "rewound"


class SemanticMappingProposal(ContractModel):
    proposal_id: str = Field(pattern=r"^semantic-proposal:[a-f0-9]{32}$")
    queue_id: str = Field(pattern=r"^semantic-review:[a-f0-9]{32}$")
    discipline_id: DisciplineId
    curriculum_item_id: CurriculumItemId | None = None
    feature_id: SemanticFeatureId
    feature: SemanticFeatureValue
    source_hash: SourceHash | None = None
    semantic_version: SemanticVersion
    classifier_version: SemanticVersion
    proposal_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    tool_version: str = Field(min_length=1, max_length=128)
    state: SemanticProposalState = SemanticProposalState.PENDING
    reviewer: str | None = Field(default=None, max_length=128)
    reviewed_at: datetime | None = None


class ReviewedSemanticArtifact(ContractModel):
    artifact_id: str = Field(pattern=r"^semantic-reviewed:[a-z0-9._-]+$")
    semantic_version: SemanticVersion
    classifier_version: SemanticVersion
    mappings: tuple[SemanticMappingProposal, ...] = Field(default=(), max_length=100_000)
    generated_at: datetime
    source_proposal_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


__all__ = [
    "ReviewedSemanticArtifact",
    "SemanticMappingProposal",
    "SemanticProposalState",
    "SemanticReviewAction",
]
