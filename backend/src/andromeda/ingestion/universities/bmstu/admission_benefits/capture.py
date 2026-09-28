from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

from pydantic import Field, HttpUrl

from andromeda.ingestion.contracts.raw import RawSourceGap, RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources, source_fetch_gap
from andromeda.ingestion.universities.bmstu.fetch import Fetcher
from andromeda.ingestion.universities.bmstu.pdf import is_pdf
from andromeda.ingestion.universities.bmstu.source_models import FetchedResource
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail

from .index import discover_document_manifest
from .source_catalog import (
    BMSTU_ADMISSION_DOCUMENTS_INDEX_URL,
    BMSTU_OFFICIAL_OLYMPIAD_PROFILE_SOURCES,
    BmstuAdmissionDocumentKind,
    BmstuAdmissionSourceManifest,
)

logger = logging.getLogger("andromeda.ingestion.bmstu.admission_benefits.capture")

FIXTURE_CAPTURED_AT = datetime(2026, 9, 22, tzinfo=UTC)
INDEX_SOURCE_KIND = "bmstu_admission_document_index"


class BmstuAdmissionCaptureReport(ContractModel):
    discovered: int = Field(default=0, strict=True, ge=0)
    fetched: int = Field(default=0, strict=True, ge=0)
    skipped: int = Field(default=0, strict=True, ge=0)
    failed: int = Field(default=0, strict=True, ge=0)
    unresolved: int = Field(default=0, strict=True, ge=0)
    source_hashes: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return (
            self.failed == 0
            and self.unresolved == 0
            and self.discovered == self.fetched
        )


class BmstuAdmissionCaptureResult(ContractModel):
    manifest: BmstuAdmissionSourceManifest
    captured: CapturedSources
    report: BmstuAdmissionCaptureReport


