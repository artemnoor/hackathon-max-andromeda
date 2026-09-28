from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, TypeVar, cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from andromeda.modules.admissions.contracts.offering_revisions import (
    AdmissionOfferingRevision,
    admission_offering_domain_rule_id,
    admission_offering_revision_hash,
)
from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    AdmissionOffering,
    AdmissionProvenance,
    AdmissionScope,
    ExamRequirement,
    FundingType,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
    ProgramAdmissions,
    Quota,
    QuotaType,
    StudyForm,
    TuitionCost,
)
from andromeda.modules.admissions.repository.ports import (
    AdmissionOfferingRevisionReader,
    AdmissionRepository,
)
from andromeda.shared.contracts.ids import ProgramId, canonical_program_id

from ..database.models import (
    AdmissionExamRequirementModel,
    AdmissionOfferingModel,
    AdmissionOfferingRevisionModel,
    AdmissionPassingScoreModel,
    AdmissionQuotaModel,
    AdmissionTuitionModel,
)

logger = logging.getLogger("andromeda.infrastructure.repositories.admissions")
_Enum = TypeVar("_Enum", bound=StrEnum)


class SqlAlchemyAdmissionRepository(AdmissionRepository, AdmissionOfferingRevisionReader):
    """Infrastructure adapter for the public admissions repository port."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_program(self, program_id: ProgramId) -> ProgramAdmissions:
        resolved_program_id = canonical_program_id(program_id)
        offerings = self._session.execute(
            select(AdmissionOfferingModel)
            .where(AdmissionOfferingModel.program_id == resolved_program_id)
            .order_by(AdmissionOfferingModel.admission_year.desc(), AdmissionOfferingModel.id)
        ).scalars().all()
        if not offerings:
            logger.warning("admissions_read_empty program_id=%s", program_id)
            return ProgramAdmissions(program_id=resolved_program_id)

        offering_ids = tuple(item.id for item in offerings)
        exams = self._by_offering(AdmissionExamRequirementModel, offering_ids)
        quotas = self._by_offering(AdmissionQuotaModel, offering_ids)
        passing_scores = self._by_offering(AdmissionPassingScoreModel, offering_ids)
        tuition = self._by_offering(AdmissionTuitionModel, offering_ids)
        result = ProgramAdmissions(
            program_id=resolved_program_id,
            offerings=tuple(
                self._offering_contract(
                    model,
                    exams.get(model.id, ()),
                    quotas.get(model.id, ()),
                    passing_scores.get(model.id, ()),
                    tuition.get(model.id, ()),
                )
                for model in offerings
            ),
        )
        logger.debug("admissions_read_complete program_id=%s offerings=%d", program_id, len(result.offerings))
        return result

    def get_for_programs(self, program_ids: tuple[ProgramId, ...]) -> tuple[ProgramAdmissions, ...]:
        """Read all candidate offerings with bounded child queries.

        Decision suggestions read the whole catalog. Keeping this batch path
        in the admissions adapter avoids one offering query per candidate
        while leaving the module-facing port source-backed and typed.
        """

        resolved_ids = tuple(dict.fromkeys(canonical_program_id(item) for item in program_ids))
        if not resolved_ids:
            return ()
        offerings = self._session.execute(
            select(AdmissionOfferingModel)
            .where(AdmissionOfferingModel.program_id.in_(resolved_ids))
            .order_by(AdmissionOfferingModel.program_id, AdmissionOfferingModel.admission_year.desc(), AdmissionOfferingModel.id)
        ).scalars().all()
        by_program: dict[str, list[AdmissionOfferingModel]] = {program_id: [] for program_id in resolved_ids}
        for offering in offerings:
            by_program.setdefault(offering.program_id, []).append(offering)
        offering_ids = tuple(item.id for item in offerings)
        exams = self._by_offering(AdmissionExamRequirementModel, offering_ids) if offering_ids else {}
        quotas = self._by_offering(AdmissionQuotaModel, offering_ids) if offering_ids else {}
        passing_scores = self._by_offering(AdmissionPassingScoreModel, offering_ids) if offering_ids else {}
        tuition = self._by_offering(AdmissionTuitionModel, offering_ids) if offering_ids else {}
        return tuple(
            ProgramAdmissions(
                program_id=program_id,
                offerings=tuple(
                    self._offering_contract(
                        model,
                        exams.get(model.id, ()),
                        quotas.get(model.id, ()),
                        passing_scores.get(model.id, ()),
                        tuition.get(model.id, ()),
                    )
                    for model in by_program[program_id]
                ),
            )
            for program_id in resolved_ids
        )

    def save(self, admissions: ProgramAdmissions) -> None:
        self.sync((admissions,))

    def sync(self, admissions: Iterable[ProgramAdmissions]) -> None:
        """Synchronize supplied program envelopes inside the caller transaction."""
        for envelope in admissions:
            self._sync_envelope(envelope)

    def _sync_envelope(self, envelope: ProgramAdmissions) -> None:
        expected_ids = {offering.id for offering in envelope.offerings}
        current_ids = set(
            self._session.scalars(
                select(AdmissionOfferingModel.id).where(AdmissionOfferingModel.program_id == envelope.program_id)
            ).all()
        )
        stale_ids = current_ids - expected_ids
        if stale_ids:
            self._delete_children(stale_ids)
            self._session.execute(delete(AdmissionOfferingModel).where(AdmissionOfferingModel.id.in_(stale_ids)))
            logger.warning("admissions_remove_stale program_id=%s count=%d", envelope.program_id, len(stale_ids))

        for offering in envelope.offerings:
            if offering.program_id != envelope.program_id:
                raise ValueError("admission offering program identity mismatch")
            self._upsert_offering(offering)
        # Models intentionally do not declare ORM relationships. Flush parent
        # rows before child inserts so FK ordering is identical on SQLite and
        # PostgreSQL.
        self._session.flush()
        for offering in envelope.offerings:
            self._sync_children(offering)
            self._append_offering_revision(offering)
        logger.info("admissions_sync_complete program_id=%s offerings=%d stale=%d", envelope.program_id, len(expected_ids), len(stale_ids))

    def get_offering_revision(
        self,
        domain_rule_id: str,
        revision: int,
        content_hash: str,
    ) -> AdmissionOfferingRevision | None:
        row = self._session.get(
            AdmissionOfferingRevisionModel, (domain_rule_id, revision)
        )
        if row is None or row.content_hash != content_hash:
            return None
        payload = row.payload_json
        try:
            result = AdmissionOfferingRevision(
                domain_rule_id=row.domain_rule_id,
                offering_id=row.offering_id,
                revision=row.revision,
                content_hash=row.content_hash,
                recorded_at=_aware_utc(row.recorded_at),
                offering=AdmissionOffering.model_validate_json(
                    json.dumps(payload), strict=False
                ),
            )
        except (TypeError, ValueError):
            logger.exception(
                "admission_offering_revision_invalid domain_rule_id=%s revision=%d",
                domain_rule_id,
                revision,
            )
            return None
        return result

    def _append_offering_revision(self, offering: AdmissionOffering) -> None:
        domain_rule_id = admission_offering_domain_rule_id(offering.id)
        latest = self._session.scalar(
            select(AdmissionOfferingRevisionModel)
            .where(AdmissionOfferingRevisionModel.domain_rule_id == domain_rule_id)
            .order_by(AdmissionOfferingRevisionModel.revision.desc())
            .limit(1)
            .with_for_update()
        )
        content_hash = admission_offering_revision_hash(offering)
        if latest is not None and latest.content_hash == content_hash:
            return
        revision_number = latest.revision + 1 if latest is not None else 1
        revision = AdmissionOfferingRevision(
            domain_rule_id=domain_rule_id,
            offering_id=offering.id,
            revision=revision_number,
            content_hash=content_hash,
            recorded_at=datetime.now(UTC),
            offering=offering,
        )
        self._session.add(
            AdmissionOfferingRevisionModel(
                domain_rule_id=revision.domain_rule_id,
                revision=revision.revision,
                offering_id=revision.offering_id,
                program_id=offering.program_id,
                admission_year=offering.admission_year,
                content_hash=revision.content_hash,
                recorded_at=revision.recorded_at,
                payload_json=offering.model_dump(mode="json"),
            )
        )
        logger.info(
            "admission_offering_revision_appended domain_rule_id=%s revision=%d content_hash_prefix=%s",
            revision.domain_rule_id,
            revision.revision,
            revision.content_hash[:12],
        )

    def _upsert_offering(self, offering: AdmissionOffering) -> None:
        existing = self._session.get(AdmissionOfferingModel, offering.id)
        primary = offering.provenance[0]
        values = {
            "id": offering.id,
            "program_id": offering.program_id,
            "admission_year": offering.admission_year,
            "study_form": _enum_value(offering.study_form, StudyForm.UNKNOWN.value),
            "funding_type": _enum_value(offering.funding_type, FundingType.UNKNOWN.value),
            "scope": offering.scope.value,
            "campus_id": offering.campus_id,
            "places": offering.places,
            "source_kind": primary.source_kind,
            "source_url": str(primary.source_url),
            "captured_at": primary.captured_at,
            "content_sha256": primary.content_sha256,
            "source_locator": primary.locator,
            "source_name": primary.source_name,
        }
        if existing is None:
            self._session.add(AdmissionOfferingModel(**values))
            return
        immutable = (
            "program_id",
            "admission_year",
            "study_form",
            "funding_type",
            "scope",
            "campus_id",
        )
        for field in immutable:
            if getattr(existing, field) != values[field]:
                logger.error("admission_identity_conflict offering_id=%s field=%s", offering.id, field)
                raise ValueError(f"admission offering identity conflict: {offering.id}")
        for field, value in values.items():
            if field != "id":
                setattr(existing, field, value)

    def _sync_children(self, offering: AdmissionOffering) -> None:
        self._sync_collection(
            AdmissionExamRequirementModel,
            offering.id,
            offering.exams,
            lambda item: _exam_values(cast(ExamRequirement, item), offering.id),
        )
        self._sync_collection(
            AdmissionQuotaModel,
            offering.id,
            offering.quotas,
            lambda item: _quota_values(cast(Quota, item), offering.id),
        )
        self._sync_collection(
            AdmissionPassingScoreModel,
            offering.id,
            offering.passing_scores,
            lambda item: _passing_values(cast(PassingScore, item), offering.id),
        )
        self._sync_collection(
            AdmissionTuitionModel,
            offering.id,
            offering.tuition,
            lambda item: _tuition_values(cast(TuitionCost, item), offering.id),
        )

    def _sync_collection(
        self,
        model: type[Any],
        offering_id: str,
        values: tuple[object, ...],
        mapper: Callable[[object], dict[str, object]],
    ) -> None:
        # Child IDs are stable over source refreshes and include all natural
        # identity fields, while mutable values remain updateable.
        mapped = [mapper(item) for item in values]
        expected_ids = {item["id"] for item in mapped}
        existing_ids = set(
            self._session.scalars(select(model.id).where(model.offering_id == offering_id)).all()
        )
        stale_ids = existing_ids - expected_ids
        if stale_ids:
            self._session.execute(delete(model).where(model.id.in_(stale_ids)))
        for item in mapped:
            existing = self._session.get(model, item["id"])
            if existing is None:
                self._session.add(model(**item))
            else:
                for field, value in item.items():
                    if field != "id":
                        setattr(existing, field, value)

    def _delete_children(self, offering_ids: set[str]) -> None:
        for model in (AdmissionExamRequirementModel, AdmissionQuotaModel, AdmissionPassingScoreModel, AdmissionTuitionModel):
            self._session.execute(delete(model).where(model.offering_id.in_(offering_ids)))

    def _by_offering(self, model: type[Any], offering_ids: tuple[str, ...]) -> dict[str, tuple[Any, ...]]:
        rows = self._session.scalars(select(model).where(model.offering_id.in_(offering_ids))).all()
        result: dict[str, list[Any]] = {}
        for row in rows:
            result.setdefault(row.offering_id, []).append(row)
        return {key: tuple(value) for key, value in result.items()}

    @staticmethod
    def _offering_contract(
        model: AdmissionOfferingModel,
        exams: tuple[AdmissionExamRequirementModel, ...],
        quotas: tuple[AdmissionQuotaModel, ...],
        passing_scores: tuple[AdmissionPassingScoreModel, ...],
        tuition: tuple[AdmissionTuitionModel, ...],
    ) -> AdmissionOffering:
        return AdmissionOffering(
            id=model.id,
            program_id=model.program_id,
            admission_year=model.admission_year,
            study_form=_optional_enum(StudyForm, model.study_form),
            funding_type=_optional_enum(FundingType, model.funding_type),
            scope=AdmissionScope(model.scope),
            campus_id=model.campus_id,
            places=model.places,
            exams=tuple(_exam_contract(row) for row in exams),
            quotas=tuple(_quota_contract(row) for row in quotas),
            passing_scores=tuple(_passing_contract(row) for row in passing_scores),
            tuition=tuple(_tuition_contract(row) for row in tuition),
            provenance=(
                AdmissionProvenance.model_validate(
                    {
                        "source_kind": model.source_kind,
                        "source_url": model.source_url,
                        "captured_at": model.captured_at,
                        "content_sha256": model.content_sha256,
                        "locator": model.source_locator,
                        "source_name": model.source_name,
                        "university_id": model.university_id,
                        "run_id": model.run_id,
                        "field": model.field,
                        "record_key": model.record_key,
                        "inferred": model.inferred,
                    }
                ),
            ),
        )


def _enum_value(value: object | None, fallback: str) -> str:
    return str(value.value) if value is not None and hasattr(value, "value") else fallback


def _aware_utc(value: datetime) -> datetime:
    # SQLite drops timezone metadata for DateTime(timezone=True); persisted values
    # are written in UTC, so restore that explicit contract at the read boundary.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_enum(enum: type[_Enum], value: str) -> _Enum | None:
    parsed = enum(value)
    return None if parsed.value == "unknown" else parsed


def _child_id(prefix: str, offering_id: str, *parts: object) -> str:
    stable = "\x1f".join([offering_id, *(str(part) for part in parts)])
    return f"admission-{prefix}:{sha256(stable.encode('utf-8')).hexdigest()[:24]}"


def _provenance_values(provenance: AdmissionProvenance) -> dict[str, object]:
    return {
        "source_kind": provenance.source_kind,
        "source_url": str(provenance.source_url),
        "captured_at": provenance.captured_at,
        "content_sha256": provenance.content_sha256,
        "source_locator": provenance.locator,
        "university_id": provenance.university_id,
        "run_id": provenance.run_id,
        "field": provenance.field,
        "record_key": provenance.record_key,
        "inferred": provenance.inferred,
    }


def _exam_values(item: ExamRequirement, offering_id: str) -> dict[str, object]:
    return {
        "id": _child_id("exam", offering_id, item.subject, item.source_name),
        "offering_id": offering_id,
        "subject": item.subject,
        "source_name": item.source_name,
        "minimum_score": item.minimum_score,
        "is_choice": item.is_choice,
        "is_required": item.is_required,
        "choice_group_id": item.choice_group_id,
        "choice_group_min": item.choice_group_min,
        "choice_group_max": item.choice_group_max,
        **_provenance_values(item.provenance),
    }


def _quota_values(item: Quota, offering_id: str) -> dict[str, object]:
    return {
        "id": _child_id("quota", offering_id, item.quota_type, item.source_name),
        "offering_id": offering_id,
        "quota_type": item.quota_type.value,
        "source_name": item.source_name,
        "places": item.places,
        **_provenance_values(item.provenance),
    }


def _passing_values(item: PassingScore, offering_id: str) -> dict[str, object]:
    return {
        "id": _child_id("passing", offering_id, item.score_type, item.competition_type, item.status, item.score),
        "offering_id": offering_id,
        "score_type": item.score_type.value,
        "competition_type": item.competition_type.value,
        "status": item.status.value,
        "score": item.score,
        **_provenance_values(item.provenance),
    }


def _tuition_values(item: TuitionCost, offering_id: str) -> dict[str, object]:
    return {
        "id": _child_id("tuition", offering_id, item.amount, item.is_discounted, item.study_form),
        "offering_id": offering_id,
        "amount": item.amount,
        "currency": item.currency,
        "academic_year": item.academic_year,
        "period": item.period,
        "study_form": item.study_form.value if item.study_form is not None else None,
        "is_discounted": item.is_discounted,
        **_provenance_values(item.provenance),
    }


def _exam_contract(row: AdmissionExamRequirementModel) -> ExamRequirement:
    return ExamRequirement(
        subject=row.subject,
        source_name=row.source_name,
        minimum_score=row.minimum_score,
        is_choice=row.is_choice,
        is_required=row.is_required,
        choice_group_id=row.choice_group_id,
        choice_group_min=row.choice_group_min,
        choice_group_max=row.choice_group_max,
        provenance=_row_provenance(row),
    )


def _quota_contract(row: AdmissionQuotaModel) -> Quota:
    return Quota(quota_type=QuotaType(row.quota_type), source_name=row.source_name, places=row.places, provenance=_row_provenance(row))


def _passing_contract(row: AdmissionPassingScoreModel) -> PassingScore:
    return PassingScore(
        score_type=PassingScoreType(row.score_type),
        competition_type=AdmissionCompetitionType(row.competition_type),
        status=PassingScoreStatus(row.status),
        score=row.score,
        provenance=_row_provenance(row),
    )


def _tuition_contract(row: AdmissionTuitionModel) -> TuitionCost:
    return TuitionCost(
        amount=row.amount,
        currency=row.currency,
        academic_year=row.academic_year,
        period=row.period,
        study_form=_optional_enum(StudyForm, row.study_form) if row.study_form else None,
        is_discounted=row.is_discounted,
        provenance=_row_provenance(row),
    )


def _row_provenance(row: object) -> AdmissionProvenance:
    return AdmissionProvenance.model_validate(
        {
            "source_kind": row.source_kind,  # type: ignore[attr-defined]
            "source_url": row.source_url,  # type: ignore[attr-defined]
            "captured_at": row.captured_at,  # type: ignore[attr-defined]
            "content_sha256": row.content_sha256,  # type: ignore[attr-defined]
            "locator": row.source_locator,  # type: ignore[attr-defined]
            "university_id": row.university_id,  # type: ignore[attr-defined]
            "run_id": row.run_id,  # type: ignore[attr-defined]
            "field": row.field,  # type: ignore[attr-defined]
            "record_key": row.record_key,  # type: ignore[attr-defined]
            "inferred": row.inferred,  # type: ignore[attr-defined]
        }
    )


__all__ = ["SqlAlchemyAdmissionRepository"]
