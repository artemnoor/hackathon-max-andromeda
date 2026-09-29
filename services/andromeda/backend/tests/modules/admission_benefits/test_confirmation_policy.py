from decimal import Decimal

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
from andromeda.modules.admission_benefits.services.confirmation import (
    evaluate_confirmation,
)


def _subject(
    name: str = "информатика",
    minimum: str | None = "75",
    kind: ConfirmationExamKind = ConfirmationExamKind.EGE,
    category: ConfirmationApplicantCategory | None = None,
) -> ConfirmationSubjectRule:
    return ConfirmationSubjectRule(
        subject=name,
        minimum_score=Decimal(minimum) if minimum is not None else None,
        exam_kind=kind,
        applicant_category=category,
        source_text="Правила приема 2026",
    )


def test_ege_threshold_is_source_backed_and_boundary_is_inclusive() -> None:
    subjects = (_subject(),)
    passed = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        subjects,
        ege_scores=(ApplicantExamScore(subject="Информатика", score=Decimal("75")),),
    )
    failed = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        subjects,
        ege_scores=(ApplicantExamScore(subject="Информатика", score=Decimal("74")),),
    )
    assert passed.status is EligibilityStatus.ELIGIBLE
    assert failed.status is EligibilityStatus.NOT_ELIGIBLE


def test_multiple_profile_subjects_require_explicit_selection() -> None:
    result = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        (_subject("информатика"), _subject("физика")),
        ege_scores=(ApplicantExamScore(subject="физика", score=Decimal("80")),),
    )
    selected = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        (_subject("информатика"), _subject("физика")),
        ege_scores=(ApplicantExamScore(subject="физика", score=Decimal("80")),),
        selected_subject="физика",
    )
    assert result.status is EligibilityStatus.INSUFFICIENT_DATA
    assert selected.status is EligibilityStatus.ELIGIBLE
    assert selected.matched_subject == "физика"


def test_internal_exam_is_not_mixed_with_ege() -> None:
    result = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        (_subject(kind=ConfirmationExamKind.INTERNAL_EXAM),),
        ege_scores=(ApplicantExamScore(subject="информатика", score=Decimal("100")),),
        internal_exam_scores=(ApplicantInternalExamScore(subject="информатика", score=Decimal("75")),),
    )
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.exam_kind is ConfirmationExamKind.INTERNAL_EXAM


def test_unknown_threshold_and_exam_kind_fail_closed() -> None:
    unknown_threshold = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        (_subject(minimum=None),),
    )
    unknown_kind = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        (_subject(kind=ConfirmationExamKind.UNKNOWN),),
        ege_scores=(ApplicantExamScore(subject="информатика", score=Decimal("100")),),
    )
    assert unknown_threshold.status is EligibilityStatus.REVIEW_REQUIRED
    assert unknown_kind.status is EligibilityStatus.REVIEW_REQUIRED


def test_conditional_65_threshold_requires_explicit_applicant_category() -> None:
    subjects = (
        _subject(),
        _subject(
            minimum="65",
            category=ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION,
        ),
    )
    no_category = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        subjects,
        ege_scores=(ApplicantExamScore(subject="информатика", score=Decimal("74")),),
    )
    standard = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        subjects,
        ege_scores=(ApplicantExamScore(subject="информатика", score=Decimal("74")),),
        applicant_category=ConfirmationApplicantCategory.STANDARD,
    )
    territorial_exception = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        subjects,
        ege_scores=(ApplicantExamScore(subject="информатика", score=Decimal("65")),),
        applicant_category=ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION,
    )
    under_all_thresholds = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        subjects,
        ege_scores=(ApplicantExamScore(subject="информатика", score=Decimal("64")),),
        applicant_category=ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION,
    )
    assert no_category.status is EligibilityStatus.INSUFFICIENT_DATA
    assert standard.status is EligibilityStatus.NOT_ELIGIBLE
    assert territorial_exception.status is EligibilityStatus.ELIGIBLE
    assert under_all_thresholds.status is EligibilityStatus.NOT_ELIGIBLE


def test_75_threshold_is_unconditional_and_applies_to_either_allowed_exam_kind() -> None:
    subjects = (
        _subject(kind=ConfirmationExamKind.EGE),
        _subject(kind=ConfirmationExamKind.INTERNAL_EXAM),
    )
    result = evaluate_confirmation(
        ConfirmationRequirement.REQUIRED,
        subjects,
        internal_exam_scores=(
            ApplicantInternalExamScore(subject="информатика", score=Decimal("75")),
        ),
    )
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.exam_kind is ConfirmationExamKind.INTERNAL_EXAM