class BmstuAdmissionBenefitsCapture:
    """Capture official BMSTU admission documents through the shared fetch policy."""

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()
        self._owns_fetcher = fetcher is None

    def close(self) -> None:
        if self._owns_fetcher:
            self.fetcher.close()

    def capture(
        self,
        *,
        mode: str = "fixture",
        fixture_dir: Path | None = None,
        admission_year: int = 2026,
    ) -> BmstuAdmissionCaptureResult:
        logger.info(
            "bmstu_admission_capture_start mode=%s admission_year=%d index_url=%s",
            mode,
            admission_year,
            BMSTU_ADMISSION_DOCUMENTS_INDEX_URL,
        )
        if mode == "fixture":
            result = self._capture_fixture(fixture_dir, admission_year)
        elif mode == "live":
            result = self._capture_live(admission_year)
        else:
            raise ContractError(
                ErrorCode.VALIDATION_ERROR,
                "admission benefits capture mode must be fixture or live",
                (
                    ErrorDetail(
                        path="mode",
                        message="unsupported capture mode",
                        type="value_error",
                    ),
                ),
            )
        logger.info(
            "bmstu_admission_capture_complete discovered=%d fetched=%d failed=%d unresolved=%d hashes=%d",
            result.report.discovered,
            result.report.fetched,
            result.report.failed,
            result.report.unresolved,
            len(result.report.source_hashes),
        )
        return result

    def _capture_live(self, admission_year: int) -> BmstuAdmissionCaptureResult:
        resource = self.fetcher.fetch_http(BMSTU_ADMISSION_DOCUMENTS_INDEX_URL)
        if not resource.ok:
            gap = source_fetch_gap(
                INDEX_SOURCE_KIND,
                BMSTU_ADMISSION_DOCUMENTS_INDEX_URL,
                resource.error_code or "source_unavailable",
            )
            manifest = BmstuAdmissionSourceManifest(
                index_url=cast(HttpUrl, BMSTU_ADMISSION_DOCUMENTS_INDEX_URL),
                admission_year=admission_year,
            )
            return self._result(
                manifest, (), (gap,), failed=1, diagnostics=("index_fetch_failed",)
            )
        index_snapshot = self._resource_snapshot(
            INDEX_SOURCE_KIND, BMSTU_ADMISSION_DOCUMENTS_INDEX_URL, resource
        )
        try:
            manifest = discover_document_manifest(
                resource.body, admission_year=admission_year
            )
        except ContractError:
            gap = source_fetch_gap(
                INDEX_SOURCE_KIND,
                BMSTU_ADMISSION_DOCUMENTS_INDEX_URL,
                "index_parse_failed",
            )
            empty = BmstuAdmissionSourceManifest(
                index_url=cast(HttpUrl, BMSTU_ADMISSION_DOCUMENTS_INDEX_URL),
                admission_year=admission_year,
            )
            return self._result(
                empty,
                (index_snapshot,),
                (gap, *_missing_required_gaps(empty)),
                failed=1 + len(empty.missing_required_kinds),
                diagnostics=("index_parse_failed",),
            )
        return self._append_profile_sources(
            self._fetch_selected(manifest, (index_snapshot,))
        )

    def _capture_fixture(
        self, fixture_dir: Path | None, admission_year: int
    ) -> BmstuAdmissionCaptureResult:
        if fixture_dir is None:
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                "BMSTU admission benefits fixture directory is required",
            )
        index_path = fixture_dir / f"document-index-{admission_year}.json"
        if not index_path.exists():
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                "BMSTU admission benefits index fixture is missing",
                (
                    ErrorDetail(
                        path="fixture_dir",
                        message=str(index_path),
                        type="source_fixture",
                    ),
                ),
            )
        index_body = index_path.read_bytes()
        manifest = discover_document_manifest(index_body, admission_year=admission_year)
        index_snapshot = _fixture_snapshot(
            INDEX_SOURCE_KIND, BMSTU_ADMISSION_DOCUMENTS_INDEX_URL, index_body
        )
        snapshots: list[RawSourceSnapshot] = [index_snapshot]
        gaps: list[RawSourceGap] = _missing_required_gaps(manifest)
        diagnostics: list[str] = list(manifest.diagnostics)
        fetched = 0
        for document in manifest.selected:
            candidate = _fixture_document_path(
                fixture_dir, document.index_id, document.kind
            )
            if candidate is None:
                gaps.append(
                    source_fetch_gap(
                        f"bmstu_admission_document:{document.kind.value}",
                        str(document.url),
                        "document_fixture_missing",
                    )
                )
                diagnostics.append(f"fixture_missing:{document.kind.value}")
                continue
            body = candidate.read_bytes()
            if not body:
                gaps.append(
                    source_fetch_gap(
                        f"bmstu_admission_document:{document.kind.value}",
                        str(document.url),
                        "document_fixture_empty",
                    )
                )
                diagnostics.append(f"fixture_empty:{document.kind.value}")
                continue
            snapshots.append(
                _fixture_snapshot(
                    _document_source_kind(document.kind), str(document.url), body
                )
            )
            fetched += 1
        return self._append_profile_sources(
            self._result(
                manifest,
                tuple(snapshots),
                tuple(gaps),
                fetched=fetched,
                diagnostics=tuple(diagnostics),
            ),
            fixture_dir=fixture_dir,
        )

    def _append_profile_sources(
        self,
        result: BmstuAdmissionCaptureResult,
        *,
        fixture_dir: Path | None = None,
    ) -> BmstuAdmissionCaptureResult:
        """Capture official profile pages used to resolve table profile subjects."""

        snapshots = list(result.captured.snapshots)
        gaps = list(result.captured.source_gaps)
        original_gap_count = len(gaps)
        profile_diagnostics: list[str] = []
        for profile_key, profile_url in BMSTU_OFFICIAL_OLYMPIAD_PROFILE_SOURCES:
            if any(
                snapshot.source_kind == f"bmstu_olympiad_profile:{profile_key}"
                for snapshot in snapshots
            ):
                continue
            if fixture_dir is not None:
                candidate = fixture_dir / f"shag-{profile_key}.html.extract.json"
                if candidate.exists():
                    snapshots.append(
                        _fixture_profile_snapshot(candidate, profile_url, profile_key)
                    )
                else:
                    gaps.append(
                        source_fetch_gap(
                            f"bmstu_olympiad_profile:{profile_key}",
                            profile_url,
                            "profile_fixture_missing",
                        )
                    )
                    profile_diagnostics.append(f"profile_fixture_missing:{profile_key}")
                continue
            resource = self.fetcher.fetch_http(profile_url)
            if not resource.ok:
                gaps.append(
                    source_fetch_gap(
                        f"bmstu_olympiad_profile:{profile_key}",
                        profile_url,
                        resource.error_code or "source_unavailable",
                    )
                )
                profile_diagnostics.append(f"profile_fetch_failed:{profile_key}")
                continue
            if not _is_markup(resource):
                gaps.append(
                    source_fetch_gap(
                        f"bmstu_olympiad_profile:{profile_key}",
                        profile_url,
                        "unsupported_document_body",
                    )
                )
                profile_diagnostics.append(f"profile_unsupported_body:{profile_key}")
                continue
            snapshots.append(
                self._resource_snapshot(
                    f"bmstu_olympiad_profile:{profile_key}", profile_url, resource
                )
            )
        report = result.report.model_copy(
            update={
                "failed": result.report.failed + len(gaps) - original_gap_count,
                "diagnostics": (*result.report.diagnostics, *profile_diagnostics),
            }
        )
        return result.model_copy(
            update={
                "captured": CapturedSources(tuple(snapshots), source_gaps=tuple(gaps)),
                "report": report,
            }
        )

    def _fetch_selected(
        self,
        manifest: BmstuAdmissionSourceManifest,
        initial_snapshots: tuple[RawSourceSnapshot, ...],
    ) -> BmstuAdmissionCaptureResult:
        snapshots = list(initial_snapshots)
        gaps: list[RawSourceGap] = _missing_required_gaps(manifest)
        diagnostics = list(manifest.diagnostics)
        fetched = 0
        for document in manifest.selected:
            resource = self.fetcher.fetch_http(str(document.url))
            if not resource.ok:
                reason = resource.error_code or "source_unavailable"
                gaps.append(
                    source_fetch_gap(
                        _document_source_kind(document.kind), str(document.url), reason
                    )
                )
                diagnostics.append(f"fetch_failed:{document.kind.value}:{reason}")
                continue
            if not is_pdf(
                resource.body, resource.content_type, str(document.url)
            ) and not _is_markup(resource):
                gaps.append(
                    source_fetch_gap(
                        _document_source_kind(document.kind),
                        str(document.url),
                        "unsupported_document_body",
                    )
                )
                diagnostics.append(f"unsupported_body:{document.kind.value}")
                continue
            snapshots.append(
                self._resource_snapshot(
                    _document_source_kind(document.kind), str(document.url), resource
                )
            )
            fetched += 1
        return self._result(
            manifest,
            tuple(snapshots),
            tuple(gaps),
            fetched=fetched,
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _resource_snapshot(
        kind: str, requested_url: str, resource: FetchedResource
    ) -> RawSourceSnapshot:
        if not resource.ok or resource.status_code is None:
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                "cannot snapshot an unsuccessful resource",
            )
        digest = sha256(resource.body).hexdigest()
        logger.info(
            "bmstu_admission_document_snapshot kind=%s url=%s status=%d bytes=%d sha256=%s",
            kind,
            requested_url.split("?", 1)[0],
            resource.status_code,
            len(resource.body),
            digest,
        )
        return RawSourceSnapshot(
            source_kind=kind,
            requested_url=cast(HttpUrl, requested_url),
            final_url=cast(HttpUrl, resource.final_url or requested_url),
            status_code=resource.status_code,
            content_type=resource.content_type,
            captured_at=datetime.fromisoformat(resource.fetched_at),
            content_sha256=digest,
            body=resource.body,
            response_class="success",
            access_mode=resource.access_mode,
            truncated=resource.truncated,
        )

    @staticmethod
    def _result(
        manifest: BmstuAdmissionSourceManifest,
        snapshots: tuple[RawSourceSnapshot, ...],
        gaps: tuple[RawSourceGap, ...],
        *,
        fetched: int = 0,
        failed: int | None = None,
        diagnostics: tuple[str, ...] = (),
    ) -> BmstuAdmissionCaptureResult:
        unique_snapshots = _deduplicate_snapshots(snapshots)
        failed_count = len(gaps) if failed is None else failed
        report = BmstuAdmissionCaptureReport(
            discovered=len(manifest.selected),
            fetched=fetched,
            skipped=len(manifest.discovered) - len(manifest.selected),
            failed=failed_count,
            unresolved=len(manifest.missing_required_kinds),
            source_hashes=tuple(
                snapshot.content_sha256 for snapshot in unique_snapshots
            ),
            diagnostics=diagnostics,
        )
        return BmstuAdmissionCaptureResult(
            manifest=manifest,
            captured=CapturedSources(unique_snapshots, source_gaps=gaps),
            report=report,
        )


