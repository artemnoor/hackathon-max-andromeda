from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitRequest,
    ApplicantAdmissionProfile,
    ApplicantSubjectScore,
)


def test_applicant_profile_is_strict_and_preserves_raw_subject() -> None:
    score = ApplicantSubjectScore(subject="  Математика  ", score=Decimal("82.50"))

    assert score.subject == "Математика"
    assert score.score == Decimal("82.50")
    assert score.model_config["extra"] == "forbid"
    assert ApplicantAdmissionProfile(scores=(score,)).model_config["extra"] == "forbid"


def test_applicant_profile_rejects_duplicate_normalized_subjects() -> None:
    with pytest.raises(ValidationError, match="unique"):
        ApplicantAdmissionProfile(
            scores=(
                ApplicantSubjectScore(subject="Математика", score=Decimal("80")),
                ApplicantSubjectScore(subject=" математика ", score=Decimal("81")),
            )
        )


def test_request_rejects_unknown_fields_and_invalid_score() -> None:
    with pytest.raises(ValidationError):
        ApplicantSubjectScore(subject="Математика", score=Decimal("101"))
    with pytest.raises(ValidationError):
        AdmissionFitRequest(
            offering_id="admission-offering:test",
            applicant=ApplicantAdmissionProfile(),
            unexpected=True,
        )
