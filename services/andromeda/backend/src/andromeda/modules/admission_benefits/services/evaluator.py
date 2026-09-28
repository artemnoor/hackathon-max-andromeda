"""Deterministic applicant-to-rule eligibility evaluator."""

from __future__ import annotations

import logging
from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
)
from andromeda.modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverage,
    AdmissionBenefitCoverageStatus,
)
from andromeda.modules.admission_benefits.contracts.policy import ScopeApplicability
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitType,
)
from andromeda.modules.admission_benefits.contracts.results import (
    AdmissionBenefitEvaluation,
    AdmissionBenefitEvidence,
    AdmissionEligibilityResult,
    EligibilityStatus,
)
from andromeda.modules.admission_benefits.contracts.status import RuleDataStatus
from andromeda.modules.admission_benefits.services.applicability import evaluate_scope
from andromeda.modules.admission_benefits.services.confirmation import (
    evaluate_confirmation,
)
from andromeda.modules.admission_benefits.services.validity import evaluate_validity
from andromeda.modules.admissions.contracts.subject_identity import (
    canonical_subject_key,
)
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.ids import AdmissionCampusId, ProgramId

logger = logging.getLogger("andromeda.modules.admission_benefits.evaluator")


class AdmissionBenefitEvaluationInput(ContractModel):
    program_id: ProgramId
    direction_code: str
    admission_year: int
    education_level: EducationLevel | None = None
    campus_id: AdmissionCampusId | None = None
    nps: str | None = None
    applicant: ApplicantAdmissionFacts
    rules: tuple[AdmissionBenefitRule, ...] = ()
    coverage: AdmissionBenefitCoverage | None = None
    coverage_gaps: tuple[str, ...] = ()


