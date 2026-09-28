from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from andromeda.ingestion.contracts.admission_benefits import (
    AdmissionBenefitCoverage,
    AdmissionBenefitParserDiagnostic,
    RawAdmissionBenefitRecord,
    RawAdmissionConfirmationThreshold,
    RawConfirmationThresholdCategory,
    RawIndividualAchievementDocumentNote,
    RawIndividualAchievementRecord,
)
from andromeda.ingestion.contracts.raw import SourceLocator
from andromeda.ingestion.universities.bmstu.admission_benefits.coverage import (
    build_coverage,
)
from andromeda.ingestion.universities.bmstu.normalizers.benefit_conflicts import (
    BenefitConflictGroup,
    detect_individual_achievement_conflicts,
)
from andromeda.ingestion.universities.bmstu.parser.admission_olympiads import (
    BmstuOlympiadProfileSource,
)
from andromeda.modules.admission_benefits.contracts.policy import (
    BenefitConditionKind,
    BenefitScope,
    BenefitScopeMode,
    BenefitTarget,
    BenefitTargetKind,
)
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AchievementCombinationPolicy,
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitCondition,
    BenefitType,
    ConfirmationApplicantCategory,
    ConfirmationExamKind,
    ConfirmationRequirement,
    ConfirmationSubjectRule,
    IndividualAchievementPolicy,
    IndividualAchievementRule,
    Olympiad,
    OlympiadProfile,
    OlympiadProfileSubject,
    OlympiadResultType,
    ValidityPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import (
    BenefitPolicyVersion,
    RuleDataStatus,
    TargetResolutionStatus,
)
from andromeda.modules.admissions.contracts.subject_identity import is_known_exam_subject
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import EducationLevel, SourceKind
from andromeda.shared.contracts.ids import UniversityId
from andromeda.shared.contracts.provenance import SourceAttribution


class IndividualAchievementNormalizationResult(ContractModel):
    policy: IndividualAchievementPolicy | None = None
    coverage: AdmissionBenefitCoverage
    diagnostics: tuple[AdmissionBenefitParserDiagnostic, ...] = ()
    conflicts: tuple[BenefitConflictGroup, ...] = ()


class OlympiadBenefitNormalizationResult(ContractModel):
    """Validated legal-rule candidates produced from BMSTU table rows."""

    olympiads: tuple[Olympiad, ...] = ()
    profiles: tuple[OlympiadProfile, ...] = ()
    rules: tuple[AdmissionBenefitRule, ...] = ()
    diagnostics: tuple[AdmissionBenefitParserDiagnostic, ...] = ()
    unresolved_targets: int = 0


class OlympiadProfileSourceEnrichment(ContractModel):
    """Parsed official profile evidence used to enrich a legal table row."""

    source: BmstuOlympiadProfileSource


@dataclass(frozen=True, slots=True)
class _IndividualAchievementCombination:
    global_max_points: Decimal
    default_policy: AchievementCombinationPolicy
    source_text: str
    source_note: RawIndividualAchievementDocumentNote


