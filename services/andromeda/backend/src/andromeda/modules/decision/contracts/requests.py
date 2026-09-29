"""Explicit commands accepted by the decision application boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import ProgramId

from ..domain.entities import AdmissionConstraints
from ..domain.values import ShortlistRole


class DecisionConstraintsUpdate(ContractModel):
    """Full replacement of admission constraints.

    ``constraints=None`` is an explicit clear operation; omitted fields inside
    a non-null constraints object remain unknown and are not defaulted.
    """

    version: Literal[1] = 1
    constraints: AdmissionConstraints | None
    expected_revision: int | None = Field(default=None, strict=True, ge=1)


class ProgramCommand(ContractModel):
    """Explicit command addressed to one canonical educational program."""

    version: Literal[1] = 1
    program_id: ProgramId
    expected_revision: int | None = Field(default=None, strict=True, ge=1)


class ShortlistCommand(ProgramCommand):
    """Add or restore a program with an explicit user-visible role."""

    role: ShortlistRole = ShortlistRole.PRIMARY


class ShortlistRoleCommand(ProgramCommand):
    """Change the role of an already active shortlist entry."""

    role: ShortlistRole


class SuggestionDecisionCommand(ProgramCommand):
    """Accept or reject one displayed system suggestion explicitly."""

    action: Literal["accept", "reject"]


class DecisionRefinementAnswer(ContractModel):
    """Answer one currently displayed candidate-refinement question."""

    version: Literal[1] = 1
    question_id: str = Field(min_length=1, max_length=128)
    option_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(strict=True, ge=1)


__all__ = [
    "DecisionConstraintsUpdate",
    "DecisionRefinementAnswer",
    "ProgramCommand",
    "ShortlistCommand",
    "ShortlistRoleCommand",
    "SuggestionDecisionCommand",
]
