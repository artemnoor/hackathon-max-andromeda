"""Small source-backed contracts reused by admission-benefit service tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantIndividualAchievement,
    ApplicantOlympiadAchievement,
)
from andromeda.modules.admission_benefits.contracts.policy import (
    BenefitScope,
    BenefitScopeMode,
    BenefitTarget,
    BenefitTargetKind,
)
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    AdmissionRoute,
    AchievementCombinationPolicy,
    BenefitType,
    ConfirmationExamKind,
    ConfirmationRequirement,
    ConfirmationSubjectRule,
    IndividualAchievementPolicy,
    IndividualAchievementRule,
    OlympiadResultType,
    ValidityPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import BenefitPolicyVersion, RuleDataStatus
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import SourceAttribution


PROGRAM_ID = "program:bmstu:09.03.03-01"
DIRECTION_CODE = "09.03.03"
RUN_ID = "ingest:" + "a" * 32
VERSIONS = BenefitPolicyVersion(
    schema_version="admission-benefits-schema.v1",
    parser_version="admission-benefits-parser.v1",
    policy_version="admission-benefits-policy.v1",
)


def provenance(locator: str = "appendix=5.1;page=1;row=1") -> BenefitProvenance:
    source_hash = "a" * 64
    source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url="https://api.www.bmstu.ru/file/124777/download",
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        content_sha256=source_hash,
        locator=locator,
        run_id=RUN_ID,
    )
    return BenefitProvenance(
        source=source,
        source_snapshot_hash=source_hash,
        source_run_id=RUN_ID,
        admission_year=2026,
        document_title="Правила приема МГТУ 2026",
        document_kind="rules_2026",
        appendix_number="5.1",
        page=1,
        row=1,
        parser_version="bmstu-admission-parser.v1",
    )


def validity(max_age_years: int | None = 4) -> ValidityPolicy:
    return ValidityPolicy(
        max_age_years=max_age_years,
        source_text="Правила приема 2026: результат олимпиады действует четыре года",
    )


def scope_all() -> BenefitScope:
    return BenefitScope(mode=BenefitScopeMode.ALL, original_text="Все направления")


def scope_only(*values: str, kind: BenefitTargetKind = BenefitTargetKind.DIRECTION) -> BenefitScope:
    return BenefitScope(
        mode=BenefitScopeMode.ONLY,
        targets=tuple(BenefitTarget(kind=kind, value=value, original_text=value) for value in values),
        original_text="Только: " + ", ".join(values),
    )


def scope_all_except(*values: str) -> BenefitScope:
    return BenefitScope(
        mode=BenefitScopeMode.ALL_EXCEPT,
        targets=tuple(BenefitTarget(kind=BenefitTargetKind.DIRECTION, value=value, original_text=value) for value in values),
        original_text="Все, кроме: " + ", ".join(values),
    )


def olympiad_rule(
    *,
    benefit_type: BenefitType = BenefitType.BVI,
    result_type: OlympiadResultType = OlympiadResultType.WINNER,
    rule_id: str = "admission-benefit:bmstu-shag-winner-bvi",
    scope: BenefitScope | None = None,
    confirmation_requirement: ConfirmationRequirement = ConfirmationRequirement.NOT_REQUIRED,
    confirmation_subjects: tuple[ConfirmationSubjectRule, ...] = (),
    target_subject: str | None = None,
    points: Decimal | None = None,
    olympiad_profile_id: str | None = None,
    status: RuleDataStatus = RuleDataStatus.ACTIVE,
) -> AdmissionBenefitRule:
    return AdmissionBenefitRule(
        id=rule_id,
        university_id="university:bmstu",
        admission_year=2026,
        route=AdmissionRoute.OLYMPIAD,
        benefit_type=benefit_type,
        olympiad_id="olympiad:shag-v-budushchee",
        olympiad_profile_id=olympiad_profile_id,
        result_type=OlympiadResultType(result_type),
        scope=scope or scope_all(),
        confirmation_requirement=confirmation_requirement,
        confirmation_subjects=confirmation_subjects,
        validity=validity(),
        target_subject=target_subject,
        points=points,
        source_text="Официальное правило МГТУ 2026",
        status=RuleDataStatus(status),
        policy_version=VERSIONS,
        provenance=provenance(),
    )


def olympiad_fact(
    *,
    result_year: int = 2026,
    result_type: OlympiadResultType = OlympiadResultType.WINNER,
    profile_id: str | None = None,
) -> ApplicantOlympiadAchievement:
    return ApplicantOlympiadAchievement(
        olympiad_id="olympiad:shag-v-budushchee",
        olympiad_profile_id=profile_id,
        result_year=result_year,
        result_type=OlympiadResultType(result_type),
    )


def achievement_rule(
    code: str,
    points: str,
    *,
    category: str = "other",
    category_cap: str | None = None,
    group: str | None = None,
    combination: AchievementCombinationPolicy = AchievementCombinationPolicy.ADDITIVE,
    required_document: str | None = None,
    rule_id: str | None = None,
) -> IndividualAchievementRule:
    return IndividualAchievementRule(
        id=rule_id or f"individual-achievement:bmstu-{re.sub(r'[^a-z0-9-]+', '-', code.casefold()).strip('-')}",
        university_id="university:bmstu",
        admission_year=2026,
        achievement_code=code,
        category=category,
        official_name=code,
        points=Decimal(points),
        category_cap=Decimal(category_cap) if category_cap is not None else None,
        combination_group=group,
        combination_policy=combination,
        required_document=required_document,
        source_text=f"{code}: {points} баллов",
        policy_version=VERSIONS,
        provenance=provenance("appendix=6;page=1;row=1"),
    )


def achievement_policy(
    *rules: IndividualAchievementRule,
    global_max_points: str | None = None,
    default_combination_policy: AchievementCombinationPolicy = AchievementCombinationPolicy.UNKNOWN,
    status: RuleDataStatus = RuleDataStatus.ACTIVE,
) -> IndividualAchievementPolicy:
    return IndividualAchievementPolicy(
        university_id="university:bmstu",
        admission_year=2026,
        global_max_points=Decimal(global_max_points) if global_max_points is not None else None,
        default_combination_policy=default_combination_policy,
        rules=tuple(rules),
        source_text="Приложение 6 МГТУ 2026",
        status=status,
        policy_version=VERSIONS,
        provenance=provenance("appendix=6;page=1;table=1"),
    )


def achievement_fact(code: str, *, year: int = 2026, evidence: str | None = "document:present") -> ApplicantIndividualAchievement:
    return ApplicantIndividualAchievement(
        achievement_code=code,
        year=year,
        evidence_reference=evidence,
    )


__all__ = [
    "DIRECTION_CODE",
    "PROGRAM_ID",
    "RUN_ID",
    "VERSIONS",
    "achievement_fact",
    "achievement_policy",
    "achievement_rule",
    "olympiad_fact",
    "olympiad_rule",
    "provenance",
    "scope_all",
    "scope_all_except",
    "scope_only",
    "validity",
]
