from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.ingestion.universities.bmstu.adapter import _parse_order_admissions
from andromeda.ingestion.universities.bmstu.mappings.admissions import (
    normalize_study_form,
)
from andromeda.ingestion.universities.bmstu.parser import admission_orders
from andromeda.ingestion.universities.bmstu.parser.admissions import (
    _exam_requirements,
    _tuition,
)

adapter_module = importlib.import_module("andromeda.ingestion.universities.bmstu.adapter")


FIXTURES = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_study_form_normalization_preserves_official_variants() -> None:
    assert normalize_study_form("очная") == "full_time"
    assert normalize_study_form("заочная") == "part_time"
    assert normalize_study_form("очно-заочная") == "evening"
    assert normalize_study_form("full_time") == "full_time"


def test_tuition_does_not_invent_academic_year() -> None:
    tuition = _tuition({"price": [{"value": 100, "currency": "RUB"}]})

    assert tuition[0].academic_year is None


def test_bmstu_choice_metadata_is_only_retained_when_source_explicitly_defines_it() -> None:
    legacy = _exam_requirements(
        {"points": [{"title": "Информатика", "point": 45, "isChoice": True}]}
    )
    explicit = _exam_requirements(
        {
            "points": [
                {
                    "title": "Информатика",
                    "point": 45,
                    "isChoice": True,
                    "choiceGroupId": "exam-choice:ege-third",
                    "choiceGroupMin": 1,
                    "choiceGroupMax": 1,
                }
            ]
        }
    )

    assert legacy[0].choice_group_id is None
    assert legacy[0].choice_group_min is None
    assert legacy[0].choice_group_max is None
    assert explicit[0].choice_group_id == "exam-choice:ege-third"
    assert (explicit[0].choice_group_min, explicit[0].choice_group_max) == (1, 1)


def test_bmstu_detail_admissions_are_emitted_as_canonical_program_contracts() -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURES)
    finally:
        adapter.close()

    assert len(raw.admissions) == 20
    assert {item.program_id for item in canonical.admissions} == {
        "program:bmstu:09.03.01-02",
        "program:bmstu:09.03.01-12",
    }
    first = canonical.admissions[0]
    current_budget = next(item for item in first.offerings if item.admission_year == 2026 and item.funding_type.value == "budget")
    current_paid = next(item for item in first.offerings if item.admission_year == 2026 and item.funding_type.value == "paid")
    assert current_budget.places == 318
    assert current_paid.places == 230
    assert {item.minimum_score for item in current_budget.exams} == {46}
    assert {item.amount for item in current_paid.tuition} == {529000, 264500}
    assert any(item.admission_year == 2024 and item.passing_scores for item in first.offerings)


def test_detail_admission_source_preserves_direction_scope_and_provenance() -> None:
    adapter = BmstuUniversityAdapter()
    try:
        _, canonical = adapter.parse_sources(fixture_dir=FIXTURES)
    finally:
        adapter.close()
    assert all(offering.scope.value == "direction" for item in canonical.admissions for offering in item.offerings)
    assert all(offering.provenance[0].source_kind == "bmstu_major_detail" for item in canonical.admissions for offering in item.offerings)


