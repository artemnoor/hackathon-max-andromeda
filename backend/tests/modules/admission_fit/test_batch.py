from __future__ import annotations

from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitStatus,
    BatchAdmissionFitRequest,
)
from andromeda.modules.admission_fit.repository.ports import AdmissionFitProgramData
from andromeda.modules.admission_fit.services.admission_fit import AdmissionFitService
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm

from .conftest import applicant, offering, program


class Reader:
    def __init__(self, snapshots: dict[str, AdmissionFitProgramData]) -> None:
        self.snapshots = snapshots

    def read(self, program_id: str) -> AdmissionFitProgramData | None:
        return self.snapshots.get(program_id)


class BulkReader(Reader):
    def __init__(self, snapshots: dict[str, AdmissionFitProgramData]) -> None:
        super().__init__(snapshots)
        self.read_many_calls: list[tuple[str, ...]] = []

    def read_many(self, program_ids: tuple[str, ...]) -> dict[str, AdmissionFitProgramData]:
        self.read_many_calls.append(program_ids)
        return {key: self.snapshots[key] for key in program_ids if key in self.snapshots}


def _snapshot(program_id: str = "program:09.03.01-02") -> AdmissionFitProgramData:
    selected = offering(program_id=program_id)
    return AdmissionFitProgramData(
        program=program(program_id),
        admissions={"program_id": program_id, "offerings": (selected,)},
    )


def test_batch_evaluation_returns_one_outcome_per_program_and_preserves_missing_source() -> None:
    present = "program:09.03.01-02"
    missing = "program:09.03.01-03"
    service = AdmissionFitService(Reader({present: _snapshot(present)}))
    result = service.evaluate_batch(
        BatchAdmissionFitRequest(
            program_ids=(present, missing),
            applicant=applicant(("Математика", "90"), ("Русский язык", "80"), ("Физика", "70")),
            funding_type=FundingType.BUDGET,
        )
    )

    assert tuple(result.by_program_id) == (present, missing)
    assert result.by_program_id[present].result is not None
    assert result.by_program_id[missing].status is AdmissionFitStatus.INSUFFICIENT_DATA
    assert result.by_program_id[missing].result is None
    assert result.by_program_id[missing].data_gaps


def test_batch_evaluation_reports_ambiguous_offerings_instead_of_picking_one() -> None:
    program_id = "program:09.03.01-02"
    first = offering(program_id=program_id)
    second = offering(program_id=program_id, funding_type=FundingType.PAID)
    snapshot = AdmissionFitProgramData(
        program=program(program_id),
        admissions={"program_id": program_id, "offerings": (first, second)},
    )
    service = AdmissionFitService(Reader({program_id: snapshot}))

    result = service.evaluate_batch(
        BatchAdmissionFitRequest(
            program_ids=(program_id,),
            applicant=applicant(("Математика", "90")),
        )
    )

    outcome = result.by_program_id[program_id]
    assert outcome.status is AdmissionFitStatus.INSUFFICIENT_DATA
    assert outcome.result is None
    assert "несколько" in outcome.data_gaps[0].message


def test_existing_one_program_evaluation_remains_available() -> None:
    from andromeda.modules.admission_fit.contracts.public import AdmissionFitRequest

    program_id = "program:09.03.01-02"
    selected = offering(program_id=program_id)
    service = AdmissionFitService(Reader({program_id: _snapshot(program_id)}))

    result = service.evaluate(
        program_id,
        AdmissionFitRequest(offering_id=selected.id, applicant=applicant(("Математика", "90"))),
    )

    assert result.program_id == program_id
    assert result.offering_id == selected.id


def test_evaluate_batches_uses_one_bulk_snapshot_read_for_all_chunks() -> None:
    first_id = "program:09.03.01-02"
    second_id = "program:09.03.01-03"
    reader = BulkReader({first_id: _snapshot(first_id), second_id: _snapshot(second_id)})
    service = AdmissionFitService(reader)
    applicant_profile = applicant(("Математика", "90"), ("Русский язык", "80"), ("Физика", "70"))

    result = service.evaluate_batches(
        (
            BatchAdmissionFitRequest(program_ids=(first_id,), applicant=applicant_profile),
            BatchAdmissionFitRequest(program_ids=(second_id,), applicant=applicant_profile),
        )
    )

    assert reader.read_many_calls == [(first_id, second_id)]
    assert set(result.by_program_id) == {first_id, second_id}


def test_latest_published_year_uses_matching_funding_and_form_in_one_bulk_read() -> None:
    first_id = "program:09.03.01-02"
    second_id = "program:09.03.01-03"
    source = offering(program_id=first_id)
    old = source.model_copy(
        update={
            "id": "admission-offering:old",
            "admission_year": 2025,
            "study_form": StudyForm.FULL_TIME,
        }
    )
    latest_paid = source.model_copy(
        update={
            "id": "admission-offering:paid",
            "funding_type": FundingType.PAID,
            "study_form": StudyForm.FULL_TIME,
        }
    )
    latest_budget = source.model_copy(
        update={"study_form": StudyForm.FULL_TIME}
    )
    first = AdmissionFitProgramData(
        program=program(first_id),
        admissions={"program_id": first_id, "offerings": (old, latest_budget, latest_paid)},
    )
    second = _snapshot(second_id)
    reader = BulkReader({first_id: first, second_id: second})

    service = AdmissionFitService(reader)
    year = service.latest_published_year(
        (first_id, second_id),
        study_form=StudyForm.FULL_TIME,
        funding_type=FundingType.BUDGET,
    )

    assert year == 2026
    assert service.latest_published_year(
        (first_id, second_id),
        study_form=StudyForm.FULL_TIME,
        funding_type=FundingType.PAID,
    ) == 2026
    assert service.latest_published_year(
        (first_id, second_id),
        study_form=StudyForm.EVENING,
        funding_type=FundingType.BUDGET,
    ) is None
    assert reader.read_many_calls == [(first_id, second_id)] * 3