def normalize_olympiad_benefits(
    records: tuple[RawAdmissionBenefitRecord, ...],
    *,
    university_id: UniversityId,
    known_direction_codes: frozenset[str],
    policy_version: BenefitPolicyVersion,
    olympiad_result_max_age_years: int | None = None,
    olympiad_result_validity_text: str | None = None,
    olympiad_confirmation_min_score: Decimal | None = None,
    olympiad_confirmation_text: str | None = None,
    olympiad_confirmation_thresholds: tuple[RawAdmissionConfirmationThreshold, ...] = (),
    rule_policy_provenance: BenefitProvenance | None = None,
    validity_locator: SourceLocator | None = None,
    profile_sources: tuple[OlympiadProfileSourceEnrichment, ...] = (),
    direction_index: Mapping[str, str] | None = None,
) -> OlympiadBenefitNormalizationResult:
    """Normalize source rows without inventing a legal admission right."""

    olympiads: dict[str, Olympiad] = {}
    profiles: dict[str, OlympiadProfile] = {}
    rules: list[AdmissionBenefitRule] = []
    diagnostics: list[AdmissionBenefitParserDiagnostic] = []
    unresolved_targets = 0
    for record in records:
        values = {candidate.field: candidate.value for candidate in record.normalized_candidates}
        if values.get("benefit_granted") != "yes":
            if values.get("benefit_granted") == "unknown":
                diagnostics.append(_review_diagnostic(record, "benefit_granted_unknown", "benefit grant status is not source-resolved"))
            continue
        olympiad_name = values.get("olympiad_name")
        result_text = values.get("result_type")
        benefit_text = values.get("benefit_type")
        route_text = values.get("route", AdmissionRoute.OLYMPIAD.value)
        if route_text not in {item.value for item in AdmissionRoute}:
            diagnostics.append(_review_diagnostic(record, "benefit_route_unknown", "admission-benefit route is unresolved"))
            continue
        if not olympiad_name or result_text not in {item.value for item in OlympiadResultType} or benefit_text not in {item.value for item in BenefitType}:
            diagnostics.append(_review_diagnostic(record, "benefit_identity_incomplete", "olympiad, result type or benefit type is unresolved"))
            continue
        route = AdmissionRoute(route_text)
        if route not in {AdmissionRoute.OLYMPIAD, AdmissionRoute.VOSH, AdmissionRoute.INTERNATIONAL}:
            diagnostics.append(_review_diagnostic(record, "benefit_route_not_olympiad", "olympiad parser produced an unsupported legal route"))
            continue
        olympiad_id = _olympiad_id(olympiad_name)
        provenance = _provenance(record)
        profile_source = _profile_source_for(
            profile_sources,
            olympiad_name=olympiad_name,
            profile_name=values.get("profile_name"),
        )
        olympiads.setdefault(
            olympiad_id,
            Olympiad(
                id=olympiad_id,
                official_name=olympiad_name,
                rsosh_level=(profile_source.source.rsosh_level if profile_source is not None else None),
                admission_year=record.admission_year,
                provenance=(provenance,),
            ),
        )
        profile_id: str | None = None
        profile_name = values.get("profile_name")
        profile_subjects = _profile_subjects(
            values.get("target_subject")
            or values.get("corresponding_subject")
            or (values.get("profile_name") if values.get("profile_name") and is_known_exam_subject(values["profile_name"]) else None),
            profile_source.source.corresponding_subjects if profile_source is not None else (),
        )
        if profile_name and profile_subjects:
            profile_id = _profile_id(olympiad_id, profile_name)
            profile_provenance = (
                provenance,
                _profile_source_provenance(profile_source.source) if profile_source is not None else provenance,
            )
            profiles.setdefault(
                profile_id,
                OlympiadProfile(
                    id=profile_id,
                    olympiad_id=olympiad_id,
                    profile_name=profile_name,
                    corresponding_subjects=tuple(
                        OlympiadProfileSubject(subject=_bounded_text(subject), source_text=_bounded_text(subject))
                        for subject in profile_subjects
                    ),
                    admission_year=record.admission_year,
                    provenance=profile_provenance,
                ),
            )
        scope_mode = _scope_mode(values.get("scope_mode"), values.get("scope_text"))
        direction_codes = tuple(dict.fromkeys(_candidate_values(record, "scope_direction_code")))
        campus_ids = tuple(dict.fromkeys(_candidate_values(record, "scope_campus_id")))
        if direction_index:
            direction_codes = tuple(
                dict.fromkeys(
                    (
                        *direction_codes,
                        *(
                            code
                            for name in _candidate_values(record, "scope_direction_name")
                            if (code := direction_index.get(_normalize_identity(name))) is not None
                        ),
                    )
                )
            )
        scope_review_required = values.get("scope_review_required") == "yes"
        if (
            (scope_mode is None or (scope_mode is BenefitScopeMode.ONLY and not direction_codes))
            and benefit_text == BenefitType.ONE_HUNDRED_POINTS.value
            and values.get("target_subject")
            and not campus_ids
        ):
            # Appendix 5.3 can describe the target subject without enumerating
            # direction codes. Preserve the legal candidate, but never make it
            # active until the program/subject applicability is source-resolved.
            scope_mode = BenefitScopeMode.ALL
            scope_review_required = True
            diagnostics.append(
                _review_diagnostic(
                    record,
                    "hundred_point_program_scope_unknown",
                    "100-point row contains a target subject but no resolved program or direction scope",
                )
            )
        elif (
            benefit_text == BenefitType.ONE_HUNDRED_POINTS.value
            and not direction_codes
            and _candidate_values(record, "scope_direction_name")
        ):
            diagnostics.append(
                _review_diagnostic(
                    record,
                    "hundred_point_program_scope_unresolved",
                    "official direction names did not resolve to a unique catalog direction code",
                )
            )
        if scope_mode is None or (
            scope_mode is not BenefitScopeMode.ALL and not direction_codes and not campus_ids
        ):
            diagnostics.append(_review_diagnostic(record, "benefit_scope_unknown", "program/direction scope is not source-resolved"))
            continue
        scope_text = values.get("scope_text") or "Официальная таблица не содержит отдельного текста области применения"
        scope = (
            BenefitScope(
                mode=scope_mode,
                targets=tuple(
                    BenefitTarget(
                        kind=BenefitTargetKind.CAMPUS,
                        value=campus_id,
                        original_text=_bounded_text(scope_text, limit=512),
                    )
                    for campus_id in campus_ids
                ),
                original_text=_bounded_text(scope_text, limit=2_000),
            )
            if campus_ids
            else normalize_direction_scope(
                mode=scope_mode,
                direction_codes=direction_codes,
                original_text=_bounded_text(scope_text, limit=2_000),
                known_direction_codes=known_direction_codes,
            )
        )
        unresolved_targets += len(scope.unresolved_targets)
        status = RuleDataStatus.REVIEW_REQUIRED if scope.unresolved_targets or scope_review_required else RuleDataStatus.ACTIVE
        benefit_type = BenefitType(benefit_text)
        target_subject = values.get("target_subject") if benefit_type is BenefitType.ONE_HUNDRED_POINTS else None
        if benefit_type is BenefitType.ONE_HUNDRED_POINTS and not target_subject:
            diagnostics.append(_review_diagnostic(record, "hundred_point_subject_unknown", "100-point target subject was not extracted"))
            continue
        confirmation_score = _decimal(values.get("confirmation_min_score"))
        confirmation_subject = values.get("confirmation_subject")
        confirmation_subjects: tuple[ConfirmationSubjectRule, ...] = ()
        confirmation_requirement = (
            ConfirmationRequirement.NOT_REQUIRED
            if values.get("confirmation_required") == "no"
            else ConfirmationRequirement.UNKNOWN
        )
        applies_shared_confirmation = (
            benefit_type in {BenefitType.BVI, BenefitType.ONE_HUNDRED_POINTS}
            and route is AdmissionRoute.OLYMPIAD
        )
        thresholds = olympiad_confirmation_thresholds
        if not thresholds and olympiad_confirmation_min_score is not None and applies_shared_confirmation:
            thresholds = (
                RawAdmissionConfirmationThreshold(
                    minimum_score=olympiad_confirmation_min_score,
                    applicant_category=RawConfirmationThresholdCategory.GENERAL,
                    exam_kinds=("ege",),
                    source_text=_bounded_text(
                        olympiad_confirmation_text
                        or "Confirmation threshold source text is unavailable"
                    ),
                    locator=record.locator,
                ),
            )
        if applies_shared_confirmation and thresholds:
            confirmation_subject = confirmation_subject or ", ".join(profile_subjects)
            if confirmation_subject:
                confirmation_subjects = tuple(
                    ConfirmationSubjectRule(
                        subject=subject,
                        minimum_score=threshold.minimum_score,
                        exam_kind=_confirmation_exam_kind(exam_kind),
                        applicant_category=_confirmation_category(threshold.applicant_category),
                        source_text=_bounded_text(threshold.source_text),
                    )
                    for subject in _subjects(confirmation_subject)
                    for threshold in thresholds
                    for exam_kind in threshold.exam_kinds
                )
                confirmation_requirement = ConfirmationRequirement.REQUIRED
            else:
                confirmation_requirement = ConfirmationRequirement.UNKNOWN
                diagnostics.append(_review_diagnostic(record, "confirmation_subject_unknown", "confirmation threshold has no resolved subject"))
        elif confirmation_score is not None:
            confirmation_requirement = ConfirmationRequirement.REQUIRED
            if confirmation_subject:
                confirmation_subjects = tuple(
                    ConfirmationSubjectRule(
                        subject=subject,
                        minimum_score=confirmation_score,
                        exam_kind=ConfirmationExamKind.EGE,
                        source_text=_bounded_text(values.get("confirmation_text", "Официальная таблица подтверждения олимпиады")),
                    )
                    for subject in _subjects(confirmation_subject)
                )
            else:
                diagnostics.append(_review_diagnostic(record, "confirmation_subject_unknown", "confirmation threshold has no resolved subject"))
        if applies_shared_confirmation and not thresholds:
            confirmation_requirement = ConfirmationRequirement.UNKNOWN
            diagnostics.append(_review_diagnostic(record, "confirmation_policy_missing", "Rules confirmation thresholds were not source-resolved"))
        confirmation_policy_needs_review = applies_shared_confirmation and (
            not thresholds
            or not confirmation_subjects
            or rule_policy_provenance is None
            or any(
                threshold.applicant_category is RawConfirmationThresholdCategory.UNKNOWN
                or "unknown" in threshold.exam_kinds
                for threshold in thresholds
            )
        )
        validity_policy_needs_review = (
            route is AdmissionRoute.OLYMPIAD
            and olympiad_result_max_age_years is None
        )
        if confirmation_policy_needs_review and thresholds:
            diagnostics.append(_review_diagnostic(record, "confirmation_policy_incomplete", "threshold category, exam kind, subject or Rules provenance remains unresolved"))
        if validity_policy_needs_review:
            diagnostics.append(
                _review_diagnostic(
                    record,
                    "olympiad_validity_policy_missing",
                    "Rules validity period was not source-resolved",
                )
            )
        conditions = [
            BenefitCondition(kind=BenefitConditionKind.RESULT_TYPE, source_text=_bounded_text(record.raw_text), normalized_value=result_text),
        ]
        if rule_policy_provenance is not None and thresholds and applies_shared_confirmation:
            if profile_source is not None and profile_subjects:
                conditions.append(
                    BenefitCondition(
                        kind=BenefitConditionKind.OTHER,
                        source_text=_bounded_text(profile_source.source.source_title),
                        normalized_value="confirmation_subjects=" + ",".join(profile_subjects),
                        provenance=_profile_source_provenance(profile_source.source),
                    )
                )
            for threshold in thresholds:
                policy_source = rule_policy_provenance.source.model_copy(
                    update={"locator": f"page={threshold.locator.page};{threshold.locator.field}"}
                )
                conditions.append(
                    BenefitCondition(
                        kind=BenefitConditionKind.CONFIRMATION_SCORE,
                        source_text=_bounded_text(threshold.source_text),
                        normalized_value=(
                            f"minimum_score={threshold.minimum_score};"
                            f"applicant_category={threshold.applicant_category.value};"
                            f"exam_kinds={','.join(threshold.exam_kinds)}"
                        ),
                        provenance=rule_policy_provenance.model_copy(
                            update={
                                "source": policy_source,
                                "page": threshold.locator.page,
                                "section": threshold.locator.field,
                            }
                        ),
                    )
                )
        elif olympiad_confirmation_min_score is not None and applies_shared_confirmation:
            conditions.append(
                BenefitCondition(
                    kind=BenefitConditionKind.CONFIRMATION_SCORE,
                    source_text=_bounded_text(
                        olympiad_confirmation_text
                        or "Правила приёма устанавливают минимальный балл подтверждения олимпиады"
                    ),
                    normalized_value=str(olympiad_confirmation_min_score),
                )
            )
        if (
            rule_policy_provenance is not None
            and olympiad_result_max_age_years is not None
            and olympiad_result_validity_text
        ):
            validity_page = validity_locator.page if validity_locator else rule_policy_provenance.page
            validity_field = (
                validity_locator.field if validity_locator else None
            ) or "section=1.11"
            validity_source = rule_policy_provenance.source.model_copy(
                update={
                    "locator": (
                        f"page={validity_page};{validity_field}"
                        if validity_page is not None
                        else validity_field
                    )
                }
            )
            validity_provenance = rule_policy_provenance.model_copy(
                update={
                    "source": validity_source,
                    "page": validity_page,
                    "section": validity_field.removeprefix("section="),
                }
            )
            conditions.append(
                BenefitCondition(
                    kind=BenefitConditionKind.VALIDITY,
                    source_text=_bounded_text(olympiad_result_validity_text),
                    normalized_value=f"max_age_years={olympiad_result_max_age_years}",
                    provenance=validity_provenance,
                )
            )
        rules.append(
            AdmissionBenefitRule(
                id=_rule_id(record, benefit_type, result_text, profile_id),
                university_id=university_id,
                admission_year=record.admission_year,
                route=route,
                benefit_type=benefit_type,
                olympiad_id=olympiad_id,
                olympiad_profile_id=profile_id,
                result_type=OlympiadResultType(result_text),
                scope=scope,
                confirmation_requirement=confirmation_requirement,
                confirmation_subjects=confirmation_subjects,
                validity=ValidityPolicy(
                    max_age_years=olympiad_result_max_age_years,
                    source_text=(
                        olympiad_result_validity_text
                        or "Срок действия результата не извлечён из этой таблицы"
                    ),
                ),
                target_subject=target_subject,
                points=Decimal(100) if benefit_type is BenefitType.ONE_HUNDRED_POINTS else None,
                conditions=tuple(_dedupe_conditions(conditions)),
                source_text=_bounded_text(record.raw_text),
                status=(
                    RuleDataStatus.REVIEW_REQUIRED
                    if confirmation_policy_needs_review or validity_policy_needs_review
                    else status
                ),
                policy_version=policy_version,
                provenance=provenance,
            )
        )
    return OlympiadBenefitNormalizationResult(
        olympiads=tuple(olympiads.values()),
        profiles=tuple(profiles.values()),
        rules=tuple(rules),
        diagnostics=tuple(diagnostics),
        unresolved_targets=unresolved_targets,
    )


