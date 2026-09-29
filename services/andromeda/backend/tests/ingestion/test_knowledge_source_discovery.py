from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.knowledge_source_adapters import (
    KnowledgeSourceCaptureAdapterRegistry,
    KnowledgeSourceCaptureError,
)
from andromeda.ingestion.knowledge_source_discovery import (
    KnowledgeSourceDiscoveryRunner,
)
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    KnowledgeSourceKind,
    SourceAllowedRoute,
    SourceIdentity,
    SourceJurisdiction,
    SourceObservation,
    SourcePollAttempt,
    SourcePollOutcome,
    SourceReliabilityTier,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
SOURCE_ID = "source:bmstu-admission"
URL = "https://priem.bmstu.ru/admission/rules.html"
PROPOSAL = "В проекте новых правил изменится минимальный балл ЕГЭ для поступления в университет."
CHANGED = "В проекте новых правил изменится минимальный балл ЕГЭ для направления подготовки."


class _SourceRepository:
    def __init__(self, registry: ApprovedSourceRegistryRevision) -> None:
        self.registry = registry
        self.identity = SourceIdentity(
            source_id=SOURCE_ID,
            issuer_id="issuer:bmstu",
            jurisdiction=SourceJurisdiction.UNIVERSITY,
            identity_key="admission-rules",
            display_name="BMSTU admission rules",
            created_at=NOW,
        )
        self.attempts: dict[str, SourcePollAttempt] = {}
        self.observations: dict[str, SourceObservation] = {}

    def list_pollable_registry_revisions(self) -> tuple[ApprovedSourceRegistryRevision, ...]:
        return (self.registry,)

    def get_latest_attempt(self, source_id: str) -> SourcePollAttempt | None:
        return self.attempts.get(source_id)

    def get_source_identity(self, source_id: str) -> SourceIdentity | None:
        return self.identity if source_id == SOURCE_ID else None

    def record_observation(self, observation: SourceObservation) -> SourceObservation:
        self.observations[observation.source_observation_id] = observation
        return observation

    def get_observation(self, observation_id: str) -> SourceObservation | None:
        return self.observations.get(observation_id)

    def record_attempt(self, attempt: SourcePollAttempt) -> SourcePollAttempt:
        self.attempts[attempt.source_id] = attempt
        return attempt


class _CandidateRepository:
    def __init__(self) -> None:
        self.claims = []

    def append_claim_candidate(self, claim):
        self.claims.append(claim)
        return claim


class _AuditWriter:
    def __init__(self) -> None:
        self.next_run = 0
        self.snapshots = []
        self.failed: list[tuple[str, Exception]] = []
        self.completed: list[str] = []

    def start_run(self, **kwargs) -> str:
        del kwargs
        self.next_run += 1
        return f"ingest:{self.next_run:032x}"

    def record_staged_source_snapshots(self, run_id: str, snapshots) -> None:
        self.snapshots.extend((run_id, item) for item in snapshots)

    def finish_source_capture_run(self, run_id: str) -> None:
        self.completed.append(run_id)

    def mark_failed(self, run_id: str, error: Exception) -> None:
        self.failed.append((run_id, error))


class _UnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _CaptureAdapter:
    adapter_id = "fake_policy_adapter"
    adapter_version = "v1"

    def __init__(self, results: list[bytes | Exception], current_time: Callable[[], datetime]) -> None:
        self.results = results
        self.current_time = current_time

    def capture(self, registry: ApprovedSourceRegistryRevision) -> RawSourceSnapshot:
        assert registry.source_id == SOURCE_ID
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return RawSourceSnapshot(
            source_kind=registry.source_kind.value,
            requested_url=URL,
            final_url=URL,
            status_code=200,
            content_type="text/plain",
            captured_at=self.current_time(),
            content_sha256=sha256(result).hexdigest(),
            body=result,
            response_class="success",
            access_mode="http",
        )

    def close(self) -> None:
        return None


def _registry() -> ApprovedSourceRegistryRevision:
    return ApprovedSourceRegistryRevision(
        source_id=SOURCE_ID,
        revision=1,
        source_kind=KnowledgeSourceKind.UNIVERSITY_ADMISSION_RULES,
        reliability_tier=SourceReliabilityTier.OFFICIAL_UNIVERSITY,
        adapter_id="fake_policy_adapter",
        adapter_version="v1",
        start_url=URL,
        allowlist=(SourceAllowedRoute(host="priem.bmstu.ru", path_prefix="/admission"),),
        poll_interval_seconds=300,
        freshness_budget_seconds=3600,
        enabled=True,
        approved_by_account_id="account:" + "a" * 32,
        approved_at=NOW,
        approval_reason="Approved in a deterministic discovery fixture",
        recorded_at=NOW,
    )


def _runner(results: list[bytes | Exception], clock: list[datetime]):
    source = _SourceRepository(_registry())
    candidates = _CandidateRepository()
    audit = _AuditWriter()
    unit_of_work = _UnitOfWork()
    adapters = KnowledgeSourceCaptureAdapterRegistry(
        {"fake_policy_adapter": lambda: _CaptureAdapter(results, lambda: clock[0])}
    )
    runner = KnowledgeSourceDiscoveryRunner(
        source_repository=source,
        candidate_repository=candidates,
        capture_audit_writer=audit,
        adapters=adapters,
        unit_of_work=unit_of_work,
        clock=lambda: clock[0],
    )
    return runner, source, candidates, audit, unit_of_work


