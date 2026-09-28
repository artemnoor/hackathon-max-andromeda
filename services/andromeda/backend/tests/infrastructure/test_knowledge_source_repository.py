from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import HttpUrl, TypeAdapter
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.base import create_engine_for_url
from andromeda.infrastructure.database.models import (
    AccountModel,
    IngestRunModel,
    KnowledgeSourceObservationModel,
    KnowledgeSourcePollAttemptModel,
    SourceSnapshotModel,
)
from andromeda.infrastructure.repositories.knowledge_source_repository import (
    SqlAlchemyKnowledgeSourceRepository,
)
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    EvidenceLocator,
    KnowledgeSourceKind,
    SourceAllowedRoute,
    SourceIdentity,
    SourceJurisdiction,
    SourceObservation,
    SourcePollAttempt,
    SourcePollOutcome,
    SourceReliabilityTier,
)
from andromeda.modules.knowledge.domain.sources import (
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ACCOUNT_ID = "account:" + "a" * 32
SOURCE_ID = "source:ministry-admission"
INGEST_RUN_1 = "ingest:" + "b" * 32
INGEST_RUN_2 = "ingest:" + "e" * 32
BODY = b"official admission rules"
SNAPSHOT_HASH = hashlib.sha256(BODY).hexdigest()


def _identity() -> SourceIdentity:
    return SourceIdentity(
        source_id=SOURCE_ID,
        issuer_id="issuer:minobrnauki",
        jurisdiction=SourceJurisdiction.FEDERAL,
        identity_key="admission-minimum-scores",
        display_name="Minobrnauki admission documents",
        created_at=NOW,
    )


def _revision(*, revision: int = 1, enabled: bool = True) -> ApprovedSourceRegistryRevision:
    return ApprovedSourceRegistryRevision(
        source_id=SOURCE_ID,
        revision=revision,
        source_kind=KnowledgeSourceKind.NORMATIVE_DOCUMENT,
        reliability_tier=SourceReliabilityTier.PRIMARY_NORMATIVE,
        adapter_id="ministry_documents",
        adapter_version="v1",
        start_url="https://official.example/admission/index",
        allowlist=(SourceAllowedRoute(host="official.example", path_prefix="/admission"),),
        poll_interval_seconds=86_400,
        freshness_budget_seconds=604_800,
        enabled=enabled,
        approved_by_account_id=ACCOUNT_ID,
        approved_at=NOW,
        approval_reason=f"Approved registry revision {revision}",
        recorded_at=NOW,
    )


def _observation(
    *, run_id: str, url_path: str, captured_at: datetime, observed_at: datetime
) -> SourceObservation:
    requested = f"https://official.example/admission/{url_path}"
    key = observation_idempotency_key(
        source_id=SOURCE_ID,
        registry_revision=1,
        ingest_run_id=run_id,
        requested_url=requested,
        snapshot_sha256=SNAPSHOT_HASH,
    )
    return SourceObservation(
        source_observation_id=observation_id_from_idempotency_key(key),
        source_id=SOURCE_ID,
        registry_revision=1,
        idempotency_key=key,
        ingest_run_id=run_id,
        snapshot_sha256=SNAPSHOT_HASH,
        requested_url=requested,
        final_url=requested,
        status_code=200,
        content_type="application/pdf",
        response_class="success",
        access_mode="http",
        truncated=False,
        captured_at=captured_at,
        observed_at=observed_at,
    )


def _seed_storage(session: Session) -> None:
    session.add(
        AccountModel(
            account_id=ACCOUNT_ID,
            email="steward@example.test",
            password_hash="test-hash",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()
    for run_id in (INGEST_RUN_1, INGEST_RUN_2):
        session.add(IngestRunModel(id=run_id, started_at=NOW, status="completed"))
    session.flush()
    session.add(
        SourceSnapshotModel(
            content_sha256=SNAPSHOT_HASH,
            ingest_run_id=INGEST_RUN_1,
            source_kind="official_ministry_rules",
            requested_url="https://official.example/admission/index",
            final_url="https://official.example/admission/index",
            status_code=200,
            content_type="application/pdf",
            captured_at=NOW,
            body=BODY,
        )
    )
    session.flush()


def test_registry_revisions_and_duplicate_content_observations_are_append_only() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    from andromeda.infrastructure.database.base import Base

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            _seed_storage(session)
            repository = SqlAlchemyKnowledgeSourceRepository(session)
            identity = _identity()
            repository.register_source_identity(identity)
            assert repository.register_source_identity(identity) == identity

            revision_one = _revision()
            repository.append_approved_registry_revision(revision_one)
            assert repository.append_approved_registry_revision(revision_one) == revision_one
            assert repository.list_pollable_registry_revisions() == (revision_one,)

            first = _observation(
                run_id=INGEST_RUN_1,
                url_path="rules-2027.pdf",
                captured_at=NOW,
                observed_at=NOW + timedelta(seconds=1),
            )
            second = _observation(
                run_id=INGEST_RUN_2,
                url_path="appendix-2027.pdf",
                captured_at=NOW + timedelta(days=1),
                observed_at=NOW + timedelta(days=1, seconds=1),
            )
            assert repository.record_observation(first) == first
            assert repository.record_observation(first) == first
            assert repository.record_observation(second) == second
            assert repository.get_observation(first.source_observation_id) == first
            assert repository.list_observations(SOURCE_ID) == (second, first)
            evidence = repository.resolve_snapshot_evidence(
                source_url=first.requested_url,
                snapshot_sha256=first.snapshot_sha256,
                locator=EvidenceLocator(page=3, table="minimum_scores", row=2),
            )
            assert evidence is not None
            assert evidence.source_id == SOURCE_ID
            assert evidence.source_observation_id == first.source_observation_id
            assert evidence.locator.page == 3
            assert repository.resolve_snapshot_evidence(
                source_url=TypeAdapter(HttpUrl).validate_python(
                    "https://official.example/admission/missing.pdf"
                ),
                snapshot_sha256=first.snapshot_sha256,
                locator=EvidenceLocator(),
            ) is None

            assert session.query(KnowledgeSourceObservationModel).count() == 2
            assert session.query(SourceSnapshotModel).count() == 1

            disabled = _revision(revision=2, enabled=False)
            repository.append_approved_registry_revision(disabled)
            assert repository.get_latest_registry_revision(SOURCE_ID) == disabled
            assert repository.list_pollable_registry_revisions() == ()

            with pytest.raises(ConflictError, match="immutable"):
                repository.append_approved_registry_revision(
                    _revision(revision=2, enabled=True)
                )
            with pytest.raises(ValidationError, match="between 1 and 500"):
                repository.list_observations(SOURCE_ID, limit=501)
    finally:
        engine.dispose()


def test_observation_requires_an_approved_revision_and_both_urls_inside_allowlist() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    from andromeda.infrastructure.database.base import Base

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            _seed_storage(session)
            repository = SqlAlchemyKnowledgeSourceRepository(session)
            repository.register_source_identity(_identity())
            repository.append_approved_registry_revision(_revision())

            observation = _observation(
                run_id=INGEST_RUN_1,
                url_path="rules-2027.pdf",
                captured_at=NOW,
                observed_at=NOW + timedelta(seconds=1),
            ).model_copy(update={"final_url": "https://evil.example/private.pdf"})
            with pytest.raises(ValidationError, match="outside the approved allowlist"):
                repository.record_observation(observation)

            no_revision = _observation(
                run_id=INGEST_RUN_2,
                url_path="rules-2027.pdf",
                captured_at=NOW,
                observed_at=NOW + timedelta(seconds=1),
            ).model_copy(update={"registry_revision": 99})
            with pytest.raises(NotFoundError, match="registry revision does not exist"):
                repository.record_observation(no_revision)
    finally:
        engine.dispose()


def test_poll_attempts_are_append_only_and_failed_polls_preserve_last_good_hash() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    from andromeda.infrastructure.database.base import Base

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            _seed_storage(session)
            repository = SqlAlchemyKnowledgeSourceRepository(session)
            repository.register_source_identity(_identity())
            repository.append_approved_registry_revision(_revision())
            observation = _observation(
                run_id=INGEST_RUN_1,
                url_path="rules-2027.pdf",
                captured_at=NOW,
                observed_at=NOW + timedelta(seconds=1),
            )
            repository.record_observation(observation)
            first = SourcePollAttempt(
                attempt_id="poll-attempt:" + "f" * 32,
                source_id=SOURCE_ID,
                registry_revision=1,
                started_at=NOW + timedelta(seconds=2),
                completed_at=NOW + timedelta(seconds=3),
                outcome=SourcePollOutcome.NEW,
                parser_version="policy_text_lines:v1",
                snapshot_sha256=SNAPSHOT_HASH,
                last_successful_snapshot_sha256=SNAPSHOT_HASH,
                source_observation_id=observation.source_observation_id,
                retry_count=0,
                extracted_candidate_count=1,
            )
            assert repository.record_attempt(first) == first
            assert repository.record_attempt(first) == first

            failed = SourcePollAttempt(
                attempt_id="poll-attempt:" + "1" * 32,
                source_id=SOURCE_ID,
                registry_revision=1,
                started_at=NOW + timedelta(seconds=4),
                completed_at=NOW + timedelta(seconds=5),
                outcome=SourcePollOutcome.UNAVAILABLE,
                parser_version="policy_text_lines:v1",
                previous_snapshot_sha256=SNAPSHOT_HASH,
                last_successful_snapshot_sha256=SNAPSHOT_HASH,
                retry_count=1,
                next_retry_at=NOW + timedelta(minutes=5),
                failure_code="http_503",
                extracted_candidate_count=0,
            )
            repository.record_attempt(failed)
            assert repository.get_latest_attempt(SOURCE_ID) == failed
            assert session.query(KnowledgeSourcePollAttemptModel).count() == 2
    finally:
        engine.dispose()
