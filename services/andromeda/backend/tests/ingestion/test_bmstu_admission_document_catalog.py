from __future__ import annotations

import json
from pathlib import Path

import pytest

from andromeda.ingestion.universities.bmstu.admission_benefits import (
    BMSTU_ADMISSION_DOCUMENTS_INDEX_URL,
    BmstuAdmissionDocumentCatalog,
    BmstuAdmissionDocumentKind,
)
from andromeda.shared.contracts.errors import ContractError


FIXTURE = Path(__file__).parent / "fixtures" / "bmstu" / "admission_benefits" / "document-index-2026.json"


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_official_index_selects_appendix_53_and_appendix_6_separately() -> None:
    manifest = BmstuAdmissionDocumentCatalog.discover(_payload())

    assert str(manifest.index_url) == BMSTU_ADMISSION_DOCUMENTS_INDEX_URL
    assert manifest.missing_required_kinds == frozenset()
    by_kind = {document.kind: document for document in manifest.selected}
    assert by_kind[BmstuAdmissionDocumentKind.APPENDIX_5_3].index_id == 315
    assert by_kind[BmstuAdmissionDocumentKind.APPENDIX_5_2].index_id == 191
    assert by_kind[BmstuAdmissionDocumentKind.APPENDIX_6].index_id == 192
    assert by_kind[BmstuAdmissionDocumentKind.APPENDIX_5_3].kind is not by_kind[BmstuAdmissionDocumentKind.APPENDIX_6].kind


def test_unknown_future_document_is_discovered_but_not_selected() -> None:
    payload = _payload()
    documents = payload["content"]["document-list"][0]["documents"]  # type: ignore[index]
    documents.append(
        {
            "id": 9999,
            "title": "Приложение 99. Новый документ",
            "url": "https://api.www.bmstu.ru/file/9999/download",
        }
    )

    manifest = BmstuAdmissionDocumentCatalog.discover(payload)

    assert any(document.index_id == 9999 and not document.selected for document in manifest.discovered)
    assert not any(document.index_id == 9999 for document in manifest.selected)


def test_non_official_selected_url_becomes_diagnostic_and_missing_kind() -> None:
    payload = _payload()
    documents = payload["content"]["document-list"][0]["documents"]  # type: ignore[index]
    next(document for document in documents if document["id"] == 315)["url"] = "https://example.com/appendix-5-3.pdf"

    manifest = BmstuAdmissionDocumentCatalog.discover(payload)

    assert BmstuAdmissionDocumentKind.APPENDIX_5_3 in manifest.missing_required_kinds
    assert any(item.startswith("non_official_url:315") for item in manifest.diagnostics)


def test_empty_index_is_rejected() -> None:
    with pytest.raises(ContractError):
        BmstuAdmissionDocumentCatalog.discover({"content": {"document-list": []}})
