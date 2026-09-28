from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.ids import canonical_program_id

from .status import ApplicabilityStatus, TargetResolutionStatus


class BenefitScopeMode(StrEnum):
    ALL = "all"
    ONLY = "only"
    ALL_EXCEPT = "all_except"


class BenefitTargetKind(StrEnum):
    DIRECTION = "direction"
    PROGRAM = "program"
    NPS = "nps"
    EDUCATION_LEVEL = "education_level"
    CAMPUS = "campus"


class BenefitConditionKind(StrEnum):
    CONFIRMATION_SCORE = "confirmation_score"
    CONFIRMATION_CATEGORY = "confirmation_category"
    VALIDITY = "validity"
    REQUIRED_DOCUMENT = "required_document"
    RESULT_TYPE = "result_type"
    TARGET_SCOPE = "target_scope"
    OTHER = "other"


class BenefitTarget(ContractModel):
    """A normalized target while retaining the exact source wording."""

    kind: BenefitTargetKind
    value: str = Field(min_length=1, max_length=256)
    original_text: str = Field(min_length=1, max_length=512)
    resolution: TargetResolutionStatus = TargetResolutionStatus.RESOLVED

    @model_validator(mode="before")
    @classmethod
    def normalize_value(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        raw_kind = data.get("kind")
        raw_resolution = data.get("resolution", TargetResolutionStatus.RESOLVED)
        if not isinstance(raw_kind, str):
            return data
        if not isinstance(raw_resolution, (str, TargetResolutionStatus)):
            return data
        try:
            kind = BenefitTargetKind(raw_kind)
            resolution = TargetResolutionStatus(raw_resolution)
        except ValueError:
            return data
        value = str(data.get("value", "")).strip()
        if resolution is TargetResolutionStatus.UNRESOLVED:
            return {**data, "value": value}
        if kind is BenefitTargetKind.DIRECTION:
            if re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{2}", value) is None:
                raise ValueError("direction target must use an OKSO code")
        elif kind is BenefitTargetKind.PROGRAM:
            if not value.startswith("program:"):
                raise ValueError("program target must use a canonical program id")
            value = canonical_program_id(value)
        elif kind is BenefitTargetKind.EDUCATION_LEVEL:
            try:
                value = EducationLevel(value.casefold()).value
            except ValueError:
                raise ValueError("education level target is unsupported")
        elif kind is BenefitTargetKind.CAMPUS:
            if re.fullmatch(r"campus:[a-z0-9][a-z0-9-]{0,62}", value) is None:
                raise ValueError("campus target must use a canonical campus id")
        else:
            value = value.casefold()
        return {**data, "value": value}


class ScopeApplicability(ContractModel):
    status: ApplicabilityStatus
    matched_target: BenefitTarget | None = None
    reason: str = Field(min_length=1, max_length=256)


class BenefitScope(ContractModel):
    """Deterministic ALL/ONLY/ALL_EXCEPT rule scope without row expansion."""

    mode: BenefitScopeMode
    targets: tuple[BenefitTarget, ...] = ()
    excluded_targets: tuple[BenefitTarget, ...] = ()
    original_text: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.mode is BenefitScopeMode.ONLY and not self.targets:
            raise ValueError("ONLY scope requires at least one target")
        if self.mode is BenefitScopeMode.ALL_EXCEPT and not self.targets:
            raise ValueError("ALL_EXCEPT scope requires at least one excluded target")
        if self.mode is BenefitScopeMode.ONLY and self.excluded_targets:
            raise ValueError("ONLY scope cannot contain excluded targets")
        if self.mode is BenefitScopeMode.ALL_EXCEPT and self.excluded_targets:
            raise ValueError("ALL_EXCEPT scope stores exclusions in targets")
        return self

    @property
    def unresolved_targets(self) -> tuple[BenefitTarget, ...]:
        return tuple(
            target
            for target in (*self.targets, *self.excluded_targets)
            if target.resolution is TargetResolutionStatus.UNRESOLVED
        )

    def applies_to(
        self,
        *,
        direction_code: str | None = None,
        program_id: str | None = None,
        nps: str | None = None,
        education_level: EducationLevel | str | None = None,
        campus_id: str | None = None,
    ) -> ScopeApplicability:
        if self.unresolved_targets:
            return ScopeApplicability(
                status=ApplicabilityStatus.REVIEW_REQUIRED,
                reason="scope contains unresolved canonical targets",
            )
        candidates = {
            BenefitTargetKind.DIRECTION: _normalize_candidate(BenefitTargetKind.DIRECTION, direction_code),
            BenefitTargetKind.PROGRAM: _normalize_candidate(BenefitTargetKind.PROGRAM, program_id),
            BenefitTargetKind.NPS: _normalize_candidate(BenefitTargetKind.NPS, nps),
            BenefitTargetKind.EDUCATION_LEVEL: _normalize_candidate(BenefitTargetKind.EDUCATION_LEVEL, education_level),
            BenefitTargetKind.CAMPUS: _normalize_candidate(BenefitTargetKind.CAMPUS, campus_id),
        }
        if self.mode is BenefitScopeMode.ONLY:
            return _evaluate_only(self.targets, candidates)
        excluded = self.excluded_targets if self.mode is BenefitScopeMode.ALL else self.targets
        return _evaluate_exclusions(excluded, candidates)


def _evaluate_only(
    targets: tuple[BenefitTarget, ...], candidates: dict[BenefitTargetKind, str | None]
) -> ScopeApplicability:
    missing = [target for target in targets if candidates[target.kind] is None]
    for target in targets:
        if candidates[target.kind] == target.value:
            return ScopeApplicability(
                status=ApplicabilityStatus.APPLICABLE,
                matched_target=target,
                reason="candidate matches an ONLY target",
            )
    if missing:
        return ScopeApplicability(
            status=ApplicabilityStatus.INSUFFICIENT_DATA,
            reason="candidate data is missing for one or more ONLY targets",
        )
    return ScopeApplicability(status=ApplicabilityStatus.NOT_APPLICABLE, reason="candidate matches no ONLY target")


def _evaluate_exclusions(
    excluded: tuple[BenefitTarget, ...], candidates: dict[BenefitTargetKind, str | None]
) -> ScopeApplicability:
    missing = [target for target in excluded if candidates[target.kind] is None]
    for target in excluded:
        if candidates[target.kind] == target.value:
            return ScopeApplicability(
                status=ApplicabilityStatus.NOT_APPLICABLE,
                matched_target=target,
                reason="candidate matches an excluded target",
            )
    if missing:
        return ScopeApplicability(
            status=ApplicabilityStatus.INSUFFICIENT_DATA,
            reason="candidate data is missing for an exclusion target",
        )
    return ScopeApplicability(status=ApplicabilityStatus.APPLICABLE, reason="candidate is within the scope")


def _normalize_candidate(kind: BenefitTargetKind, value: object) -> str | None:
    if value is None:
        return None
    if kind is BenefitTargetKind.PROGRAM:
        return canonical_program_id(str(value).strip())
    if kind is BenefitTargetKind.DIRECTION:
        return str(value).strip()
    if kind is BenefitTargetKind.EDUCATION_LEVEL:
        try:
            return EducationLevel(str(value).casefold()).value
        except ValueError:
            return str(value).casefold().strip()
    if kind is BenefitTargetKind.CAMPUS:
        return str(value).strip().casefold()
    return str(value).casefold().strip()


__all__ = [
    "BenefitConditionKind",
    "BenefitScope",
    "BenefitScopeMode",
    "BenefitTarget",
    "BenefitTargetKind",
    "ScopeApplicability",
]