def test_order_observations_are_projected_by_direction_and_missing_main_is_a_gap(monkeypatch) -> None:
    budget_quota_body = b"budget-quota-order"
    budget_main_body = b"budget-main-order"
    paid_body = b"paid-order"
    pages = {
        budget_quota_body: (
            "Сведения о зачисленных с 1 сентября 2026 г.\n"
            "1. Перечень зачисленных на направление 09.03.01 имеющих особые права в пределах установленной квоты:\n"
            "§1. Код ЕПГУ: 1; Сумма баллов: 247 (ВИ 247, ИД 0);\n"
            "2. Перечень зачисленных на направление 09.03.01 в пределах отдельной квоты:\n"
            "§2. Код ЕПГУ: 2; Сумма баллов: 261 (ВИ 251, ИД 10);\n"
            "§3. Код ЕПГУ: 3; Без проведения вступительных испытаний;\n"
            "3. Перечень зачисленных на направление 09.03.01 в рамках целевой квоты:\n"
            "§4. Код ЕПГУ: 4; Сумма баллов: 195 (ВИ 195, ИД 0);\n"
            "§5. Код ЕПГУ: 5; Без вступительных испытаний;\n"
            "4. Перечень зачисленных без вступительных испытаний на направление 09.03.01:\n"
            "§6. Код ЕПГУ: 6; Без проведения вступительных испытаний;",
        ),
        budget_main_body: (
            "Сведения о зачисленных с 1 сентября 2026 г.\n"
            "1. Перечень зачисленных на направление 10.03.01 основной этап:\n"
            "§1. Код ЕПГУ: 7; Сумма баллов: 300 (ВИ 290, ИД 10);",
        ),
        paid_body: (
            "Сведения о зачисленных с 1 сентября 2026 г.\n"
            "1. Перечень зачисленных на направление 09.03.01 основной этап:\n"
            "§1. Код ЕПГУ: 8; Сумма баллов: 220 (ВИ 210, ИД 10);",
        ),
    }
    manifest_url = "https://priem.bmstu.ru/lists/orders.json"
    urls = {
        budget_quota_body: "https://priem.bmstu.ru/lists/budget-quota.pdf",
        budget_main_body: "https://priem.bmstu.ru/lists/budget-main.pdf",
        paid_body: "https://priem.bmstu.ru/lists/paid.pdf",
    }
    titles = {
        budget_quota_body: "Высшее образование, бакалавриат, специалитет, бюджетная основа, особая, отдельная и целевая квоты, Москва",
        budget_main_body: "Высшее образование, бакалавриат, специалитет, бюджетная основа, основной этап, Москва",
        paid_body: "Высшее образование, бакалавриат, специалитет, платная основа, основной этап, Москва",
    }

    def snapshot(kind: str, url: str, body: bytes) -> RawSourceSnapshot:
        return RawSourceSnapshot(
            source_kind=kind,
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="application/pdf" if kind.endswith("document") else "application/json",
            captured_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            content_sha256=sha256(body).hexdigest(),
            body=body,
        )

    def fake_pages(body: bytes) -> tuple[str, ...]:
        return pages[body]

    monkeypatch.setattr(admission_orders, "iter_pdf_pages", fake_pages)
    monkeypatch.setattr(adapter_module, "iter_pdf_pages", fake_pages)
    fixture_adapter = BmstuUniversityAdapter()
    try:
        fixture_captured = fixture_adapter.capture(fixture_dir=FIXTURES)
        manifest = json.dumps(
            {
                "list": [
                    {"title": titles[body], "href": url}
                    for body, url in urls.items()
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")
        captured = CapturedSources(
            snapshots=(
                *fixture_captured.snapshots,
                snapshot("bmstu_admission_orders_index", manifest_url, manifest),
                *(snapshot("bmstu_admission_orders_document", urls[body], body) for body in urls),
            )
        )
        raw_programs = fixture_adapter.parse(fixture_captured)[0].programs
        first_records, first_gaps = _parse_order_admissions(captured, raw_programs)
        second_records, second_gaps = _parse_order_admissions(captured, raw_programs)
    finally:
        fixture_adapter.close()

    assert first_records == second_records
    assert first_gaps == second_gaps
    assert all(record.scope == "direction" for record in first_records)
    assert all(
        record.program_code == "09.03.01"
        for record in first_records
        if str(record.source_url) != urls[budget_main_body]
    )
    score_facts = {
        (score.competition_type, score.status, score.score)
        for record in first_records
        for score in record.passing_scores
    }
    assert ("special_quota", "numeric", 247) in score_facts
    assert ("separate_quota", "numeric", 261) in score_facts
    assert ("separate_quota", "bvi", None) in score_facts
    assert ("targeted", "numeric", 195) in score_facts
    assert ("targeted", "bvi", None) in score_facts
    assert ("bvi", "bvi", None) in score_facts
    assert not any(
        record.program_code == "09.03.01"
        and record.funding_type == "budget"
        and score.competition_type == "general"
        for record in first_records
        for score in record.passing_scores
    )
    assert any(
        gap.reason == "direction_section_not_published" and gap.entity_key.startswith("09.03.01:")
        for gap in first_gaps
    )
