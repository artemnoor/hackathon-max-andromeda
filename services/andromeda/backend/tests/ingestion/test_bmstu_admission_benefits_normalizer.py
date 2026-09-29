from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.ingestion.contracts.raw import RawAdmissionBenefitDocument, RawIndividualAchievementRecord
from andromeda.ingestion.universities.bmstu.normalizers.admission_benefits import (
    normalize_direction_scope,
    normalize_individual_achievements,
)
from andromeda.modules.admission_benefits.contracts.policy import BenefitScopeMode
from andromeda.modules.admission_benefits.contracts.status import BenefitPolicyVersion, RuleDataStatus, TargetResolutionStatus
from andromeda.shared.contracts.enums import SourceKind


def _record(name: str, points: str, *, row: int = 1, kind: str = "appendix_6") -> RawIndividualAchievementRecord:
    url = "https://api.www.bmstu.ru/file/125465/download"
    return RawIndividualAchievementRecord(
        record_id=f"raw-individual-achievement:test:{row}",
        document_kind=kind,
        document_title=f"Приложение {kind.removeprefix('appendix_')} 2026",
        admission_year=2026,
        source_url=url,
        source_snapshot_hash="7" * 64,
        source_run_id="ingest:" + "8" * 32,
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        locator={"source_url": url, "page": 1, "row": row},
        raw_text=f"{name} | {points}",
        normalized_candidates=({"field": "official_name", "value": name}, {"field": "points", "value": points}),
        parser_version="bmstu-admission-parser.v1",
        official_name_candidate=name,
        points_text=points,
    )


VERSIONS = BenefitPolicyVersion(
    schema_version="admission-benefits-schema.v1",
    parser_version="admission-benefits-parser.v1",
    policy_version="admission-benefits-policy.v1",
)


def test_normalizer_builds_year_specific_policy_with_source_provenance() -> None:
    result = normalize_individual_achievements(
        (_record("Золотой знак ГТО", "5"),),
        university_id="university:bmstu",
        policy_version=VERSIONS,
        documents_discovered=1,
        documents_captured=1,
    )

    assert result.policy is not None
    assert result.policy.admission_year == 2026
    assert result.policy.rules[0].points == Decimal("5")
    assert result.policy.rules[0].provenance.source.kind is SourceKind.BMSTU_ADMISSION_INDIVIDUAL_ACHIEVEMENTS
    assert result.coverage.records_normalized == 1


def test_conflicting_points_are_preserved_as_conflict_not_last_write_wins() -> None:
    result = normalize_individual_achievements(
        (_record("Олимпиада X", "5", row=1), _record("Олимпиада X", "10", row=2)),
        university_id="university:bmstu",
        policy_version=VERSIONS,
    )

    assert len(result.conflicts) == 1
    assert result.policy is not None
    assert result.policy.status is RuleDataStatus.CONFLICT
    assert {rule.status for rule in result.policy.rules} == {RuleDataStatus.CONFLICT}


def test_direction_scope_resolves_known_codes_and_keeps_unknown_reviewable() -> None:
    scope = normalize_direction_scope(
        mode=BenefitScopeMode.ALL_EXCEPT,
        direction_codes=("09.03.04", "99.99.99"),
        original_text="все, кроме 09.03.04 и 99.99.99",
        known_direction_codes=frozenset({"09.03.04"}),
    )

    assert scope.targets[0].resolution is TargetResolutionStatus.RESOLVED
    assert scope.targets[1].resolution is TargetResolutionStatus.UNRESOLVED
    assert scope.applies_to(direction_code="09.03.03").status.value == "review_required"
