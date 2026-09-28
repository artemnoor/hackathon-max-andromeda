"""Bounded registry-driven source polling and candidate staging use case."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol
from uuid import uuid4

from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.knowledge_source_adapters import (
    KnowledgeSourceCaptureAdapterRegistry,
    KnowledgeSourceCaptureError,
)
from andromeda.ingestion.ports import SourceCaptureAuditWriter
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    Claim,
    SourceDiscoverySummary,
    SourceObservation,
    SourcePollAttempt,
    SourcePollOutcome,
)
from andromeda.modules.knowledge.domain.sources import (
    is_allowed_source_url,
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)
from andromeda.modules.knowledge.repository.ports import (
    KnowledgeCandidateRepository,
    KnowledgeSourceRepository,
)
from andromeda.modules.knowledge.services.candidate_normalizer import (
    POLICY_CANDIDATE_PARSER_VERSION,
    normalize_policy_claim_candidates,
)

logger = logging.getLogger("andromeda.ingestion.knowledge_source_discovery")
_MAX_SOURCES_PER_RUN = 100


class DiscoveryUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class KnowledgeSourceDiscoveryRunner:
    """Poll approved source registry entries without writing canonical policy."""

    def __init__(
        self,
        *,
        source_repository: KnowledgeSourceRepository,
        candidate_repository: KnowledgeCandidateRepository,
        capture_audit_writer: SourceCaptureAuditWriter,
        adapters: KnowledgeSourceCaptureAdapterRegistry,
        unit_of_work: DiscoveryUnitOfWork,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sources = source_repository
        self._candidates = candidate_repository
        self._audit = capture_audit_writer
        self._adapters = adapters
        self._unit_of_work = unit_of_work
        self._clock = clock or (lambda: datetime.now(UTC))

    def poll_due_sources(self, *, max_sources: int = _MAX_SOURCES_PER_RUN) -> SourceDiscoverySummary:
        if not 1 <= max_sources <= _MAX_SOURCES_PER_RUN:
            raise ValueError(f"max_sources must be between 1 and {_MAX_SOURCES_PER_RUN}")
        now = _aware(self._clock())
        revisions = self._sources.list_pollable_registry_revisions()
        latest_by_source = {
            item.source_id: self._sources.get_latest_attempt(item.source_id)
            for item in revisions
        }
        due = tuple(
            item
            for item in revisions
            if _is_due(item, latest_by_source[item.source_id], now)
        )
        due_to_process = due[:max_sources]
        outcomes = {outcome: 0 for outcome in SourcePollOutcome}
        staged_count = 0
        for registry in due_to_process:
            latest = latest_by_source[registry.source_id]
            outcome, candidate_count = self._poll_one(
                registry,
                latest,
                _aware(self._clock()),
            )
            outcomes[outcome] += 1
            staged_count += candidate_count
        deferred_count = len(revisions) - len(due_to_process)
        summary = SourceDiscoverySummary(
            sources_considered=len(revisions),
            sources_due=len(due_to_process),
            sources_deferred=deferred_count,
            outcomes=outcomes,
            candidates_staged=staged_count,
        )
        logger.info(
            "knowledge_source_discovery_run_complete considered=%d due=%d deferred=%d candidates=%d",
            summary.sources_considered,
            summary.sources_due,
            summary.sources_deferred,
            summary.candidates_staged,
        )
        return summary

    def _poll_one(
        self,
        registry: ApprovedSourceRegistryRevision,
        latest: SourcePollAttempt | None,
        started_at: datetime,
    ) -> tuple[SourcePollOutcome, int]:
        previous_hash = latest.last_successful_snapshot_sha256 if latest is not None else None
        run_id = self._audit.start_run(
            source_profile=f"knowledge:{registry.source_id}",
            source_revision=f"registry:{registry.revision}",
            configuration_version=f"{registry.adapter_id}:{registry.adapter_version}",
            university_id="university:legacy",
            projection_target="knowledge_capture",
        )
        adapter = None
        try:
            if not _url_is_allowlisted(str(registry.start_url), registry):
                raise KnowledgeSourceCaptureError("start_url_outside_allowlist")
            adapter = self._adapters.create(registry.adapter_id, registry.adapter_version)
            snapshot = adapter.capture(registry)
            _validate_capture(registry, snapshot)
        except Exception as exc:  # noqa: BLE001 - normalize failures at the capture adapter boundary.
            self._audit.mark_failed(run_id, exc)
            self._unit_of_work.rollback()
            outcome = (
                SourcePollOutcome.REMOVED
                if isinstance(exc, KnowledgeSourceCaptureError) and exc.status_code == 404
                else SourcePollOutcome.UNAVAILABLE
            )
            attempt = _failed_attempt(
                registry=registry,
                latest=latest,
                started_at=started_at,
                completed_at=_aware(self._clock()),
                outcome=outcome,
                failure_code=_failure_code(exc),
            )
            self._sources.record_attempt(attempt)
            self._unit_of_work.commit()
            logger.warning(
                "knowledge_source_poll_failed source_id=%s outcome=%s failure_code=%s",
                registry.source_id,
                outcome.value,
                attempt.failure_code,
            )
            return outcome, 0

        finally:
            if adapter is not None:
                adapter.close()

        assert snapshot is not None
        completed_at = _aware(self._clock())
        outcome = _snapshot_outcome(previous_hash, snapshot.content_sha256)
        self._audit.record_staged_source_snapshots(run_id, (snapshot,))
        key = observation_idempotency_key(
            source_id=registry.source_id,
            registry_revision=registry.revision,
            ingest_run_id=run_id,
            requested_url=str(snapshot.requested_url),
            snapshot_sha256=snapshot.content_sha256,
        )
        observation = SourceObservation(
            source_observation_id=observation_id_from_idempotency_key(key),
            source_id=registry.source_id,
            registry_revision=registry.revision,
            idempotency_key=key,
            ingest_run_id=run_id,
            snapshot_sha256=snapshot.content_sha256,
            requested_url=snapshot.requested_url,
            final_url=snapshot.final_url,
            status_code=snapshot.status_code,
            content_type=snapshot.content_type,
            response_class=snapshot.response_class,
            access_mode=snapshot.access_mode,
            truncated=snapshot.truncated,
            captured_at=snapshot.captured_at,
            observed_at=completed_at,
        )
        self._sources.record_observation(observation)

        candidates: tuple[Claim, ...] = ()
        reparse_unchanged = (
            outcome is SourcePollOutcome.UNCHANGED
            and latest is not None
            and latest.parser_version != POLICY_CANDIDATE_PARSER_VERSION
        )
        if outcome is not SourcePollOutcome.UNCHANGED or reparse_unchanged:
            try:
                text = _extract_document_text(snapshot)
                identity = self._sources.get_source_identity(registry.source_id)
                if identity is None:
                    raise ValueError("registered source identity is missing")
                candidates = normalize_policy_claim_candidates(
                    text,
                    source=identity,
                    observation=observation,
                    recorded_at=completed_at,
                )
            except ValueError as exc:
                logger.warning(
                    "knowledge_source_extraction_needs_review source_id=%s observation_id=%s error_code=%s",
                    registry.source_id,
                    observation.source_observation_id,
                    _failure_code(exc),
                )
                candidates = ()
            for claim in candidates:
                self._candidates.append_claim_candidate(claim)

        attempt = SourcePollAttempt(
            attempt_id=f"poll-attempt:{uuid4().hex}",
            source_id=registry.source_id,
            registry_revision=registry.revision,
            started_at=started_at,
            completed_at=completed_at,
            outcome=outcome,
            parser_version=POLICY_CANDIDATE_PARSER_VERSION,
            previous_snapshot_sha256=previous_hash,
            snapshot_sha256=snapshot.content_sha256,
            last_successful_snapshot_sha256=snapshot.content_sha256,
            source_observation_id=observation.source_observation_id,
            retry_count=0,
            next_retry_at=None,
            failure_code=None,
            extracted_candidate_count=len(candidates),
        )
        self._sources.record_attempt(attempt)
        self._unit_of_work.commit()
        self._audit.finish_source_capture_run(run_id)
        return outcome, len(candidates)


def _extract_document_text(snapshot: RawSourceSnapshot) -> str:
    content_type = (snapshot.content_type or "").split(";", 1)[0].strip().casefold()
    if content_type in {"application/pdf", "application/x-pdf"} or snapshot.body.startswith(b"%PDF-"):
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(snapshot.body), strict=False)
        if len(reader.pages) > 500:
            raise ValueError("pdf_page_budget_exceeded")
        page_texts: list[str] = []
        total_chars = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if len(page_text) > _MAX_PAGE_TEXT:
                raise ValueError("pdf_page_text_budget_exceeded")
            total_chars += len(page_text)
            if total_chars > _MAX_DOCUMENT_CHARS:
                raise ValueError("pdf_document_text_budget_exceeded")
            page_texts.append(page_text)
        return "\f".join(page_texts)
    if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise ValueError("unsupported_source_mime_type")
    decoded = snapshot.body.decode("utf-8", errors="replace")
    if content_type == "text/plain":
        return decoded[:2_000_000]
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(decoded[:30_000_000], "html.parser")
    for node in soup(("script", "style", "noscript", "svg", "nav", "footer")):
        node.decompose()
    return soup.get_text("\n", strip=True)[:2_000_000]


def _is_due(
    registry: ApprovedSourceRegistryRevision,
    latest: SourcePollAttempt | None,
    now: datetime,
) -> bool:
    if latest is None:
        return True
    if latest.registry_revision != registry.revision:
        return True
    due_at = latest.next_retry_at or latest.completed_at + timedelta(
        seconds=registry.poll_interval_seconds
    )
    return due_at <= now


def _snapshot_outcome(previous_hash: str | None, current_hash: str) -> SourcePollOutcome:
    if previous_hash is None:
        return SourcePollOutcome.NEW
    return SourcePollOutcome.UNCHANGED if previous_hash == current_hash else SourcePollOutcome.CHANGED


def _failed_attempt(
    *,
    registry: ApprovedSourceRegistryRevision,
    latest: SourcePollAttempt | None,
    started_at: datetime,
    completed_at: datetime,
    outcome: SourcePollOutcome,
    failure_code: str,
) -> SourcePollAttempt:
    retry_count = (
        min(latest.retry_count + 1, 10)
        if latest is not None
        and latest.registry_revision == registry.revision
        and latest.outcome in {SourcePollOutcome.UNAVAILABLE, SourcePollOutcome.REMOVED}
        else 1
    )
    retry_delay = min(registry.poll_interval_seconds * (2 ** min(retry_count - 1, 10)), 86_400)
    last_successful_hash = latest.last_successful_snapshot_sha256 if latest is not None else None
    return SourcePollAttempt(
        attempt_id=f"poll-attempt:{uuid4().hex}",
        source_id=registry.source_id,
        registry_revision=registry.revision,
        started_at=started_at,
        completed_at=completed_at,
        outcome=outcome,
        parser_version=latest.parser_version if latest is not None else "unparsed",
        previous_snapshot_sha256=last_successful_hash,
        snapshot_sha256=None,
        last_successful_snapshot_sha256=last_successful_hash,
        source_observation_id=None,
        retry_count=retry_count,
        next_retry_at=completed_at + timedelta(seconds=retry_delay),
        failure_code=failure_code,
        extracted_candidate_count=0,
    )


def _validate_capture(
    registry: ApprovedSourceRegistryRevision,
    snapshot: RawSourceSnapshot,
) -> None:
    if not all(
        _url_is_allowlisted(str(url), registry)
        for url in (snapshot.requested_url, snapshot.final_url)
    ):
        raise KnowledgeSourceCaptureError("capture_url_outside_allowlist", status_code=snapshot.status_code)
    if snapshot.status_code < 200 or snapshot.status_code >= 300:
        raise KnowledgeSourceCaptureError("unexpected_http_status", status_code=snapshot.status_code)
    if snapshot.truncated:
        raise KnowledgeSourceCaptureError("body_limit_exceeded", status_code=snapshot.status_code)
    if sha256(snapshot.body).hexdigest() != snapshot.content_sha256:
        raise KnowledgeSourceCaptureError("snapshot_hash_mismatch", status_code=snapshot.status_code)


def _url_is_allowlisted(url: str, registry: ApprovedSourceRegistryRevision) -> bool:
    return any(
        is_allowed_source_url(url, host=route.host, path_prefix=route.path_prefix)
        for route in registry.allowlist
    )


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, KnowledgeSourceCaptureError):
        return exc.failure_code[:64]
    code = type(exc).__name__.casefold()
    return "capture_failed" if not code or not code[0].isalpha() else code[:64]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("discovery clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


_MAX_PAGE_TEXT = 100_000
_MAX_DOCUMENT_CHARS = 2_000_000


__all__ = ["KnowledgeSourceDiscoveryRunner"]
