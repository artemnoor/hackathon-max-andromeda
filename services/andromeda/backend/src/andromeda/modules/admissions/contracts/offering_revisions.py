"""Immutable, source-backed revisions of normalized admission offerings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .public import AdmissionOffering, AdmissionProvenance

AdmissionOfferingDomainRuleId = Annotated[
    str,
    StringConstraints(pattern=r"^admission:offering:[a-f0-9]{64}$"),
]


def admission_offering_domain_rule_id(offering_id: str) -> AdmissionOfferingDomainRuleId:
    """Return a stable, bounded admissions-owner ID without embedding source text."""

    if not offering_id.startswith("admission-offering:"):
        raise ValueError("admission offering ID has an unsupported namespace")
    digest = hashlib.sha256(offering_id.encode("utf-8")).hexdigest()
    return f"admission:offering:{digest}"


def admission_offering_revision_hash(offering: AdmissionOffering) -> SourceHash:
    """Hash normalized owner facts while excluding volatile capture metadata."""

    payload = offering.model_dump(mode="json")
    _strip_capture_metadata(payload)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strip_capture_metadata(payload: dict[str, object]) -> None:
    provenance = payload.get("provenance")
    if isinstance(provenance, list):
        for item in provenance:
            _strip_provenance(item)
    for collection_name in ("exams", "quotas", "passing_scores", "tuition"):
        collection = payload.get(collection_name)
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, dict):
                    _strip_provenance(item.get("provenance"))


def _strip_provenance(value: object) -> None:
    if isinstance(value, dict):
        value.pop("captured_at", None)
        value.pop("run_id", None)


class AdmissionOfferingRevision(ContractModel):
    domain_rule_id: AdmissionOfferingDomainRuleId
    offering_id: str = Field(min_length=1, max_length=320)
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    content_hash: SourceHash
    recorded_at: datetime
    offering: AdmissionOffering

    @field_validator("recorded_at")
    @classmethod
    def recorded_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("admission offering revision time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_exact_owner_revision(self) -> AdmissionOfferingRevision:
        if self.offering.id != self.offering_id:
            raise ValueError("admission offering revision ID does not match its payload")
        if self.domain_rule_id != admission_offering_domain_rule_id(self.offering_id):
            raise ValueError("admission offering domain rule ID does not match its payload")
        if self.content_hash != admission_offering_revision_hash(self.offering):
            raise ValueError("admission offering revision hash does not match its payload")
        captured_at = tuple(
            item.captured_at
            for item in _all_provenance(self.offering)
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in captured_at):
            raise ValueError("admission offering source capture times must be timezone-aware")
        if captured_at and self.recorded_at < max(captured_at):
            raise ValueError("admission offering revision cannot precede source capture")
        return self


def _all_provenance(offering: AdmissionOffering) -> Iterator[AdmissionProvenance]:
    yield from offering.provenance
    for collection in (offering.exams, offering.quotas, offering.passing_scores, offering.tuition):
        for item in collection:
            yield item.provenance


__all__ = [
    "AdmissionOfferingDomainRuleId",
    "AdmissionOfferingRevision",
    "admission_offering_domain_rule_id",
    "admission_offering_revision_hash",
]
