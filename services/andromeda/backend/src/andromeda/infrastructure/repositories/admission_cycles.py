"""Append-only persistence for reviewed admission-cycle revisions."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    AccountModel,
    AdmissionCycleEvidenceModel,
    AdmissionCycleModel,
    KnowledgeSourceAllowlistModel,
    KnowledgeSourceObservationModel,
    KnowledgeSourceRegistryRevisionModel,
    UniversityModel,
)
from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycle,
    AdmissionCycleResolution,
    AdmissionCycleResolutionStatus,
    InclusiveDateWindow,
)
from andromeda.modules.admissions.repository.ports import AdmissionCycleRepository
from andromeda.modules.knowledge.contracts.public import EvidenceLocator, EvidenceRef
from andromeda.modules.knowledge.domain.sources import is_allowed_source_url
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from andromeda.shared.contracts.ids import EducationYear, UniversityId

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class SqlAlchemyAdmissionCycleRepository(AdmissionCycleRepository):
    """Infrastructure adapter; transaction ownership remains with the caller."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve_for_admission(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        as_known_at: datetime | None = None,
    ) -> AdmissionCycleResolution:
        if as_known_at is not None:
            _require_aware(as_known_at, "as_known_at")
        statement = select(AdmissionCycleModel).where(
            AdmissionCycleModel.university_id == university_id,
            AdmissionCycleModel.admission_year == admission_year,
        )
        if as_known_at is not None:
            statement = statement.where(AdmissionCycleModel.recorded_at <= _utc(as_known_at))
        row = self._session.scalar(
            statement.order_by(AdmissionCycleModel.revision.desc()).limit(1)
        )
        if row is None:
            return AdmissionCycleResolution(
                status=AdmissionCycleResolutionStatus.BLOCKED_BY_MISSING_DATA,
                reason="No approved source-backed admission cycle is known for this university and year.",
            )
        return AdmissionCycleResolution(
            status=AdmissionCycleResolutionStatus.RESOLVED,
            cycle=self._to_contract(row),
        )

    def append_approved_revision(self, cycle: AdmissionCycle) -> AdmissionCycle:
        if self._session.get(UniversityModel, cycle.university_id) is None:
            raise NotFoundError("Admission cycle university does not exist")
        if self._session.get(AccountModel, cycle.approved_by_account_id) is None:
            raise NotFoundError("Admission cycle approver account does not exist")

        existing = self._session.get(AdmissionCycleModel, (cycle.cycle_id, cycle.revision))
        if existing is not None:
            stored = self._to_contract(existing)
            if stored != cycle:
                raise ConflictError("Admission cycle revisions are immutable")
            return stored

        latest = self._session.scalar(
            select(AdmissionCycleModel)
            .where(
                AdmissionCycleModel.university_id == cycle.university_id,
                AdmissionCycleModel.admission_year == cycle.admission_year,
            )
            .order_by(AdmissionCycleModel.revision.desc())
            .limit(1)
        )
        expected_revision = latest.revision + 1 if latest is not None else 1
        if cycle.revision != expected_revision:
            raise ConflictError("Admission cycle revisions must be appended consecutively")
        if latest is not None and cycle.recorded_at <= _aware(latest.recorded_at):
            raise ValidationError("new admission cycle revision must have a later recorded_at")

        evidence_rows = []
        for ordinal, evidence in enumerate(cycle.evidence):
            observation = self._session.get(
                KnowledgeSourceObservationModel, evidence.source_observation_id
            )
            if observation is None:
                raise NotFoundError("Admission cycle evidence observation does not exist")
            if (
                observation.source_id != evidence.source_id
                or observation.snapshot_sha256 != evidence.snapshot_sha256
            ):
                raise ValidationError("Admission cycle evidence does not match its captured observation")
            if _utc(cycle.recorded_at) < _utc(_aware(observation.observed_at)):
                raise ValidationError("Admission cycle revision cannot predate its evidence observation")
            if _utc(cycle.approved_at) < _utc(_aware(observation.observed_at)):
                raise ValidationError("Admission cycle approval cannot predate its evidence observation")
            registry = self._session.get(
                KnowledgeSourceRegistryRevisionModel,
                (observation.source_id, observation.registry_revision),
            )
            if registry is None:
                raise NotFoundError("Evidence registry revision does not exist")
            routes = self._session.scalars(
                select(KnowledgeSourceAllowlistModel).where(
                    KnowledgeSourceAllowlistModel.source_id == observation.source_id,
                    KnowledgeSourceAllowlistModel.revision == observation.registry_revision,
                )
            ).all()
            if not any(
                is_allowed_source_url(
                    str(evidence.source_url), host=route.host, path_prefix=route.path_prefix
                )
                for route in routes
            ):
                raise ValidationError("Admission cycle evidence URL is outside its approved source allowlist")
            evidence_rows.append(self._evidence_model(cycle, ordinal, evidence))

        self._session.add(
            AdmissionCycleModel(
                cycle_id=cycle.cycle_id,
                revision=cycle.revision,
                university_id=cycle.university_id,
                admission_year=cycle.admission_year,
                academic_year=cycle.academic_year,
                application_start=(
                    cycle.application_period.start_date if cycle.application_period else None
                ),
                application_end=(
                    cycle.application_period.end_date if cycle.application_period else None
                ),
                enrollment_start=(
                    cycle.enrollment_period.start_date if cycle.enrollment_period else None
                ),
                enrollment_end=(
                    cycle.enrollment_period.end_date if cycle.enrollment_period else None
                ),
                state=cycle.state.value,
                approved_by_account_id=cycle.approved_by_account_id,
                approved_at=_utc(cycle.approved_at),
                approval_reason=cycle.approval_reason,
                recorded_at=_utc(cycle.recorded_at),
            )
        )
        self._session.flush()
        self._session.add_all(evidence_rows)
        self._session.flush()
        return cycle

    def _to_contract(self, row: AdmissionCycleModel) -> AdmissionCycle:
        evidence_rows = self._session.execute(
            select(AdmissionCycleEvidenceModel, KnowledgeSourceObservationModel)
            .join(
                KnowledgeSourceObservationModel,
                AdmissionCycleEvidenceModel.source_observation_id
                == KnowledgeSourceObservationModel.source_observation_id,
            )
            .where(
                AdmissionCycleEvidenceModel.cycle_id == row.cycle_id,
                AdmissionCycleEvidenceModel.cycle_revision == row.revision,
            )
            .order_by(AdmissionCycleEvidenceModel.ordinal)
        ).all()
        evidence = tuple(
            EvidenceRef(
                source_id=observation.source_id,
                source_observation_id=observation.source_observation_id,
                snapshot_sha256=observation.snapshot_sha256,
                source_url=_HTTP_URL_ADAPTER.validate_python(item.source_url),
                locator=EvidenceLocator(
                    page=item.locator_page,
                    table=item.locator_table,
                    row=item.locator_row,
                    section=item.locator_section,
                    field=item.locator_field,
                    record_key=item.locator_record_key,
                ),
                inferred=item.inferred,
            )
            for item, observation in evidence_rows
        )
        if not evidence:
            raise ConflictError("Persisted admission cycle revision has no evidence")
        application_period = (
            InclusiveDateWindow(start_date=row.application_start, end_date=row.application_end)
            if row.application_start is not None and row.application_end is not None
            else None
        )
        enrollment_period = (
            InclusiveDateWindow(start_date=row.enrollment_start, end_date=row.enrollment_end)
            if row.enrollment_start is not None and row.enrollment_end is not None
            else None
        )
        from andromeda.modules.admissions.contracts.admission_cycles import (
            AdmissionCycleState,
        )

        return AdmissionCycle(
            cycle_id=row.cycle_id,
            revision=row.revision,
            university_id=row.university_id,
            admission_year=row.admission_year,
            academic_year=row.academic_year,
            application_period=application_period,
            enrollment_period=enrollment_period,
            state=AdmissionCycleState(row.state),
            evidence=evidence,
            approved_by_account_id=row.approved_by_account_id,
            approved_at=_aware(row.approved_at),
            approval_reason=row.approval_reason,
            recorded_at=_aware(row.recorded_at),
        )

    @staticmethod
    def _evidence_model(cycle: AdmissionCycle, ordinal: int, evidence: EvidenceRef) -> AdmissionCycleEvidenceModel:
        locator = evidence.locator
        return AdmissionCycleEvidenceModel(
            cycle_id=cycle.cycle_id,
            cycle_revision=cycle.revision,
            ordinal=ordinal,
            source_observation_id=evidence.source_observation_id,
            source_url=str(evidence.source_url),
            locator_page=locator.page,
            locator_table=locator.table,
            locator_row=locator.row,
            locator_section=locator.section,
            locator_field=locator.field,
            locator_record_key=locator.record_key,
            inferred=evidence.inferred,
        )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field_name} must be timezone-aware")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _utc(value: datetime) -> datetime:
    _require_aware(value, "datetime")
    return value.astimezone(UTC)


__all__ = ["SqlAlchemyAdmissionCycleRepository"]
