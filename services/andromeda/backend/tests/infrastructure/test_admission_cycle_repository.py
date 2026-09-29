from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.base import Base, create_engine_for_url
from andromeda.infrastructure.database.models import (
    AccountModel,
    AdmissionCycleEvidenceModel,
    AdmissionCycleModel,
    IngestRunModel,
    SourceSnapshotModel,
    UniversityModel,
)
from andromeda.infrastructure.repositories.admission_cycles import (
    SqlAlchemyAdmissionCycleRepository,
)
from andromeda.infrastructure.repositories.knowledge_source_repository import (
    SqlAlchemyKnowledgeSourceRepository,
)
from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycle,
    AdmissionCycleResolutionStatus,
    AdmissionCycleState,
    InclusiveDateWindow,
    admission_cycle_id,
)
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    EvidenceLocator,
    EvidenceRef,
    KnowledgeSourceKind,
    SourceAllowedRoute,
    SourceIdentity,
    SourceJurisdiction,
    SourceObservation,
    SourceReliabilityTier,
)
from andromeda.modules.knowledge.domain.sources import (
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)
from andromeda.shared.contracts.errors import ConflictError, ValidationError

NOW = datetime(2027, 12, 15, 12, tzinfo=UTC)
ACCOUNT_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
SOURCE_ID = "source:bmstu-admission"
RUN_ID = "ingest:" + "b" * 32
BODY = b"official admission calendar 2028"
SNAPSHOT_HASH = hashlib.sha256(BODY).hexdigest()
SOURCE_URL = "https://admission.bmstu.example/rules-2028.pdf"


def _seed(session: Session) -> EvidenceRef:
    session.add_all(
        [
            AccountModel(
                account_id=ACCOUNT_ID,
                email="cycle-reviewer@example.test",
                password_hash="test-hash",
                created_at=NOW,
                updated_at=NOW,
            ),
            UniversityModel(
                id=UNIVERSITY_ID,
                name="Bauman Moscow State Technical University",
                city="Moscow",
                official_site="https://bmstu.example",
                address="Moscow",
            ),
            IngestRunModel(id=RUN_ID, started_at=NOW, status="completed"),
        ]
    )
    session.flush()
    session.add(
        SourceSnapshotModel(
            content_sha256=SNAPSHOT_HASH,
            ingest_run_id=RUN_ID,
            source_kind="official_university_admission_rules",
            requested_url=SOURCE_URL,
            final_url=SOURCE_URL,
            status_code=200,
            content_type="application/pdf",
            captured_at=NOW,
            body=BODY,
        )
    )
    session.flush()

    sources = SqlAlchemyKnowledgeSourceRepository(session)
    sources.register_source_identity(
        SourceIdentity(
            source_id=SOURCE_ID,
            issuer_id="issuer:bmstu",
            jurisdiction=SourceJurisdiction.UNIVERSITY,
            identity_key="admission-calendar",
            display_name="BMSTU admission calendar",
            created_at=NOW,
        )
    )
    sources.append_approved_registry_revision(
        ApprovedSourceRegistryRevision(
            source_id=SOURCE_ID,
            revision=1,
            source_kind=KnowledgeSourceKind.UNIVERSITY_ADMISSION_RULES,
            reliability_tier=SourceReliabilityTier.OFFICIAL_UNIVERSITY,
            adapter_id="bmstu_admissions",
            adapter_version="v1",
            start_url=SOURCE_URL,
            allowlist=(
                SourceAllowedRoute(
                    host="admission.bmstu.example", path_prefix="/"
                ),
            ),
            poll_interval_seconds=86_400,
            freshness_budget_seconds=604_800,
            enabled=True,
            approved_by_account_id=ACCOUNT_ID,
            approved_at=NOW,
            approval_reason="Official admission source approved for the test.",
            recorded_at=NOW,
        )
    )
    key = observation_idempotency_key(
        source_id=SOURCE_ID,
        registry_revision=1,
        ingest_run_id=RUN_ID,
        requested_url=SOURCE_URL,
        snapshot_sha256=SNAPSHOT_HASH,
    )
    observation = SourceObservation(
        source_observation_id=observation_id_from_idempotency_key(key),
        source_id=SOURCE_ID,
        registry_revision=1,
        idempotency_key=key,
        ingest_run_id=RUN_ID,
        snapshot_sha256=SNAPSHOT_HASH,
        requested_url=SOURCE_URL,
        final_url=SOURCE_URL,
        status_code=200,
        content_type="application/pdf",
        response_class="success",
        access_mode="http",
        truncated=False,
        captured_at=NOW,
        observed_at=NOW + timedelta(seconds=1),
    )
    sources.record_observation(observation)
    return EvidenceRef(
        source_id=SOURCE_ID,
        source_observation_id=observation.source_observation_id,
        snapshot_sha256=SNAPSHOT_HASH,
        source_url=SOURCE_URL,
        locator=EvidenceLocator(page=4, section="Application dates"),
    )


