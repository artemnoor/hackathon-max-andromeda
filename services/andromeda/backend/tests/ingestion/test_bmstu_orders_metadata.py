from __future__ import annotations

from andromeda.ingestion.universities.bmstu.capture import AdmissionOrderManifestEntry
from andromeda.ingestion.universities.bmstu.source_metadata import (
    BmstuOrderCampus,
    BmstuOrderCompetition,
    BmstuOrderDocumentKind,
    BmstuOrderFunding,
    BmstuOrderStage,
    classify_competition_heading,
    classify_order_document,
)


def _entry(title: str) -> AdmissionOrderManifestEntry:
    return AdmissionOrderManifestEntry(title=title, requested_url="https://priem.bmstu.ru/orders/test.pdf")


def test_budget_quota_document_is_bachelor_budget_first_stage() -> None:
    result = classify_order_document(
        _entry("Высшее образование, бакалавриат, специалитет, бюджетная основа, БВИ, особая, отдельная и целевая квоты, Москва"),
        ("Сведения о зачисленных с 1 сентября 2026 г.",),
    )

    assert result.document_kind is BmstuOrderDocumentKind.BACHELOR_SPECIALIST
    assert result.funding is BmstuOrderFunding.BUDGET
    assert result.stage is BmstuOrderStage.FIRST
    assert result.campus is BmstuOrderCampus.MOSCOW
    assert result.admission_year == 2026
    assert result.supported_catalog


def test_paid_document_is_separate_from_budget_route() -> None:
    result = classify_order_document(
        _entry("Высшее образование, бакалавриат, специалитет, платная основа, основной этап, Москва"),
        ("Основа обучения: платная", "Зачисление с 1 сентября 2026 года"),
    )

    assert result.funding is BmstuOrderFunding.PAID
    assert result.stage is BmstuOrderStage.MAIN
    assert result.document_kind is BmstuOrderDocumentKind.BACHELOR_SPECIALIST
    assert result.admission_year == 2026


def test_master_and_postgraduate_documents_are_not_bachelor_projection() -> None:
    master = classify_order_document(_entry("Магистратура, бюджетные места, Москва"), ("2026 год",))
    postgraduate = classify_order_document(_entry("Аспирантура, платная основа, Москва"), ("2026 год",))

    assert master.document_kind is BmstuOrderDocumentKind.MASTER
    assert postgraduate.document_kind is BmstuOrderDocumentKind.POSTGRADUATE
    assert not master.supported_catalog
    assert not postgraduate.supported_catalog


def test_competition_headings_are_explicit_and_unknown_is_not_general() -> None:
    assert classify_competition_heading("В пределах установленной квоты особые права")[0] is BmstuOrderCompetition.SPECIAL_QUOTA
    assert classify_competition_heading("В пределах отдельной квоты")[0] is BmstuOrderCompetition.SEPARATE_QUOTA
    assert classify_competition_heading("Целевое обучение в пределах целевой квоты")[0] is BmstuOrderCompetition.TARGETED
    assert classify_competition_heading("Перечень зачисленных без проведения вступительных испытаний")[0] is BmstuOrderCompetition.BVI
    assert classify_competition_heading("Неизвестная опубликованная секция") == (
        BmstuOrderCompetition.OTHER,
        "competition_heading_unknown",
    )
