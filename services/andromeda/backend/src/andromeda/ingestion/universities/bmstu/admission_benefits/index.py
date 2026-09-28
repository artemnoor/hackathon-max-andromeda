from __future__ import annotations

import json
import logging
from typing import cast

from andromeda.ingestion.contracts.raw import JsonValue
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail

from .source_catalog import BmstuAdmissionDocumentCatalog
from .source_manifest import BmstuAdmissionSourceManifest

logger = logging.getLogger("andromeda.ingestion.bmstu.admission_benefits.index")


def parse_document_index(body: bytes) -> dict[str, JsonValue]:
    """Decode the official document-index JSON without applying legal defaults."""

    logger.debug("bmstu_admission_index_decode_start bytes=%d", len(body))
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("bmstu_admission_index_decode_failed reason=invalid_json")
        raise ContractError(
            ErrorCode.SOURCE_CONTRACT_ERROR,
            "BMSTU admission document index is not valid JSON",
            (ErrorDetail(path="index", message="JSON object expected", type="source_index_json"),),
        ) from exc
    if not isinstance(value, dict):
        raise ContractError(
            ErrorCode.SOURCE_CONTRACT_ERROR,
            "BMSTU admission document index root must be an object",
            (ErrorDetail(path="index", message="object expected", type="source_index_object"),),
        )
    return cast(dict[str, JsonValue], value)


def discover_document_manifest(body: bytes, *, admission_year: int = 2026) -> BmstuAdmissionSourceManifest:
    """Parse and classify one official index response."""

    payload = parse_document_index(body)
    return BmstuAdmissionDocumentCatalog.discover(payload, admission_year=admission_year)


__all__ = ["discover_document_manifest", "parse_document_index"]
