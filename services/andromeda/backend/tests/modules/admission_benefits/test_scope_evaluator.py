from andromeda.modules.admission_benefits.contracts.policy import BenefitTarget, BenefitTargetKind, BenefitScope, BenefitScopeMode
from andromeda.modules.admission_benefits.contracts.status import TargetResolutionStatus
from andromeda.modules.admission_benefits.services.applicability import evaluate_scope

from .test_helpers import DIRECTION_CODE, PROGRAM_ID, olympiad_rule, scope_all, scope_all_except, scope_only


def test_all_scope_applies_without_expanding_direction_rows() -> None:
    result = evaluate_scope(olympiad_rule(scope=scope_all()), direction_code=DIRECTION_CODE, program_id=PROGRAM_ID)
    assert result.status.value == "applicable"


def test_only_scope_matches_program_target() -> None:
    scope = scope_only(PROGRAM_ID, kind=BenefitTargetKind.PROGRAM)
    result = evaluate_scope(olympiad_rule(scope=scope), direction_code=DIRECTION_CODE, program_id=PROGRAM_ID)
    assert result.status.value == "applicable"
    assert result.matched_target is not None


def test_all_except_scope_rejects_only_excluded_direction() -> None:
    scope = scope_all_except(DIRECTION_CODE)
    excluded = evaluate_scope(olympiad_rule(scope=scope), direction_code=DIRECTION_CODE, program_id=PROGRAM_ID)
    allowed = evaluate_scope(olympiad_rule(scope=scope), direction_code="09.03.04", program_id=PROGRAM_ID)
    assert excluded.status.value == "not_applicable"
    assert allowed.status.value == "applicable"


def test_unresolved_scope_is_review_required() -> None:
    scope = BenefitScope(
        mode=BenefitScopeMode.ONLY,
        targets=(
            BenefitTarget(
                kind=BenefitTargetKind.DIRECTION,
                value="09.03.03",
                original_text="09.03.03",
                resolution=TargetResolutionStatus.UNRESOLVED,
            ),
        ),
        original_text="Только 09.03.03",
    )
    result = evaluate_scope(olympiad_rule(scope=scope), direction_code=DIRECTION_CODE)
    assert result.status.value == "review_required"
