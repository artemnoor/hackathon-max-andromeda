from __future__ import annotations

from andromeda.modules.proftest.contracts.public import ProgramSignal, source_capabilities


def test_source_capability_inventory_is_explicit_and_no_hour_breakdown_is_invented() -> None:
    capabilities = {item.signal: item for item in source_capabilities()}

    assert capabilities[ProgramSignal.AREA_SHARE].supported is True
    assert capabilities[ProgramSignal.ASSESSMENT_TYPES].supported is True
    for signal in (ProgramSignal.LECTURE_HOURS, ProgramSignal.LAB_HOURS, ProgramSignal.PRACTICE_HOURS):
        assert capabilities[signal].supported is False
        assert capabilities[signal].gap_code
