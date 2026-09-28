from __future__ import annotations

from decimal import Decimal

from andromeda.ingestion.universities.bmstu.capture import AdmissionOrderManifestEntry
from andromeda.ingestion.universities.bmstu.parser import admission_orders
from andromeda.ingestion.universities.bmstu.source_metadata import (
    BmstuOrderCompetition,
    BmstuOrderDocumentKind,
    BmstuOrderFunding,
    BmstuOrderStage,
    classify_order_document,
)


def _metadata(title: str, pages: tuple[str, ...]):
    entry = AdmissionOrderManifestEntry(title=title, requested_url="https://priem.bmstu.ru/lists/upload/orders/sample.pdf")
    return classify_order_document(entry, pages)


def test_parser_keeps_quota_routes_and_bvi_separate(monkeypatch) -> None:
    pages = (
        """Сведения о зачисленных
Основа обучения: бюджетная
1. Перечень зачисленных на специальность 01.03.02 имеющих особые права в пределах установленной квоты:
§1. Код ЕПГУ: 1; Сумма баллов: 247 (ВИ 247, ИД 0);
2. Перечень зачисленных на специальность 01.03.02 в пределах отдельной квоты:
§2. Код ЕПГУ: 2; Сумма баллов: 270 (ВИ 260, ИД 10);
§3. Код ЕПГУ: 3; Без проведения вступительных испытаний;
3. Перечень зачисленных на специальность 01.03.02 в рамках целевой квоты:
§4. Код ЕПГУ: 4; Сумма баллов: 254 (ВИ 246, ИД 8);
§5. Код ЕПГУ: 5; Сумма баллов: 195 (ВИ 195, ИД 0);
§6. Код ЕПГУ: 6; Без вступительных испытаний;
4. Перечень зачисленных без вступительных испытаний на специальность 01.03.02:
§7. Код ЕПГУ: 7; Без проведения вступительных испытаний;""",
    )
    metadata = _metadata(
        "Высшее образование, бакалавриат, специалитет, бюджетная основа, БВИ, особая, отдельная и целевая квоты, Москва",
        ("Сведения о зачисленных с 1 сентября 2026 г.",),
    )
    monkeypatch.setattr(admission_orders, "iter_pdf_pages", lambda body: pages)

    result = admission_orders.parse_admission_order_document(b"ignored", metadata)

    numeric = {(item.competition_type, item.score) for item in result.observations if item.status == "numeric"}
    bvi = {item.competition_type for item in result.observations if item.status == "bvi"}
    assert numeric == {
        (BmstuOrderCompetition.SPECIAL_QUOTA, Decimal("247")),
        (BmstuOrderCompetition.SEPARATE_QUOTA, Decimal("270")),
        (BmstuOrderCompetition.TARGETED, Decimal("195")),
    }
    assert bvi == {
        BmstuOrderCompetition.SEPARATE_QUOTA,
        BmstuOrderCompetition.TARGETED,
        BmstuOrderCompetition.BVI,
    }
    assert all(item.score is None for item in result.observations if item.status == "bvi")
    assert all(item.page == 1 and item.row >= 1 for item in result.observations)


def test_parser_uses_total_score_not_exam_or_individual_components(monkeypatch) -> None:
    pages = (
        "Сведения о зачисленных с 1 сентября 2026 г.\n"
        "1. Перечень зачисленных на направление 09.03.01 основной этап:\n"
        "§1. Код ЕПГУ: 1; Сумма баллов: 254 (ВИ 234, ИД 20);\n"
        "§2. Код ЕПГУ: 2; Сумма баллов: 280 (ВИ 270, ИД 10);",
    )
    metadata = _metadata(
        "Высшее образование, бакалавриат, специалитет, бюджетная основа, основной этап, Москва",
        pages,
    )
    monkeypatch.setattr(admission_orders, "iter_pdf_pages", lambda body: pages)

    result = admission_orders.parse_admission_order_document(b"ignored", metadata)

    assert len(result.observations) == 1
    assert result.observations[0].score == Decimal("254")
    assert result.observations[0].competition_type is BmstuOrderCompetition.GENERAL
    assert result.observations[0].status == "numeric"


def test_parser_does_not_invent_score_for_missing_or_malformed_row(monkeypatch) -> None:
    pages = (
        "Сведения о зачисленных с 1 сентября 2026 г.\n"
        "1. Перечень зачисленных на направление 01.03.02 основной этап:\n"
        "§1. Код ЕПГУ: 1; Сумма баллов: not-published;",
    )
    metadata = _metadata(
        "Высшее образование, бакалавриат, специалитет, бюджетная основа, основной этап, Москва",
        pages,
    )
    monkeypatch.setattr(admission_orders, "iter_pdf_pages", lambda body: pages)

    result = admission_orders.parse_admission_order_document(b"ignored", metadata)

    assert result.observations == ()
    assert any("row_without_score_or_bvi" in warning for warning in result.warnings)
    assert all(item.score != Decimal("0") for item in result.observations)


def test_unsupported_education_document_is_not_projected(monkeypatch) -> None:
    pages = ("Магистратура, бюджетные места\nСведения о зачисленных с 1 сентября 2026 г.",)
    metadata = _metadata("Магистратура, бюджетные места, Москва", pages)
    monkeypatch.setattr(admission_orders, "iter_pdf_pages", lambda body: pages)

    result = admission_orders.parse_admission_order_document(b"ignored", metadata)

    assert metadata.document_kind is BmstuOrderDocumentKind.MASTER
    assert metadata.funding is BmstuOrderFunding.BUDGET
    assert metadata.stage is BmstuOrderStage.UNKNOWN
    assert result.observations == ()
    assert "unsupported_education_kind:master" in result.warnings