def normalize_individual_achievements(
    records: tuple[RawIndividualAchievementRecord, ...],
    *,
    university_id: UniversityId,
    policy_version: BenefitPolicyVersion,
    documents_discovered: int | None = None,
    documents_captured: int | None = None,
) -> IndividualAchievementNormalizationResult:
    conflicts = detect_individual_achievement_conflicts(records)
    conflicted_ids = {record_id for group in conflicts for record_id in group.record_ids}
    diagnostics = [diagnostic for record in records for diagnostic in record.diagnostics]
    combination = _individual_achievement_combination_policy(records)
    if combination is None:
        diagnostics.extend(
            _review_diagnostic(
                record,
                "individual_achievement_combination_policy_unknown",
                "The official source does not provide a complete, unambiguous sum-and-cap policy",
            )
            for record in records[:1]
        )
    rules: list[IndividualAchievementRule] = []
    variant_counts: dict[tuple[str, str, int | None], int] = {}
    for record in records:
        row_identity = (
            record.source_snapshot_hash,
            record.document_kind,
            record.locator.row,
        )
        variant_counts[row_identity] = variant_counts.get(row_identity, 0) + 1
    for record in records:
        name = record.official_name_candidate or _candidate(record, "official_name")
        points_text = record.points_text or _candidate(record, "points")
        points = _decimal(points_text)
        if not name or points is None:
            continue
        category = (
            record.achievement_code_candidate
            or _candidate(record, "category")
            or (
                f"{record.document_kind}:row:{record.locator.row}"
                if record.locator.row is not None
                else "unresolved"
            )
        )
        variant_identity = record.variant_label or record.required_document_text
        canonical_name = (
            f"{name} — {variant_identity}" if variant_identity else name
        )
        code = _achievement_code(name, variant_identity)
        row_identity = (
            record.source_snapshot_hash,
            record.document_kind,
            record.locator.row,
        )
        has_sourced_variants = (
            variant_counts.get(row_identity, 0) > 1
            and combination is not None
        )
        combination_group = (
            f"{record.document_kind}:{record.locator.row}"
            if has_sourced_variants and record.locator.row is not None
            else None
        )
        status = RuleDataStatus.CONFLICT if record.record_id in conflicted_ids else RuleDataStatus.ACTIVE
        if record.diagnostics and status is not RuleDataStatus.CONFLICT:
            status = RuleDataStatus.REVIEW_REQUIRED
        rules.append(
            IndividualAchievementRule(
                id=f"individual-achievement:{sha256((record.record_id + name).encode('utf-8')).hexdigest()[:24]}",
                university_id=university_id,
                admission_year=record.admission_year,
                education_level=_education_level(record),
                achievement_code=code,
                category=category,
                official_name=_bounded_text(canonical_name),
                points=points,
                combination_group=combination_group,
                combination_policy=(
                    AchievementCombinationPolicy.MAX_ONLY
                    if combination_group is not None
                    else (
                        combination.default_policy
                        if combination is not None
                        else AchievementCombinationPolicy.UNKNOWN
                    )
                ),
                required_document=_bounded_text(record.required_document_text or _candidate(record, "required_document")) if (record.required_document_text or _candidate(record, "required_document")) else None,
                conditions=_individual_achievement_source_conditions(record),
                source_text=_bounded_text(record.raw_text),
                status=status,
                policy_version=policy_version,
                provenance=_provenance(record),
            )
        )
    policy = None
    if rules:
        policy_provenance = _individual_achievement_policy_provenance(
            records, combination
        )
        policy = IndividualAchievementPolicy(
            university_id=university_id,
            admission_year=rules[0].admission_year,
            education_level=None,
            global_max_points=(
                combination.global_max_points if combination is not None else None
            ),
            default_combination_policy=(
                combination.default_policy
                if combination is not None
                else AchievementCombinationPolicy.UNKNOWN
            ),
            rules=tuple(rules),
            source_text=(
                _bounded_text(combination.source_text)
                if combination is not None
                else "Политика суммирования ИД не подтверждена источником"
            ),
            status=(
                RuleDataStatus.CONFLICT
                if conflicts
                else (
                    RuleDataStatus.REVIEW_REQUIRED
                    if diagnostics or combination is None
                    else RuleDataStatus.ACTIVE
                )
            ),
            policy_version=policy_version,
            provenance=policy_provenance,
        )
    coverage = build_coverage(
        documents_discovered=documents_discovered if documents_discovered is not None else len({record.source_snapshot_hash for record in records}),
        documents_captured=documents_captured if documents_captured is not None else len({record.source_snapshot_hash for record in records}),
        records=tuple(record for record in records),
        normalized_count=len(rules),
        conflicts=len(conflicts),
        review_required_rows=len(diagnostics),
    )
    return IndividualAchievementNormalizationResult(
        policy=policy,
        coverage=coverage,
        diagnostics=tuple(diagnostics),
        conflicts=conflicts,
    )


