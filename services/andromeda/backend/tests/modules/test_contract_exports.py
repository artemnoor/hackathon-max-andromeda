from __future__ import annotations

from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitRequest,
    AdmissionFitResult,
    ApplicantAdmissionProfile,
    ApplicantSubjectScore,
)
from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.proftest.contracts.public import UserProfile
from andromeda.modules.recommendations.contracts.public import RecommendationRequest, RecommendationResult
from andromeda.modules.universities.contracts.public import Direction, University


def test_subject_modules_expose_typed_public_contracts() -> None:
    assert all(
        cls.model_config["extra"] == "forbid"
        for cls in (
            University,
            Direction,
            Program,
            Curriculum,
            CurriculumItem,
            Discipline,
            UserProfile,
            ApplicantSubjectScore,
            ApplicantAdmissionProfile,
            AdmissionFitRequest,
            AdmissionFitResult,
        )
    )


def test_recommendation_module_exposes_strict_envelopes() -> None:
    assert RecommendationRequest.model_config["extra"] == "forbid"
    assert RecommendationResult.model_config["extra"] == "forbid"
