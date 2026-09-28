from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.applicant import ApplicantAdmissionFacts
from andromeda.modules.admission_benefits.contracts.public import AchievementCombinationPolicy
from andromeda.modules.admission_benefits.contracts.results import EligibilityStatus, IndividualAchievementStatus
from andromeda.modules.admission_benefits.services.individual_achievements import IndividualAchievementCalculator

from .test_helpers import achievement_fact, achievement_policy, achievement_rule


def test_fixed_and_additive_achievements_are_counted_from_source_rules() -> None:
    policy = achievement_policy(
        achievement_rule("red_attestat", "10"),
        achievement_rule("gto_gold", "5"),
    )
    result = IndividualAchievementCalculator().calculate(
        policy,
        ApplicantAdmissionFacts(individual_achievements=(achievement_fact("red_attestat"), achievement_fact("gto_gold"))),
    )
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.total_points == Decimal("15")
    assert all(item.status is IndividualAchievementStatus.ACCEPTED for item in result.evaluations)


def test_global_cap_is_applied_and_reported() -> None:
    policy = achievement_policy(
        achievement_rule("red_attestat", "8"),
        achievement_rule("gto_gold", "5"),
        global_max_points="10",
    )
    result = IndividualAchievementCalculator().calculate(
        policy,
        ApplicantAdmissionFacts(individual_achievements=(achievement_fact("red_attestat"), achievement_fact("gto_gold"))),
    )
    assert result.total_points == Decimal("10")
    assert result.global_cap == Decimal("10")
    assert any(item.status is IndividualAchievementStatus.CAPPED for item in result.evaluations)


def test_max_only_group_selects_the_highest_and_duplicate_basis_counts_once() -> None:
    policy = achievement_policy(
        achievement_rule(
            "sport_gold",
            "5",
            group="sport",
            combination=AchievementCombinationPolicy.MAX_ONLY,
            rule_id="individual-achievement:bmstu-sport-gold",
        ),
        achievement_rule(
            "sport_silver",
            "3",
            group="sport",
            combination=AchievementCombinationPolicy.MAX_ONLY,
            rule_id="individual-achievement:bmstu-sport-silver",
        ),
    )
    result = IndividualAchievementCalculator().calculate(
        policy,
        ApplicantAdmissionFacts(
            individual_achievements=(
                achievement_fact("sport_gold"),
                achievement_fact("sport_silver"),
                achievement_fact("sport_gold"),
            )
        ),
    )
    assert result.total_points == Decimal("5")
    assert sum(item.status is IndividualAchievementStatus.DEDUPLICATED for item in result.evaluations) == 2


def test_required_document_and_unknown_code_never_award_points() -> None:
    policy = achievement_policy(
        achievement_rule("volunteer", "2", required_document="волонтерская книжка"),
    )
    result = IndividualAchievementCalculator().calculate(
        policy,
        ApplicantAdmissionFacts(
            individual_achievements=(achievement_fact("volunteer", evidence=None), achievement_fact("unknown")),
        ),
    )
    assert result.total_points == Decimal("0")
    assert result.status is EligibilityStatus.REVIEW_REQUIRED
    assert all(item.status is IndividualAchievementStatus.REVIEW_REQUIRED for item in result.evaluations)


def test_olympiad_achievement_can_be_excluded_when_used_for_a_right() -> None:
    policy = achievement_policy(achievement_rule("olympiad:shag-v-budushchee", "5"))
    result = IndividualAchievementCalculator().calculate(
        policy,
        ApplicantAdmissionFacts(individual_achievements=(achievement_fact("olympiad:shag-v-budushchee"),)),
        excluded_achievement_codes=frozenset({"olympiad:shag-v-budushchee"}),
    )
    assert result.total_points == Decimal("0")
    assert result.evaluations[0].status is IndividualAchievementStatus.EXCLUDED