def _fixture_snapshot(kind: str, requested_url: str, body: bytes) -> RawSourceSnapshot:
    digest = sha256(body).hexdigest()
    return RawSourceSnapshot(
        source_kind=kind,
        requested_url=cast(HttpUrl, requested_url),
        final_url=cast(HttpUrl, requested_url),
        status_code=200,
        content_type="application/pdf" if is_pdf(body) else "application/json",
        captured_at=FIXTURE_CAPTURED_AT,
        content_sha256=digest,
        body=body,
        response_class="success",
        access_mode="fixture",
    )


def _missing_required_gaps(
    manifest: BmstuAdmissionSourceManifest,
) -> list[RawSourceGap]:
    return [
        source_fetch_gap(
            _document_source_kind(kind),
            str(manifest.index_url),
            "required_document_not_discovered",
        )
        for kind in sorted(manifest.missing_required_kinds, key=lambda item: item.value)
    ]


def _fixture_profile_snapshot(
    path: Path, requested_url: str, profile_key: str
) -> RawSourceSnapshot:
    body = path.read_bytes()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    source_url = (
        payload.get("source_url", requested_url)
        if isinstance(payload, dict)
        else requested_url
    )
    source_hash = payload.get("content_sha256") if isinstance(payload, dict) else None
    return RawSourceSnapshot(
        source_kind=f"bmstu_olympiad_profile:{profile_key}",
        requested_url=cast(HttpUrl, source_url),
        final_url=cast(HttpUrl, source_url),
        status_code=200,
        content_type="application/json",
        captured_at=FIXTURE_CAPTURED_AT,
        content_sha256=source_hash
        if isinstance(source_hash, str)
        else sha256(body).hexdigest(),
        body=body,
        response_class="success",
        access_mode="fixture",
    )


