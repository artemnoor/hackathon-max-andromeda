"""Explicit, versioned capture adapters for approved knowledge sources."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from pydantic import HttpUrl

from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.fetch_policy import SourceHostPolicy, SourcePolicyError
from andromeda.ingestion.universities.bmstu.fetch import (
    BMSTU_SOURCE_HOST_POLICY,
    FetchConfig,
    Fetcher,
)
from andromeda.modules.knowledge.contracts.public import ApprovedSourceRegistryRevision
from andromeda.modules.knowledge.domain.sources import is_allowed_source_url

logger = logging.getLogger("andromeda.ingestion.knowledge_source_adapters")


class KnowledgeSourceCaptureError(RuntimeError):
    def __init__(self, failure_code: str, *, status_code: int | None = None) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.status_code = status_code


class KnowledgeSourceCaptureAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def capture(self, registry: ApprovedSourceRegistryRevision) -> RawSourceSnapshot: ...

    def close(self) -> None: ...


class RegisteredOfficialPageCaptureAdapter:
    """Capture one registry-selected page through a fixed official-host adapter."""

    adapter_id = "registered_official_page"
    adapter_version = "v1"

    def __init__(
        self,
        adapter_id: str,
        allowed_hosts: frozenset[str],
        *,
        fetcher: Fetcher | None = None,
    ) -> None:
        self.adapter_id = adapter_id
        self._fetcher = fetcher or Fetcher(
            FetchConfig(
                browser_mode="never",
                user_agent="Andromeda-Source-Discovery/0.1 (+research; contact owner)",
                host_policy=SourceHostPolicy(allowed_hosts=allowed_hosts),
            )
        )

    def capture(self, registry: ApprovedSourceRegistryRevision) -> RawSourceSnapshot:
        if registry.adapter_id != self.adapter_id or registry.adapter_version != self.adapter_version:
            raise KnowledgeSourceCaptureError("adapter_version_mismatch")
        resource = self._fetcher.fetch_http(
            str(registry.start_url),
            url_validator=lambda url: _validate_registry_route(url, registry),
        )
        if not resource.ok or resource.status_code is None or not 200 <= resource.status_code < 300:
            raise KnowledgeSourceCaptureError(
                resource.error_code or "http_status_unavailable",
                status_code=resource.status_code,
            )
        if resource.truncated:
            raise KnowledgeSourceCaptureError("body_limit_exceeded", status_code=resource.status_code)
        captured_at = datetime.fromisoformat(resource.fetched_at)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        digest = sha256(resource.body).hexdigest()
        if digest != resource.content_hash:
            raise KnowledgeSourceCaptureError("snapshot_hash_mismatch", status_code=resource.status_code)
        logger.info(
            "knowledge_source_capture_complete source_id=%s status=%d bytes=%d hash_prefix=%s",
            registry.source_id,
            resource.status_code,
            len(resource.body),
            digest[:12],
        )
        return RawSourceSnapshot(
            source_kind=registry.source_kind.value,
            requested_url=HttpUrl(resource.requested_url),
            final_url=HttpUrl(resource.final_url),
            status_code=resource.status_code,
            content_type=resource.content_type,
            captured_at=captured_at.astimezone(UTC),
            content_sha256=digest,
            body=resource.body,
            response_class="success",
            access_mode=resource.access_mode,
            truncated=False,
        )

    def close(self) -> None:
        self._fetcher.close()


class BmstuPolicyPageCaptureAdapter(RegisteredOfficialPageCaptureAdapter):
    """Capture BMSTU pages with the existing Stage 2 host and redirect allowlist."""

    adapter_id = "bmstu_policy_page"

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        super().__init__(
            self.adapter_id,
            BMSTU_SOURCE_HOST_POLICY.allowed_hosts,
            fetcher=fetcher,
        )


class KnowledgeSourceCaptureAdapterRegistry:
    """Fixed adapter map. Registry data cannot import arbitrary Python code."""

    def __init__(self, factories: Mapping[str, Callable[[], KnowledgeSourceCaptureAdapter]]) -> None:
        self._factories = dict(factories)

    def create(self, adapter_id: str, adapter_version: str) -> KnowledgeSourceCaptureAdapter:
        factory = self._factories.get(adapter_id)
        if factory is None:
            raise KnowledgeSourceCaptureError("adapter_not_registered")
        adapter = factory()
        if adapter.adapter_version != adapter_version:
            adapter.close()
            raise KnowledgeSourceCaptureError("adapter_version_mismatch")
        return adapter


def default_knowledge_source_adapters() -> KnowledgeSourceCaptureAdapterRegistry:
    return KnowledgeSourceCaptureAdapterRegistry(
        {
            BmstuPolicyPageCaptureAdapter.adapter_id: BmstuPolicyPageCaptureAdapter,
            "ministry_documents": lambda: OfficialPolicyPageCaptureAdapter(
                "ministry_documents",
                frozenset({"minobrnauki.gov.ru", "www.minobrnauki.gov.ru"}),
            ),
            "federal_normative_documents": lambda: OfficialPolicyPageCaptureAdapter(
                "federal_normative_documents", frozenset({"publication.pravo.gov.ru"})
            ),
            "bmstu_admission_orders": lambda: OfficialPolicyPageCaptureAdapter(
                "bmstu_admission_orders", frozenset({"priem.bmstu.ru"})
            ),
        }
    )


class OfficialPolicyPageCaptureAdapter(RegisteredOfficialPageCaptureAdapter):
    """Configured official-host adapter with path checks on every redirect hop."""

    def __init__(self, adapter_id: str, allowed_hosts: frozenset[str]) -> None:
        super().__init__(adapter_id, allowed_hosts)


__all__ = [
    "BmstuPolicyPageCaptureAdapter",
    "KnowledgeSourceCaptureAdapter",
    "KnowledgeSourceCaptureAdapterRegistry",
    "KnowledgeSourceCaptureError",
    "OfficialPolicyPageCaptureAdapter",
    "RegisteredOfficialPageCaptureAdapter",
    "default_knowledge_source_adapters",
]


def _validate_registry_route(url: str, registry: ApprovedSourceRegistryRevision) -> None:
    if not any(
        is_allowed_source_url(url, host=route.host, path_prefix=route.path_prefix)
        for route in registry.allowlist
    ):
        raise SourcePolicyError("path_not_allowed", "source URL is outside the approved path allowlist")