class AdmissionBenefitEvaluator:
    """Evaluate legal rights; it never consults historical passing scores."""

    def evaluate(
        self, request: AdmissionBenefitEvaluationInput
    ) -> AdmissionEligibilityResult:
        evaluations: list[AdmissionBenefitEvaluation] = []
        source_gaps: list[str] = []
        for rule in request.rules:
            evaluation, gaps = self._evaluate_rule(rule, request)
            evaluations.append(evaluation)
            source_gaps.extend(gaps)
        eligible = tuple(
            item for item in evaluations if item.status is EligibilityStatus.ELIGIBLE
        )
        review = tuple(
            item
            for item in evaluations
            if item.status is EligibilityStatus.REVIEW_REQUIRED
        )
        coverage_incomplete = (
            request.coverage is not None
            and request.coverage.status is not AdmissionBenefitCoverageStatus.COMPLETE
        )
        status = (
            EligibilityStatus.ELIGIBLE
            if eligible
            else EligibilityStatus.REVIEW_REQUIRED
            if review
            else EligibilityStatus.INSUFFICIENT_DATA
            if coverage_incomplete
            else EligibilityStatus.NOT_ELIGIBLE
            if evaluations
            else EligibilityStatus.INSUFFICIENT_DATA
        )
        if coverage_incomplete:
            source_gaps.extend(request.coverage_gaps)
            if not request.coverage_gaps:
                source_gaps.append("admission benefit source coverage is incomplete")
        route = _route_for(eligible)
        logger.info(
            "admission_benefit_evaluation_complete program_id=%s year=%d route=%s status=%s accepted=%d rejected=%d review=%d",
            request.program_id,
            request.admission_year,
            route,
            status,
            len(eligible),
            len(evaluations) - len(eligible) - len(review),
            len(review),
        )
        return AdmissionEligibilityResult(
            program_id=request.program_id,
            admission_year=request.admission_year,
            status=status,
            route=route,
            evaluations=tuple(evaluations),
            base_competitive_score=None,
            effective_competitive_score=None,
            source_gaps=tuple(dict.fromkeys(source_gaps)),
        )

    def _evaluate_rule(
        self,
        rule: AdmissionBenefitRule,
        request: AdmissionBenefitEvaluationInput,
    ) -> tuple[AdmissionBenefitEvaluation, tuple[str, ...]]:
        evidence_items: list[AdmissionBenefitEvidence] = [
            AdmissionBenefitEvidence(
                rule_id=rule.id,
                provenance=rule.provenance,
                # Keep bounded excerpts; raw source snapshots remain the audit source.
                excerpt=rule.source_text[:256],
            )
        ]
        seen_provenance = {rule.provenance.source_snapshot_hash}
        for condition in rule.conditions:
            provenance = condition.provenance
            if provenance is None or provenance.source_snapshot_hash in seen_provenance:
                continue
            seen_provenance.add(provenance.source_snapshot_hash)
            evidence_items.append(
                AdmissionBenefitEvidence(
                    rule_id=rule.id,
                    provenance=provenance,
                    excerpt=condition.source_text[:256],
                )
            )
        evidence = tuple(evidence_items)
        if rule.status is not RuleDataStatus.ACTIVE:
            return self._evaluation(
                rule, EligibilityStatus.REVIEW_REQUIRED, "Rule is not active", evidence
            ), ("rule status requires review",)
        if rule.admission_year != request.admission_year:
            return (
                self._evaluation(
                    rule,
                    EligibilityStatus.REVIEW_REQUIRED,
                    "Rule admission year does not match request",
                    evidence,
                ),
                ("rule admission year mismatch",),
            )
        if (
            rule.education_level is not None
            and request.education_level is not rule.education_level
        ):
            return self._evaluation(
                rule,
                EligibilityStatus.NOT_ELIGIBLE,
                "Rule education level does not match request",
                evidence,
            ), ()
        if rule.route in {
            AdmissionRoute.OLYMPIAD,
            AdmissionRoute.VOSH,
            AdmissionRoute.INTERNATIONAL,
        }:
            applicant_fact = next(
                (
                    fact
                    for fact in request.applicant.olympiad_achievements
                    if fact.olympiad_id == rule.olympiad_id
                    and fact.result_type is rule.result_type
                    and (
                        rule.olympiad_profile_id is None
                        or fact.olympiad_profile_id == rule.olympiad_profile_id
                    )
                ),
                None,
            )
            if applicant_fact is None:
                return self._evaluation(
                    rule,
                    EligibilityStatus.NOT_ELIGIBLE,
                    "Applicant has no matching Olympiad result",
                    evidence,
                ), ()
            matched_fact = rule.olympiad_id
            validity = evaluate_validity(
                rule.validity,
                result_year=applicant_fact.result_year,
                admission_year=request.admission_year,
            )
            if validity.status is not EligibilityStatus.ELIGIBLE:
                return self._evaluation(
                    rule, validity.status, validity.reason, evidence, matched_fact
                ), _gap(validity.status, validity.reason)
            scope = evaluate_scope(
                rule,
                direction_code=request.direction_code,
                program_id=request.program_id,
                nps=request.nps,
                education_level=request.education_level,
                campus_id=request.campus_id,
            )
            if scope.status.value != "applicable":
                status = _scope_status(scope)
                return self._evaluation(
                    rule, status, scope.reason, evidence, matched_fact
                ), _gap(status, scope.reason)
            confirmation = evaluate_confirmation(
                rule.confirmation_requirement,
                rule.confirmation_subjects,
                ege_scores=request.applicant.ege_scores,
                internal_exam_scores=request.applicant.internal_exam_scores,
                applicant_category=request.applicant.confirmation_category,
                selected_subject=applicant_fact.confirmation_subject,
            )
            if confirmation.status is not EligibilityStatus.ELIGIBLE:
                return self._evaluation(
                    rule,
                    confirmation.status,
                    confirmation.reason,
                    evidence,
                    matched_fact,
                ), _gap(confirmation.status, confirmation.reason)
            change = None
            if rule.benefit_type is BenefitType.ONE_HUNDRED_POINTS:
                current = next(
                    (
                        score.score
                        for score in request.applicant.ege_scores
                        if _same_subject(score.subject, rule.target_subject or "")
                    ),
                    None,
                )
                change = Decimal(100) - current if current is not None else None
            return self._evaluation(
                rule,
                EligibilityStatus.ELIGIBLE,
                "All source-backed conditions passed",
                evidence,
                matched_fact,
                change,
            ), ()
        return self._evaluation(
            rule,
            EligibilityStatus.REVIEW_REQUIRED,
            "Non-Olympiad route requires a dedicated source policy",
            evidence,
        ), ("route policy requires review",)

    @staticmethod
    def _evaluation(
        rule: AdmissionBenefitRule,
        status: EligibilityStatus,
        reason: str,
        evidence: tuple[AdmissionBenefitEvidence, ...],
        matched_fact: str | None = None,
        score_change: Decimal | None = None,
    ) -> AdmissionBenefitEvaluation:
        return AdmissionBenefitEvaluation(
            rule_id=rule.id,
            benefit_type=rule.benefit_type,
            route=rule.route,
            status=status,
            result_type=rule.result_type,
            matched_applicant_fact=matched_fact,
            rejection_reason=None
            if status is EligibilityStatus.ELIGIBLE
            else reason[:256],
            effective_score_change=score_change,
            points_contribution=Decimal(100)
            if status is EligibilityStatus.ELIGIBLE
            and rule.benefit_type is BenefitType.ONE_HUNDRED_POINTS
            else None,
            evidence=evidence,
        )


def _scope_status(scope: ScopeApplicability) -> EligibilityStatus:
    return {
        "not_applicable": EligibilityStatus.NOT_ELIGIBLE,
        "insufficient_data": EligibilityStatus.INSUFFICIENT_DATA,
        "review_required": EligibilityStatus.REVIEW_REQUIRED,
    }.get(scope.status.value, EligibilityStatus.REVIEW_REQUIRED)


def _route_for(
    evaluations: tuple[AdmissionBenefitEvaluation, ...],
) -> AdmissionRoute | None:
    from .routes import route_for_benefit_type

    for item in evaluations:
        if item.status is EligibilityStatus.ELIGIBLE and item.benefit_type is BenefitType.BVI:
            return item.route or route_for_benefit_type(item.benefit_type)
    for item in evaluations:
        route = item.route or route_for_benefit_type(item.benefit_type)
        if route is not None:
            return route
    return None


def _same_subject(left: str, right: str) -> bool:
    return canonical_subject_key(left) == canonical_subject_key(right)


def _gap(status: EligibilityStatus, reason: str) -> tuple[str, ...]:
    return (
        (reason,)
        if status
        in {EligibilityStatus.REVIEW_REQUIRED, EligibilityStatus.INSUFFICIENT_DATA}
        else ()
    )


__all__ = ["AdmissionBenefitEvaluationInput", "AdmissionBenefitEvaluator"]
