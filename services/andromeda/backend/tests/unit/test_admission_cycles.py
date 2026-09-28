from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycle,
    AdmissionCycleResolution,
    AdmissionCycleResolutionStatus,
    AdmissionCycleState,
    InclusiveDateWindow,
)
from andromeda.modules.knowledge.contracts.public import EvidenceLocator, EvidenceRef

NOW = datetime(2027, 12, 15, tzinfo=UTC)
ACCOUNT_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
OBSERVATION_ID = "source-observation:" + "b" * 32
SNAPSHOT_HASH = "c" * 64


def _cycle(*, revision: int = 1, year: int = 2028, recorded_at: datetime = NOW) -> AdmissionCycle:
    return AdmissionCycle(
        cycle_id=f"admission-cycle:bmstu:{year}",
        revision=revision,
        university_id=UNIVERSITY_ID,
        admission_year=year,
        academic_year="2028/2029",
        application_period=InclusiveDateWindow(
            start_date=date(2028, 6, 20), end_date=date(2028, 7, 25)
        ),
        enrollment_period=None,
        state=AdmissionCycleState.PUBLISHED,
        evidence=(
            EvidenceRef(
                source_id="source:bmstu-admission",
                source_observation_id=OBSERVATION_ID,
                snapshot_sha256=SNAPSHOT_HASH,
                source_url="https://admission.bmstu.example/rules-2028.pdf",
                locator=EvidenceLocator(page=3, section="Admission calendar"),
            ),
        ),
        approved_by_account_id=ACCOUNT_ID,
        approved_at=NOW,
        approval_reason="Cycle was checked against the cited admission rules.",
        recorded_at=recorded_at,
    )


def test_admission_cycle_does_not_infer_admission_year_from_academic_year() -> None:
    cycle = _cycle(year=2027)

    assert cycle.admission_year == 2027
    assert cycle.academic_year == "2028/2029"
    assert cycle.cycle_id == "admission-cycle:bmstu:2027"
    assert cycle.application_period is not None
    assert cycle.application_period.start_date == date(2028, 6, 20)


def test_admission_cycle_requires_matching_identity_and_approval_clock() -> None:
    with pytest.raises(ValidationError, match="cycle_id must match"):
        AdmissionCycle.model_validate(
            _cycle().model_dump(mode="python")
            | {"cycle_id": "admission-cycle:other:2028"}
        )

    with pytest.raises(ValidationError, match="cannot precede approval"):
        AdmissionCycle.model_validate(
            _cycle().model_dump(mode="python") | {"recorded_at": datetime(2027, 12, 14, tzinfo=UTC)}
        )


def test_cycle_resolution_exposes_missing_data_and_resolved_states() -> None:
    missing = AdmissionCycleResolution(
        status=AdmissionCycleResolutionStatus.BLOCKED_BY_MISSING_DATA,
        reason="No reviewed cycle is known.",
    )
    resolved = AdmissionCycleResolution(
        status=AdmissionCycleResolutionStatus.RESOLVED,
        cycle=_cycle(),
    )

    assert missing.cycle is None
    assert resolved.cycle is not None
    with pytest.raises(ValidationError, match="requires a cycle"):
        AdmissionCycleResolution(status=AdmissionCycleResolutionStatus.RESOLVED)


def test_inclusive_date_window_rejects_reversed_period() -> None:
    with pytest.raises(ValidationError, match="cannot follow"):
        InclusiveDateWindow(start_date=date(2028, 7, 26), end_date=date(2028, 7, 25))
