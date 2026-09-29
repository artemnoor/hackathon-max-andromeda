"""Calculate a competitive score from one source-backed admission offering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
)
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitType,
)
from andromeda.modules.admission_benefits.contracts.results import (
    AdmissionBenefitEvaluation,
    CompetitiveExamScore,
    CompetitiveScoreStatus,
    EffectiveCompetitiveScore,
    EligibilityStatus,
    IndividualAchievementBreakdown,
)
from andromeda.modules.admissions.contracts.public import (
    AdmissionOffering,
    ExamRequirement,
)
from andromeda.modules.admissions.contracts.subject_identity import (
    SubjectResolutionStatus,
    canonical_subject_key,
    resolve_subject,
)
from andromeda.shared.contracts.ids import ProgramId

logger = logging.getLogger("andromeda.modules.admission_benefits.competitive_score")


@dataclass(frozen=True, slots=True)
class _ExamCandidate:
    requirement: ExamRequirement
    raw_score: Decimal | None
    effective_score: Decimal | None
    benefit_rule_ids: tuple[str, ...]
    valid: bool
    reason: str | None = None


class EffectiveCompetitiveScoreCalculator:
    """Apply allowed exam combinations, verified 100-point rights and ID policy."""

    def calculate(
        self,
        *,
        program_id: ProgramId,
        admission_year: int,
        offering: AdmissionOffering | None,
        applicant: ApplicantAdmissionFacts,
        evaluations: tuple[AdmissionBenefitEvaluation, ...],
        rules: tuple[AdmissionBenefitRule, ...],
        achievement_breakdown: IndividualAchievementBreakdown | None,
        legal_route: AdmissionRoute | None,
    ) -> EffectiveCompetitiveScore:
        if legal_route is not None and any(
            item.status is EligibilityStatus.ELIGIBLE
            and item.benefit_type is BenefitType.BVI
            for item in evaluations
        ):
            result = EffectiveCompetitiveScore(
                status=CompetitiveScoreStatus.NOT_APPLICABLE,
                offering_id=offering.id if offering is not None else None,
                individual_achievement_points=(
                    achievement_breakdown.total_points
                    if achievement_breakdown is not None
                    else None
                ),
                source_gaps=(
                    "BVI is the applicable legal route; general competitive score is not the primary result",
                ),
            )
            self._log(program_id, admission_year, result)
            return result
        if offering is None:
            return self._unavailable(
                "No unique source-backed admission offering was selected"
            )
        if (
            offering.program_id != program_id
            or offering.admission_year != admission_year
        ):
            return self._unavailable(
                "Admission offering identity/year does not match the request",
                offering.id,
            )

        if not offering.exams:
            return self._unavailable(
                "Selected offering has no source-backed exam requirements", offering.id
            )

        score_by_key: dict[str, list[Decimal]] = {}
        input_subjects = tuple(score.subject for score in applicant.ege_scores)
        for score in applicant.ege_scores:
            score_by_key.setdefault(canonical_subject_key(score.subject), []).append(
                score.score
            )

        eligible_hundred_points: dict[str, list[str]] = {}
        rules_by_id = {rule.id: rule for rule in rules}
        for evaluation in evaluations:
            if (
                evaluation.status is not EligibilityStatus.ELIGIBLE
                or evaluation.benefit_type is not BenefitType.ONE_HUNDRED_POINTS
            ):
                continue
            rule = rules_by_id.get(evaluation.rule_id)
            if rule is not None and rule.target_subject:
                eligible_hundred_points.setdefault(
                    canonical_subject_key(rule.target_subject), []
                ).append(rule.id)

        candidates = tuple(
            self._candidate(
                exam, applicant, input_subjects, score_by_key, eligible_hundred_points
            )
            for exam in offering.exams
        )
        required: list[_ExamCandidate] = []
        choice_groups: dict[str, list[_ExamCandidate]] = {}
        unresolved_choice = False
        for candidate in candidates:
            exam = candidate.requirement
            if exam.choice_group_id is not None:
                choice_groups.setdefault(exam.choice_group_id, []).append(candidate)
            elif exam.is_choice:
                unresolved_choice = True
            elif exam.is_required:
                required.append(candidate)

        gaps = [item.reason for item in candidates if item.reason]
        if unresolved_choice:
            gaps.append(
                "An offering exam is marked as a choice but its source-defined choice group is missing"
            )
        selected: list[_ExamCandidate] = []
        selected.extend(required)
        candidates_considered = len(candidates)
        for group_id, members in sorted(choice_groups.items()):
            cardinalities = {
                (
                    member.requirement.choice_group_min,
                    member.requirement.choice_group_max,
                )
                for member in members
            }
            if len(cardinalities) != 1:
                gaps.append(
                    f"Choice group {group_id} has inconsistent source cardinality"
                )
                unresolved_choice = True
                continue
            minimum, maximum = next(iter(cardinalities))
            if minimum is None or maximum is None:
                gaps.append(
                    f"Choice group {group_id} has no source-defined minimum and maximum cardinality"
                )
                unresolved_choice = True
                continue
            valid = sorted(
                (
                    member
                    for member in members
                    if member.valid and member.effective_score is not None
                ),
                key=lambda item: (
                    -(item.effective_score or Decimal(0)),
                    canonical_subject_key(item.requirement.subject),
                ),
            )
            if len(valid) < minimum:
                gaps.append(
                    f"Choice group {group_id} has fewer valid supplied scores than its minimum selection"
                )
                return self._unavailable(
                    "No valid score combination satisfies a source-defined exam choice group",
                    offering.id,
                    gaps=tuple(gaps),
                    candidates_considered=candidates_considered,
                    status=CompetitiveScoreStatus.INSUFFICIENT_DATA
                    if any(item.raw_score is None for item in members)
                    else CompetitiveScoreStatus.NOT_APPLICABLE,
                )
            selected.extend(valid[: min(maximum, len(valid))])

        if unresolved_choice:
            return self._unavailable(
                "Source-defined exam choice cardinality is incomplete",
                offering.id,
                gaps=tuple(gaps),
                candidates_considered=candidates_considered,
            )
        invalid_required = [candidate for candidate in required if not candidate.valid]
        if invalid_required:
            return self._unavailable(
                "A required exam is missing or below its source minimum score",
                offering.id,
                gaps=tuple(gaps),
                candidates_considered=candidates_considered,
                status=(
                    CompetitiveScoreStatus.INSUFFICIENT_DATA
                    if any(
                        candidate.raw_score is None
                        and candidate.effective_score is None
                        for candidate in invalid_required
                    )
                    else CompetitiveScoreStatus.NOT_APPLICABLE
                ),
            )
        if not selected:
            return self._unavailable(
                "No required exam or valid choice was selected",
                offering.id,
                gaps=tuple(gaps),
            )

        selected.sort(key=lambda item: canonical_subject_key(item.requirement.subject))
        before = tuple(
            self._result_item(item, after_benefits=False) for item in selected
        )
        after = tuple(self._result_item(item, after_benefits=True) for item in selected)
        raw_total = (
            sum(
                (item.raw_score for item in selected if item.raw_score is not None),
                Decimal(0),
            )
            if all(item.raw_score is not None for item in selected)
            else None
        )
        exam_total = sum(
            (item.effective_score or Decimal(0) for item in selected), Decimal(0)
        )
        id_points = (
            achievement_breakdown.total_points
            if achievement_breakdown is not None
            else None
        )
        review_required = (
            achievement_breakdown is not None
            and achievement_breakdown.status is EligibilityStatus.REVIEW_REQUIRED
        )
        score_status = (
            CompetitiveScoreStatus.PARTIAL
            if gaps or id_points is None or review_required
            else CompetitiveScoreStatus.AVAILABLE
        )
        score_gaps = list(gaps)
        if id_points is None:
            score_gaps.append(
                "Individual-achievement policy/result is unavailable; total excludes unverified ID points"
            )
        elif review_required and achievement_breakdown is not None:
            score_gaps.extend(achievement_breakdown.source_gaps)
        total = exam_total + id_points if id_points is not None else exam_total
        result = EffectiveCompetitiveScore(
            status=score_status,
            offering_id=offering.id,
            selected_exam_combination=tuple(
                item.requirement.subject for item in selected
            ),
            exam_scores_before=before,
            exam_scores_after_benefits=after,
            candidate_exams_considered=candidates_considered,
            base_exam_score=raw_total,
            post_benefit_exam_score=exam_total,
            individual_achievement_points=id_points,
            effective_total=total,
            source_gaps=tuple(dict.fromkeys(score_gaps)),
        )
        self._log(program_id, admission_year, result)
        return result

    @staticmethod
    def _candidate(
        exam: ExamRequirement,
        applicant: ApplicantAdmissionFacts,
        input_subjects: tuple[str, ...],
        score_by_key: dict[str, list[Decimal]],
        eligible_hundred_points: dict[str, list[str]],
    ) -> _ExamCandidate:
        resolution = resolve_subject(exam.subject, input_subjects)
        raw_score = None
        if resolution.status is SubjectResolutionStatus.MATCHED:
            matches = score_by_key.get(canonical_subject_key(exam.subject), [])
            if len(matches) == 1:
                raw_score = matches[0]
        elif resolution.status is SubjectResolutionStatus.AMBIGUOUS:
            return _ExamCandidate(
                exam,
                None,
                None,
                (),
                False,
                f"Ambiguous applicant score subject for offering exam {exam.subject}",
            )

        rule_ids = tuple(
            eligible_hundred_points.get(canonical_subject_key(exam.subject), ())
        )
        effective = Decimal(100) if rule_ids else raw_score
        if effective is None:
            return _ExamCandidate(
                exam,
                raw_score,
                None,
                rule_ids,
                False,
                f"Missing applicant exam score for {exam.subject}",
            )
        if exam.minimum_score is not None and effective < exam.minimum_score:
            return _ExamCandidate(
                exam,
                raw_score,
                effective,
                rule_ids,
                False,
                f"Score for {exam.subject} is below the source minimum",
            )
        return _ExamCandidate(exam, raw_score, effective, rule_ids, True)

    @staticmethod
    def _result_item(
        candidate: _ExamCandidate, *, after_benefits: bool
    ) -> CompetitiveExamScore:
        return CompetitiveExamScore(
            subject=candidate.requirement.subject,
            source_name=candidate.requirement.source_name,
            raw_score=candidate.raw_score,
            effective_score=candidate.effective_score if after_benefits else None,
            minimum_score=candidate.requirement.minimum_score,
            applied_benefit_rule_ids=candidate.benefit_rule_ids
            if after_benefits
            else (),
            provenance=(candidate.requirement.provenance,),
        )

    def _unavailable(
        self,
        reason: str,
        offering_id: str | None = None,
        *,
        gaps: tuple[str, ...] = (),
        candidates_considered: int = 0,
        status: CompetitiveScoreStatus = CompetitiveScoreStatus.INSUFFICIENT_DATA,
    ) -> EffectiveCompetitiveScore:
        return EffectiveCompetitiveScore(
            status=status,
            offering_id=offering_id,
            candidate_exams_considered=candidates_considered,
            source_gaps=tuple(dict.fromkeys((reason, *gaps))),
        )

    @staticmethod
    def _log(
        program_id: ProgramId, year: int, result: EffectiveCompetitiveScore
    ) -> None:
        logger.info(
            "admission_competitive_score_calculated program_id=%s year=%d offering_id=%s status=%s selected_exam_count=%d candidates=%d id_points=%s total=%s gaps=%d",
            program_id,
            year,
            result.offering_id,
            result.status,
            len(result.selected_exam_combination),
            result.candidate_exams_considered,
            result.individual_achievement_points,
            result.effective_total,
            len(result.source_gaps),
        )


__all__ = ["EffectiveCompetitiveScoreCalculator"]
