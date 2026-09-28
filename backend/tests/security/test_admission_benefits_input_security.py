from __future__ import annotations

import pytest
from pydantic import ValidationError

from andromeda.api.schemas.admission_benefits import AdmissionEligibilityRequest


def _request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "universityId": "university:bmstu",
        "directionCode": "09.03.03",
        "admissionYear": 2026,
        "applicant": {},
    }
    value.update(overrides)
    return value


def test_admission_benefit_request_rejects_invalid_canonical_identifiers() -> None:
    with pytest.raises(ValidationError):
        AdmissionEligibilityRequest.model_validate(_request(universityId="university:../secrets"))
    with pytest.raises(ValidationError):
        AdmissionEligibilityRequest.model_validate(_request(directionCode="09.03.03;DROP TABLE"))


def test_admission_benefit_request_bounds_applicant_collections() -> None:
    scores = [{"subject": f"subject-{index}", "score": 80} for index in range(21)]

    with pytest.raises(ValidationError):
        AdmissionEligibilityRequest.model_validate(_request(applicant={"egeScores": scores}))


def test_admission_benefit_request_rejects_unknown_fields_and_oversized_evidence() -> None:
    with pytest.raises(ValidationError):
        AdmissionEligibilityRequest.model_validate(_request(applicant={}, rawSql="select 1"))
    with pytest.raises(ValidationError):
        AdmissionEligibilityRequest.model_validate(
            _request(
                applicant={
                    "individualAchievements": [
                        {
                            "achievementCode": "gto",
                            "details": "x" * 513,
                        }
                    ]
                }
            )
        )
