"""Build curriculum-backed fingerprints without storage or transport access."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
import logging
from typing import Literal, TypeVar

from andromeda.modules.curricula.contracts.public import Curriculum
from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.ids import DisciplineId

from ..domain.entities import ActivityCode, CurriculumEvidence, ProgramFingerprint
from ..domain.signals import ACTIVITY_SIGNAL_WEIGHTS
from ..domain.values import ZERO, quantize_ratio


logger = logging.getLogger("andromeda.proftest.fingerprint")
KeyT = TypeVar("KeyT", bound=str)


class FingerprintBuilder:
    """Pure deterministic builder over canonical module contracts."""

    def build(
        self,
        program: Program,
        curriculum: Curriculum,
        disciplines: Mapping[DisciplineId, Discipline],
    ) -> ProgramFingerprint:
        logger.debug("fingerprint_start program_id=%s item_count=%d", _safe_id(program.id), len(curriculum.items))
        total_hours = sum(item.hours for item in curriculum.items)
        total_credits = sum((item.credits or ZERO for item in curriculum.items), ZERO)
        basis: Literal["hours", "credits"] = "hours" if total_hours > 0 else "credits"
        total_workload = Decimal(total_hours) if basis == "hours" else total_credits
        if total_workload <= ZERO:
            logger.warning("fingerprint_zero_workload program_id=%s", _safe_id(program.id))

        area_workload: dict[DisciplineAreaCode, Decimal] = defaultdict(lambda: ZERO)
        semester_workload: dict[str, Decimal] = defaultdict(lambda: ZERO)
        evidence: list[CurriculumEvidence] = []
        for item in curriculum.items:
            discipline = disciplines.get(item.discipline_id)
            if discipline is None:
                logger.error("fingerprint_discipline_missing program_id=%s discipline_id=%s", _safe_id(program.id), _safe_id(item.discipline_id))
                raise ValueError(f"curriculum item discipline is missing: {item.discipline_id}")
            item_workload = Decimal(item.hours) if basis == "hours" else (item.credits or ZERO)
            area_weights = discipline.area_weights
            if sum((weight.weight for weight in area_weights), ZERO) != Decimal("1"):
                logger.error("fingerprint_invalid_area_vector program_id=%s", _safe_id(program.id))
                raise ValueError(f"discipline area weights must sum to one: {discipline.id}")
            for weight in area_weights:
                area_workload[weight.area] += item_workload * weight.weight
            semester_key = str(item.semester) if item.semester is not None else "unassigned"
            semester_workload[semester_key] += item_workload
            evidence.append(
                CurriculumEvidence(
                    source_name=item.source_name,
                    normalized_name=discipline.normalized_name,
                    hours=item.hours,
                    credits=item.credits,
                    semester=item.semester,
                    assessment_types=item.assessment_types,
                    workload=item_workload,
                    area_weights=area_weights,
                    provenance=curriculum.provenance,
                    source_gaps=curriculum.source_gaps,
                )
            )

        area_share = _shares(area_workload, total_workload)
        semester_share = _shares(semester_workload, total_workload)
        activity_signals = _activity_signals(area_share)
        fingerprint = ProgramFingerprint(
            program_id=program.id,
            program_code=program.code,
            program_name=program.name,
            basis=basis,
            total_hours=total_hours,
            total_credits=total_credits,
            total_workload=total_workload,
            area_hours=dict(sorted(area_workload.items(), key=lambda entry: entry[0].value)),
            area_share=dict(sorted(area_share.items(), key=lambda entry: entry[0].value)),
            semester_distribution=dict(sorted(semester_share.items())),
            activity_signals=dict(sorted(activity_signals.items(), key=lambda entry: entry[0].value)),
            evidence=tuple(evidence),
            provenance=(*program.provenance, *curriculum.provenance),
            source_gaps=(*program.source_gaps, *curriculum.source_gaps),
        )
        logger.info(
            "fingerprint_complete program_id=%s basis=%s total_hours=%d total_credits=%s area_count=%d",
            _safe_id(fingerprint.program_id), fingerprint.basis, fingerprint.total_hours, fingerprint.total_credits, len(fingerprint.area_share),
        )
        return fingerprint

    def add_distinctive_subjects(
        self,
        fingerprints: Iterable[ProgramFingerprint],
        *,
        limit: int = 8,
    ) -> tuple[ProgramFingerprint, ...]:
        """Enrich fingerprints with catalog-relative, evidence-backed subjects."""

        from ..domain.entities import DistinctiveSubject

        fingerprint_list = tuple(fingerprints)
        total_programs = len(fingerprint_list)
        if total_programs == 0:
            return ()
        program_presence: dict[str, set[str]] = defaultdict(set)
        for fingerprint in fingerprint_list:
            for evidence in fingerprint.evidence:
                if evidence.workload > ZERO:
                    program_presence[evidence.normalized_name].add(fingerprint.program_id)

        enriched: list[ProgramFingerprint] = []
        for fingerprint in fingerprint_list:
            by_name: dict[str, list[CurriculumEvidence]] = defaultdict(list)
            for evidence in fingerprint.evidence:
                by_name[evidence.normalized_name].append(evidence)
            subjects: list[DistinctiveSubject] = []
            for normalized_name, evidence_rows in by_name.items():
                workload = sum((row.workload for row in evidence_rows), ZERO)
                if fingerprint.total_workload <= ZERO or workload <= ZERO:
                    continue
                share = workload / fingerprint.total_workload
                frequency = len(program_presence.get(normalized_name, set()))
                rarity = Decimal("1") - (Decimal(frequency) / Decimal(total_programs))
                distinctiveness = max(ZERO, min(Decimal("1"), share * rarity))
                if distinctiveness <= ZERO:
                    continue
                representative = max(evidence_rows, key=lambda row: (row.workload, row.source_name))
                primary_area = max(representative.area_weights, key=lambda weight: (weight.weight, weight.area.value)).area
                subjects.append(
                    DistinctiveSubject(
                        source_name=representative.source_name,
                        normalized_name=normalized_name,
                        primary_area=primary_area,
                        workload=workload,
                        share=quantize_ratio(share),
                        rarity=quantize_ratio(rarity),
                        distinctiveness=quantize_ratio(distinctiveness),
                    )
                )
            subjects.sort(key=lambda subject: (-subject.distinctiveness, -subject.share, subject.normalized_name))
            enriched.append(fingerprint.model_copy(update={"distinctive_subjects": tuple(subjects[:limit])}))
        return tuple(enriched)


def _shares(values: Mapping[KeyT, Decimal], total: Decimal) -> dict[KeyT, Decimal]:
    if total <= ZERO:
        return {}
    ordered_values = sorted(((key, value) for key, value in values.items() if value > ZERO), key=lambda entry: str(entry[0]))
    if not ordered_values:
        return {}
    shares = {key: quantize_ratio(value / total) for key, value in ordered_values}
    last_key = ordered_values[-1][0]
    shares[last_key] += Decimal("1") - sum(shares.values(), ZERO)
    return shares


def _activity_signals(area_share: Mapping[DisciplineAreaCode, Decimal]) -> dict[ActivityCode, Decimal]:
    signals: dict[ActivityCode, Decimal] = defaultdict(lambda: ZERO)
    for area, area_ratio in area_share.items():
        for signal, weight in ACTIVITY_SIGNAL_WEIGHTS[area].items():
            signals[signal] += area_ratio * weight
    total = sum(signals.values(), ZERO)
    if total <= ZERO:
        return {}
    ordered_signals = sorted(((signal, value) for signal, value in signals.items() if value > ZERO), key=lambda entry: entry[0].value)
    normalized = {signal: quantize_ratio(value / total) for signal, value in ordered_signals}
    last_signal = ordered_signals[-1][0]
    normalized[last_signal] += Decimal("1") - sum(normalized.values(), ZERO)
    return normalized


def _safe_id(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


__all__ = ["FingerprintBuilder"]
