"""Evidence-backed fit and anti-fit explanations."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
import logging

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, area_definition
from andromeda.shared.contracts.provenance import SourceAttribution

from ..contracts.public import ActivityCode, MatchReason, ProgramFingerprint, ReasonKind, UserProfile


logger = logging.getLogger("andromeda.recommendations")
ZERO = Decimal("0")


class ExplanationBuilder:
    """Build reasons only from profile weights and fingerprint evidence."""

    def build(self, profile: UserProfile, fingerprint: ProgramFingerprint) -> tuple[MatchReason, ...]:
        reasons = self._positive_area_reasons(profile, fingerprint) + self._positive_activity_reasons(profile, fingerprint) + self._negative_reasons(profile, fingerprint) + self._distinctive_reasons(profile, fingerprint)
        if not reasons:
            if not fingerprint.evidence:
                logger.warning("recommendations_explanation_evidence_missing program_id=%s", _safe_id(fingerprint.program_id))
                reasons.append(MatchReason(kind=ReasonKind.FIT, text="Доказательств недостаточно: source-backed отпечаток учебного плана не представлен.", workload=ZERO, share=ZERO, source_names=(), provenance=()))
            else:
                reasons.append(MatchReason(kind=ReasonKind.FIT, text="Профиль пока нейтральный: результат основан на доступной структуре учебного плана.", workload=fingerprint.total_workload, share=Decimal("1") if fingerprint.total_workload > ZERO else ZERO, source_names=(), provenance=fingerprint.provenance))
        return tuple(reasons[:8])

    def _positive_area_reasons(self, profile: UserProfile, fingerprint: ProgramFingerprint) -> list[MatchReason]:
        if not fingerprint.evidence:
            return []
        rows: list[MatchReason] = []
        for area, preference in sorted(profile.preferred_subject_weights.items(), key=lambda entry: (-entry[1], entry[0].value)):
            share = fingerprint.area_share.get(area, ZERO)
            if share <= ZERO:
                continue
            workload = fingerprint.area_hours.get(area, ZERO)
            rows.append(MatchReason(kind=ReasonKind.FIT, area=area, text=f"Совпадает интерес к области «{area_definition(area).name}»: {_format_workload(workload, fingerprint)} ({_format_percent(share)} учебного плана).", workload=workload, share=_quantize_ratio(share), source_names=_source_names_for_area(fingerprint, area), provenance=_provenance_for_area(fingerprint, area)))
        return rows[:3]

    def _positive_activity_reasons(self, profile: UserProfile, fingerprint: ProgramFingerprint) -> list[MatchReason]:
        if not fingerprint.evidence:
            return []
        rows: list[MatchReason] = []
        for activity, preference in sorted(profile.preferred_activity_weights.items(), key=lambda entry: (-entry[1], entry[0].value)):
            share = fingerprint.activity_signals.get(activity, ZERO)
            if share <= ZERO:
                continue
            workload = fingerprint.total_workload * share
            rows.append(MatchReason(kind=ReasonKind.FIT, activity=activity, text=f"Сигнал «{_activity_label(activity)}» занимает около {_format_percent(share)} нагрузки ({_format_workload(workload, fingerprint)}).", workload=workload, share=_quantize_ratio(share), provenance=_inferred_provenance(fingerprint)))
        return rows[:2]

    def _negative_reasons(self, profile: UserProfile, fingerprint: ProgramFingerprint) -> list[MatchReason]:
        if not fingerprint.evidence:
            return []
        rows: list[MatchReason] = []
        for area, intensity in sorted(profile.negative_weights.items(), key=lambda entry: (-entry[1], entry[0].value)):
            share = fingerprint.area_share.get(area, ZERO)
            if share <= ZERO:
                continue
            workload = fingerprint.area_hours.get(area, ZERO)
            rows.append(MatchReason(kind=ReasonKind.ANTI_FIT, area=area, text=f"Антиинтерес к области «{area_definition(area).name}»: {_format_percent(share)} учебного плана ({_format_workload(workload, fingerprint)}), интенсивность {_format_percent(intensity)}.", workload=workload, share=_quantize_ratio(share), source_names=_source_names_for_area(fingerprint, area), provenance=_provenance_for_area(fingerprint, area)))
        return rows[:3]

    def _distinctive_reasons(self, profile: UserProfile, fingerprint: ProgramFingerprint) -> list[MatchReason]:
        if not fingerprint.evidence:
            return []
        rows: list[MatchReason] = []
        for subject in fingerprint.distinctive_subjects:
            preference = profile.preferred_subject_weights.get(subject.primary_area, ZERO)
            if preference <= ZERO:
                continue
            rows.append(MatchReason(kind=ReasonKind.FIT, area=subject.primary_area, text=f"Отличительная дисциплина «{subject.source_name}» занимает {_format_percent(subject.share)} нагрузки и редко встречается в каталоге.", workload=subject.workload, share=subject.share, source_names=(subject.source_name,), provenance=_provenance_for_subject(fingerprint, subject.normalized_name)))
        return rows[:2]


def _source_names_for_area(fingerprint: ProgramFingerprint, area: DisciplineAreaCode) -> tuple[str, ...]:
    return tuple(dict.fromkeys(evidence.source_name for evidence in fingerprint.evidence if any(weight.area is area for weight in evidence.area_weights)))[:3]


def _provenance_for_area(fingerprint: ProgramFingerprint, area: DisciplineAreaCode) -> tuple[SourceAttribution, ...]:
    return _unique_provenance(
        provenance
        for evidence in fingerprint.evidence
        if any(weight.area is area for weight in evidence.area_weights)
        for provenance in evidence.provenance
    )


def _provenance_for_subject(fingerprint: ProgramFingerprint, normalized_name: str) -> tuple[SourceAttribution, ...]:
    return _unique_provenance(
        provenance
        for evidence in fingerprint.evidence
        if evidence.normalized_name == normalized_name
        for provenance in evidence.provenance
    )


def _inferred_provenance(fingerprint: ProgramFingerprint) -> tuple[SourceAttribution, ...]:
    return tuple(value.model_copy(update={"field": "activity_signals", "inferred": True}) for value in fingerprint.provenance)


def _unique_provenance(values: Iterable[SourceAttribution]) -> tuple[SourceAttribution, ...]:
    result: list[SourceAttribution] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _format_workload(workload: Decimal, fingerprint: ProgramFingerprint) -> str:
    return f"{_decimal_text(workload)} {'часов' if fingerprint.basis == 'hours' else 'ЗЕТ'}"


def _format_percent(value: Decimal) -> str:
    return f"{_decimal_text(value * Decimal('100'))}%"


def _decimal_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)).rstrip("0").rstrip(".")


def _quantize_ratio(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _activity_label(activity: ActivityCode) -> str:
    return {
        ActivityCode.ANALYTICAL: "анализировать и находить закономерности",
        ActivityCode.SOFTWARE_CREATION: "создавать цифровые инструменты",
        ActivityCode.SYSTEM_DESIGN: "проектировать системы",
        ActivityCode.RESEARCH: "исследовать и проверять гипотезы",
        ActivityCode.PHYSICAL_ENGINEERING: "собирать физические решения",
        ActivityCode.COMMUNICATION: "объяснять и работать с людьми",
        ActivityCode.CREATIVE: "придумывать и визуализировать",
        ActivityCode.BUSINESS: "организовывать и принимать решения",
        ActivityCode.DATA: "работать с данными",
    }[activity]


def _safe_id(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


__all__ = ["ExplanationBuilder"]
