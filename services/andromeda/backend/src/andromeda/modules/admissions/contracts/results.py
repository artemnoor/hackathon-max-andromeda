"""Result aliases kept separate from HTTP schemas."""

from andromeda.modules.programs.contracts.public import Program

from .public import ProgramAdmissions

AdmissionResult = ProgramAdmissions


class ProgramAdmissionsResult(ProgramAdmissions):
    """Application result carrying the validated program public contract."""

    program: Program

__all__ = ["AdmissionResult", "ProgramAdmissionsResult"]
