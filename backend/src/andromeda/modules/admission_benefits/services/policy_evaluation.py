"""Evaluate a complete, exact policy-selected benefit revision set."""

from __future__ import annotations

import logging

from andromeda.modules.admissions.repository.ports import AdmissionReader
from andromeda.shared.contracts.enums import EducationLevel

from ..contracts.domain_revision import (
    admission_benefit_revision_hash,
    individual_achievement_domain_rule_id,
)
from ..contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluation,
    AdmissionBenefitPolicyEvaluationRequest,
    AdmissionBenefitPolicyEvaluationStatus,
    ApplicantFactDimension,
)
from ..contracts.public import AdmissionBenefitRule, IndividualAchievementPolicy
from ..contracts.status import RuleDataStatus
from ..repository.ports import AdmissionBenefitReader
from .admission_decision import AdmissionDecisionService
from .evaluator import AdmissionBenefitEvaluationInput

logger = logging.getLogger("andromeda.modules.admission_benefits.policy_evaluation")


class AdmissionBenefitsPolicyEvaluationService:
    """Bridge exact approved references to the sole existing domain evaluator.

    The policy resolver selects revisions. This service verifies that the
    selection covers the complete current owner set for one program, checks
    applicant-fact completeness, and delegates every calculation to
    ``AdmissionDecisionService``.
    """

    def __init__(
        self,
        reader: AdmissionBenefitReader,
        admissions: AdmissionReader,
        decision_service: AdmissionDecisionService | None = None,
    ) -> None:
        self._reader = reader
        self._admissions = admissions
        self._decision_service = decision_service or AdmissionDecisionService()

    def evaluate(
        self, request: AdmissionBenefitPolicyEvaluationRequest
    ) -> AdmissionBenefitPolicyEvaluation:
        active_rules = self._reader.get_rules_for_program(
            request.program_id, request.admission_year
        )
        level, level_error = _selected_education_level(request, active_rules)
        if level_error is not None:
            return self._unavailable(level_error)
        catalog = self._reader.get_catalog(
            request.university_id, request.admission_year, level
        )
        if catalog is None:
            return self._unavailable("admission_benefit_catalog_unavailable")
        current_policy = self._reader.get_individual_achievement_policy(
            request.university_id, request.admission_year, level
        )
        exact_rules, exact_policy, missing = self._load_exact_selection(
            request, active_rules, current_policy
        )
        if missing:
            return self._unavailable(*missing)

        if catalog.coverage.status.value != "complete":
            return self._unavailable("admission_benefit_source_coverage_incomplete")

        required_dimensions = _required_applicant_dimensions(exact_rules, exact_policy)
        missing_dimensions = tuple(
            item
            for item in required_dimensions
            if item not in request.applicant.complete_dimensions
        )
        if missing_dimensions:
            return AdmissionBenefitPolicyEvaluation(
                status=AdmissionBenefitPolicyEvaluationStatus.INSUFFICIENT_DATA,
                missing_input_codes=tuple(
                    f"applicant_{item.value}_completeness_unconfirmed"
                    for item in missing_dimensions
                ),
            )

        offerings = tuple(
            item
            for item in self._admissions.get_for_program(request.program_id).offerings
            if item.admission_year == request.admission_year
        )
        offering = offerings[0] if len(offerings) == 1 else None
        request_input = AdmissionBenefitEvaluationInput(
            program_id=request.program_id,
            direction_code=request.direction_code,
            admission_year=request.admission_year,
            education_level=level,
            campus_id=offering.campus_id if offering is not None else None,
            applicant=request.applicant.facts,
            rules=exact_rules,
            coverage=catalog.coverage,
            coverage_gaps=tuple(gap.message for gap in catalog.source_gaps),
        )
        decision = self._decision_service.evaluate(
            request_input,
            individual_policy=exact_policy,
            offering=offering,
        )
        logger.info(
            "admission_benefit_policy_evaluation_complete program_id=%s year=%d rules=%d individual_policy=%s status=%s",
            request.program_id,
            request.admission_year,
            len(exact_rules),
            exact_policy is not None,
            decision.status.value,
        )
        if decision.status.value in {"insufficient_data", "review_required"}:
            return AdmissionBenefitPolicyEvaluation(
                status=AdmissionBenefitPolicyEvaluationStatus.INSUFFICIENT_DATA,
                decision=decision,
                missing_input_codes=(
                    "admission_benefit_domain_result_requires_review"
                    if decision.status.value == "review_required"
                    else "admission_benefit_domain_result_insufficient_data",
                ),
            )
        return AdmissionBenefitPolicyEvaluation(
            status=AdmissionBenefitPolicyEvaluationStatus.EVALUATED,
            decision=decision,
        )

    def _load_exact_selection(
        self,
        request: AdmissionBenefitPolicyEvaluationRequest,
        active_rules: tuple[AdmissionBenefitRule, ...],
        current_policy: IndividualAchievementPolicy | None,
    ) -> tuple[
        tuple[AdmissionBenefitRule, ...],
        IndividualAchievementPolicy | None,
        tuple[str, ...],
    ]:
        selected_by_id = {
            item.rule_id: item.revision_hash for item in request.selected_rules
        }
        exact_rules: list[AdmissionBenefitRule] = []
        missing: list[str] = []
        for reference in request.selected_rules:
            rule = self._reader.get_rule_revision(
                reference.rule_id, reference.revision_hash
            )
            if (
                rule is None
                or rule.status is not RuleDataStatus.ACTIVE
                or admission_benefit_revision_hash(rule) != reference.revision_hash
                or rule.university_id != request.university_id
                or rule.admission_year != request.admission_year
            ):
                missing.append("exact_admission_benefit_revision_unavailable")
                continue
            exact_rules.append(rule)

        expected_by_id = {
            item.id: admission_benefit_revision_hash(item) for item in active_rules
        }
        if selected_by_id != expected_by_id:
            missing.append("effective_policy_does_not_cover_complete_benefit_rule_set")

        exact_policy: IndividualAchievementPolicy | None = None
        if current_policy is None:
            if request.selected_individual_policy_hash is not None:
                missing.append("exact_individual_achievement_policy_unavailable")
        else:
            canonical_id = individual_achievement_domain_rule_id(current_policy)
            policy_id = f"individual-achievement-policy:{canonical_id.removeprefix('individual-achievement:')}"
            expected_hash = admission_benefit_revision_hash(current_policy)
            if (
                request.selected_individual_policy_id != canonical_id
                or request.selected_individual_policy_hash != expected_hash
            ):
                missing.append(
                    "effective_policy_does_not_cover_individual_achievement_policy"
                )
            else:
                exact_policy = self._reader.get_individual_achievement_policy_revision(
                    policy_id, request.selected_individual_policy_hash
                )
                if (
                    exact_policy is None
                    or exact_policy.status is not RuleDataStatus.ACTIVE
                    or admission_benefit_revision_hash(exact_policy)
                    != request.selected_individual_policy_hash
                    or exact_policy.university_id != request.university_id
                    or exact_policy.admission_year != request.admission_year
                ):
                    missing.append("exact_individual_achievement_policy_unavailable")

        return (
            tuple(sorted(exact_rules, key=lambda item: item.id)),
            exact_policy,
            tuple(dict.fromkeys(missing)),
        )

    @staticmethod
    def _unavailable(*codes: str) -> AdmissionBenefitPolicyEvaluation:
        return AdmissionBenefitPolicyEvaluation(
            status=AdmissionBenefitPolicyEvaluationStatus.UNAVAILABLE,
            missing_input_codes=tuple(dict.fromkeys(codes)),
        )


