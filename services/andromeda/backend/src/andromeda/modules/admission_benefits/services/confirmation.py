"""Pure EGE/internal-exam confirmation evaluation."""

from __future__ import annotations

import logging
from decimal import Decimal

from pydantic import Field

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantExamScore,
    ApplicantInternalExamScore,
)
from andromeda.modules.admission_benefits.contracts.public import (
    ConfirmationApplicantCategory,
    ConfirmationExamKind,
    ConfirmationRequirement,
    ConfirmationSubjectRule,
)
from andromeda.modules.admission_benefits.contracts.results import EligibilityStatus
from andromeda.modules.admissions.contracts.subject_identity import (
    canonical_subject_key,
)
from andromeda.shared.contracts.base import ContractModel

logger = logging.getLogger("andromeda.modules.admission_benefits.confirmation")


class ConfirmationEvaluation(ContractModel):
    status: EligibilityStatus
    reason: str = Field(min_length=1, max_length=256)
    matched_subject: str | None = None
    required_score: Decimal | None = None
    provided_score: Decimal | None = None
    exam_kind: ConfirmationExamKind | None = None


def evaluate_confirmation(
    requirement: ConfirmationRequirement,
    subjects: tuple[ConfirmationSubjectRule, ...],
    *,
    ege_scores: tuple[ApplicantExamScore, ...] = (),
    internal_exam_scores: tuple[ApplicantInternalExamScore, ...] = (),
    applicant_category: ConfirmationApplicantCategory | None = None,
    selected_subject: str | None = None,
) -> ConfirmationEvaluation:
    if requirement is ConfirmationRequirement.NOT_REQUIRED:
        return _result(EligibilityStatus.ELIGIBLE, "Source rule does not require confirmation")
    if requirement is ConfirmationRequirement.UNKNOWN:
        return _result(EligibilityStatus.REVIEW_REQUIRED, "Source confirmation requirement is unknown")
    if not subjects:
        return _result(EligibilityStatus.REVIEW_REQUIRED, "Confirmation subject or threshold is missing")

    distinct_subjects = {canonical_subject_key(item.subject) for item in subjects}
    if selected_subject is not None:
        normalized_selection = canonical_subject_key(selected_subject)
        if normalized_selection not in distinct_subjects:
            return _result(EligibilityStatus.REVIEW_REQUIRED, "Selected confirmation subject is not source-listed for this profile")
        subjects = tuple(item for item in subjects if _same_subject(item.subject, selected_subject))
    elif len(distinct_subjects) > 1:
        return _result(EligibilityStatus.INSUFFICIENT_DATA, "Applicant must select the profile section/confirmation subject")

    insufficient = False
    below_threshold = False
    conditional_category = False
    unresolved_source_policy = False
    for subject_rule in subjects:
        if subject_rule.minimum_score is None:
            return _result(EligibilityStatus.REVIEW_REQUIRED, "Confirmation threshold is unknown")
        scores: tuple[ApplicantExamScore, ...] | tuple[ApplicantInternalExamScore, ...]
        if subject_rule.exam_kind is ConfirmationExamKind.INTERNAL_EXAM:
            scores = internal_exam_scores
        elif subject_rule.exam_kind is ConfirmationExamKind.EGE:
            scores = ege_scores
        else:
            return _result(EligibilityStatus.REVIEW_REQUIRED, "Confirmation exam kind is unknown")
        score = next((item.score for item in scores if _same_subject(item.subject, subject_rule.subject)), None)
        if score is None:
            insufficient = True
            continue
        category = applicant_category
        if category is ConfirmationApplicantCategory.UNKNOWN:
            category = None
        if subject_rule.applicant_category is ConfirmationApplicantCategory.UNKNOWN:
            unresolved_source_policy = True
            continue
        if subject_rule.applicant_category is ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION:
            if category is ConfirmationApplicantCategory.STANDARD:
                continue
            if category is None:
                if score >= subject_rule.minimum_score:
                    conditional_category = True
                continue
        if score >= subject_rule.minimum_score:
            return ConfirmationEvaluation(
                status=EligibilityStatus.ELIGIBLE,
                reason="Applicant result satisfies the source confirmation threshold",
                matched_subject=subject_rule.subject,
                required_score=subject_rule.minimum_score,
                provided_score=score,
                exam_kind=subject_rule.exam_kind,
            )
        below_threshold = True
    if conditional_category:
        return _result(EligibilityStatus.INSUFFICIENT_DATA, "Applicant category is required to apply the lower source confirmation threshold")
    if unresolved_source_policy:
        return _result(EligibilityStatus.REVIEW_REQUIRED, "Source threshold category is unresolved")
    if insufficient:
        return _result(EligibilityStatus.INSUFFICIENT_DATA, "Applicant confirmation subject is missing")
    if below_threshold:
        return _result(EligibilityStatus.NOT_ELIGIBLE, "Applicant result is below the source confirmation threshold")
    return _result(
        EligibilityStatus.NOT_ELIGIBLE,
        "Applicant confirmation does not satisfy any allowed subject",
    )


def _same_subject(left: str, right: str) -> bool:
    return canonical_subject_key(left) == canonical_subject_key(right)


def _result(status: EligibilityStatus, reason: str) -> ConfirmationEvaluation:
    logger.info("admission_benefit_confirmation_evaluated status=%s reason=%s", status, reason)
    return ConfirmationEvaluation(status=status, reason=reason)


__all__ = ["ConfirmationEvaluation", "evaluate_confirmation"]
