from __future__ import annotations

from decimal import Decimal
from typing import Annotated, TypeAlias

from pydantic import Field, StringConstraints

NonEmptyText: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
ShortText: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
UniversityId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^university:[a-z0-9][a-z0-9-]{0,62}$")]
AdmissionCampusId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^campus:[a-z0-9][a-z0-9-]{0,62}$")]
AdmissionExamChoiceGroupId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^exam-choice:[a-z0-9][a-z0-9-]{0,62}$"),
]
DirectionId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^direction:(?:[a-z0-9][a-z0-9-]{0,62}:)?[0-9]{2}\.[0-9]{2}\.[0-9]{2}$")]
DirectionCode: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[0-9]{2}\.[0-9]{2}\.[0-9]{2}$")]
ProgramId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^program:(?:[a-z0-9][a-z0-9-]{0,62}:)?[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}$"),
]
ProgramCode: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}$")]
DepartmentId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^department:[a-z0-9][a-z0-9-]{0,62}:[a-z0-9][a-z0-9-]{0,62}$"),
]
EventId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^event:[a-z0-9][a-z0-9-]{0,62}:[a-z0-9][a-z0-9-]{0,127}$"),
]
VenueId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^venue:[a-z0-9][a-z0-9-]{0,62}:[a-z0-9][a-z0-9-]{0,62}$"),
]
CurriculumId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^curriculum:(?:[a-z0-9][a-z0-9-]{0,62}:)?[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}-20[0-9]{2}$"),
]
CurriculumItemId: TypeAlias = Annotated[
    str,
    StringConstraints(
        pattern=r"^curriculum-item:program:(?:[a-z0-9][a-z0-9-]{0,62}:)?[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}:discipline:[a-f0-9]{16}:(?:unassigned|[1-9]|1[0-2])$"
    ),
]
DisciplineId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^discipline:[a-f0-9]{16}$")]
SemanticFeatureId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^semantic-feature:[a-z0-9][a-z0-9_-]{0,62}$"),
]
SemanticFeatureCode: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$"),
]
OlympiadId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^olympiad:[a-z0-9][a-z0-9-]{0,127}$"),
]
OlympiadProfileId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^olympiad-profile:[a-z0-9][a-z0-9-]{0,127}$"),
]
AdmissionBenefitRuleId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^admission-benefit:[a-z0-9][a-z0-9-]{0,127}$"),
]
IndividualAchievementRuleId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^individual-achievement:[a-z0-9][a-z0-9-]{0,127}$"),
]
SemanticVersion: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}\.v[0-9]+$"),
]
SourcePosition: TypeAlias = Annotated[int, Field(strict=True, ge=1, le=10_000)]
SourceHash: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
AccountId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^account:[a-f0-9]{32}$")]
UniversityMembershipId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^membership:[a-f0-9]{32}$")]
UniversityUnitId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^unit:[a-z0-9][a-z0-9-]{0,62}:[a-z0-9][a-z0-9-]{0,62}$"),
]
UniversityCategoryId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^category:[a-z0-9][a-z0-9-]{0,62}:[a-z0-9][a-z0-9-]{0,62}$"),
]
UniversityEventId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^university-event:[a-z0-9][a-z0-9-]{0,62}:[a-f0-9]{32}$"),
]
SessionTokenHash: TypeAlias = SourceHash
IngestRunId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^ingest:[a-f0-9]{32}$")]
EducationYear: TypeAlias = Annotated[int, Field(strict=True, ge=2000, le=2100)]
Semester: TypeAlias = Annotated[int, Field(strict=True, ge=1, le=12)]
HourCount: TypeAlias = Annotated[int, Field(strict=True, ge=0, le=2000)]
Credits: TypeAlias = Annotated[Decimal, Field(strict=True, ge=Decimal("0"), le=Decimal("60"), max_digits=6, decimal_places=2)]


def canonical_program_id(program_id: str) -> str:
    """Resolve the legacy unscoped BMSTU ID at read boundaries only.

    Canonical storage always uses university-scoped IDs. This compatibility
    alias keeps older links and clients usable during the identity transition.
    """

    if program_id.startswith("program:") and program_id.count(":") == 1:
        return f"program:bmstu:{program_id.removeprefix('program:')}"
    return program_id