def _selected_education_level(
    request: AdmissionBenefitPolicyEvaluationRequest,
    active_rules: tuple[AdmissionBenefitRule, ...],
) -> tuple[EducationLevel | None, str | None]:
    levels = {
        rule.education_level
        for rule in active_rules
        if rule.education_level is not None
    }
    selected_policy_id = request.selected_individual_policy_id
    if selected_policy_id is not None:
        selected_level = selected_policy_id.rsplit(":", 1)[-1]
        if selected_level != "unknown":
            try:
                levels.add(EducationLevel(selected_level))
            except ValueError:
                return (
                    None,
                    "selected_individual_achievement_education_level_unsupported",
                )
    if len(levels) > 1:
        return None, "admission_benefit_education_level_ambiguous"
    return next(iter(levels)) if levels else None, None


def _required_applicant_dimensions(
    rules: tuple[AdmissionBenefitRule, ...],
    individual_policy: IndividualAchievementPolicy | None,
) -> tuple[ApplicantFactDimension, ...]:
    required: set[ApplicantFactDimension] = set()
    if individual_policy is not None:
        required.add(ApplicantFactDimension.INDIVIDUAL_ACHIEVEMENTS)
    for rule in rules:
        if rule.olympiad_id is not None:
            required.add(ApplicantFactDimension.OLYMPIAD_ACHIEVEMENTS)
        if rule.confirmation_requirement.value == "required":
            kinds = {item.exam_kind.value for item in rule.confirmation_subjects}
            if "ege" in kinds:
                required.add(ApplicantFactDimension.EGE_SCORES)
            if "internal_exam" in kinds:
                required.add(ApplicantFactDimension.INTERNAL_EXAM_SCORES)
            if any(
                item.applicant_category is not None
                for item in rule.confirmation_subjects
            ):
                required.add(ApplicantFactDimension.CONFIRMATION_CATEGORY)
    return tuple(sorted(required, key=lambda item: item.value))


__all__ = ["AdmissionBenefitsPolicyEvaluationService"]