def normalize_direction_scope(
    *,
    mode: BenefitScopeMode,
    direction_codes: tuple[str, ...],
    original_text: str,
    known_direction_codes: frozenset[str],
) -> BenefitScope:
    targets = tuple(
        BenefitTarget(
            kind=BenefitTargetKind.DIRECTION,
            value=code,
            original_text=code,
            resolution=TargetResolutionStatus.RESOLVED if code in known_direction_codes else TargetResolutionStatus.UNRESOLVED,
        )
        for code in direction_codes
    )
    if mode is BenefitScopeMode.ALL:
        return BenefitScope(mode=mode, excluded_targets=targets, original_text=original_text)
    return BenefitScope(mode=mode, targets=targets, original_text=original_text)


def _individual_achievement_combination_policy(
    records: tuple[RawIndividualAchievementRecord, ...],
) -> _IndividualAchievementCombination | None:
    notes: dict[str, RawIndividualAchievementDocumentNote] = {}
    for record in records:
        for note in record.document_notes:
            existing = notes.get(note.marker)
            if existing is not None and existing.source_text != note.source_text:
                return None
            notes[note.marker] = note

    sum_note = notes.get("2")
    category_note = notes.get("4")
    if sum_note is None or category_note is None:
        return None

    sum_text = _normalize_policy_text(sum_note.source_text)
    category_text = _normalize_policy_text(category_note.source_text)
    permits_sum = re.search(
        r"суммир\w*\s+балл\w*.*различн\w+\s+достижен\w+",
        sum_text,
    ) is not None
    cap_match = re.search(
        r"(?:не\s+более|не\s+может\s+быть\s+более|не\s+может\s+превышать)"
        r"\s*(\d{1,2})\s+балл\w*",
        sum_text,
    )
    single_category_award = (
        re.search(r"достижен\w+.*(?:однократн\w*|один\s+раз)", category_text)
        is not None
        and re.search(
            r"категор\w+.*(?:однократн\w*|один\s+раз)", category_text
        )
        is not None
    )
    if not permits_sum or cap_match is None or not single_category_award:
        return None

    cap = Decimal(cap_match.group(1))
    if cap < 0 or cap > 100:
        return None
    return _IndividualAchievementCombination(
        global_max_points=cap,
        default_policy=AchievementCombinationPolicy.ADDITIVE,
        source_text=f"{sum_note.source_text} {category_note.source_text}",
        source_note=sum_note,
    )


