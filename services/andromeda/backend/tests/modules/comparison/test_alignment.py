from __future__ import annotations

from decimal import Decimal

from andromeda.modules.comparison.domain.alignment import align_workloads
from andromeda.modules.comparison.domain.entities import Workload
from andromeda.shared.contracts.enums import CompareStatus


def _workload(hours: int) -> Workload:
    return Workload(hours=hours, credits=Decimal("1.00"))


def test_alignment_classifies_all_four_row_statuses() -> None:
    left = {("both", 1): _workload(1), ("different", 1): _workload(1), ("only-a", 1): _workload(1)}
    right = {("both", 1): _workload(1), ("different", 1): _workload(2), ("only-b", 1): _workload(1)}
    statuses = {entry.key[0]: entry.status for entry in align_workloads(left, right)}
    assert statuses == {
        "both": CompareStatus.BOTH,
        "different": CompareStatus.DIFFERENT,
        "only-a": CompareStatus.ONLY_A,
        "only-b": CompareStatus.ONLY_B,
    }
