"""Bounded hierarchical selection contracts layered over deterministic resolution."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel

from .public import EntityResolutionCandidate, ResolutionEntityType, ResolutionStatus


class SelectionFailureReason(StrEnum):
    TIMEOUT = "timeout"
    MALFORMED = "malformed"
    BUDGET = "budget"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CANDIDATE_TAMPERING = "candidate_tampering"


class SelectionNode(ContractModel):
    node_id: str = Field(min_length=1, max_length=128)
    depth: int = Field(strict=True, ge=0, le=8)
    candidate_ids: tuple[str, ...] = Field(default=(), max_length=256)
    children: tuple[SelectionNode, ...] = Field(default=(), max_length=32)


class SelectionTree(ContractModel):
    root: SelectionNode
    max_depth: int = Field(default=4, strict=True, ge=1, le=8)
    max_fanout: int = Field(default=16, strict=True, ge=1, le=64)


class SelectionRequest(ContractModel):
    entity_type: ResolutionEntityType
    query: str = Field(min_length=1, max_length=512)
    candidates: tuple[EntityResolutionCandidate, ...] = Field(min_length=1, max_length=1000)
    tree: SelectionTree
    candidate_threshold: int = Field(strict=True, ge=1, le=1000)
    definition_version: str = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(default=1.5, gt=0, le=15)


class SelectionResult(ContractModel):
    status: ResolutionStatus
    selected_id: str | None = Field(default=None, max_length=256)
    candidate_ids: tuple[str, ...] = Field(default=(), max_length=1000)
    strategy: str = Field(min_length=1, max_length=64)
    candidate_hash: str = Field(min_length=1, max_length=128)
    failure_reason: SelectionFailureReason | None = None

    @model_validator(mode="after")
    def validate_selected_id(self) -> SelectionResult:
        if self.selected_id is not None and self.selected_id not in self.candidate_ids:
            raise ValueError("hierarchical selector returned a non-canonical candidate")
        return self


class HierarchicalSelectionPort(Protocol):
    def select(self, request: SelectionRequest) -> SelectionResult: ...


__all__ = [
    "HierarchicalSelectionPort",
    "SelectionFailureReason",
    "SelectionNode",
    "SelectionRequest",
    "SelectionResult",
    "SelectionTree",
]
