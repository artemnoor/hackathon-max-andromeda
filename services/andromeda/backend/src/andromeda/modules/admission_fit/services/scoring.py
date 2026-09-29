"""Explainable scoring for one canonical admission offering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    AdmissionOffering,
    ExamRequirement,
    FundingType,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
)
from andromeda.modules.admissions.contracts.subject_identity import (
    SubjectResolutionStatus,
    resolve_subject,
)
from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import (
    AdmissionFitBreakdown,
    AdmissionFitDataQuality,
    AdmissionFitMetric,
    AdmissionFitMetricStatus,
    AdmissionFitReason,
    AdmissionFitReasonKind,
    AdmissionFitResult,
    AdmissionFitStatus,
    ApplicantAdmissionProfile,
)
from ..domain.policy import (
    BORDERLINE_SCORE,
    COMPLETENESS_WEIGHT,
    MINIMUM_WEIGHT,
    PASSING_BORDERLINE_RATIO,
    PASSING_WEIGHT,
    REALISTIC_SCORE,
    clamp_ratio,
    percentage,
    rounded_score,
)

logger = logging.getLogger("andromeda.admission_fit.scoring")
ZERO = Decimal("0")
ONE = Decimal("1")
ONE_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class _ExamEvaluation:
    exam: ExamRequirement
    applicant_score: Decimal | None
    resolution: SubjectResolutionStatus
    ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class _Metric:
    value: Decimal | None
    status: AdmissionFitMetricStatus


class AdmissionFitScoringService:
    """Score an applicant against source-backed admission facts."""

    def score(
        self,
        program_id: ProgramId,
        offering: AdmissionOffering,
        applicant: ApplicantAdmissionProfile,
    ) -> AdmissionFitResult:
        mandatory = tuple(exam for exam in offering.exams if exam.is_required and not exam.is_choice)
        evaluations = tuple(self._evaluate_exam(exam, applicant) for exam in mandatory)
        minimum = self._minimum_metric(evaluations)
        completeness = self._completeness_metric(evaluations)
        passing_score = self._select_passing_score(offering)
        passing = self._passing_metric(evaluations, passing_score)
        final_score = self._final_score(minimum, passing, completeness)
        minimum_failed = any(
            item.applicant_score is not None
            and item.exam.minimum_score is not None
            and item.applicant_score < item.exam.minimum_score
            for item in evaluations
        )
        missing_mandatory = any(item.resolution is not SubjectResolutionStatus.MATCHED for item in evaluations)
        status = self._status(
            final_score=final_score,
            minimum_failed=minimum_failed,
            missing_mandatory=missing_mandatory,
            passing=passing,
            minimum=minimum,
            completeness=completeness,
        )
        reasons, anti_reasons, data_gaps = self._reasons(evaluations, passing_score, passing)
        data_quality = self._data_quality(evaluations, minimum, passing, completeness)
        total_score = self._applicant_total(evaluations)
        result = AdmissionFitResult(
            program_id=program_id,
            offering_id=offering.id,
            admission_year=offering.admission_year,
            study_form=offering.study_form,
            funding_type=offering.funding_type,
            status=status,
            score=final_score,
            applicant_total_score=total_score,
            data_quality=data_quality,
            breakdown=AdmissionFitBreakdown(
                minimum_readiness=AdmissionFitMetric(value=minimum.value, status=minimum.status),
                passing_readiness=AdmissionFitMetric(value=passing.value, status=passing.status),
                data_completeness=AdmissionFitMetric(value=completeness.value, status=completeness.status),
            ),
            reasons=reasons,
            anti_reasons=anti_reasons,
            data_gaps=data_gaps,
        )
        logger.info(
            "admission_fit_scoring_complete program_id=%s offering_id=%s status=%s score=%d",
            program_id,
            offering.id,
            status.value,
            final_score,
        )
        return result

    @staticmethod
    def _evaluate_exam(exam: ExamRequirement, applicant: ApplicantAdmissionProfile) -> _ExamEvaluation:
        resolution = resolve_subject(exam.subject, tuple(item.subject for item in applicant.scores))
        if resolution.status is not SubjectResolutionStatus.MATCHED or resolution.matched_subject is None:
            return _ExamEvaluation(exam=exam, applicant_score=None, resolution=resolution.status, ratio=None)
        applicant_score = next(item.score for item in applicant.scores if item.subject == resolution.matched_subject)
        if exam.minimum_score is None:
            return _ExamEvaluation(exam=exam, applicant_score=applicant_score, resolution=resolution.status, ratio=None)
        if exam.minimum_score == ZERO:
            ratio = ONE if applicant_score >= ZERO else ZERO
        else:
            ratio = clamp_ratio(applicant_score / exam.minimum_score)
        return _ExamEvaluation(exam=exam, applicant_score=applicant_score, resolution=resolution.status, ratio=ratio)

    @staticmethod
    def _minimum_metric(evaluations: tuple[_ExamEvaluation, ...]) -> _Metric:
        with_minimum = tuple(item for item in evaluations if item.exam.minimum_score is not None)
        comparable = tuple(item for item in with_minimum if item.ratio is not None)
        if not with_minimum:
            return _Metric(value=None, status=AdmissionFitMetricStatus.NOT_AVAILABLE)
        if not comparable:
            return _Metric(value=None, status=AdmissionFitMetricStatus.NOT_AVAILABLE)
        value = percentage(sum((item.ratio or ZERO for item in comparable), ZERO) / Decimal(len(comparable)))
        status = AdmissionFitMetricStatus.AVAILABLE if len(comparable) == len(with_minimum) else AdmissionFitMetricStatus.PARTIAL
        return _Metric(value=value, status=status)

    @staticmethod
    def _completeness_metric(evaluations: tuple[_ExamEvaluation, ...]) -> _Metric:
        if not evaluations:
            return _Metric(value=None, status=AdmissionFitMetricStatus.NOT_AVAILABLE)
        matched = sum(item.resolution is SubjectResolutionStatus.MATCHED for item in evaluations)
        value = (Decimal(matched) / Decimal(len(evaluations)) * ONE_HUNDRED).quantize(Decimal("0.01"))
        status = AdmissionFitMetricStatus.AVAILABLE if matched == len(evaluations) else AdmissionFitMetricStatus.PARTIAL
        return _Metric(value=value, status=status)

    @staticmethod
    def _select_passing_score(offering: AdmissionOffering) -> PassingScore | None:
        eligible = tuple(
            item
            for item in offering.passing_scores
            if item.status is PassingScoreStatus.NUMERIC
            and item.competition_type is AdmissionCompetitionType.GENERAL
            and item.score is not None
        )
        if not eligible:
            if offering.passing_scores:
                logger.debug("passing_score_unavailable_reason=bvi_or_quota_only")
            return None
        preferred: PassingScoreType | None = None
        if offering.funding_type is FundingType.BUDGET:
            preferred = PassingScoreType.BUDGET
        elif offering.funding_type is FundingType.PAID:
            preferred = PassingScoreType.PAID
        if preferred is not None:
            exact = next((item for item in eligible if item.score_type is preferred), None)
            if exact is not None:
                return exact
        return next(
            (
                item
                for item in eligible
                if item.score_type in (PassingScoreType.AVERAGE, PassingScoreType.OTHER)
            ),
            None,
        )

    @staticmethod
    def _passing_metric(evaluations: tuple[_ExamEvaluation, ...], passing_score: PassingScore | None) -> _Metric:
        if passing_score is None or passing_score.score is None:
            return _Metric(value=None, status=AdmissionFitMetricStatus.NOT_AVAILABLE)
        matched_scores = tuple(item.applicant_score for item in evaluations if item.applicant_score is not None)
        if not matched_scores:
            return _Metric(value=None, status=AdmissionFitMetricStatus.NOT_AVAILABLE)
        total = sum(matched_scores, ZERO)
        ratio = ZERO if passing_score.score == ZERO else clamp_ratio(total / passing_score.score)
        status = (
            AdmissionFitMetricStatus.AVAILABLE
            if len(matched_scores) == len(evaluations)
            else AdmissionFitMetricStatus.PARTIAL
        )
        return _Metric(value=percentage(ratio), status=status)

    @staticmethod
    def _final_score(minimum: _Metric, passing: _Metric, completeness: _Metric) -> int:
        components = (
            (minimum, MINIMUM_WEIGHT),
            (passing, PASSING_WEIGHT),
            (completeness, COMPLETENESS_WEIGHT),
        )
        available = tuple((metric.value, weight) for metric, weight in components if metric.value is not None)
        if not available:
            return 0
        numerator = sum((value * weight for value, weight in available), ZERO)
        denominator = sum((weight for _, weight in available), ZERO)
        return max(0, min(100, rounded_score(numerator / denominator)))

    @staticmethod
    def _status(
        *,
        final_score: int,
        minimum_failed: bool,
        missing_mandatory: bool,
        passing: _Metric,
        minimum: _Metric,
        completeness: _Metric,
    ) -> AdmissionFitStatus:
        if minimum_failed:
            return AdmissionFitStatus.UNLIKELY
        if minimum.value is None and passing.value is None:
            return AdmissionFitStatus.INSUFFICIENT_DATA
        if missing_mandatory or completeness.status is AdmissionFitMetricStatus.PARTIAL:
            return AdmissionFitStatus.INSUFFICIENT_DATA
        if passing.value is not None and passing.value < PASSING_BORDERLINE_RATIO * ONE_HUNDRED:
            return AdmissionFitStatus.UNLIKELY
        if passing.value is not None and passing.value < ONE_HUNDRED:
            return AdmissionFitStatus.BORDERLINE
        if final_score >= REALISTIC_SCORE:
            return AdmissionFitStatus.REALISTIC
        if final_score >= BORDERLINE_SCORE:
            return AdmissionFitStatus.BORDERLINE
        return AdmissionFitStatus.UNLIKELY

    @staticmethod
    def _data_quality(
        evaluations: tuple[_ExamEvaluation, ...],
        minimum: _Metric,
        passing: _Metric,
        completeness: _Metric,
    ) -> AdmissionFitDataQuality:
        if not evaluations and minimum.value is None and passing.value is None:
            return AdmissionFitDataQuality.UNAVAILABLE
        if completeness.status is AdmissionFitMetricStatus.AVAILABLE and (
            minimum.value is not None or passing.value is not None
        ):
            return AdmissionFitDataQuality.COMPLETE
        return AdmissionFitDataQuality.PARTIAL

    @staticmethod
    def _reasons(
        evaluations: tuple[_ExamEvaluation, ...],
        passing_score: PassingScore | None,
        passing: _Metric,
    ) -> tuple[tuple[AdmissionFitReason, ...], tuple[AdmissionFitReason, ...], tuple[AdmissionFitReason, ...]]:
        reasons: list[AdmissionFitReason] = []
        anti_reasons: list[AdmissionFitReason] = []
        data_gaps: list[AdmissionFitReason] = []
        for item in evaluations:
            provenance = (item.exam.provenance,)
            if item.resolution is SubjectResolutionStatus.AMBIGUOUS:
                data_gaps.append(
                    AdmissionFitReason(
                        kind=AdmissionFitReasonKind.DATA_GAP,
                        message=f"Нельзя однозначно сопоставить предмет «{item.exam.subject}» с введёнными баллами",
                        subject=item.exam.subject,
                        source_name=item.exam.source_name,
                        provenance=provenance,
                    )
                )
                continue
            if item.resolution is SubjectResolutionStatus.MISSING:
                data_gaps.append(
                    AdmissionFitReason(
                        kind=AdmissionFitReasonKind.DATA_GAP,
                        message=f"Не указан балл по обязательному предмету «{item.exam.subject}»",
                        subject=item.exam.subject,
                        reference_score=item.exam.minimum_score,
                        source_name=item.exam.source_name,
                        provenance=provenance,
                    )
                )
                continue
            if item.applicant_score is None:
                continue
            if item.exam.minimum_score is None:
                reasons.append(
                    AdmissionFitReason(
                        kind=AdmissionFitReasonKind.FIT,
                        message=f"Предмет «{item.exam.subject}» есть в требованиях выбранного набора",
                        subject=item.exam.subject,
                        applicant_score=item.applicant_score,
                        source_name=item.exam.source_name,
                        provenance=provenance,
                    )
                )
            elif item.applicant_score >= item.exam.minimum_score:
                reasons.append(
                    AdmissionFitReason(
                        kind=AdmissionFitReasonKind.FIT,
                        message=f"Баллы по предмету «{item.exam.subject}» выше опубликованного минимума",
                        subject=item.exam.subject,
                        applicant_score=item.applicant_score,
                        reference_score=item.exam.minimum_score,
                        source_name=item.exam.source_name,
                        provenance=provenance,
                    )
                )
            else:
                anti_reasons.append(
                    AdmissionFitReason(
                        kind=AdmissionFitReasonKind.ANTI_FIT,
                        message=f"Баллы по предмету «{item.exam.subject}» ниже опубликованного минимума",
                        subject=item.exam.subject,
                        applicant_score=item.applicant_score,
                        reference_score=item.exam.minimum_score,
                        source_name=item.exam.source_name,
                        provenance=provenance,
                    )
                )
        if passing_score is None:
            data_gaps.append(
                AdmissionFitReason(
                    kind=AdmissionFitReasonKind.DATA_GAP,
                    message="Для выбранного набора нет опубликованного проходного балла",
                    provenance=(),
                )
            )
        elif passing.value is not None and passing_score.score is not None:
            provenance = (passing_score.provenance,)
            total = sum((item.applicant_score for item in evaluations if item.applicant_score is not None), ZERO)
            if total >= passing_score.score:
                reasons.append(
                    AdmissionFitReason(
                        kind=AdmissionFitReasonKind.FIT,
                        message="Сумма введённых баллов не ниже опубликованного проходного балла",
                        applicant_total_score=total,
                        reference_score=passing_score.score,
                        source_name=passing_score.provenance.source_name,
                        provenance=provenance,
                    )
                )
            else:
                anti_reasons.append(
                    AdmissionFitReason(
                        kind=AdmissionFitReasonKind.ANTI_FIT,
                        message="Сумма введённых баллов ниже опубликованного проходного балла",
                        applicant_total_score=total,
                        reference_score=passing_score.score,
                        source_name=passing_score.provenance.source_name,
                        provenance=provenance,
                    )
                )
        return tuple(reasons), tuple(anti_reasons), tuple(data_gaps)

    @staticmethod
    def _applicant_total(evaluations: tuple[_ExamEvaluation, ...]) -> Decimal | None:
        values = tuple(item.applicant_score for item in evaluations if item.applicant_score is not None)
        return sum(values, ZERO) if values else None


__all__ = ["AdmissionFitScoringService"]