def _individual_achievement_policy_provenance(
    records: tuple[RawIndividualAchievementRecord, ...],
    combination: _IndividualAchievementCombination | None,
) -> BenefitProvenance:
    if combination is None or not records:
        return _provenance(records[0])
    evidence_record = next(
        (
            record
            for record in records
            if combination.source_note in record.document_notes
        ),
        records[0],
    )
    return _provenance(
        evidence_record.model_copy(update={"locator": combination.source_note.locator})
    )


def _individual_achievement_source_conditions(
    record: RawIndividualAchievementRecord,
) -> tuple[BenefitCondition, ...]:
    conditions: list[BenefitCondition] = []
    if record.combination_text:
        conditions.append(
            BenefitCondition(
                kind=BenefitConditionKind.OTHER,
                source_text=_bounded_text(record.combination_text),
            )
        )
    for note in record.document_notes:
        if note.marker not in {"2", "4"}:
            continue
        note_record = record.model_copy(update={"locator": note.locator})
        conditions.append(
            BenefitCondition(
                kind=BenefitConditionKind.OTHER,
                source_text=_bounded_text(note.source_text),
                normalized_value=f"appendix_6_note:{note.marker}",
                provenance=_provenance(note_record),
            )
        )
    return tuple(conditions)


def _normalize_policy_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _candidate(record: RawAdmissionBenefitRecord, field: str) -> str | None:
    return next((candidate.value for candidate in record.normalized_candidates if candidate.field == field), None)


