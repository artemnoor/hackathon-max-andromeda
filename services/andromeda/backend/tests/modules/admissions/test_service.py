from __future__ import annotations

from datetime import UTC, datetime
import pytest

from andromeda.modules.admissions.contracts.public import AdmissionOffering, AdmissionProvenance, AdmissionScope, FundingType, ProgramAdmissions
from andromeda.modules.admissions.services.admissions import AdmissionService
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.errors import NotFoundError


def _provenance() -> AdmissionProvenance:
    return AdmissionProvenance(
        source_kind="fixture",
        source_url="https://example.test/admissions",
        captured_at=datetime.now(UTC),
        content_sha256="a" * 64,
    )


def _program() -> Program:
    return Program(
        id="program:01.01.01-01",
        direction_id="direction:01.01.01",
        code="01.01.01-01",
        name="Test program",
        education_year=2025,
        study_plan_url="https://example.test/plan.pdf",
        source_url="https://example.test/program",
    )


class ProgramReaderStub:
    def __init__(self, program: Program | None) -> None:
        self.program = program

    def get(self, program_id: str) -> Program | None:
        return self.program if self.program and self.program.id == program_id else None


class AdmissionReaderStub:
    def get_for_program(self, program_id: str) -> ProgramAdmissions:
        return ProgramAdmissions(program_id=program_id, offerings=(AdmissionOffering(id="admission-offering:program:01.01.01-01:2025:program:budget", program_id=program_id, admission_year=2025, funding_type=FundingType.BUDGET, scope=AdmissionScope.PROGRAM, places=10, provenance=(_provenance(),)),))


def test_service_returns_program_and_admissions_as_application_contract() -> None:
    result = AdmissionService(ProgramReaderStub(_program()), AdmissionReaderStub()).get_for_program("program:01.01.01-01")

    assert result.program.id == "program:01.01.01-01"
    assert result.program_id == "program:01.01.01-01"
    assert result.offerings[0].places == 10


def test_service_does_not_return_admissions_for_missing_program() -> None:
    with pytest.raises(NotFoundError):
        AdmissionService(ProgramReaderStub(None), AdmissionReaderStub()).get_for_program("program:99.99.99-99")
