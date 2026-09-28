from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import cast

from pydantic import HttpUrl

from andromeda.ingestion.contracts.raw import JsonValue
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail

from .source_manifest import (
    BmstuAdmissionDocumentIndexItem,
    BmstuAdmissionDocumentKind,
    BmstuAdmissionDocumentSpec,
    BmstuAdmissionSourceManifest,
)

logger = logging.getLogger("andromeda.ingestion.bmstu.admission_benefits.source_catalog")

BMSTU_ADMISSION_DOCUMENTS_INDEX_URL = "https://api.www.bmstu.ru/page/admission-committee-documents"
BMSTU_OFFICIAL_HOSTS = frozenset({"api.www.bmstu.ru", "bmstu.ru", "www.bmstu.ru"})
BMSTU_OFFICIAL_OLYMPIAD_PROFILE_SOURCES = (
    ("engineering", "https://olymp.bmstu.ru/ru/engeneering-olymp"),
    ("programming", "https://olymp.bmstu.ru/ru/programming-olymp"),
)

_APPENDIX_PATTERNS: tuple[tuple[str, BmstuAdmissionDocumentKind], ...] = (
    ("5.1", BmstuAdmissionDocumentKind.APPENDIX_5_1),
    ("5.2", BmstuAdmissionDocumentKind.APPENDIX_5_2),
    ("5.3", BmstuAdmissionDocumentKind.APPENDIX_5_3),
    ("5.4", BmstuAdmissionDocumentKind.APPENDIX_5_4),
    ("5.5", BmstuAdmissionDocumentKind.APPENDIX_5_5),
    ("8.1", BmstuAdmissionDocumentKind.APPENDIX_8_1),
    ("8.3", BmstuAdmissionDocumentKind.APPENDIX_8_3),
    ("5", BmstuAdmissionDocumentKind.APPENDIX_5),
    ("6", BmstuAdmissionDocumentKind.APPENDIX_6),
    ("7", BmstuAdmissionDocumentKind.APPENDIX_7),
)


