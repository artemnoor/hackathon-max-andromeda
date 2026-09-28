"""Typed legal-route mapping for admission-benefit evaluation."""

from __future__ import annotations

from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionRoute,
    BenefitType,
)

_ROUTE_BY_BENEFIT: dict[BenefitType, AdmissionRoute] = {
    BenefitType.BVI: AdmissionRoute.OLYMPIAD,
    BenefitType.ONE_HUNDRED_POINTS: AdmissionRoute.OLYMPIAD,
    BenefitType.MAX_INTERNAL_EXAM_SCORE: AdmissionRoute.OLYMPIAD,
    BenefitType.SPECIAL_RIGHT: AdmissionRoute.SPECIAL_RIGHT,
    BenefitType.PREFERENTIAL_RIGHT: AdmissionRoute.PREFERENTIAL_RIGHT,
    BenefitType.SPECIAL_QUOTA: AdmissionRoute.SPECIAL_QUOTA,
    BenefitType.SEPARATE_QUOTA: AdmissionRoute.SEPARATE_QUOTA,
    BenefitType.TARGETED_ROUTE: AdmissionRoute.TARGETED,
}


def route_for_benefit_type(benefit_type: BenefitType) -> AdmissionRoute | None:
    """Return the legal route represented by a canonical benefit type."""

    return _ROUTE_BY_BENEFIT.get(benefit_type)


__all__ = ["route_for_benefit_type"]
