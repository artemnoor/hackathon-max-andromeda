"""Application-facing facade over the admission-benefit repository port."""

from __future__ import annotations

import logging
from time import perf_counter

from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    IndividualAchievementPolicy,
)
from andromeda.modules.admission_benefits.contracts.results import (
    AdmissionDecisionResult,
)
from andromeda.modules.admission_benefits.contracts.snapshot import (
    AdmissionBenefitsSnapshot,
)
from andromeda.modules.admission_benefits.repository.ports import AdmissionBenefitReader
from andromeda.modules.admission_benefits.services.admission_decision import (
    AdmissionDecisionService,
)
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
)
from andromeda.modules.admissions.contracts.public import (
    AdmissionOffering,
    FundingType,
    StudyForm,
)
from andromeda.modules.admissions.repository.ports import AdmissionReader
from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.ids import (
    DirectionCode,
    EducationYear,
    OlympiadId,
    ProgramId,
    UniversityId,
)

logger = logging.getLogger("andromeda.modules.admission_benefits.facade")


class AdmissionBenefitCatalogService:
    """Read source-backed benefit facts in forward and reverse directions."""

    def __init__(self, reader: AdmissionBenefitReader) -> None:
        self._reader = reader

    def university_catalog(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None = None,
    ) -> AdmissionBenefitsSnapshot | None:
        started = perf_counter()
        result = self._reader.get_catalog(
            university_id, admission_year, education_level
        )
        logger.info(
            "admission_benefit_catalog_read university_id=%s year=%d found=%s duration_ms=%d",
            university_id,
            admission_year,
            result is not None,
            _elapsed_ms(started),
        )
        return result

    def program_rules(
        self,
        program_id: ProgramId,
        admission_year: EducationYear,
        *,
        include_review: bool = False,
        campus_id: str | None = None,
    ) -> tuple[AdmissionBenefitRule, ...]:
        return self._reader.get_rules_for_program(
            program_id, admission_year, include_review=include_review, campus_id=campus_id
        )

    def direction_rules(
        self,
        direction_code: DirectionCode,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        education_level: EducationLevel | None = None,
        include_review: bool = False,
    ) -> tuple[AdmissionBenefitRule, ...]:
        return self._reader.get_rules_for_direction(
            direction_code,
            university_id,
            admission_year,
            education_level=education_level,
            include_review=include_review,
        )

    def olympiad_rules(
        self,
        olympiad_id: OlympiadId,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        benefit_type: str | None = None,
        include_review: bool = False,
    ) -> tuple[AdmissionBenefitRule, ...]:
        return self._reader.get_programs_for_olympiad(
            olympiad_id,
            university_id,
            admission_year,
            benefit_type=benefit_type,
            include_review=include_review,
        )

    def individual_achievement_policy(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None = None,
        *,
        include_review: bool = False,
    ) -> IndividualAchievementPolicy | None:
        return self._reader.get_individual_achievement_policy(
            university_id,
            admission_year,
            education_level,
            include_review=include_review,
        )


class AdmissionEligibilityService:
    """Load canonical rules, then delegate legal evaluation to pure services."""

    def __init__(
        self,
        reader: AdmissionBenefitReader,
        decision_service: AdmissionDecisionService | None = None,
        admission_reader: AdmissionReader | None = None,
    ) -> None:
        self._reader = reader
        self._decision_service = decision_service or AdmissionDecisionService()
        self._admission_reader = admission_reader

    def evaluate(
        self,
        request: AdmissionBenefitEvaluationInput,
        *,
        university_id: UniversityId,
        include_review: bool = True,
        offering_id: str | None = None,
        study_form: StudyForm | None = None,
        funding_type: FundingType | None = None,
        campus_id: str | None = None,
    ) -> AdmissionDecisionResult:
        started = perf_counter()
        offering, available_offerings, offering_gap = self._select_offering(
            request.program_id,
            request.admission_year,
            offering_id=offering_id,
            study_form=study_form,
            funding_type=funding_type,
            campus_id=campus_id,
        )
        rules = self._reader.get_rules_for_program(
            request.program_id,
            request.admission_year,
            include_review=include_review,
            campus_id=offering.campus_id if offering is not None else None,
        )
        catalog = self._reader.get_catalog(
            university_id, request.admission_year, request.education_level
        )
        policy = self._reader.get_individual_achievement_policy(
            university_id,
            request.admission_year,
            request.education_level,
            include_review=include_review,
        )
        result = self._decision_service.evaluate(
            request.model_copy(
                update={
                    "campus_id": offering.campus_id if offering is not None else None,
                    "rules": rules,
                    "coverage": catalog.coverage if catalog is not None else None,
                    "coverage_gaps": tuple(gap.message for gap in catalog.source_gaps)
                    if catalog is not None
                    else (),
                }
            ),
            individual_policy=policy,
            offering=offering,
        )
        if offering_gap:
            score = result.competitive_score
            if score is not None:
                score = score.model_copy(
                    update={
                        "available_offering_ids": tuple(item.id for item in available_offerings),
                        "source_gaps": tuple(dict.fromkeys((*score.source_gaps, offering_gap))),
                    }
                )
                result = result.model_copy(
                    update={"competitive_score": score, "source_gaps": tuple(dict.fromkeys((*result.source_gaps, offering_gap)))}
                )
        logger.info(
            "admission_eligibility_service_complete program_id=%s university_id=%s year=%d rules=%d policy=%s status=%s duration_ms=%d",
            request.program_id,
            university_id,
            request.admission_year,
            len(rules),
            policy is not None,
            result.status,
            _elapsed_ms(started),
        )
        return result

    def _select_offering(
        self,
        program_id: ProgramId,
        admission_year: EducationYear,
        *,
        offering_id: str | None,
        study_form: StudyForm | None,
        funding_type: FundingType | None,
        campus_id: str | None,
    ) -> tuple[AdmissionOffering | None, tuple[AdmissionOffering, ...], str | None]:
        if self._admission_reader is None:
            return None, (), "Source-backed admission offering lookup is unavailable"
        catalog = self._admission_reader.get_for_program(program_id)
        matches = tuple(
            item
            for item in catalog.offerings
            if item.admission_year == admission_year
            and (offering_id is None or item.id == offering_id)
            and (study_form is None or item.study_form is study_form)
            and (funding_type is None or item.funding_type is funding_type)
            and (campus_id is None or item.campus_id == campus_id)
        )
        if len(matches) == 1:
            return matches[0], matches, None
        if not matches:
            reason = (
                "Requested offering id does not match this program/year"
                if offering_id is not None
                else "No source-backed admission offering matches the requested program/year/selectors"
            )
            return None, (), reason
        return None, matches, "Multiple source-backed offerings match; select one offering or narrow form/funding/campus"


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


__all__ = ["AdmissionBenefitCatalogService", "AdmissionEligibilityService"]
