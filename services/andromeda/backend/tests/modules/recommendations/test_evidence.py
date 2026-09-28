from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, DisciplineAreaWeight
from andromeda.modules.proftest.contracts.public import ActivityCode, CurriculumEvidence, EvidenceSignal, EvidenceStatus
from andromeda.modules.recommendations.services.evidence import RecommendationEvidenceService
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import GapSeverity, SourceAttribution, SourceGapReference

from .factories import fingerprint, profile


def _source() -> SourceAttribution:
    return SourceAttribution(
        kind=SourceKind.BMSTU_CURRICULUM_DOCUMENT,
        url="https://bmstu.ru/plan.pdf",
        captured_at=datetime(2026, 9, 18, 10, tzinfo=timezone.utc),
        content_sha256="a" * 64,
        university_id="university:bmstu",
        run_id="ingest:" + "b" * 32,
        field="curriculum",
        record_key="program:09.03.01-02",
    )


def test_evidence_is_deterministic_and_separates_inferred_activity_mapping() -> None:
    value = fingerprint().model_copy(
        update={
            "evidence": (
                CurriculumEvidence(
                    source_name="Алгоритмы",
                    normalized_name="алгоритмы",
                    hours=100,
                    workload=Decimal("100"),
                    area_weights=(
                        DisciplineAreaWeight(
                            area=DisciplineAreaCode.COMPUTER_SCIENCE_DATA,
                            weight=Decimal("1"),
                        ),
                    ),
                    provenance=(_source(),),
                ),
            ),
            "provenance": (_source(),),
            "source_gaps": (
                SourceGapReference(
                    code="taxonomy_override_pending",
                    severity=GapSeverity.DEGRADABLE,
                    message="Одно правило требует проверки.",
                ),
            ),
        },
    )
    service = RecommendationEvidenceService()

    activity_profile = profile(activity={ActivityCode.SOFTWARE_CREATION: Decimal("1")})
    first = service.build(activity_profile, value, profile_revision=3, question_set_version="proftest-v3")
    second = service.build(activity_profile, value, profile_revision=3, question_set_version="proftest-v3")

    assert first == second
    assert first.profile_confidence.value == Decimal("1")
    assert first.catalog_completeness.status is EvidenceStatus.PARTIAL
    assert first.source_freshness.status is EvidenceStatus.AVAILABLE
    assert first.reliability.status is EvidenceStatus.AVAILABLE
    assert EvidenceSignal.CURRICULUM_ACTIVITY_MAPPING in first.inferred_signals
    assert first.catalog_run_ids == ("ingest:" + "b" * 32,)
    assert first.question_set_version == "proftest-v3"
    assert first.missing_data[0].severity is GapSeverity.DEGRADABLE


def test_missing_profile_or_fingerprint_is_not_encoded_as_numeric_zero() -> None:
    result = RecommendationEvidenceService().build(None, None)

    assert result.profile_confidence.value is None
    assert result.catalog_completeness.value is None
    assert result.source_freshness.value is None
    assert result.reliability.value is None
    assert result.reliability.status is EvidenceStatus.NOT_AVAILABLE
    assert {item.code for item in result.missing_data} == {
        "profile_preferences_missing",
        "curriculum_fingerprint_missing",
    }


def test_legacy_source_without_run_id_is_explicitly_partial() -> None:
    fingerprint_without_run = fingerprint().model_copy(update={"provenance": (_source().model_copy(update={"run_id": None}),)})

    result = RecommendationEvidenceService().build(profile(), fingerprint_without_run)

    assert result.source_freshness.status is EvidenceStatus.PARTIAL
    assert result.source_freshness.snapshot_consistent is False
    assert result.source_freshness.value == Decimal("0.5000")
