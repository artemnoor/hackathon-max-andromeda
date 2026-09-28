"""Input contracts for recommendation use cases."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import Field, ValidationError, model_validator

from andromeda.modules.proftest.contracts.public import ProgramFingerprint, UserProfile
from andromeda.shared.contracts.base import ContractModel


logger = logging.getLogger("andromeda.recommendations")


class RecommendationRequest(ContractModel):
    """Request for ranking real program fingerprints for one profile."""

    profile: UserProfile
    limit: int = Field(default=10, strict=True, ge=1, le=20)

    @model_validator(mode="wrap")
    @classmethod
    def log_contract_error(cls, values: Any, handler: Any) -> Any:
        try:
            return handler(values)
        except ValidationError as exc:
            paths = tuple(".".join(str(part) for part in error.get("loc", ())) for error in exc.errors())
            logger.error("recommendation_request_rejected paths=%s", paths)
            raise

    @model_validator(mode="after")
    def log_request(self) -> "RecommendationRequest":
        logger.debug(
            "recommendation_request_validated limit=%d subject_axes=%d activity_axes=%d anti_axes=%d",
            self.limit,
            len(self.profile.preferred_subject_weights),
            len(self.profile.preferred_activity_weights),
            len(self.profile.negative_weights),
        )
        return self


class CandidateRankingRequest(ContractModel):
    """Rank only the source-backed candidates supplied by an orchestrator."""

    version: int = Field(default=1, strict=True, ge=1, le=1)
    profile: UserProfile
    fingerprints: tuple[ProgramFingerprint, ...] = Field(default=(), max_length=200)
    limit: int = Field(default=5, strict=True, ge=1, le=20)

    @model_validator(mode="after")
    def validate_candidates(self) -> "CandidateRankingRequest":
        program_ids = tuple(item.program_id for item in self.fingerprints)
        if len(program_ids) != len(set(program_ids)):
            raise ValueError("candidate fingerprints must have unique program ids")
        return self


__all__ = ["CandidateRankingRequest", "RecommendationRequest"]
