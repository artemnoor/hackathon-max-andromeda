"""Deterministic evidence-quality calculation for recommendation consumers."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
import logging

from andromeda.modules.disciplines.contracts.public import TAXONOMY_VERSION
from andromeda.modules.proftest.contracts.public import (
    EvidenceMetric,
    EvidenceSignal,
    EvidenceStatus,
    ProgramFingerprint,
    RecommendationEvidence,
    SourceFreshness,
    UserProfile,
)
from andromeda.shared.contracts.provenance import GapSeverity, SourceGapReference

from ..domain.policy import RECOMMENDATION_POLICY_VERSION


logger = logging.getLogger("andromeda.recommendations")
ZERO = Decimal("0")
ONE = Decimal("1")


class RecommendationEvidenceService:
    """Build source/profile evidence without changing Content Fit ranking."""

    def build(
        self,
        profile: UserProfile | None,
        fingerprint: ProgramFingerprint | None,
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> RecommendationEvidence:
        missing = list(fingerprint.source_gaps if fingerprint is not None else ())
        if profile is None:
            missing.append(
                _gap(
                    "profile_preferences_missing",
                    GapSeverity.BLOCKING,
                    "Профиль предпочтений не заполнен; Content Fit не является основанием выбора.",
                    can_continue=False,
                )
            )
        elif not _has_profile_signals(profile):
            missing.append(
                _gap(
                    "profile_signals_missing",
                    GapSeverity.DEGRADABLE,
                    "В профиле пока нет предметных, activity- или anti-interest сигналов.",
                )
            )
        if fingerprint is None:
            missing.append(
                _gap(
                    "curriculum_fingerprint_missing",
                    GapSeverity.BLOCKING,
                    "Для программы не найден source-backed отпечаток учебного плана.",
                    field="curriculum",
                    can_continue=False,
                )
            )

        profile_metric = _profile_confidence(profile)
        catalog_metric = _catalog_completeness(fingerprint)
        freshness = _source_freshness(fingerprint)
        reliability = _reliability(profile_metric, catalog_metric, freshness)
        signals, inferred = _signals(profile, fingerprint)
        run_ids = freshness.run_ids
        result = RecommendationEvidence(
            profile_confidence=profile_metric,
            catalog_completeness=catalog_metric,
            source_freshness=freshness,
            reliability=reliability,
            signals_used=signals,
            inferred_signals=inferred,
            missing_data=_unique_gaps(missing),
            policy_version=RECOMMENDATION_POLICY_VERSION,
            taxonomy_version=TAXONOMY_VERSION,
            question_set_version=question_set_version,
            profile_revision=profile_revision,
            catalog_run_ids=run_ids,
        )
        logger.debug(
            "recommendation_evidence_built profile_revision=%s question_set_version=%s fingerprint=%s profile_status=%s catalog_status=%s freshness_status=%s reliability_status=%s run_count=%d signal_count=%d inferred_count=%d missing_count=%d policy_version=%s taxonomy_version=%s",
            profile_revision if profile_revision is not None else "unknown",
            question_set_version or "unknown",
            "available" if fingerprint is not None else "missing",
            profile_metric.status.value,
            catalog_metric.status.value,
            freshness.status.value,
            reliability.status.value,
            len(run_ids),
            len(signals),
            len(inferred),
            len(result.missing_data),
            result.policy_version,
            result.taxonomy_version,
        )
        return result


def _has_profile_signals(profile: UserProfile) -> bool:
    return bool(profile.preferred_subject_weights or profile.preferred_activity_weights or profile.negative_weights)


def _profile_confidence(profile: UserProfile | None) -> EvidenceMetric:
    if profile is None or not _has_profile_signals(profile):
        return EvidenceMetric(value=None, status=EvidenceStatus.NOT_AVAILABLE)
    return EvidenceMetric(value=profile.confidence.value, status=EvidenceStatus.AVAILABLE)


def _catalog_completeness(fingerprint: ProgramFingerprint | None) -> EvidenceMetric:
    if fingerprint is None or not fingerprint.evidence or fingerprint.total_workload <= ZERO:
        return EvidenceMetric(value=None, status=EvidenceStatus.NOT_AVAILABLE)
    severities = {gap.severity for gap in fingerprint.source_gaps}
    if GapSeverity.BLOCKING in severities:
        return EvidenceMetric(value=None, status=EvidenceStatus.NOT_AVAILABLE)
    if GapSeverity.DEGRADABLE in severities:
        return EvidenceMetric(value=Decimal("0.7500"), status=EvidenceStatus.PARTIAL)
    if GapSeverity.INFORMATIONAL in severities:
        return EvidenceMetric(value=Decimal("0.9000"), status=EvidenceStatus.PARTIAL)
    return EvidenceMetric(value=ONE, status=EvidenceStatus.AVAILABLE)


def _source_freshness(fingerprint: ProgramFingerprint | None) -> SourceFreshness:
    if fingerprint is None or not fingerprint.provenance:
        return SourceFreshness(value=None, status=EvidenceStatus.NOT_AVAILABLE)
    run_ids = tuple(sorted({item.run_id for item in fingerprint.provenance if item.run_id is not None}))
    latest = max(item.captured_at for item in fingerprint.provenance)
    consistent = bool(run_ids) and len(run_ids) == 1 and all(item.run_id is not None for item in fingerprint.provenance)
    if consistent:
        return SourceFreshness(
            value=ONE,
            status=EvidenceStatus.AVAILABLE,
            latest_captured_at=latest,
            run_ids=run_ids,
            snapshot_consistent=True,
        )
    return SourceFreshness(
        value=Decimal("0.7500") if run_ids else Decimal("0.5000"),
        status=EvidenceStatus.PARTIAL,
        latest_captured_at=latest,
        run_ids=run_ids,
        snapshot_consistent=False,
    )


def _reliability(
    profile: EvidenceMetric,
    catalog: EvidenceMetric,
    freshness: SourceFreshness,
) -> EvidenceMetric:
    if profile.value is None:
        return EvidenceMetric(value=None, status=EvidenceStatus.NOT_AVAILABLE)
    weighted: tuple[tuple[Decimal, Decimal], ...] = ((profile.value, Decimal("0.50")),)
    if catalog.value is not None:
        weighted += ((catalog.value, Decimal("0.30")),)
    if freshness.value is not None:
        weighted += ((freshness.value, Decimal("0.20")),)
    if len(weighted) < 2:
        return EvidenceMetric(value=None, status=EvidenceStatus.NOT_AVAILABLE)
    total_weight = sum((weight for _value, weight in weighted), ZERO)
    value = (sum((item * weight for item, weight in weighted), ZERO) / total_weight).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    status = EvidenceStatus.AVAILABLE if len(weighted) == 3 else EvidenceStatus.PARTIAL
    return EvidenceMetric(value=value, status=status)


def _signals(
    profile: UserProfile | None,
    fingerprint: ProgramFingerprint | None,
) -> tuple[tuple[EvidenceSignal, ...], tuple[EvidenceSignal, ...]]:
    if fingerprint is None:
        return (), ()
    signals: set[EvidenceSignal] = set()
    inferred: set[EvidenceSignal] = set()
    if profile is not None and profile.preferred_subject_weights and fingerprint.area_share:
        signals.update((EvidenceSignal.PROFILE_SUBJECT_PREFERENCE, EvidenceSignal.CURRICULUM_AREA_SHARE))
    if profile is not None and profile.preferred_activity_weights and fingerprint.activity_signals:
        signals.add(EvidenceSignal.PROFILE_ACTIVITY_PREFERENCE)
        signals.add(EvidenceSignal.CURRICULUM_ACTIVITY_MAPPING)
        inferred.add(EvidenceSignal.CURRICULUM_ACTIVITY_MAPPING)
    if profile is not None and profile.negative_weights and fingerprint.area_share:
        signals.update((EvidenceSignal.PROFILE_ANTI_INTEREST, EvidenceSignal.CURRICULUM_AREA_SHARE))
    if profile is not None and (profile.preferred_subject_weights or profile.preferred_activity_weights) and fingerprint.distinctive_subjects:
        signals.add(EvidenceSignal.DISTINCTIVE_SUBJECT)
    if fingerprint.semester_distribution:
        signals.add(EvidenceSignal.SEMESTER_DISTRIBUTION)
    return (
        tuple(sorted(signals, key=lambda item: item.value)),
        tuple(sorted(inferred, key=lambda item: item.value)),
    )


def _gap(
    code: str,
    severity: GapSeverity,
    message: str,
    *,
    field: str | None = None,
    can_continue: bool = True,
) -> SourceGapReference:
    return SourceGapReference(code=code, severity=severity, message=message, field=field, can_continue=can_continue)


def _unique_gaps(values: Iterable[SourceGapReference]) -> tuple[SourceGapReference, ...]:
    result: list[SourceGapReference] = []
    for value in values:
        if value not in result:
            result.append(value)
        if len(result) >= 16:
            break
    return tuple(result)


__all__ = ["RecommendationEvidenceService"]
