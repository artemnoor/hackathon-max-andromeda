"""Data-quality gate for serving persisted BMSTU admission-benefit rules."""

from __future__ import annotations

from collections import Counter

from pydantic import Field

from andromeda.modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverageStatus,
)
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionRoute,
    BenefitType,
    ConfirmationRequirement,
)
from andromeda.modules.admission_benefits.contracts.snapshot import (
    AdmissionBenefitsSnapshot,
)
from andromeda.modules.admission_benefits.contracts.status import RuleDataStatus
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import EducationLevel


class BmstuAdmissionBenefitsReleaseReport(ContractModel):
    """Auditable readiness result; review rows are visible but never activated."""

    university_id: str = "university:bmstu"
    admission_year: int
    education_level: EducationLevel | None = None
    coverage_status: AdmissionBenefitCoverageStatus
    required_documents_expected: int = Field(ge=0)
    required_documents_captured: int = Field(ge=0)
    documents_discovered: int = Field(ge=0)
    documents_captured: int = Field(ge=0)
    source_hash_count: int = Field(ge=0)
    olympiads: int = Field(ge=0)
    olympiad_profiles: int = Field(ge=0)
    rules_by_route_benefit_result: dict[str, int]
    active_rules: int = Field(ge=0)
    review_required_rules: int = Field(ge=0)
    stale_rules: int = Field(ge=0)
    conflicting_rules: int = Field(ge=0)
    unresolved_active_targets: int = Field(ge=0)
    active_100_point_rules_without_subject: int = Field(ge=0)
    active_rules_with_unknown_confirmation: int = Field(ge=0)
    active_rules_missing_confirmation_subject: int = Field(ge=0)
    achievement_rules_active: int = Field(ge=0)
    achievement_rules_review_required: int = Field(ge=0)
    achievement_rules_stale: int = Field(ge=0)
    achievement_rules_conflicting: int = Field(ge=0)
    achievement_policy_status: RuleDataStatus | None = None
    active_achievement_rules_with_unknown_combination: int = Field(ge=0)
    source_gaps: int = Field(ge=0)
    coverage_complete: bool
    production_ready: bool
    blockers: tuple[str, ...] = ()


