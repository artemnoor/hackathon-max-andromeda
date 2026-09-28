"""Pure scope evaluation for canonical admission-benefit rules."""

from __future__ import annotations

import logging

from andromeda.modules.admission_benefits.contracts.policy import ScopeApplicability
from andromeda.modules.admission_benefits.contracts.public import AdmissionBenefitRule
from andromeda.shared.contracts.enums import EducationLevel

logger = logging.getLogger("andromeda.modules.admission_benefits.applicability")


def evaluate_scope(
    rule: AdmissionBenefitRule,
    *,
    direction_code: str | None = None,
    program_id: str | None = None,
    nps: str | None = None,
    education_level: EducationLevel | str | None = None,
    campus_id: str | None = None,
) -> ScopeApplicability:
    result = rule.scope.applies_to(
        direction_code=direction_code,
        program_id=program_id,
        nps=nps,
        education_level=education_level,
        campus_id=campus_id,
    )
    logger.info(
        "admission_benefit_scope_evaluated rule_id=%s mode=%s status=%s",
        rule.id,
        rule.scope.mode,
        result.status,
    )
    return result


__all__ = ["evaluate_scope"]
