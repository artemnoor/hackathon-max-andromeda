from andromeda.modules.admission_benefits.contracts.results import EligibilityStatus
from andromeda.modules.admission_benefits.services.validity import evaluate_validity

from .test_helpers import validity


def test_four_year_boundary_accepts_2024_for_admission_2026() -> None:
    result = evaluate_validity(validity(4), result_year=2024, admission_year=2026)
    assert result.status is EligibilityStatus.ELIGIBLE


def test_result_older_than_source_period_is_not_eligible() -> None:
    result = evaluate_validity(validity(4), result_year=2021, admission_year=2026)
    assert result.status is EligibilityStatus.NOT_ELIGIBLE


def test_missing_or_untyped_validity_requires_review() -> None:
    missing = evaluate_validity(validity(None), result_year=2026, admission_year=2026)
    absent = evaluate_validity(validity(4), result_year=None, admission_year=2026)
    future = evaluate_validity(validity(4), result_year=2027, admission_year=2026)
    assert missing.status is EligibilityStatus.REVIEW_REQUIRED
    assert absent.status is EligibilityStatus.INSUFFICIENT_DATA
    assert future.status is EligibilityStatus.NOT_ELIGIBLE
