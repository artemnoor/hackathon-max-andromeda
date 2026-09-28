from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from andromeda.infrastructure.database.base import Base, create_engine_for_url
from andromeda.infrastructure.database.models import (
    AccountModel,
    IngestRunModel,
    SourceSnapshotModel,
    UniversityModel,
)
from andromeda.infrastructure.repositories.knowledge_manual import (
    SqlAlchemyKnowledgeManualSubmissionRepository,
)
from andromeda.infrastructure.repositories.knowledge_source_repository import (
    SqlAlchemyKnowledgeSourceRepository,
)
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    KnowledgeManualSubmission,
    KnowledgeSourceKind,
    ManualSubmissionKind,
    SourceAllowedRoute,
    SourceIdentity,
    SourceJurisdiction,
    SourceObservation,
    SourceReliabilityTier,
    manual_request_fingerprint,
    manual_submission_id,
)
from andromeda.modules.knowledge.domain.sources import (
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)

ACTOR_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
SOURCE_ID = "source:bmstu-admission"
ISSUER_ID = "issuer:bmstu"
SOURCE_URL = "https://priem.bmstu.ru/admission/rules.pdf"
NOW = datetime(2027, 12, 15, 12, tzinfo=UTC)


def test_manual_submission_audit_persists_exact_revision_history(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'manual.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                AccountModel(
                    account_id=ACTOR_ID,
                    email="manual-operator@example.test",
                    password_hash="test-hash",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                UniversityModel(
                    id=UNIVERSITY_ID,
                    name="Bauman Moscow State Technical University",
                    city="Moscow",
                    official_site="https://bmstu.ru",
                    address="Moscow",
                )
            )
            session.add(
                IngestRunModel(id="ingest:" + "b" * 32, started_at=NOW, status="completed")
            )
            body = b"source snapshot bytes"
            snapshot_hash = hashlib.sha256(body).hexdigest()
            session.add(
                SourceSnapshotModel(
                    content_sha256=snapshot_hash,
                    ingest_run_id="ingest:" + "b" * 32,
                    source_kind="university_admission_rules",
                    requested_url=SOURCE_URL,
                    final_url=SOURCE_URL,
                    status_code=200,
                    content_type="application/pdf",
                    captured_at=NOW,
                    body=body,
                )
            )
            session.flush()

            sources = SqlAlchemyKnowledgeSourceRepository(session)
            sources.register_source_identity(
                SourceIdentity(
                    source_id=SOURCE_ID,
                    issuer_id=ISSUER_ID,
                    jurisdiction=SourceJurisdiction.UNIVERSITY,
                    identity_key="admission-rules",
                    display_name="BMSTU admission rules",
                    created_at=NOW,
                )
            )
            sources.append_approved_registry_revision(
                ApprovedSourceRegistryRevision(
                    source_id=SOURCE_ID,
                    revision=1,
                    source_kind=KnowledgeSourceKind.UNIVERSITY_ADMISSION_RULES,
                    reliability_tier=SourceReliabilityTier.OFFICIAL_UNIVERSITY,
                    adapter_id="bmstu_admission_rules",
                    adapter_version="v1",
                    start_url=SOURCE_URL,
                    allowlist=(
                        SourceAllowedRoute(host="priem.bmstu.ru", path_prefix="/admission"),
                    ),
                    poll_interval_seconds=86_400,
                    freshness_budget_seconds=604_800,
                    enabled=False,
                    approved_by_account_id=ACTOR_ID,
                    approved_at=NOW,
                    approval_reason="Bounded manual source audit test",
                    recorded_at=NOW,
                )
            )
            run_id = "ingest:" + "b" * 32
            capture_key = observation_idempotency_key(
                source_id=SOURCE_ID,
                registry_revision=1,
                ingest_run_id=run_id,
                requested_url=SOURCE_URL,
                snapshot_sha256=snapshot_hash,
            )
            observation = SourceObservation(
                source_observation_id=observation_id_from_idempotency_key(capture_key),
                source_id=SOURCE_ID,
                registry_revision=1,
                idempotency_key=capture_key,
                ingest_run_id=run_id,
                snapshot_sha256=snapshot_hash,
                requested_url=SOURCE_URL,
                final_url=SOURCE_URL,
                status_code=200,
                content_type="application/pdf",
                response_class="success",
                access_mode="manual_upload",
                truncated=False,
                captured_at=NOW,
                observed_at=NOW + timedelta(seconds=1),
            )
            sources.record_observation(observation)

            repository = SqlAlchemyKnowledgeManualSubmissionRepository(session)
            first = _submission(observation.source_observation_id, revision=1, recorded_at=NOW)
            second = _submission(
                observation.source_observation_id,
                revision=2,
                recorded_at=NOW + timedelta(minutes=1),
            )
            repository.append_submission(first)
            repository.append_submission(second)
            session.commit()

            assert repository.get_latest_for_target(first.target_id) == second
            assert repository.get_by_idempotency_key(ACTOR_ID, first.idempotency_key) == first
    finally:
        engine.dispose()


def _submission(
    observation_id: str, *, revision: int, recorded_at: datetime
) -> KnowledgeManualSubmission:
    key = hashlib.sha256(f"manual-key-{revision}".encode()).hexdigest()
    fingerprint = manual_request_fingerprint(
        {"claim": "claim:" + "c" * 64, "revision": revision}
    )
    return KnowledgeManualSubmission(
        submission_id=manual_submission_id(
            actor_account_id=ACTOR_ID,
            idempotency_key=key,
            request_fingerprint=fingerprint,
        ),
        kind=ManualSubmissionKind.CLAIM_CANDIDATE,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        actor_account_id=ACTOR_ID,
        university_id=UNIVERSITY_ID,
        reason=f"Manual claim revision {revision}",
        target_id="claim:" + "c" * 64,
        target_revision=revision,
        target_hash=hashlib.sha256(f"claim-content-{revision}".encode()).hexdigest(),
        source_observation_id=observation_id,
        expires_at=None,
        recorded_at=recorded_at,
    )
