from __future__ import annotations

import pytest

from andromeda.modules.admission_fit.contracts.public import AdmissionFitRequest, ApplicantAdmissionProfile
from andromeda.modules.admission_fit.repository.ports import AdmissionFitProgramData
from andromeda.modules.admission_fit.services.admission_fit import AdmissionFitService
from andromeda.shared.contracts.errors import ContractError, NotFoundError

from .conftest import applicant, offering, program


class Reader:
    def __init__(self, snapshot: AdmissionFitProgramData | None) -> None:
        self.snapshot = snapshot

    def read(self, program_id: str) -> AdmissionFitProgramData | None:
        return self.snapshot if self.snapshot and self.snapshot.program.id == program_id else None


class AlwaysReader:
    def __init__(self, snapshot: AdmissionFitProgramData) -> None:
        self.snapshot = snapshot

    def read(self, program_id: str) -> AdmissionFitProgramData:
        return self.snapshot


def test_service_reads_public_snapshot_and_evaluates_selected_offering() -> None:
    selected = offering()
    snapshot = AdmissionFitProgramData(
        program=program(),
        admissions={"program_id": program().id, "offerings": (selected,)},
    )
    request = AdmissionFitRequest(offering_id=selected.id, applicant=applicant(("Математика", "90")))

    result = AdmissionFitService(Reader(snapshot)).evaluate(program().id, request)

    assert result.program_id == program().id
    assert result.offering_id == selected.id


def test_service_rejects_unknown_program_and_offering() -> None:
    service = AdmissionFitService(Reader(None))
    request = AdmissionFitRequest(offering_id="admission-offering:missing", applicant=ApplicantAdmissionProfile())
    with pytest.raises(NotFoundError):
        service.evaluate("program:09.03.01-02", request)

    selected = offering()
    snapshot = AdmissionFitProgramData(
        program=program(),
        admissions={"program_id": program().id, "offerings": (selected,)},
    )
    with pytest.raises(NotFoundError):
        AdmissionFitService(Reader(snapshot)).evaluate(
            program().id,
            AdmissionFitRequest(offering_id="admission-offering:unknown", applicant=ApplicantAdmissionProfile()),
        )


def test_service_rejects_reader_identity_mismatch() -> None:
    selected = offering()
    snapshot = AdmissionFitProgramData(
        program=program(),
        admissions={"program_id": program().id, "offerings": (selected,)},
    )
    request = AdmissionFitRequest(offering_id=selected.id, applicant=ApplicantAdmissionProfile())

    with pytest.raises(ContractError):
        AdmissionFitService(AlwaysReader(snapshot)).evaluate("program:09.03.01-12", request)
