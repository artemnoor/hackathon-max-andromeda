from __future__ import annotations

from andromeda.modules.admission_fit.domain.subject_identity import (
    SubjectResolutionStatus,
    canonical_subject_key,
    normalize_subject_name,
    resolve_subject,
)


def test_subject_identity_normalizes_typography_and_explicit_aliases() -> None:
    assert normalize_subject_name("  ФИЗИКА — профиль  ") == "физика профиль"
    assert canonical_subject_key("Русский") == canonical_subject_key("Русский язык")
    result = resolve_subject("русский", ("Русский язык",))

    assert result.status is SubjectResolutionStatus.MATCHED
    assert result.matched_subject == "Русский язык"


def test_subject_identity_does_not_choose_between_ambiguous_candidates() -> None:
    result = resolve_subject("Математика профиль", ("Математика", "Математика (профиль)"))

    assert result.status is SubjectResolutionStatus.AMBIGUOUS
    assert result.matched_subject is None
    assert result.candidates == ("Математика", "Математика (профиль)")


def test_subject_identity_reports_missing_without_fuzzy_match() -> None:
    result = resolve_subject("Инженерная графика", ("Математика", "Физика"))

    assert result.status is SubjectResolutionStatus.MISSING
    assert result.candidates == ()
