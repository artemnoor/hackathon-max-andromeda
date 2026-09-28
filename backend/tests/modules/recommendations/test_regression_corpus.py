from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, DisciplineAreaWeight, TAXONOMY_VERSION
from andromeda.modules.proftest.contracts.public import (
    ActivityCode,
    CurriculumEvidence,
    EvidenceSignal,
    EvidenceStatus,
    ProgramFingerprint,
)
from andromeda.modules.recommendations.domain.policy import RECOMMENDATION_POLICY_VERSION
from andromeda.modules.recommendations.contracts.public import RecommendationRequest
from andromeda.modules.recommendations.services.recommendations import RecommendationService
from andromeda.modules.recommendations.services.scoring import RecommendationScoringService
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import GapSeverity, SourceAttribution, SourceGapReference

from .factories import fingerprint_from_areas, profile


CORPUS_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "recommendations" / "regression-v1.json"


class _Reader:
    def __init__(self, fingerprints: tuple[ProgramFingerprint, ...]) -> None:
        self._fingerprints = fingerprints

    def list_fingerprints(self) -> tuple[ProgramFingerprint, ...]:
        return self._fingerprints


def _cases() -> list[dict[str, Any]]:
    corpus = cast(dict[str, Any], json.loads(CORPUS_PATH.read_text(encoding="utf-8")))
    assert corpus["corpus_version"] == "recommendations-regression.v1"
    assert corpus["policy_version"] == RECOMMENDATION_POLICY_VERSION
    assert corpus["taxonomy_version"] == TAXONOMY_VERSION
    return cast(list[dict[str, Any]], corpus["cases"])


def _decimal_map(value: object, enum_type: type[Any]) -> dict[Any, Decimal]:
    raw = cast(dict[str, str], value)
    return {enum_type(key): Decimal(item) for key, item in raw.items()}


def _source(case_id: str, code: str) -> SourceAttribution:
    return SourceAttribution(
        kind=SourceKind.BMSTU_CURRICULUM_DOCUMENT,
        url=f"https://fixture.invalid/recommendations/{case_id}/{code}.pdf",
        captured_at=datetime(2026, 9, 18, 10, tzinfo=timezone.utc),
        content_sha256=(case_id + code).encode().hex().ljust(64, "a")[:64],
        university_id="university:fixture",
        run_id="ingest:" + "f" * 32,
        field="curriculum",
        record_key=f"program:{code}",
    )


def _fingerprint(case_id: str, item: dict[str, Any], *, source_state: str | None = None) -> ProgramFingerprint:
    code = cast(str, item["code"])
    areas = _decimal_map(item["areas"], DisciplineAreaCode)
    activities = _decimal_map(item["activities"], ActivityCode)
    value = fingerprint_from_areas(code, areas, activities)
    state = source_state or cast(str, item["source_state"])
    if state == "missing":
        return value.model_copy(
            update={
                "source_gaps": (
                    SourceGapReference(
                        code="curriculum_source_missing",
                        severity=GapSeverity.DEGRADABLE,
                        message="Fixture deliberately omits the curriculum source.",
                        field="curriculum",
                    ),
                )
            }
        )

    source = _source(case_id, code)
    evidence = CurriculumEvidence(
        source_name=f"Fixture curriculum {code}",
        normalized_name=f"fixture-{code}",
        hours=100,
        workload=Decimal("100"),
        area_weights=tuple(
            DisciplineAreaWeight(area=area, weight=share)
            for area, share in value.area_share.items()
        ),
        provenance=(source,),
    )
    gaps: tuple[SourceGapReference, ...] = ()
    if state == "partial":
        gaps = (
            SourceGapReference(
                code="curriculum_partial",
                severity=GapSeverity.DEGRADABLE,
                message="Fixture deliberately marks one curriculum source as partial.",
                field="curriculum",
            ),
        )
    return value.model_copy(update={"evidence": (evidence,), "provenance": (source,), "source_gaps": gaps})


def _profile(case: dict[str, Any]):
    value = cast(dict[str, Any], case["profile"])
    return profile(
        subject=_decimal_map(value["subject"], DisciplineAreaCode),
        activity=_decimal_map(value["activity"], ActivityCode),
        negative=_decimal_map(value["negative"], DisciplineAreaCode),
    )


