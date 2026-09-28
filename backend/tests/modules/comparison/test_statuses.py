from __future__ import annotations

from andromeda.modules.comparison.contracts.public import ComparisonRequest
from andromeda.shared.contracts.enums import ComparisonScope


def test_comparison_request_requires_semester_only_for_semester_scope() -> None:
    request = ComparisonRequest(program_a_id="program:09.03.01-02", program_b_id="program:09.03.01-12")
    assert request.scope is ComparisonScope.ALL
