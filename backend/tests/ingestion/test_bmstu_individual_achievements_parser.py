from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import HttpUrl

from andromeda.ingestion.contracts.raw import (
    RawAdmissionBenefitDocument,
    RawIndividualAchievementRecord,
    SourceLocator,
)
from andromeda.ingestion.universities.bmstu.normalizers.admission_benefits import (
    normalize_individual_achievements,
)
from andromeda.ingestion.universities.bmstu.parser.individual_achievements import (
    parse_individual_achievement_tables,
)
from andromeda.modules.admission_benefits.contracts.public import (
    AchievementCombinationPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import (
    BenefitPolicyVersion,
    RuleDataStatus,
)

OFFICIAL_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "bmstu"
    / "admission_benefits"
    / "appendix-6-extract.json"
)
VERSIONS = BenefitPolicyVersion(
    schema_version="admission-benefits-schema.v1",
    parser_version="admission-benefits-parser.v1",
    policy_version="admission-benefits-policy.v1",
)


def _document(kind: str = "appendix_6") -> RawAdmissionBenefitDocument:
    url = "https://api.www.bmstu.ru/file/125465/download" if kind == "appendix_6" else "https://api.www.bmstu.ru/file/124926/download"
    return RawAdmissionBenefitDocument(
        document_kind=kind,
        document_title=f"Приложение {kind.removeprefix('appendix_')} 2026",
        admission_year=2026,
        source_url=HttpUrl(url),
        source_snapshot_hash="5" * 64,
        source_run_id="ingest:" + "6" * 32,
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        locator=SourceLocator(source_url=HttpUrl(url)),
        parser_version="bmstu-admission-parser.v1",
    )


def test_appendix_6_rows_preserve_points_and_document_requirements() -> None:
    records, diagnostics = parse_individual_achievement_tables(
        _document(),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Вид индивидуального достижения", "Подтверждающий документ", "Баллы"],
                    ["1", "Аттестат о среднем общем образовании с отличием", "аттестат", "10"],
                    ["5", "Золотой знак ГТО", "удостоверение ГТО", "5"],
                ],
            },
        ),
    )

    assert len(records) == 2
    assert diagnostics == ()
    assert records[0].official_name_candidate == "Аттестат о среднем общем образовании с отличием"
    assert records[0].points_text == "10"
    assert records[1].required_document_text == "удостоверение ГТО"


def test_appendix_7_rows_are_marked_master_only() -> None:
    records, _ = parse_individual_achievement_tables(
        _document("appendix_7"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [["№", "Вид достижения", "Баллы"], ["1", "Научная публикация", "5"]],
            },
        ),
    )

    assert any(candidate.field == "education_level" and candidate.value == "master" for candidate in records[0].normalized_candidates)


def test_oversized_official_achievement_name_is_bounded_in_typed_projection() -> None:
    long_name = "Наличие " + ("документа о достижении, " * 60)
    records, diagnostics = parse_individual_achievement_tables(
        _document(),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Вид индивидуального достижения", "Баллы"],
                    ["1", long_name, "5"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert records[0].official_name_candidate == f"{long_name[:509]}..."
    assert any(candidate.field == "official_name" and candidate.value == long_name.strip() for candidate in records[0].normalized_candidates)


def test_not_counted_for_special_rights_is_not_misclassified_as_non_combinable() -> None:
    records, diagnostics = parse_individual_achievement_tables(
        _document(),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Вид индивидуального достижения", "Условие", "Баллы"],
                    ["1", "Олимпиада", "результаты не учитывались при получении особых прав", "5"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert records
    assert not any(candidate.field == "combination_policy" for candidate in records[0].normalized_candidates)


def _official_source() -> tuple[
    RawAdmissionBenefitDocument,
    dict[str, Any],
    tuple[RawIndividualAchievementRecord, ...],
]:
    payload = json.loads(OFFICIAL_FIXTURE.read_text(encoding="utf-8"))
    document = _document().model_copy(
        update={"source_snapshot_hash": payload["content_sha256"]}
    )
    records, diagnostics = parse_individual_achievement_tables(
        document,
        payload["tables"],
        document_pages=tuple(
            (item["page"], item["text"])
            for item in payload["text_layer_pages"]
        ),
    )
    assert diagnostics == ()
    return document, payload, records


def test_official_appendix_6_extract_covers_all_numbered_rows_and_tiers() -> None:
    _, payload, records = _official_source()

    assert payload["source_url"] == "https://api.www.bmstu.ru/file/125465/download"
    assert payload["content_sha256"] == "5ae90e108dc8940b37fe3b07f211664b7871791792abdc6ddc0dd365fb948bb9"
    assert {record.locator.row for record in records} == set(range(1, 47))
    assert len(records) == 82

    gto = [record for record in records if record.locator.row == 5]
    assert {record.points_text for record in gto} == {"5", "4", "3"}
    assert all(record.variant_label for record in gto)
    assert all("удостоверение ГТО" in (record.required_document_text or "") for record in gto)
    assert all(record.source_pages == (2,) for record in gto)

    note_markers = {note.marker for note in records[0].document_notes}
    assert note_markers == {"*", "1", "2", "3", "4"}
    assert next(note for note in records[0].document_notes if note.marker == "2").locator.page == 7
    assert next(note for note in records[0].document_notes if note.marker == "4").locator.page == 8
    assert "Заместитель председателя" not in next(
        note.source_text for note in records[0].document_notes if note.marker == "4"
    )


def test_official_appendix_6_policy_reaches_normalized_contract_with_provenance() -> None:
    document, _, records = _official_source()
    normalized = normalize_individual_achievements(
        records,
        university_id="university:bmstu",
        policy_version=VERSIONS,
    )

    policy = normalized.policy
    assert policy is not None
    assert policy.status is RuleDataStatus.ACTIVE
    assert policy.global_max_points == 10
    assert policy.default_combination_policy is AchievementCombinationPolicy.ADDITIVE
    assert policy.provenance.source.content_sha256 == document.source_snapshot_hash
    assert policy.provenance.page == 7
    assert "document_note=2" in (policy.provenance.source.locator or "")

    gto = [rule for rule in policy.rules if rule.provenance.row == 5]
    assert len(gto) == 3
    assert len({rule.achievement_code for rule in gto}) == 3
    assert len({rule.combination_group for rule in gto}) == 1
    assert all(rule.combination_policy is AchievementCombinationPolicy.MAX_ONLY for rule in gto)
    note_four_evidence = next(
        condition.provenance
        for rule in gto
        for condition in rule.conditions
        if condition.normalized_value == "appendix_6_note:4"
    )
    assert note_four_evidence is not None
    assert note_four_evidence.page == 8
    assert "document_note=4" in (note_four_evidence.source.locator or "")
    assert all(rule.status is RuleDataStatus.ACTIVE for rule in policy.rules)


def test_missing_official_combination_notes_keeps_achievement_policy_review_required() -> None:
    records, _ = parse_individual_achievement_tables(
        _document(),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Вид индивидуального достижения", "Подтверждающий документ", "Баллы"],
                    ["1", "Аттестат с отличием", "аттестат", "10"],
                ],
            },
        ),
    )
    normalized = normalize_individual_achievements(
        records,
        university_id="university:bmstu",
        policy_version=VERSIONS,
    )

    assert normalized.policy is not None
    assert normalized.policy.status is RuleDataStatus.REVIEW_REQUIRED
    assert normalized.policy.global_max_points is None
    assert normalized.policy.default_combination_policy is AchievementCombinationPolicy.UNKNOWN