def _fixture_document_path(
    fixture_dir: Path,
    index_id: int,
    kind: BmstuAdmissionDocumentKind | None = None,
) -> Path | None:
    candidate: Path | None = None
    for suffix in (".pdf", ".html", ".json", ".bin"):
        candidate = fixture_dir / f"document-{index_id}{suffix}"
        if candidate.exists():
            return candidate
    if kind is not None:
        aliases = {
            BmstuAdmissionDocumentKind.APPENDIX_5_1: "appendix-5-1-extract.json",
            BmstuAdmissionDocumentKind.APPENDIX_5_2: "appendix-5-2-extract.json",
            BmstuAdmissionDocumentKind.APPENDIX_5_3: "appendix-5-3-extract.json",
            BmstuAdmissionDocumentKind.APPENDIX_5_4: "appendix-5-4-extract.json",
            BmstuAdmissionDocumentKind.APPENDIX_5_5: "appendix-5-5-extract.json",
            BmstuAdmissionDocumentKind.APPENDIX_6: "appendix-6-extract.json",
        }
        filename = aliases.get(kind)
        candidate = fixture_dir / filename if filename is not None else None
        if candidate is not None and candidate.exists():
            return candidate
    return None


def _document_source_kind(kind: BmstuAdmissionDocumentKind) -> str:
    return f"bmstu_admission_document:{kind.value}"


def _is_markup(resource: FetchedResource) -> bool:
    content_type = (resource.content_type or "").casefold()
    return "html" in content_type or "json" in content_type


def _deduplicate_snapshots(
    snapshots: tuple[RawSourceSnapshot, ...],
) -> tuple[RawSourceSnapshot, ...]:
    seen: set[tuple[str, str, str]] = set()
    result: list[RawSourceSnapshot] = []
    for snapshot in snapshots:
        key = (
            snapshot.source_kind,
            str(snapshot.requested_url),
            snapshot.content_sha256,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(snapshot)
    return tuple(result)


__all__ = [
    "BmstuAdmissionBenefitsCapture",
    "BmstuAdmissionCaptureReport",
    "BmstuAdmissionCaptureResult",
]