def _recommendations(case: dict[str, Any]):
    fingerprints = tuple(_fingerprint(cast(str, case["id"]), item) for item in cast(list[dict[str, Any]], case["programs"]))
    return RecommendationService(_Reader(fingerprints)).recommend(
        RecommendationRequest(profile=_profile(case), limit=len(fingerprints))
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda case: cast(str, case["id"]))
def test_versioned_corpus_replays_expected_top_and_is_deterministic(case: dict[str, Any]) -> None:
    first = _recommendations(case)
    second = _recommendations(case)

    assert first == second
    assert first.recommendations[0].program_code == case["expected_top_code"]
    assert first.recommendations[0].evidence.policy_version == RECOMMENDATION_POLICY_VERSION
    assert first.recommendations[0].evidence.taxonomy_version == TAXONOMY_VERSION
    assert first.recommendations[0].evidence.catalog_completeness.status.value == case["expected_catalog_status"]
    assert cast(str, case["reviewer_rationale"])

    expected_gaps = set(cast(list[str], case.get("expected_gap_codes", [])))
    assert expected_gaps <= {gap.code for gap in first.recommendations[0].evidence.missing_data}
    for signal in cast(list[str], case.get("required_signals", [])):
        assert EvidenceSignal(signal) in first.recommendations[0].evidence.signals_used

    anti_interest_codes = set(cast(list[str], case.get("anti_interest_codes", [])))
    for recommendation in first.recommendations:
        if recommendation.program_code in anti_interest_codes:
            assert recommendation.anti_fit_reasons


def test_corpus_reasons_are_source_backed_or_explicitly_unknown() -> None:
    for case in _cases():
        result = _recommendations(case)
        for recommendation in result.recommendations:
            for reason in (*recommendation.reasons, *recommendation.anti_fit_reasons):
                assert reason.provenance or "Доказательств недостаточно" in reason.text


def test_profile_change_affects_only_the_expected_content_fit_axes() -> None:
    program = _fingerprint(
        "metamorphic-profile-axis",
        {
            "code": "09.03.01-02",
            "areas": {"computer_science_data": "0.7", "mathematics_statistics": "0.3"},
            "activities": {"software_creation": "1"},
            "source_state": "complete",
        },
    )
    scorer = RecommendationScoringService()
    subject_computer = profile(subject={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")}, activity={ActivityCode.SOFTWARE_CREATION: Decimal("1")})
    subject_math = profile(subject={DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("1")}, activity={ActivityCode.SOFTWARE_CREATION: Decimal("1")})

    before = scorer.score(subject_computer, program)
    after = scorer.score(subject_math, program)

    assert before.breakdown.subject_fit != after.breakdown.subject_fit
    assert before.breakdown.activity_fit == after.breakdown.activity_fit
    assert before.breakdown.anti_penalty == after.breakdown.anti_penalty


def test_removing_curriculum_source_reduces_evidence_without_changing_content_ranking() -> None:
    case = next(item for item in _cases() if item["id"] == "missing-curriculum-source")
    item = cast(list[dict[str, Any]], case["programs"])[0]
    full = _fingerprint(cast(str, case["id"]), item, source_state="complete")
    missing = _fingerprint(cast(str, case["id"]), item, source_state="missing")
    subject_profile = _profile(case)
    service = RecommendationService(_Reader((full, missing)))

    full_evidence = service.build_evidence(subject_profile, full)
    missing_evidence = service.build_evidence(subject_profile, missing)
    missing_result = RecommendationService(_Reader((missing,))).recommend(
        RecommendationRequest(profile=subject_profile, limit=1)
    )

    assert full_evidence.catalog_completeness.status is EvidenceStatus.AVAILABLE
    assert missing_evidence.catalog_completeness.value is None
    assert missing_evidence.source_freshness.value is None
    assert missing_evidence.reliability.value is None
    assert missing_result.recommendations[0].reasons[0].provenance == ()
    assert "Доказательств недостаточно" in missing_result.recommendations[0].reasons[0].text
