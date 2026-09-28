"""Deterministic individual-achievement points calculator."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
    ApplicantIndividualAchievement,
)
from andromeda.modules.admission_benefits.contracts.public import (
    AchievementCombinationPolicy,
    IndividualAchievementPolicy,
    IndividualAchievementRule,
)
from andromeda.modules.admission_benefits.contracts.results import (
    AdmissionBenefitEvidence,
    EligibilityStatus,
    IndividualAchievementBreakdown,
    IndividualAchievementEvaluation,
    IndividualAchievementStatus,
)
from andromeda.modules.admission_benefits.contracts.status import RuleDataStatus
from andromeda.shared.contracts.enums import EducationLevel

logger = logging.getLogger("andromeda.modules.admission_benefits.individual_achievements")


@dataclass(frozen=True, slots=True)
class _Candidate:
    index: int
    fact: ApplicantIndividualAchievement
    rule: IndividualAchievementRule


class IndividualAchievementCalculator:
    """Apply only persisted source rules; no university-specific branches live here."""

    def calculate(
        self,
        policy: IndividualAchievementPolicy,
        applicant: ApplicantAdmissionFacts,
        *,
        education_level: EducationLevel | None = None,
        excluded_achievement_codes: frozenset[str] = frozenset(),
    ) -> IndividualAchievementBreakdown:
        evaluations: list[IndividualAchievementEvaluation] = []
        candidates: list[_Candidate] = []
        source_gaps: list[str] = []
        excluded = {code.casefold() for code in excluded_achievement_codes}

        for index, fact in enumerate(applicant.individual_achievements):
            matching = tuple(
                rule
                for rule in policy.rules
                if rule.achievement_code.casefold() == fact.achievement_code.casefold()
                and (rule.education_level is None or rule.education_level is education_level)
            )
            if not matching:
                evaluations.append(
                    _evaluation(
                        fact,
                        status=IndividualAchievementStatus.REVIEW_REQUIRED,
                        reason="No source-backed rule matches this achievement code",
                    )
                )
                source_gaps.append(f"unknown individual achievement: {fact.achievement_code}")
                continue
            if len(matching) > 1:
                evaluations.append(
                    _evaluation(
                        fact,
                        status=IndividualAchievementStatus.REVIEW_REQUIRED,
                        rule=matching[0],
                        reason="Multiple source rules match this achievement code",
                    )
                )
                source_gaps.append(f"conflicting individual achievement rules: {fact.achievement_code}")
                continue
            rule = matching[0]
            if rule.status is not RuleDataStatus.ACTIVE or policy.status is not RuleDataStatus.ACTIVE:
                evaluations.append(
                    _evaluation(
                        fact,
                        status=IndividualAchievementStatus.REVIEW_REQUIRED,
                        rule=rule,
                        reason="Source achievement policy requires review",
                    )
                )
                source_gaps.append(f"review-required individual achievement: {fact.achievement_code}")
                continue
            if fact.achievement_code.casefold() in excluded:
                evaluations.append(
                    _evaluation(
                        fact,
                        status=IndividualAchievementStatus.EXCLUDED,
                        rule=rule,
                        reason="The same Olympiad result is already used for an accepted admission right",
                    )
                )
                continue
            if rule.required_document and not fact.evidence_reference:
                evaluations.append(
                    _evaluation(
                        fact,
                        status=IndividualAchievementStatus.REVIEW_REQUIRED,
                        rule=rule,
                        reason="Required supporting-document metadata is missing",
                    )
                )
                source_gaps.append(f"missing evidence metadata: {fact.achievement_code}")
                continue
            candidates.append(_Candidate(index=index, fact=fact, rule=rule))
            evaluations.append(
                _evaluation(
                    fact,
                    status=IndividualAchievementStatus.ACCEPTED,
                    rule=rule,
                    awarded_points=rule.points,
                    reason="Source-backed individual achievement accepted",
                )
            )

        ordered_candidates = sorted(candidates, key=_candidate_source_order)
        self._deduplicate_basis(ordered_candidates, evaluations)
        self._apply_combination_policy(
            policy, ordered_candidates, evaluations, source_gaps
        )
        uncapped_points = sum(
            (item.awarded_points for item in evaluations if item.status is IndividualAchievementStatus.ACCEPTED),
            Decimal(0),
        )
        self._apply_category_caps(ordered_candidates, evaluations, source_gaps)
        self._apply_global_cap(
            policy.global_max_points,
            ordered_candidates,
            evaluations,
            source_gaps,
        )
        total_points = sum(
            (item.awarded_points for item in evaluations),
            Decimal(0),
        )
        review_present = any(
            item.status is IndividualAchievementStatus.REVIEW_REQUIRED for item in evaluations
        ) or policy.status is not RuleDataStatus.ACTIVE
        status = EligibilityStatus.REVIEW_REQUIRED if review_present else EligibilityStatus.ELIGIBLE
        logger.info(
            "individual_achievement_calculation_complete year=%d status=%s accepted=%d review=%d points=%s policy_status=%s",
            policy.admission_year,
            status,
            sum(item.status in {IndividualAchievementStatus.ACCEPTED, IndividualAchievementStatus.CAPPED} for item in evaluations),
            sum(item.status is IndividualAchievementStatus.REVIEW_REQUIRED for item in evaluations),
            total_points,
            policy.status,
        )
        return IndividualAchievementBreakdown(
            status=status,
            total_points=total_points,
            uncapped_points=uncapped_points,
            global_cap=policy.global_max_points,
            evaluations=tuple(evaluations),
            source_gaps=tuple(dict.fromkeys(source_gaps)),
        )

    @staticmethod
    def _deduplicate_basis(
        candidates: list[_Candidate],
        evaluations: list[IndividualAchievementEvaluation],
    ) -> None:
        seen: set[tuple[str, int | None]] = set()
        for candidate in candidates:
            key = (candidate.fact.achievement_code.casefold(), candidate.fact.year)
            if key not in seen:
                seen.add(key)
                continue
            evaluations[candidate.index] = evaluations[candidate.index].model_copy(
                update={
                    "status": IndividualAchievementStatus.DEDUPLICATED,
                    "awarded_points": Decimal(0),
                    "reason": "Duplicate achievement basis is counted once",
                }
            )

    @staticmethod
    def _apply_combination_policy(
        policy: IndividualAchievementPolicy,
        candidates: list[_Candidate],
        evaluations: list[IndividualAchievementEvaluation],
        source_gaps: list[str],
    ) -> None:
        grouped: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            if evaluations[candidate.index].status is not IndividualAchievementStatus.ACCEPTED:
                continue
            combination = candidate.rule.combination_policy
            if combination is AchievementCombinationPolicy.ADDITIVE:
                continue
            if combination is AchievementCombinationPolicy.UNKNOWN:
                combination = policy.default_combination_policy
            if combination in {AchievementCombinationPolicy.ADDITIVE, AchievementCombinationPolicy.UNKNOWN}:
                if combination is AchievementCombinationPolicy.UNKNOWN:
                    evaluations[candidate.index] = evaluations[candidate.index].model_copy(
                        update={
                            "status": IndividualAchievementStatus.REVIEW_REQUIRED,
                            "awarded_points": Decimal(0),
                            "reason": "Source combination policy is unknown",
                        }
                    )
                    source_gaps.append(f"unknown combination policy: {candidate.fact.achievement_code}")
                continue
            if candidate.rule.combination_group is None:
                evaluations[candidate.index] = evaluations[candidate.index].model_copy(
                    update={
                        "status": IndividualAchievementStatus.REVIEW_REQUIRED,
                        "awarded_points": Decimal(0),
                        "reason": "Non-additive achievement has no source combination group",
                    }
                )
                source_gaps.append(f"missing combination group: {candidate.fact.achievement_code}")
                continue
            grouped.setdefault(candidate.rule.combination_group, []).append(candidate)

        for group, group_candidates in grouped.items():
            winner = min(
                group_candidates,
                key=lambda item: (-item.rule.points, _candidate_source_order(item)),
            )
            for candidate in group_candidates:
                if candidate is winner:
                    continue
                evaluations[candidate.index] = evaluations[candidate.index].model_copy(
                    update={
                        "status": IndividualAchievementStatus.DEDUPLICATED,
                        "awarded_points": Decimal(0),
                        "reason": f"Combination group {group} allows only the highest applicable achievement",
                    }
                )

    @staticmethod
    def _apply_category_caps(
        candidates: list[_Candidate],
        evaluations: list[IndividualAchievementEvaluation],
        source_gaps: list[str],
    ) -> None:
        grouped: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            if evaluations[candidate.index].status is IndividualAchievementStatus.ACCEPTED:
                grouped.setdefault(candidate.rule.category, []).append(candidate)
        for category, category_candidates in grouped.items():
            caps = {candidate.rule.category_cap for candidate in category_candidates if candidate.rule.category_cap is not None}
            if not caps:
                continue
            cap = min(caps)
            consumed = Decimal(0)
            for candidate in category_candidates:
                available = max(Decimal(0), cap - consumed)
                awarded = min(candidate.rule.points, available)
                consumed += awarded
                if awarded != candidate.rule.points:
                    evaluations[candidate.index] = evaluations[candidate.index].model_copy(
                        update={
                            "status": IndividualAchievementStatus.CAPPED,
                            "awarded_points": awarded,
                            "reason": f"Category {category} is limited by the source cap",
                        }
                    )
            if len(caps) > 1:
                source_gaps.append(f"conflicting category caps: {category}")

    @staticmethod
    def _apply_global_cap(
        global_cap: Decimal | None,
        candidates: list[_Candidate],
        evaluations: list[IndividualAchievementEvaluation],
        source_gaps: list[str],
    ) -> None:
        if global_cap is None:
            return
        consumed = Decimal(0)
        for candidate in candidates:
            index = candidate.index
            evaluation = evaluations[index]
            if evaluation.status not in {IndividualAchievementStatus.ACCEPTED, IndividualAchievementStatus.CAPPED}:
                continue
            available = max(Decimal(0), global_cap - consumed)
            awarded = min(evaluation.awarded_points, available)
            consumed += awarded
            if awarded != evaluation.awarded_points:
                evaluations[index] = evaluation.model_copy(
                    update={
                        "status": IndividualAchievementStatus.CAPPED,
                        "awarded_points": awarded,
                        "reason": "The source policy global maximum was applied",
                    }
                )
        if consumed >= global_cap:
            source_gaps.append("individual achievement global cap applied")


def _candidate_source_order(candidate: _Candidate) -> tuple[str, int, str, int, str]:
    return (
        candidate.rule.provenance.document_kind,
        candidate.rule.provenance.row or 2**31,
        candidate.rule.id,
        candidate.fact.year or 2**31,
        candidate.fact.evidence_reference or "",
    )


def _evaluation(
    fact: ApplicantIndividualAchievement,
    *,
    status: IndividualAchievementStatus,
    reason: str,
    rule: IndividualAchievementRule | None = None,
    awarded_points: Decimal = Decimal(0),
) -> IndividualAchievementEvaluation:
    evidence = (
        AdmissionBenefitEvidence(
            rule_id=rule.id,
            provenance=rule.provenance,
            excerpt=rule.source_text[:256],
        ),
    ) if rule is not None else ()
    return IndividualAchievementEvaluation(
        rule_id=rule.id if rule is not None else None,
        achievement_code=fact.achievement_code,
        status=status,
        applicant_year=fact.year,
        rule_points=rule.points if rule is not None else None,
        awarded_points=awarded_points,
        combination_policy=rule.combination_policy if rule is not None else None,
        reason=reason[:256],
        evidence=evidence,
    )


__all__ = ["IndividualAchievementCalculator"]