def test_polling_is_idempotent_by_content_hash_and_never_projects_candidates() -> None:
    clock = [NOW]
    runner, source, candidates, audit, unit_of_work = _runner(
        [PROPOSAL.encode(), PROPOSAL.encode(), CHANGED.encode()], clock
    )

    first = runner.poll_due_sources()
    assert first.outcomes[SourcePollOutcome.NEW] == 1
    assert first.candidates_staged == 1
    assert len(candidates.claims) == 1

    clock[0] += timedelta(seconds=299)
    deferred = runner.poll_due_sources()
    assert deferred.sources_due == 0
    assert deferred.sources_deferred == 1

    clock[0] += timedelta(seconds=1)
    unchanged = runner.poll_due_sources()
    assert unchanged.outcomes[SourcePollOutcome.UNCHANGED] == 1
    assert unchanged.candidates_staged == 0
    assert len(candidates.claims) == 1

    clock[0] += timedelta(seconds=300)
    changed = runner.poll_due_sources()
    assert changed.outcomes[SourcePollOutcome.CHANGED] == 1
    assert changed.candidates_staged == 1
    assert len(source.observations) == 3
    assert len(audit.snapshots) == 3
    assert len(audit.completed) == 3
    assert unit_of_work.commits == 3
    assert unit_of_work.rollbacks == 0


def test_missing_adapter_is_fail_closed_and_backs_off_without_claiming_source_removed() -> None:
    clock = [NOW]
    runner, source, candidates, audit, unit_of_work = _runner(
        [KnowledgeSourceCaptureError("http_not_found", status_code=404)], clock
    )

    first = runner.poll_due_sources()
    attempt = source.attempts[SOURCE_ID]
    assert first.outcomes[SourcePollOutcome.REMOVED] == 1
    assert attempt.outcome is SourcePollOutcome.REMOVED
    assert attempt.next_retry_at == NOW + timedelta(seconds=300)
    assert attempt.last_successful_snapshot_sha256 is None
    assert candidates.claims == []
    assert source.observations == {}
    assert audit.failed and not audit.snapshots
    assert unit_of_work.rollbacks == 1

    clock[0] += timedelta(seconds=299)
    deferred = runner.poll_due_sources()
    assert deferred.sources_due == 0
    assert len(audit.failed) == 1


def test_capture_redirect_outside_registry_path_is_not_persisted() -> None:
    clock = [NOW]
    runner, source, candidates, audit, unit_of_work = _runner(
        [b"An HTTP adapter should reject this redirect before capture."], clock
    )
    original = _CaptureAdapter.capture

    def bad_redirect(self, registry):
        captured = original(self, registry)
        return captured.model_copy(update={"final_url": "https://priem.bmstu.ru/private/rules.pdf"})

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_CaptureAdapter, "capture", bad_redirect)
    try:
        summary = runner.poll_due_sources()
    finally:
        monkeypatch.undo()

    attempt = source.attempts[SOURCE_ID]
    assert summary.outcomes[SourcePollOutcome.UNAVAILABLE] == 1
    assert attempt.failure_code == "capture_url_outside_allowlist"
    assert source.observations == {}
    assert audit.snapshots == []
    assert candidates.claims == []
    assert unit_of_work.rollbacks == 1


def test_repeated_poll_failures_use_a_capped_persistent_backoff() -> None:
    clock = [NOW]
    failure = KnowledgeSourceCaptureError("http_503", status_code=503)
    runner, source, _, _, _ = _runner([failure, failure, failure], clock)

    runner.poll_due_sources()
    first = source.attempts[SOURCE_ID]
    assert first.retry_count == 1
    assert first.next_retry_at == NOW + timedelta(seconds=300)

    clock[0] = first.next_retry_at
    runner.poll_due_sources()
    second = source.attempts[SOURCE_ID]
    assert second.retry_count == 2
    assert second.next_retry_at == clock[0] + timedelta(seconds=600)

    clock[0] = second.next_retry_at
    runner.poll_due_sources()
    third = source.attempts[SOURCE_ID]
    assert third.retry_count == 3
    assert third.next_retry_at == clock[0] + timedelta(seconds=1200)


def test_unchanged_snapshot_is_reparsed_after_extractor_version_changes() -> None:
    clock = [NOW]
    runner, source, candidates, _, _ = _runner(
        [PROPOSAL.encode(), PROPOSAL.encode()], clock
    )
    runner.poll_due_sources()
    source.attempts[SOURCE_ID] = source.attempts[SOURCE_ID].model_copy(
        update={"parser_version": "previous_parser:v0"}
    )

    clock[0] += timedelta(seconds=300)
    outcome = runner.poll_due_sources()

    assert outcome.outcomes[SourcePollOutcome.UNCHANGED] == 1
    assert outcome.candidates_staged == 1
    assert len(candidates.claims) == 2
