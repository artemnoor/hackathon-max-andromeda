"""Bounded, source-row-only semantic predicate contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
import re
from typing import Protocol

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel


class SemanticPredicateStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    UNAVAILABLE = "unavailable"


class SemanticPredicateFailureReason(StrEnum):
    BUDGET = "budget"
    AUTH = "auth"
    API = "api"
    INTERNAL = "internal"
    TRANSPORT = "transport"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CIRCUIT_OPEN = "circuit_open"


class SemanticPredicate(ContractModel):
    definition_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    definition_version: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    question: str = Field(min_length=1, max_length=1024)
    allowed_fields: tuple[str, ...] = Field(min_length=1, max_length=16)
    max_rows: int = Field(default=100, strict=True, ge=1, le=1000)
    max_chars_per_row: int = Field(default=2000, strict=True, ge=1, le=8000)

    @model_validator(mode="after")
    def validate_definition(self) -> SemanticPredicate:
        if len(set(self.allowed_fields)) != len(self.allowed_fields):
            raise ValueError("semantic predicate fields must be unique")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field) for field in self.allowed_fields):
            raise ValueError("semantic predicate fields must be allow-listed identifiers")
        if re.search(r"(?i)(?:\bselect\b|\bfrom\b|\bjoin\b|;|https?://)", self.question):
            raise ValueError("semantic predicate cannot contain SQL or endpoint instructions")
        return self


class SemanticPredicateRow(ContractModel):
    canonical_id: str = Field(min_length=1, max_length=256)
    fields: dict[str, str] = Field(min_length=1, max_length=16)


class SemanticPredicateRequest(ContractModel):
    predicate: SemanticPredicate
    rows: tuple[SemanticPredicateRow, ...] = Field(max_length=1000)
    batch_size: int = Field(default=32, strict=True, ge=1, le=100)
    concurrency: int = Field(default=1, strict=True, ge=1, le=8)
    timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    @model_validator(mode="after")
    def validate_budget(self) -> SemanticPredicateRequest:
        if len(self.rows) > self.predicate.max_rows:
            raise ValueError("semantic predicate row budget exceeded")
        for row in self.rows:
            if any(field not in self.predicate.allowed_fields for field in row.fields):
                raise ValueError("semantic predicate row contains a field outside the definition")
            if sum(len(value) for value in row.fields.values()) > self.predicate.max_chars_per_row:
                raise ValueError("semantic predicate row character budget exceeded")
        return self


class SemanticPredicateEvidence(ContractModel):
    canonical_id: str
    definition_id: str
    definition_version: str
    result: bool | None = None
    confidence: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"), le=Decimal("1"))
    status: SemanticPredicateStatus
    reason: SemanticPredicateFailureReason | None = None


class SemanticPredicateResult(ContractModel):
    status: SemanticPredicateStatus
    matches: dict[str, bool | None] = Field(default_factory=dict, max_length=1000)
    selected_ids: tuple[str, ...] = Field(default=(), max_length=1000)
    evaluated_population: int = Field(default=0, strict=True, ge=0)
    confidence: Decimal = Field(default=Decimal("0"), strict=True, ge=Decimal("0"), le=Decimal("1"))
    provider: str = Field(default="deterministic", max_length=64)
    model: str = Field(default="none", max_length=128)
    cache_identity: str | None = Field(default=None, max_length=256)
    failure_reason: SemanticPredicateFailureReason | None = None
    evidence: tuple[SemanticPredicateEvidence, ...] = Field(default=(), max_length=1000)


class SemanticPredicatePort(Protocol):
    def evaluate(self, request: SemanticPredicateRequest) -> SemanticPredicateResult: ...


__all__ = [
    "SemanticPredicate",
    "SemanticPredicateEvidence",
    "SemanticPredicateFailureReason",
    "SemanticPredicatePort",
    "SemanticPredicateRequest",
    "SemanticPredicateResult",
    "SemanticPredicateRow",
    "SemanticPredicateStatus",
]
