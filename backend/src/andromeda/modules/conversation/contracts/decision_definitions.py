"""Vendor-neutral definitions for bounded decision-model operations."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel


class DecisionDefinitionKind(StrEnum):
    INTENT = "intent"
    METRIC = "metric"
    NEXT_ACTION = "next_action"
    PRESENTATION = "presentation"
    SEMANTIC_FEATURE = "semantic_feature"
    ENTITY_RESOLUTION = "entity_resolution"


class DecisionTimeoutClass(StrEnum):
    INTERACTIVE = "interactive"
    ENRICHMENT = "enrichment"
    EVALUATION = "evaluation"


class DecisionPiiPolicy(StrEnum):
    REDACTED = "redacted"
    SANITIZED = "sanitized"
    LOCAL_ONLY = "local_only"


class DecisionOption(ContractModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    description: str = Field(min_length=1, max_length=256)


class DecisionOutputSchema(ContractModel):
    fields: tuple[str, ...] = Field(default=(), max_length=32)
    allowed_values: tuple[str, ...] = Field(default=(), max_length=128)
    additional_properties: bool = False


class DecisionDefinition(ContractModel):
    definition_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    kind: DecisionDefinitionKind
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    version: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    instructions: str = Field(min_length=1, max_length=4000)
    criteria: tuple[str, ...] = Field(default=(), max_length=16)
    options: tuple[DecisionOption, ...] = Field(default=(), max_length=128)
    input_fields: tuple[str, ...] = Field(default=(), max_length=32)
    output_schema: DecisionOutputSchema
    deterministic_fallback: str = Field(min_length=1, max_length=128)
    timeout_class: DecisionTimeoutClass
    max_input_chars: int = Field(default=2000, ge=1, le=20_000)
    pii_policy: DecisionPiiPolicy
    evidence_required: bool = True
    evaluation_dataset_key: str = Field(min_length=1, max_length=128)
    calibration_lock_id: str | None = Field(default=None, max_length=128)


class QuestionRegistryPort(Protocol):
    def get(self, definition_id: str) -> DecisionDefinition: ...

    def for_operation(self, operation: str) -> DecisionDefinition: ...

    def all(self) -> tuple[DecisionDefinition, ...]: ...


__all__ = [
    "DecisionDefinition",
    "DecisionDefinitionKind",
    "DecisionOption",
    "DecisionOutputSchema",
    "DecisionPiiPolicy",
    "DecisionTimeoutClass",
    "QuestionRegistryPort",
]