class BmstuAdmissionDocumentCatalog:
    """Discover and classify BMSTU admission documents without legal fallbacks."""

    @classmethod
    def discover(
        cls,
        payload: Mapping[str, JsonValue],
        *,
        index_url: str = BMSTU_ADMISSION_DOCUMENTS_INDEX_URL,
        admission_year: int = 2026,
    ) -> BmstuAdmissionSourceManifest:
        logger.info(
            "bmstu_admission_document_discovery_start index_url=%s admission_year=%d",
            index_url,
            admission_year,
        )
        entries = tuple(cls._extract_items(payload))
        discovered: list[BmstuAdmissionDocumentSpec] = []
        diagnostics: list[str] = []
        by_kind: dict[BmstuAdmissionDocumentKind, BmstuAdmissionDocumentSpec] = {}

        for entry in entries:
            kind, appendix_number = cls._classify(entry.title)
            selected = kind is not BmstuAdmissionDocumentKind.OTHER
            if selected and not cls._is_official_url(entry.url):
                diagnostics.append(f"non_official_url:{entry.index_id}:{entry.url}")
                selected = False
                kind = BmstuAdmissionDocumentKind.OTHER
            spec = BmstuAdmissionDocumentSpec(
                index_id=entry.index_id,
                title=entry.title,
                url=cast(HttpUrl, entry.url),
                admission_year=admission_year,
                kind=kind,
                appendix_number=appendix_number,
                selected=selected,
            )
            if selected:
                previous = by_kind.get(kind)
                if previous is not None:
                    diagnostics.append(f"duplicate_document_kind:{kind.value}:{previous.index_id}:{entry.index_id}")
                    selected = False
                    spec = spec.model_copy(update={"selected": False})
                else:
                    by_kind[kind] = spec
            discovered.append(spec)

        selected_documents = tuple(document for document in discovered if document.selected)
        manifest = BmstuAdmissionSourceManifest(
            index_url=cast(HttpUrl, index_url),
            admission_year=admission_year,
            discovered=tuple(discovered),
            selected=selected_documents,
            diagnostics=tuple(diagnostics),
        )
        if manifest.missing_required_kinds:
            diagnostics.extend(f"missing_document_kind:{kind.value}" for kind in sorted(manifest.missing_required_kinds, key=lambda item: item.value))
            manifest = manifest.model_copy(update={"diagnostics": tuple(diagnostics)})
        logger.info(
            "bmstu_admission_document_discovery_complete discovered=%d selected=%d missing=%d diagnostics=%d",
            len(manifest.discovered),
            len(manifest.selected),
            len(manifest.missing_required_kinds),
            len(manifest.diagnostics),
        )
        return manifest

    @staticmethod
    def _extract_items(payload: Mapping[str, JsonValue]) -> tuple[BmstuAdmissionDocumentIndexItem, ...]:
        content = _as_mapping(payload.get("content"))
        groups = _as_list(content.get("document-list"))
        if not groups:
            groups = _as_list(payload.get("document-list"))
        items: list[BmstuAdmissionDocumentIndexItem] = []
        for group_index, group_value in enumerate(groups, start=1):
            group = _as_mapping(group_value)
            documents = _as_list(group.get("documents"))
            for document_index, document_value in enumerate(documents, start=1):
                document = _as_mapping(document_value)
                raw_id = document.get("id")
                title = _as_text(document.get("title"))
                url = _as_text(document.get("url"))
                if not isinstance(raw_id, int) or not title or not url:
                    raise ContractError(
                        ErrorCode.SOURCE_CONTRACT_ERROR,
                        "BMSTU admission document index item is incomplete",
                        (
                            ErrorDetail(
                                path=f"content.document-list[{group_index}].documents[{document_index}]",
                                message="id, title and url are required",
                                type="source_index_item",
                            ),
                        ),
                    )
                items.append(BmstuAdmissionDocumentIndexItem(index_id=raw_id, title=title, url=url))
        if not items:
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                "BMSTU admission document index contains no documents",
                (ErrorDetail(path="content.document-list", message="document list is empty", type="source_index_empty"),),
            )
        return tuple(items)

    @staticmethod
    def _classify(title: str) -> tuple[BmstuAdmissionDocumentKind, str | None]:
        normalized = re.sub(r"\s+", " ", title.casefold().replace("ё", "е")).strip()
        if normalized.startswith("правила приема") or normalized.startswith("правила приeма"):
            if "2026" in normalized:
                return BmstuAdmissionDocumentKind.RULES, None
            return BmstuAdmissionDocumentKind.OTHER, None
        for appendix_number, kind in _APPENDIX_PATTERNS:
            pattern = rf"приложение\s+{re.escape(appendix_number)}(?:\D|$)"
            if re.search(pattern, normalized):
                return kind, appendix_number
        return BmstuAdmissionDocumentKind.OTHER, None

    @staticmethod
    def _is_official_url(url: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in BMSTU_OFFICIAL_HOSTS


def _as_mapping(value: JsonValue | object) -> Mapping[str, JsonValue]:
    return cast(Mapping[str, JsonValue], value) if isinstance(value, Mapping) else {}


def _as_list(value: JsonValue | object) -> list[JsonValue]:
    return list(value) if isinstance(value, list) else []


def _as_text(value: JsonValue | object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "BMSTU_ADMISSION_DOCUMENTS_INDEX_URL",
    "BMSTU_OFFICIAL_HOSTS",
    "BMSTU_OFFICIAL_OLYMPIAD_PROFILE_SOURCES",
    "BmstuAdmissionDocumentCatalog",
    "BmstuAdmissionDocumentKind",
    "BmstuAdmissionDocumentSpec",
    "BmstuAdmissionSourceManifest",
]
