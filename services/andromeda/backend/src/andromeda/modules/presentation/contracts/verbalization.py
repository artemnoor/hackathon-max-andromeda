"""Bounded presentation planning contracts with no fact-generating fields."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import Field, StringConstraints, model_validator

from andromeda.shared.contracts.base import ContractModel

from .knowledge_response import ResponseMode

PresentationSectionId = Annotated[
    str,
    StringConstraints(pattern=r"^section:[a-f0-9]{64}$"),
]
ResponseNaturalizationReferenceId = Annotated[
    str,
    StringConstraints(pattern=r"^reference:[a-f0-9]{64}$"),
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


class ResponseNaturalizationReferenceKind(StrEnum):
    FACT = "fact"
    ENTITY = "entity"
    SOURCE = "source"
    POLICY = "policy"


class ResponseNaturalizationReference(ContractModel):
    reference_id: ResponseNaturalizationReferenceId
    kind: ResponseNaturalizationReferenceKind
    label: str = Field(min_length=1, max_length=256)
    value: str | None = Field(default=None, max_length=512)


class ResponseNaturalizationSection(ContractModel):
    section: PresentationSectionRef
    text: str = Field(min_length=1, max_length=4_000)
    allowed_reference_ids: tuple[ResponseNaturalizationReferenceId, ...] = Field(
        min_length=1, max_length=64
    )

    @model_validator(mode="after")
    def allowed_references_are_unique(self) -> ResponseNaturalizationSection:
        if len(self.allowed_reference_ids) != len(set(self.allowed_reference_ids)):
            raise ValueError("naturalization reference IDs must be unique per section")
        return self


class ResponseNaturalizationRequest(ContractModel):
    schema_version: Literal["source-backed-naturalization.v1"] = (
        "source-backed-naturalization.v1"
    )
    response_mode: Literal[ResponseMode.DETERMINISTIC] = ResponseMode.DETERMINISTIC
    sections: tuple[ResponseNaturalizationSection, ...] = Field(
        min_length=1, max_length=16
    )
    allowed_references: tuple[ResponseNaturalizationReference, ...] = Field(
        default=(), max_length=256
    )
    required_section_order: tuple[PresentationSectionId, ...] = Field(
        min_length=1, max_length=16
    )

    @model_validator(mode="after")
    def naturalization_request_is_bounded_and_consistent(
        self,
    ) -> ResponseNaturalizationRequest:
        section_ids = tuple(item.section.section_id for item in self.sections)
        if section_ids != self.required_section_order:
            raise ValueError("required naturalization section order must match inputs")
        reference_ids = tuple(item.reference_id for item in self.allowed_references)
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("naturalization references must be unique")
        allowed = set(reference_ids)
        allowed.update(section_reference_id(section_id) for section_id in section_ids)
        for section in self.sections:
            if not set(section.allowed_reference_ids).issubset(allowed):
                raise ValueError("section references must be declared by the request")
        if sum(len(item.text) for item in self.sections) > 20_000:
            raise ValueError("naturalization input exceeds the total text limit")
        return self


class ResponseNaturalizedSection(ContractModel):
    section_id: PresentationSectionId
    text: str = Field(min_length=1, max_length=4_000)
    reference_ids: tuple[ResponseNaturalizationReferenceId, ...] = Field(
        min_length=1, max_length=64
    )

    @model_validator(mode="after")
    def output_references_are_unique(self) -> ResponseNaturalizedSection:
        if len(self.reference_ids) != len(set(self.reference_ids)):
            raise ValueError("naturalized section references must be unique")
        return self


class ResponseNaturalizationResult(ContractModel):
    schema_version: Literal["source-backed-naturalization.v1"] = (
        "source-backed-naturalization.v1"
    )
    sections: tuple[ResponseNaturalizedSection, ...] = Field(
        min_length=1, max_length=16
    )

    @model_validator(mode="after")
    def result_sections_are_unique(self) -> ResponseNaturalizationResult:
        ids = tuple(item.section_id for item in self.sections)
        if len(ids) != len(set(ids)):
            raise ValueError("naturalized section IDs must be unique")
        return self


class ResponseNaturalizerPort(Protocol):
    """Optional prose adapter; it cannot persist or change typed response data."""

    def naturalize(
        self,
        request: ResponseNaturalizationRequest,
        *,
        rate_limit_key: str,
    ) -> ResponseNaturalizationResult: ...


def section_reference_id(section_id: PresentationSectionId) -> str:
    """Return the typed reference used to anchor prose to one supplied section."""

    return "reference:" + hashlib.sha256(section_id.encode("utf-8")).hexdigest()


__all__ = [
    "KnowledgeResponseRenderResult",
    "PresentationSectionId",
    "PresentationSectionKind",
    "PresentationSectionRef",
    "ResponseNaturalizationReference",
    "ResponseNaturalizationReferenceId",
    "ResponseNaturalizationReferenceKind",
    "ResponseNaturalizationRequest",
    "ResponseNaturalizationResult",
    "ResponseNaturalizationSection",
    "ResponseNaturalizedSection",
    "ResponseNaturalizerPort",
    "ResponseVerbalizationPlan",
    "ResponseVerbalizationRequest",
    "ResponseVerbalizerPort",
    "section_reference_id",
]