def evaluate_bmstu_admission_benefits_release(
    snapshot: AdmissionBenefitsSnapshot,
    *,
    education_level: EducationLevel | None = None,
) -> BmstuAdmissionBenefitsReleaseReport:
    """Evaluate persisted canonical facts without guessing or mutating status."""

    benefit_rules = tuple(
        rule
        for rule in snapshot.benefit_rules
        if education_level is None or rule.education_level in {None, education_level}
    )
    policy = snapshot.individual_achievement_policy
    achievement_rules = (
        tuple(
            rule
            for rule in policy.rules
            if education_level is None
            or (
                policy.education_level in {None, education_level}
                and rule.education_level in {None, education_level}
            )
        )
        if policy is not None
        else ()
    )
    counts = Counter(
        ":".join(
            (
                rule.route.value,
                rule.benefit_type.value,
                rule.result_type.value
                if rule.result_type is not None
                else "not_applicable",
            )
        )
        for rule in benefit_rules
    )
    active_rules = tuple(
        rule for rule in benefit_rules if rule.status is RuleDataStatus.ACTIVE
    )
    review_rules = tuple(
        rule for rule in benefit_rules if rule.status is RuleDataStatus.REVIEW_REQUIRED
    )
    stale_rules = tuple(
        rule for rule in benefit_rules if rule.status is RuleDataStatus.STALE
    )
    conflicting_rules = tuple(
        rule for rule in benefit_rules if rule.status is RuleDataStatus.CONFLICT
    )
    unresolved_targets = sum(
        len(rule.scope.unresolved_targets) for rule in active_rules
    )
    missing_100_subject = sum(
        rule.benefit_type is BenefitType.ONE_HUNDRED_POINTS
        and rule.target_subject is None
        for rule in active_rules
    )
    unknown_confirmation = sum(
        rule.confirmation_requirement is ConfirmationRequirement.UNKNOWN
        for rule in active_rules
        if rule.route
        in {AdmissionRoute.OLYMPIAD, AdmissionRoute.VOSH, AdmissionRoute.INTERNATIONAL}
    )
    missing_confirmation_subject = sum(
        rule.confirmation_requirement is ConfirmationRequirement.REQUIRED
        and not rule.confirmation_subjects
        for rule in active_rules
    )
    active_achievement_rules = tuple(
        rule
        for rule in achievement_rules
        if rule.status is RuleDataStatus.ACTIVE
        and policy is not None
        and policy.status is RuleDataStatus.ACTIVE
    )
    review_achievement_rules = tuple(
        rule
        for rule in achievement_rules
        if rule.status is RuleDataStatus.REVIEW_REQUIRED
        or (policy is not None and policy.status is not RuleDataStatus.ACTIVE)
    )
    stale_achievement_rules = tuple(
        rule for rule in achievement_rules if rule.status is RuleDataStatus.STALE
    )
    conflicting_achievement_rules = tuple(
        rule for rule in achievement_rules if rule.status is RuleDataStatus.CONFLICT
    )
    unknown_combination = sum(
        rule.combination_policy.value == "unknown"
        and policy is not None
        and policy.default_combination_policy.value == "unknown"
        for rule in active_achievement_rules
    )
    coverage = snapshot.coverage
    coverage_complete = (
        coverage.status is AdmissionBenefitCoverageStatus.COMPLETE
        and coverage.required_documents_expected > 0
        and coverage.required_documents_captured == coverage.required_documents_expected
        and coverage.documents_captured == coverage.documents_selected
        and coverage.documents_parsed == coverage.documents_captured
    )
    source_gaps = len(snapshot.source_gaps)

    blockers: list[str] = []
    if not coverage_complete:
        blockers.append("required_source_documents_or_parse_coverage_incomplete")
    if coverage.conflicts or conflicting_rules:
        blockers.append("official_source_conflicts_present")
    if unresolved_targets:
        blockers.append("active_rule_targets_unresolved")
    if missing_100_subject:
        blockers.append("active_100_point_rule_missing_target_subject")
    if unknown_confirmation:
        blockers.append("active_olympiad_confirmation_requirement_unknown")
    if missing_confirmation_subject:
        blockers.append("active_confirmation_rule_missing_subject")
    if unknown_combination:
        blockers.append("active_individual_achievement_combination_unknown")
    if policy is not None and policy.status is not RuleDataStatus.ACTIVE:
        blockers.append("individual_achievement_policy_not_active")
    if any(not gap.can_continue for gap in snapshot.source_gaps):
        blockers.append("blocking_source_gaps_present")

    return BmstuAdmissionBenefitsReleaseReport(
        admission_year=snapshot.admission_year,
        education_level=education_level,
        coverage_status=coverage.status,
        required_documents_expected=coverage.required_documents_expected,
        required_documents_captured=coverage.required_documents_captured,
        documents_discovered=coverage.documents_discovered,
        documents_captured=coverage.documents_captured,
        source_hash_count=len(coverage.source_hashes),
        olympiads=len(snapshot.olympiads),
        olympiad_profiles=len(snapshot.olympiad_profiles),
        rules_by_route_benefit_result=dict(sorted(counts.items())),
        active_rules=len(active_rules),
        review_required_rules=len(review_rules),
        stale_rules=len(stale_rules),
        conflicting_rules=len(conflicting_rules) + coverage.conflicts,
        unresolved_active_targets=unresolved_targets,
        active_100_point_rules_without_subject=missing_100_subject,
        active_rules_with_unknown_confirmation=unknown_confirmation,
        active_rules_missing_confirmation_subject=missing_confirmation_subject,
        achievement_rules_active=len(active_achievement_rules),
        achievement_rules_review_required=len(review_achievement_rules),
        achievement_rules_stale=len(stale_achievement_rules),
        achievement_rules_conflicting=len(conflicting_achievement_rules),
        achievement_policy_status=policy.status if policy is not None else None,
        active_achievement_rules_with_unknown_combination=unknown_combination,
        source_gaps=source_gaps,
        coverage_complete=coverage_complete,
        production_ready=not blockers,
        blockers=tuple(blockers),
    )


__all__ = [
    "BmstuAdmissionBenefitsReleaseReport",
    "evaluate_bmstu_admission_benefits_release",
]
