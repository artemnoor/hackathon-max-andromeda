"""Deterministic explanations for decision candidates."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitStatus,
    BatchAdmissionFitOutcome,
)
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.proftest.contracts.public import MatchScore
from andromeda.modules.program_analytics.contracts.public import ProgramFingerprint

from ..contracts.public import (
    DecisionCandidatePartition,
    DecisionConstraintApplicability,
    DecisionConstraintOutcome,
    DecisionSuggestionReasons,
)
from ..domain.values import AdmissionGate


class DecisionExplanationBuilder:
    """Build stable reason buckets from source-backed evidence only."""

    def build(
        self,
        *,
        program: Program | None,
        fingerprint: ProgramFingerprint | None,
        admission: BatchAdmissionFitOutcome | None,
        content_fit: MatchScore | None,
        profile_present: bool,
        partition: DecisionCandidatePartition,
        constraint_outcomes: Iterable[DecisionConstraintOutcome] = (),
        extra_missing: Iterable[str] = (),
    ) -> tuple[DecisionSuggestionReasons, tuple[str, ...]]:
        included: list[str] = []
        may_not_fit: list[str] = []
        admission_risk: list[str] = []
        content_differences: list[str] = []
        missing: list[str] = []
        source_gaps: list[str] = []

        if program is not None:
            included.append("Вариант найден в каноническом каталоге программ")
        if content_fit is not None:
            included.append("Для учебного плана рассчитано отдельное Content Fit-свидетельство")
        elif profile_present:
            missing.append("Для программы не найден полный отпечаток учебного плана для Content Fit")
            source_gaps.append("curriculum_fingerprint_unavailable")

        if fingerprint is not None:
            content_differences.extend(self._content_differences(fingerprint))
        if content_fit is not None and content_fit.content_fit < 50:
            may_not_fit.append("Content Fit не показывает выраженного соответствия текущим предпочтениям")

        if admission is None:
            missing.append("Admission Fit ещё не проверялся: добавьте ограничения поступления")
            admission_risk.append("Риск поступления не оценён")
        else:
            self._admission_reasons(admission, admission_risk, included, may_not_fit, missing, source_gaps)

        self._constraint_reasons(constraint_outcomes, included, may_not_fit, missing, source_gaps)

        if partition is DecisionCandidatePartition.ALTERNATIVE:
            included.append("Вариант оставлен среди ближайших альтернатив для дальнейшего сравнения")
        elif partition is DecisionCandidatePartition.INELIGIBLE:
            may_not_fit.append("По опубликованным данным вариант сейчас выглядит малореалистичным")
        elif partition is DecisionCandidatePartition.INSUFFICIENT_DATA:
            may_not_fit.append("Нельзя надёжно отнести вариант к реалистичным без полного набора данных")

        if not profile_present:
            missing.append("Профиль предпочтений не заполнен; Content Fit не является основанием выбора")
        missing.extend(extra_missing)

        return (
            DecisionSuggestionReasons(
                why_included=_unique(included),
                why_may_not_fit=_unique(may_not_fit),
                admission_risk=_unique(admission_risk),
                content_differences=_unique(content_differences),
                missing_data=_unique(missing),
            ),
            _unique(source_gaps),
        )

    @staticmethod
    def _constraint_reasons(
        outcomes: Iterable[DecisionConstraintOutcome],
        included: list[str],
        may_not_fit: list[str],
        missing: list[str],
        source_gaps: list[str],
    ) -> None:
        for outcome in outcomes:
            if outcome.applicability is DecisionConstraintApplicability.APPLIED and outcome.satisfied is True:
                included.append(outcome.message)
            elif outcome.applicability is DecisionConstraintApplicability.APPLIED and outcome.satisfied is False:
                may_not_fit.append(outcome.message)
            elif outcome.applicability is DecisionConstraintApplicability.INSUFFICIENT_DATA:
                missing.append(outcome.message)
            source_gaps.extend(outcome.source_gaps)

    @staticmethod
    def _admission_reasons(
        outcome: BatchAdmissionFitOutcome,
        admission_risk: list[str],
        included: list[str],
        may_not_fit: list[str],
        missing: list[str],
        source_gaps: list[str],
    ) -> None:
        messages = tuple(reason.message for reason in outcome.data_gaps)
        source_gaps.extend(messages)
        if outcome.status is AdmissionFitStatus.REALISTIC:
            included.append("Admission Fit: опубликованные факты выглядят реалистично, но не гарантируют поступление")
            admission_risk.append("Риск поступления: realistic по доступным историческим и экзаменационным данным")
        elif outcome.status is AdmissionFitStatus.BORDERLINE:
            may_not_fit.append("Admission Fit показывает пограничный сценарий поступления")
            admission_risk.append("Риск поступления: borderline; исторический порог не является гарантией")
        elif outcome.status is AdmissionFitStatus.UNLIKELY:
            may_not_fit.append("Admission Fit показывает малореалистичный сценарий поступления")
            admission_risk.append("Риск поступления: unlikely по доступным данным")
        else:
            missing.append("Admission Fit недостаточен для вывода о реалистичности")
            admission_risk.append("Риск поступления не определён из-за source gap")
        missing.extend(messages)

    @staticmethod
    def _content_differences(fingerprint: ProgramFingerprint) -> tuple[str, ...]:
        ordered = sorted(
            fingerprint.area_share.items(),
            key=lambda item: (-item[1], item[0].value),
        )
        return tuple(
            f"Учебный план заметно сосредоточен на области «{area.value}»"
            for area, share in ordered[:3]
            if share > Decimal("0")
        )


def _unique(values: Iterable[str], *, limit: int = 8) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= limit:
            break
    return tuple(result)


def admission_gate(status: AdmissionFitStatus | None) -> AdmissionGate:
    """Map local Admission Fit status without collapsing it into a score."""

    if status is None:
        return AdmissionGate.NOT_EVALUATED
    return {
        AdmissionFitStatus.REALISTIC: AdmissionGate.REALISTIC,
        AdmissionFitStatus.BORDERLINE: AdmissionGate.BORDERLINE,
        AdmissionFitStatus.UNLIKELY: AdmissionGate.UNLIKELY,
        AdmissionFitStatus.INSUFFICIENT_DATA: AdmissionGate.INSUFFICIENT_DATA,
    }[status]


__all__ = ["DecisionExplanationBuilder", "admission_gate"]