def _bounded_text(value: str | None, *, limit: int = 512) -> str:
    """Fit source excerpts into canonical bounded text fields.

    The complete official value remains in the raw source snapshot and raw
    candidates. Canonical entities keep a deterministic excerpt so a single
    malformed/very wide PDF row cannot abort the whole ingestion run.
    """
    normalized = (value or "").strip()
    if not normalized:
        return "Неизвестно"
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", ".").strip())
    except InvalidOperation:
        return None


def _subjects(value: str) -> tuple[str, ...]:
    """Split source-listed confirmation subjects without changing their wording."""

    parts = re.split(r"\s*(?:,|;|\s+и\s+)\s*", value, flags=re.IGNORECASE)
    return tuple(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _confirmation_exam_kind(value: str) -> ConfirmationExamKind:
    try:
        return ConfirmationExamKind(value)
    except ValueError:
        return ConfirmationExamKind.UNKNOWN


def _confirmation_category(
    value: RawConfirmationThresholdCategory,
) -> ConfirmationApplicantCategory | None:
    if value is RawConfirmationThresholdCategory.GENERAL:
        return None
    if value is RawConfirmationThresholdCategory.TERRITORIAL_EXCEPTION:
        return ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION
    return ConfirmationApplicantCategory.UNKNOWN


def _dedupe_conditions(conditions: list[BenefitCondition]) -> tuple[BenefitCondition, ...]:
    unique: dict[str, BenefitCondition] = {}
    for condition in conditions:
        key = repr(condition.model_dump(mode="json"))
        unique.setdefault(key, condition)
    return tuple(unique.values())


def _code(value: str) -> str:
    transliterated = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return f"bmstu-{transliterated or sha256(value.encode('utf-8')).hexdigest()[:16]}"


def _achievement_code(name: str, variant: str | None) -> str:
    base = _code(name)
    if not variant:
        return base
    digest = sha256(f"{name.casefold()}|{variant.casefold()}".encode()).hexdigest()[:12]
    return f"{base}-variant-{digest}"


def _education_level(record: RawIndividualAchievementRecord) -> EducationLevel | None:
    candidate = _candidate(record, "education_level")
    if candidate == "master" or record.document_kind == "appendix_7":
        return EducationLevel.MASTER
    return None


def _profile_source_for(
    sources: tuple[OlympiadProfileSourceEnrichment, ...],
    *,
    olympiad_name: str,
    profile_name: str | None,
) -> OlympiadProfileSourceEnrichment | None:
    if not profile_name:
        return None
    key = (_normalize_identity(olympiad_name), _normalize_identity(profile_name))
    return next(
        (
            source
            for source in sources
            if (
                _normalize_identity(source.source.olympiad_name),
                _normalize_identity(source.source.profile_name),
            )
            == key
        ),
        None,
    )


def _profile_subjects(
    row_subject: str | None,
    source_subjects: tuple[str, ...],
) -> tuple[str, ...]:
    if row_subject:
        return _subjects(row_subject)
    return tuple(dict.fromkeys(subject.strip() for subject in source_subjects if subject.strip()))


def _profile_source_provenance(source: BmstuOlympiadProfileSource) -> BenefitProvenance:
    source_attribution = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url=source.source_url,
        captured_at=source.captured_at,
        content_sha256=source.source_snapshot_hash,
        university_id="university:bmstu",
        run_id=source.source_run_id,
        locator=source.locator.field,
    )
    return BenefitProvenance(
        source=source_attribution,
        source_snapshot_hash=source.source_snapshot_hash,
        source_run_id=source.source_run_id,
        admission_year=source.admission_year,
        document_title=source.source_title,
        document_kind="official_olympiad_profile",
        section=source.locator.field,
        parser_version="bmstu-admission-olympiad-profile.v1",
    )


