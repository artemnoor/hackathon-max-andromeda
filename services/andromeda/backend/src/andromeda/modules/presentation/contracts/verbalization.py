"""Bounded presentation planning contracts with no fact-generating fields."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import Field, StringConstraints, model_validator

from andromeda.shared.contracts.base import ContractModel

from .knowledge_response import ResponseMode

PresentationSectionId = Annotated[
    str,
    StringConstraints(pattern=r"^section:[a-f0-9]{64}$"),
]


class PresentationSectionKind(StrEnum):
    STATUS = "status"
    SOURCE_ASSERTIONS = "source_assertions"
    FACTS = "facts"
    RESOLUTION = "resolution"
    CYCLE_COMPARISON = "cycle_comparison"
    SCOPE = "scope"
    EXCEPTIONS = "exceptions"
    IMPACT = "impact"
    UNCERTAINTY = "uncertainty"
    EVIDENCE = "evidence"


class PresentationSectionRef(ContractModel):
    section_id: PresentationSectionId
    kind: PresentationSectionKind


class ResponseVerbalizationRequest(ContractModel):
    schema_version: Literal["source-backed-verbalization.v1"] = (
        "source-backed-verbalization.v1"
    )
    sections: tuple[PresentationSectionRef, ...] = Field(min_length=1, max_length=16)
    fixed_first_section: PresentationSectionId
    fixed_last_section: PresentationSectionId | None = None

    @model_validator(mode="after")
    def refs_are_unique_and_anchored(self) -> ResponseVerbalizationRequest:
        ids = tuple(item.section_id for item in self.sections)
        if len(ids) != len(set(ids)):
            raise ValueError("presentation section references must be unique")
        if ids[0] != self.fixed_first_section:
            raise ValueError("the status section must remain first")
        if self.fixed_last_section is not None and ids[-1] != self.fixed_last_section:
            raise ValueError("the evidence section must remain last")
        return self


class ResponseVerbalizationPlan(ContractModel):
    section_order: tuple[PresentationSectionId, ...] = Field(
        min_length=1, max_length=16
    )

    @model_validator(mode="after")
    def section_order_is_unique(self) -> ResponseVerbalizationPlan:
        if len(self.section_order) != len(set(self.section_order)):
            raise ValueError("presentation section order cannot contain duplicates")
        return self


class KnowledgeResponseRenderResult(ContractModel):
    text: str = Field(max_length=20_000)
    response_mode: ResponseMode = ResponseMode.DETERMINISTIC


class ResponseVerbalizerPort(Protocol):
    """Optional provider-neutral layout selection; it cannot return prose or facts."""

    def plan(
        self, request: ResponseVerbalizationRequest
    ) -> ResponseVerbalizationPlan: ...


__all__ = [
    "KnowledgeResponseRenderResult",
    "PresentationSectionId",
    "PresentationSectionKind",
    "PresentationSectionRef",
    "ResponseVerbalizationPlan",
    "ResponseVerbalizationRequest",
    "ResponseVerbalizerPort",
]
