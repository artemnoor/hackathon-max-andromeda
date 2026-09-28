"""Application service for the Admission Fit vertical slice."""

from __future__ import annotations

import logging

from andromeda.shared.contracts.errors import ContractError, ErrorCode, NotFoundError
from andromeda.shared.contracts.ids import (
    EducationYear,
    ProgramId,
    canonical_program_id,
)

from ...admissions.contracts.public import AdmissionOffering, FundingType, StudyForm
from ..contracts.public import (
    AdmissionFitReason,
    AdmissionFitReasonKind,
    AdmissionFitRequest,
    AdmissionFitResult,
    AdmissionFitStatus,
    BatchAdmissionFitOutcome,
    BatchAdmissionFitRequest,
    BatchAdmissionFitResult,
)
from ..repository.ports import AdmissionFitDataReader, AdmissionFitProgramData
from .scoring import AdmissionFitScoringService

logger = logging.getLogger("andromeda.admission_fit")


class AdmissionFitService:
    """Coordinate public program/admissions readers and the pure scorer."""

    def __init__(
        self,
        reader: AdmissionFitDataReader,
        scorer: AdmissionFitScoringService | None = None,
    ) -> None:
        self._reader = reader
        self._scorer = scorer or AdmissionFitScoringService()

    def evaluate(self, program_id: ProgramId, request: AdmissionFitRequest) -> AdmissionFitResult:
        resolved_program_id = canonical_program_id(program_id)
        logger.debug(
            "admission_fit_evaluation_started program_id=%s offering_id=%s subject_count=%d",
            program_id,
            request.offering_id,
            len(request.applicant.scores),
        )
        try:
            snapshot = self._reader.read(resolved_program_id)
            if snapshot is None and resolved_program_id != program_id:
                # One-cycle compatibility for in-memory/legacy consumers. The
                # canonical repositories write only university-scoped IDs.
                snapshot = self._reader.read(program_id)
        except Exception:
            logger.exception("admission_fit_reader_failed program_id=%s", program_id)
            raise
        if snapshot is None:
            raise NotFoundError(f"Program not found: {program_id}")
        if snapshot.program.id not in {resolved_program_id, program_id} or snapshot.admissions.program_id not in {resolved_program_id, program_id}:
            logger.error("admission_fit_reader_contract_mismatch program_id=%s", program_id)
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Admission Fit reader returned an incompatible program contract")
        offering = next((item for item in snapshot.admissions.offerings if item.id == request.offering_id), None)
        if offering is None:
            raise NotFoundError(f"Admission offering not found: {request.offering_id}")
        result = self._scorer.score(program_id, offering, request.applicant)
        logger.debug(
            "admission_fit_evaluation_finished program_id=%s offering_id=%s data_quality=%s",
            program_id,
            request.offering_id,
            result.data_quality.value,
        )
        return result

    def evaluate_batch(self, request: BatchAdmissionFitRequest) -> BatchAdmissionFitResult:
        """Evaluate each candidate independently, preserving source gaps."""

        return self._evaluate_programs(request, request.program_ids)

    def evaluate_batches(self, requests: tuple[BatchAdmissionFitRequest, ...]) -> BatchAdmissionFitResult:
        """Evaluate consecutive bounded requests as one bulk catalog operation."""

        if not requests:
            return BatchAdmissionFitResult()
        first = requests[0]
        if any(
            item.applicant != first.applicant
            or item.admission_year != first.admission_year
            or item.study_form is not first.study_form
            or item.funding_type is not first.funding_type
            for item in requests[1:]
        ):
            raise ContractError(ErrorCode.INVALID_QUERY, "Batched admission requests must share applicant and offering filters")
        program_ids = tuple(program_id for item in requests for program_id in item.program_ids)
        if len(program_ids) != len(set(program_ids)):
            raise ContractError(ErrorCode.INVALID_QUERY, "Batched admission requests must contain unique programs")
        if len(program_ids) > 5000:
            raise ContractError(ErrorCode.INVALID_QUERY, "Admission candidate set exceeds the 5000-program safety bound")
        return self._evaluate_programs(first, program_ids)

    def latest_published_year(
        self,
        program_ids: tuple[ProgramId, ...],
        *,
        study_form: StudyForm,
        funding_type: FundingType,
    ) -> EducationYear | None:
        """Resolve the newest year present for the exact form/funding selection."""

        candidates = tuple(dict.fromkeys(program_ids))
        if len(candidates) > 5000:
            raise ContractError(ErrorCode.INVALID_QUERY, "Admission candidate set exceeds the 5000-program safety bound")
        if not candidates:
            return None
        read_many = getattr(self._reader, "read_many", None)
        if callable(read_many):
            snapshots = read_many(candidates)
        else:
            snapshots = {
                canonical_program_id(program_id): snapshot
                for program_id in candidates
                if (
                    snapshot := self._read_snapshot(
                        canonical_program_id(program_id),
                        legacy_program_id=program_id,
                    )
                ) is not None
            }
        matching_years = tuple(
            offering.admission_year
            for snapshot in snapshots.values()
            for offering in snapshot.admissions.offerings
            if offering.study_form is study_form and offering.funding_type is funding_type
        )
        latest_year = max(matching_years) if matching_years else None
        logger.info(
            "admission_fit_latest_published_year candidate_count=%d matching_offerings=%d admission_year=%s study_form=%s funding_type=%s",
            len(candidates),
            len(matching_years),
            latest_year if latest_year is not None else "unavailable",
            study_form.value,
            funding_type.value,
        )
        return latest_year

    def _evaluate_programs(
        self,
        request: BatchAdmissionFitRequest,
        program_ids: tuple[ProgramId, ...],
    ) -> BatchAdmissionFitResult:
        logger.debug(
            "admission_fit_batch_started candidate_count=%d admission_year=%s study_form=%s funding_type=%s",
            len(program_ids),
            request.admission_year,
            request.study_form.value if request.study_form is not None else "unknown",
            request.funding_type.value if request.funding_type is not None else "unknown",
        )
        outcomes: dict[ProgramId, BatchAdmissionFitOutcome] = {}
        read_many = getattr(self._reader, "read_many", None)
        snapshots = read_many(program_ids) if callable(read_many) else None
        for program_id in program_ids:
            resolved_program_id = canonical_program_id(program_id)
            if snapshots is None:
                snapshot = self._read_snapshot(resolved_program_id, legacy_program_id=program_id)
            else:
                snapshot = snapshots.get(resolved_program_id) or snapshots.get(program_id)
            if snapshot is None:
                outcomes[program_id] = _missing_outcome(program_id, "Для программы нет source-backed данных поступления")
                continue
            public_program_id = program_id
            offering, gap = _select_offering(snapshot.admissions.offerings, request)
            if offering is None:
                outcomes[public_program_id] = _missing_outcome(public_program_id, gap)
                continue
            result = self._scorer.score(public_program_id, offering, request.applicant)
            outcomes[public_program_id] = BatchAdmissionFitOutcome(
                program_id=public_program_id,
                status=result.status,
                result=result,
                data_gaps=result.data_gaps,
            )
        response = BatchAdmissionFitResult(by_program_id=outcomes)
        logger.info(
            "admission_fit_batch_complete candidate_count=%d result_count=%d insufficient_count=%d",
            len(program_ids),
            len(response.by_program_id),
            sum(item.status is AdmissionFitStatus.INSUFFICIENT_DATA for item in response.by_program_id.values()),
        )
        return response

    def _read_snapshot(self, program_id: ProgramId, *, legacy_program_id: ProgramId | None = None) -> AdmissionFitProgramData | None:
        try:
            snapshot = self._reader.read(program_id)
        except Exception:
            logger.exception("admission_fit_batch_reader_failed program_id=%s", program_id)
            raise
        if snapshot is None and legacy_program_id is not None and legacy_program_id != program_id:
            snapshot = self._reader.read(legacy_program_id)
        accepted_ids = {program_id, legacy_program_id} - {None}
        if snapshot is not None and (snapshot.program.id not in accepted_ids or snapshot.admissions.program_id not in accepted_ids):
            logger.error("admission_fit_batch_reader_contract_mismatch program_id=%s", program_id)
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Admission Fit reader returned an incompatible program contract")
        return snapshot


def _select_offering(
    offerings: tuple[AdmissionOffering, ...],
    request: BatchAdmissionFitRequest,
) -> tuple[AdmissionOffering | None, str]:
    matching = tuple(
        offering
        for offering in offerings
        if (request.admission_year is None or offering.admission_year == request.admission_year)
        and (request.study_form is None or offering.study_form is request.study_form)
        and (request.funding_type is None or offering.funding_type is request.funding_type)
    )
    if len(matching) == 1:
        return matching[0], ""
    if not matching:
        return None, "Для заданных года, формы или типа финансирования нет опубликованного набора"
    return None, "Для заданных ограничений опубликовано несколько наборов; offering нельзя выбрать однозначно"


def _missing_outcome(program_id: ProgramId, message: str) -> BatchAdmissionFitOutcome:
    return BatchAdmissionFitOutcome(
        program_id=program_id,
        status=AdmissionFitStatus.INSUFFICIENT_DATA,
        data_gaps=(AdmissionFitReason(kind=AdmissionFitReasonKind.DATA_GAP, message=message),),
    )


__all__ = ["AdmissionFitService"]