def _normalize_identity(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def _combination_policy(record: RawIndividualAchievementRecord) -> AchievementCombinationPolicy:
    candidate = _candidate(record, "combination_policy")
    try:
        return AchievementCombinationPolicy(candidate) if candidate else AchievementCombinationPolicy.UNKNOWN
    except ValueError:
        return AchievementCombinationPolicy.UNKNOWN


def _candidate_values(record: RawAdmissionBenefitRecord, field: str) -> tuple[str, ...]:
    return tuple(candidate.value for candidate in record.normalized_candidates if candidate.field == field)


def _scope_mode(value: str | None, text: str | None) -> BenefitScopeMode | None:
    normalized = (value or text or "").casefold()
    try:
        return BenefitScopeMode(normalized)
    except ValueError:
        if "кроме" in normalized or "за исключением" in normalized or "except" in normalized:
            return BenefitScopeMode.ALL_EXCEPT
        if "только" in normalized or "only" in normalized:
            return BenefitScopeMode.ONLY
        if "все" in normalized or "all" in normalized:
            return BenefitScopeMode.ALL
        return None


def _olympiad_id(name: str) -> str:
    return "olympiad:bmstu-" + sha256(name.casefold().strip().encode("utf-8")).hexdigest()[:24]


def _profile_id(olympiad_id: str, name: str) -> str:
    return "olympiad-profile:bmstu-" + sha256(f"{olympiad_id}|{name.casefold().strip()}".encode()).hexdigest()[:24]


def _rule_id(
    record: RawAdmissionBenefitRecord,
    benefit_type: BenefitType,
    result_type: str,
    profile_id: str | None,
) -> str:
    identity = f"{record.record_id}|{benefit_type.value}|{result_type}|{profile_id or ''}"
    return "admission-benefit:" + sha256(identity.encode("utf-8")).hexdigest()[:24]


def _provenance(record: RawAdmissionBenefitRecord) -> BenefitProvenance:
    kind = (
        SourceKind.BMSTU_ADMISSION_INDIVIDUAL_ACHIEVEMENTS
        if record.document_kind in {"appendix_6", "appendix_7"}
        else SourceKind.BMSTU_ADMISSION_BENEFITS
    )
    locator = ";".join(
        value
        for value in (
            f"page={record.locator.page}" if record.locator.page is not None else None,
            f"row={record.locator.row}" if record.locator.row is not None else None,
            f"field={record.locator.field}" if record.locator.field else None,
        )
        if value
    )
    source = SourceAttribution(
        kind=kind,
        url=record.source_url,
        captured_at=record.captured_at,
        content_sha256=record.source_snapshot_hash,
        locator=locator or None,
        university_id="university:bmstu",
        run_id=record.source_run_id,
        record_key=record.record_id,
    )
    return BenefitProvenance(
        source=source,
        source_snapshot_hash=record.source_snapshot_hash,
        source_run_id=record.source_run_id,
        admission_year=record.admission_year,
        document_title=record.document_title,
        document_kind=record.document_kind,
        appendix_number=record.document_kind.removeprefix("appendix_") if record.document_kind.startswith("appendix_") else None,
        page=record.locator.page,
        table=record.locator.field,
        row=record.locator.row,
        section=record.locator.field,
        parser_version=record.parser_version,
    )


def _review_diagnostic(record: RawAdmissionBenefitRecord, code: str, message: str) -> AdmissionBenefitParserDiagnostic:
    return AdmissionBenefitParserDiagnostic(
        code=code,
        stage="normalization",
        message=message,
        severity="ambiguous",
        locator=record.locator,
    )


__all__ = [
    "IndividualAchievementNormalizationResult",
    "OlympiadBenefitNormalizationResult",
    "normalize_direction_scope",
    "normalize_individual_achievements",
    "normalize_olympiad_benefits",
]
