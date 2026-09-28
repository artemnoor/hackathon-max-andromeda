from __future__ import annotations

import logging

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
)
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
    AdmissionBenefitEvaluator,
)


def test_evaluator_logs_safe_aggregate_metadata_without_private_payload(caplog) -> None:
    caplog.set_level(logging.INFO)

    AdmissionBenefitEvaluator().evaluate(
        AdmissionBenefitEvaluationInput(
            program_id="program:bmstu:09.03.03-01",
            direction_code="09.03.03",
            admission_year=2026,
            applicant=ApplicantAdmissionFacts(),
        )
    )

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "admission_benefit_evaluation_complete" in messages
    assert "password" not in messages.casefold()
    assert "token" not in messages.casefold()
    assert "cookie" not in messages.casefold()
    assert "raw" not in messages.casefold()
