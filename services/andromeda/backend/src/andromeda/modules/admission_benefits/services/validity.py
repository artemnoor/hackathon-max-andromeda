"""Source-backed Olympiad result-year validity evaluation."""

from __future__ import annotations

import logging

from pydantic import Field

from andromeda.modules.admission_benefits.contracts.public import ValidityPolicy
from andromeda.modules.admission_benefits.contracts.results import EligibilityStatus
from andromeda.shared.contracts.base import ContractModel

logger = logging.getLogger("andromeda.modules.admission_benefits.validity")


class ValidityEvaluation(ContractModel):
    status: EligibilityStatus
    reason: str = Field(min_length=1, max_length=256)


def evaluate_validity(
    policy: ValidityPolicy,
    *,
    result_year: int | None,
    admission_year: int,
) -> ValidityEvaluation:
    if result_year is None:
        return _result(EligibilityStatus.INSUFFICIENT_DATA, "Olympiad result year is missing")
    if admission_year < result_year:
        return _result(EligibilityStatus.NOT_ELIGIBLE, "Admission year precedes the Olympiad result year")
    if policy.valid_from_result_year is not None and result_year < policy.valid_from_result_year:
        return _result(EligibilityStatus.NOT_ELIGIBLE, "Result year is earlier than the source validity boundary")
    if policy.valid_until_result_year is not None and result_year > policy.valid_until_result_year:
        return _result(EligibilityStatus.NOT_ELIGIBLE, "Result year is later than the source validity boundary")
    if policy.max_age_years is None and policy.valid_from_result_year is None and policy.valid_until_result_year is None:
        return _result(EligibilityStatus.REVIEW_REQUIRED, "Source validity policy has no typed year constraint")
    if policy.max_age_years is not None and admission_year - result_year > policy.max_age_years:
        return _result(EligibilityStatus.NOT_ELIGIBLE, "Olympiad result is outside the source validity period")
    return _result(EligibilityStatus.ELIGIBLE, "Result year satisfies the source validity policy")


def _result(status: EligibilityStatus, reason: str) -> ValidityEvaluation:
    logger.info("admission_benefit_validity_evaluated status=%s reason=%s", status, reason)
    return ValidityEvaluation(status=status, reason=reason)


__all__ = ["ValidityEvaluation", "evaluate_validity"]