def _cycle(evidence: EvidenceRef, *, revision: int, recorded_at: datetime) -> AdmissionCycle:
    return AdmissionCycle(
        cycle_id=admission_cycle_id(UNIVERSITY_ID, 2028),
        revision=revision,
        university_id=UNIVERSITY_ID,
        admission_year=2028,
        academic_year="2028/2029",
        application_period=InclusiveDateWindow(
            start_date=date(2028, 6, 20), end_date=date(2028, 7, 25)
        ),
        enrollment_period=None,
        state=AdmissionCycleState.PUBLISHED if revision == 1 else AdmissionCycleState.CLOSED,
        evidence=(evidence,),
        approved_by_account_id=ACCOUNT_ID,
        approved_at=recorded_at,
        approval_reason=f"Reviewed admission cycle revision {revision}.",
        recorded_at=recorded_at,
    )


def test_cycle_repository_reads_approved_revisions_as_known_at() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    second_recorded_at = NOW + timedelta(days=10)
    try:
        with Session(engine) as session, session.begin():
            evidence = _seed(session)
            repository = SqlAlchemyAdmissionCycleRepository(session)
            first = _cycle(evidence, revision=1, recorded_at=NOW + timedelta(minutes=1))

            missing = repository.resolve_for_admission(
                UNIVERSITY_ID, 2028, as_known_at=NOW
            )
            assert missing.status is AdmissionCycleResolutionStatus.BLOCKED_BY_MISSING_DATA

            assert repository.append_approved_revision(first) == first
            assert repository.append_approved_revision(first) == first
            at_first = repository.resolve_for_admission(
                UNIVERSITY_ID, 2028, as_known_at=NOW + timedelta(minutes=1)
            )
            assert at_first.status is AdmissionCycleResolutionStatus.RESOLVED
            assert at_first.cycle == first

            second = _cycle(evidence, revision=2, recorded_at=second_recorded_at)
            assert repository.append_approved_revision(second) == second
            earlier_view = repository.resolve_for_admission(
                UNIVERSITY_ID, 2028, as_known_at=NOW + timedelta(days=1)
            )
            current_view = repository.resolve_for_admission(UNIVERSITY_ID, 2028)
            assert earlier_view.cycle == first
            assert current_view.cycle == second
            assert session.query(AdmissionCycleModel).count() == 2
            assert session.query(AdmissionCycleEvidenceModel).count() == 2
            assert len(current_view.cycle.evidence) == 1  # type: ignore[union-attr]
    finally:
        engine.dispose()


def test_cycle_repository_rejects_revision_gaps_and_unallowlisted_evidence() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            evidence = _seed(session)
            repository = SqlAlchemyAdmissionCycleRepository(session)
            with pytest.raises(ConflictError, match="consecutively"):
                repository.append_approved_revision(
                    _cycle(evidence, revision=2, recorded_at=NOW + timedelta(minutes=1))
                )

            reviewed_too_early = AdmissionCycle.model_validate(
                _cycle(evidence, revision=1, recorded_at=NOW + timedelta(minutes=1)).model_dump(
                    mode="python"
                )
                | {"approved_at": NOW}
            )
            with pytest.raises(ValidationError, match="approval cannot predate"):
                repository.append_approved_revision(reviewed_too_early)

            unsafe = evidence.model_copy(
                update={"source_url": "https://other.example/rules.pdf"}
            )
            with pytest.raises(ValidationError, match="outside its approved source allowlist"):
                repository.append_approved_revision(
                    _cycle(unsafe, revision=1, recorded_at=NOW + timedelta(minutes=1))
                )
    finally:
        engine.dispose()
