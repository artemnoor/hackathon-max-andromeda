"""SQLAlchemy adapter for canonical admission-benefit rules."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from andromeda.modules.admission_benefits.contracts.domain_revision import (
    admission_benefit_revision_hash,
)
from andromeda.modules.admission_benefits.contracts.policy import (
    BenefitScope,
    BenefitScopeMode,
    BenefitTarget,
    BenefitTargetKind,
)
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
from andromeda.modules.admission_benefits.contracts.snapshot import (
    AdmissionBenefitsSnapshot,
)
from andromeda.modules.admission_benefits.contracts.status import (
    RuleDataStatus,
    TargetResolutionStatus,
)
from andromeda.modules.admission_benefits.repository.ports import (
    AdmissionBenefitRepository,
    AdmissionBenefitSyncStats,
)
from andromeda.shared.contracts.enums import EducationLevel, SourceKind
from andromeda.shared.contracts.ids import (
    AdmissionCampusId,
    DirectionCode,
    EducationYear,
    IngestRunId,
    OlympiadId,
    ProgramId,
    UniversityId,
    canonical_program_id,
)
from andromeda.shared.contracts.provenance import (
    GapSeverity,
    SourceAttribution,
    SourceGapReference,
)
from andromeda.shared.contracts.versions import (
    ADMISSION_BENEFITS_PARSER_VERSION,
    ADMISSION_BENEFITS_POLICY_VERSION,
    ADMISSION_BENEFITS_SCHEMA_VERSION,
)

from ..database.models import (
    AdmissionBenefitIngestionCoverageModel,
    AdmissionBenefitOlympiadModel,
    AdmissionBenefitOlympiadProfileModel,
    AdmissionBenefitProfileSubjectModel,
    AdmissionBenefitRuleModel,
    AdmissionBenefitRuleScopeModel,
    AdmissionBenefitRuleSubjectModel,
    DirectionModel,
    IndividualAchievementPolicyModel,
    IndividualAchievementRuleModel,
    ProgramModel,
)

logger = logging.getLogger("andromeda.infrastructure.repositories.admission_benefits")
_ACTIVE_STATUSES = (RuleDataStatus.ACTIVE.value,)
_NON_STALE_STATUSES = tuple(
    status.value for status in RuleDataStatus if status is not RuleDataStatus.STALE
)


class SqlAlchemyAdmissionBenefitsRepository(AdmissionBenefitRepository):
    """Session-scoped repository; transaction ownership remains with the caller."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def sync_snapshot(
        self,
        snapshot: AdmissionBenefitsSnapshot,
        *,
        source_run_id: IngestRunId,
    ) -> AdmissionBenefitSyncStats:
        started = perf_counter()
        self._validate_source_run(snapshot, source_run_id)
        university_id = _snapshot_university_id(snapshot)
        if university_id is None:
            raise ValueError("admission-benefit snapshot must identify its university")
        stale_rows = self._stale_snapshot_sources(snapshot, university_id)
        olympiad_counts = [0, 0]
        profile_counts = [0, 0]
        rule_counts = [0, 0]
        achievement_counts = [0, 0]
        conflict_rows = 0

        for olympiad in snapshot.olympiads:
            outcome = self._upsert_olympiad(olympiad)
            olympiad_counts[_outcome_index(outcome)] += 1
        self._session.flush()
        for profile in snapshot.olympiad_profiles:
            outcome = self._upsert_profile(profile)
            profile_counts[_outcome_index(outcome)] += 1
            self._replace_profile_subjects(profile)
        self._session.flush()
        for benefit_rule in snapshot.benefit_rules:
            outcome = self._upsert_benefit_rule(benefit_rule)
            rule_counts[_outcome_index(outcome)] += 1
            conflict_rows += int(benefit_rule.status is RuleDataStatus.CONFLICT)
            self._replace_rule_children(benefit_rule)
        self._session.flush()
        if snapshot.individual_achievement_policy is not None:
            policy = snapshot.individual_achievement_policy
            self._upsert_achievement_policy(policy)
            self._session.flush()
            for achievement_rule in policy.rules:
                outcome = self._upsert_achievement_rule(policy, achievement_rule)
                achievement_counts[_outcome_index(outcome)] += 1
                conflict_rows += int(achievement_rule.status is RuleDataStatus.CONFLICT)
        self._session.flush()
        self._upsert_coverage(
            snapshot, university_id=university_id, source_run_id=source_run_id
        )
        self._session.flush()
        logger.info(
            "admission_benefits_sync_complete year=%s university_id=%s olympiads=%d profiles=%d rules=%d achievement_rules=%d stale=%d conflicts=%d duration_ms=%d",
            snapshot.admission_year,
            university_id,
            len(snapshot.olympiads),
            len(snapshot.olympiad_profiles),
            len(snapshot.benefit_rules),
            len(snapshot.individual_achievement_policy.rules)
            if snapshot.individual_achievement_policy
            else 0,
            stale_rows,
            conflict_rows,
            _elapsed_ms(started),
        )
        return AdmissionBenefitSyncStats(
            olympiads_inserted=olympiad_counts[0],
            profiles_inserted=profile_counts[0],
            rules_inserted=rule_counts[0],
            achievement_rules_inserted=achievement_counts[0],
            stale_rows=stale_rows,
            unchanged_rows=olympiad_counts[1]
            + profile_counts[1]
            + rule_counts[1]
            + achievement_counts[1],
            conflict_rows=conflict_rows,
        )

    def mark_stale_for_source_revision(
        self,
        *,
        university_id: UniversityId,
        admission_year: EducationYear,
        source_kind: str,
        source_url: str,
        current_hash: str,
    ) -> int:
        """Mark only facts from one replaced source document as stale."""

        count = 0
        for model in _SOURCE_MODELS:
            statement = (
                update(model)
                .where(
                    model.admission_year == admission_year,
                    model.source_kind == source_kind,
                    model.source_url == source_url,
                    model.source_snapshot_hash != current_hash,
                    model.status != RuleDataStatus.STALE.value,
                )
                .values(status=RuleDataStatus.STALE.value)
            )
            # Olympiad/profile rows have no university column in the canonical
            # contract. Their document/source identity is the safe scope.
            if hasattr(model, "university_id"):
                statement = statement.where(model.university_id == university_id)
            result = self._session.execute(statement)
            count += int(getattr(result, "rowcount", 0) or 0)
        logger.warning(
            "admission_benefits_source_staled university_id=%s year=%s source_kind=%s source_url=%s count=%d",
            university_id,
            admission_year,
            source_kind,
            source_url,
            count,
        )
        return count

    def get_catalog(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None = None,
    ) -> AdmissionBenefitsSnapshot | None:
        rules = self._rule_models(
            university_id=university_id,
            admission_year=admission_year,
            education_level=education_level,
            include_review=True,
        )
        policy_model = self._policy_model(
            university_id, admission_year, education_level, include_review=True
        )
        coverage_model = self._coverage_model(university_id, admission_year)
        profile_ids = {
            row.olympiad_profile_id
            for row in rules
            if row.olympiad_profile_id is not None
        }
        olympiad_ids = {row.olympiad_id for row in rules if row.olympiad_id is not None}
        profiles = self._profile_models(admission_year, profile_ids)
        olympiads = self._olympiad_models(
            admission_year, olympiad_ids | {row.olympiad_id for row in profiles}
        )
        if (
            not rules
            and policy_model is None
            and not olympiads
            and coverage_model is None
        ):
            return None
        policy = (
            _to_policy(
                policy_model,
                self._achievement_rule_models(
                    policy_model.id, policy_model.source_snapshot_hash
                )
                if policy_model
                else (),
            )
            if policy_model
            else None
        )
        source_rows: list[Any] = [*olympiads, *profiles, *rules]
        if policy_model is not None:
            source_rows.append(policy_model)
            source_rows.extend(
                self._achievement_rule_models(
                    policy_model.id, policy_model.source_snapshot_hash
                )
            )
        persisted_sources = (
            _persisted_sources(coverage_model) if coverage_model is not None else ()
        )
        sources = _deduplicate_attributions(
            (*_deduplicate_sources(source_rows), *persisted_sources)
        )
        source_gaps = (
            _persisted_source_gaps(coverage_model) if coverage_model is not None else ()
        )
        coverage = (
            _coverage_from_model(coverage_model)
            if coverage_model is not None
            else _legacy_coverage_from_rows(source_rows, sources)
        )
        if coverage_model is None and source_rows:
            source_gaps = (
                SourceGapReference(
                    code="coverage_not_recorded_for_legacy_snapshot",
                    severity=GapSeverity.DEGRADABLE,
                    message="admission benefit coverage was not recorded for this legacy source run",
                    can_continue=True,
                ),
            )
        profile_subjects = self._profile_subject_rows(profiles)
        rule_scopes = self._rule_scope_rows(rules)
        rule_subjects = self._rule_subject_rows(rules)
        return AdmissionBenefitsSnapshot(
            university_id=university_id,
            admission_year=admission_year,
            sources=sources,
            olympiads=tuple(_to_olympiad(row) for row in olympiads),
            olympiad_profiles=tuple(
                self._to_profile(
                    row, subjects=profile_subjects.get(_profile_identity(row), ())
                )
                for row in profiles
            ),
            benefit_rules=tuple(
                self._to_rule(
                    row,
                    scopes=rule_scopes.get(_rule_identity(row), ()),
                    subjects=rule_subjects.get(_rule_identity(row), ()),
                )
                for row in rules
            ),
            individual_achievement_policy=policy,
            coverage=coverage,
            source_gaps=source_gaps,
        )

    def get_rule_revision(
        self, rule_id: str, revision_hash: str
    ) -> AdmissionBenefitRule | None:
        rows = tuple(
            self._session.scalars(
                select(AdmissionBenefitRuleModel)
                .where(AdmissionBenefitRuleModel.id == rule_id)
                .order_by(
                    AdmissionBenefitRuleModel.admission_year.desc(),
                    AdmissionBenefitRuleModel.source_snapshot_hash,
                )
                .limit(101)
            ).all()
        )
        if len(rows) > 100:
            return None
        scopes = self._rule_scope_rows(rows)
        subjects = self._rule_subject_rows(rows)
        matches = tuple(
            value
            for row in rows
            if admission_benefit_revision_hash(
                value := self._to_rule(
                    row,
                    scopes=scopes.get(_rule_identity(row), ()),
                    subjects=subjects.get(_rule_identity(row), ()),
                )
            )
            == revision_hash
        )
        return matches[0] if len(matches) == 1 else None

    def get_individual_achievement_policy_revision(
        self, policy_id: str, revision_hash: str
    ) -> IndividualAchievementPolicy | None:
        rows = tuple(
            self._session.scalars(
                select(IndividualAchievementPolicyModel)
                .where(IndividualAchievementPolicyModel.id == policy_id)
                .order_by(IndividualAchievementPolicyModel.source_snapshot_hash)
                .limit(101)
            ).all()
        )
        if len(rows) > 100:
            return None
        matches: list[IndividualAchievementPolicy] = []
        for row in rows:
            rules = self._achievement_rule_models(row.id, row.source_snapshot_hash)
            value = _to_policy(row, rules)
            if admission_benefit_revision_hash(value) == revision_hash:
                matches.append(value)
        return matches[0] if len(matches) == 1 else None

    def get_rules_for_program(
        self,
        program_id: ProgramId,
        admission_year: EducationYear,
        *,
        include_review: bool = False,
        campus_id: AdmissionCampusId | None = None,
    ) -> tuple[AdmissionBenefitRule, ...]:
        resolved_program_id = canonical_program_id(program_id)
        program = self._session.get(ProgramModel, resolved_program_id)
        if program is None:
            logger.info(
                "admission_benefits_program_not_found program_id=%s year=%s",
                program_id,
                admission_year,
            )
            return ()
        direction = self._session.get(DirectionModel, program.direction_id)
        if direction is None:
            logger.warning(
                "admission_benefits_program_direction_missing program_id=%s",
                resolved_program_id,
            )
            return ()
        rows = self._rule_models(
            university_id=_university_from_direction(direction),
            admission_year=admission_year,
            education_level=_education_level(direction.education_level),
            include_review=include_review,
        )
        rule_scopes = self._rule_scope_rows(rows)
        rule_subjects = self._rule_subject_rows(rows)
        result = tuple(
            self._to_rule(
                row,
                scopes=rule_scopes.get(_rule_identity(row), ()),
                subjects=rule_subjects.get(_rule_identity(row), ()),
            )
            for row in rows
            if self._scope_matches(
                row,
                direction_code=direction.code,
                program_id=resolved_program_id,
                education_level=direction.education_level,
                campus_id=campus_id,
                scope_rows=rule_scopes.get(_rule_identity(row), ()),
            )
        )
        logger.debug(
            "admission_benefits_program_read program_id=%s year=%s rules=%d",
            resolved_program_id,
            admission_year,
            len(result),
        )
        return result

    def get_rules_for_direction(
        self,
        direction_code: DirectionCode,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        education_level: EducationLevel | None = None,
        include_review: bool = False,
        campus_id: AdmissionCampusId | None = None,
    ) -> tuple[AdmissionBenefitRule, ...]:
        rows = self._rule_models(
            university_id=university_id,
            admission_year=admission_year,
            education_level=education_level,
            include_review=include_review,
        )
        rule_scopes = self._rule_scope_rows(rows)
        rule_subjects = self._rule_subject_rows(rows)
        result = tuple(
            self._to_rule(
                row,
                scopes=rule_scopes.get(_rule_identity(row), ()),
                subjects=rule_subjects.get(_rule_identity(row), ()),
            )
            for row in rows
            if self._scope_matches(
                row,
                direction_code=direction_code,
                education_level=education_level,
                campus_id=campus_id,
                scope_rows=rule_scopes.get(_rule_identity(row), ()),
            )
        )
        logger.debug(
            "admission_benefits_direction_read university_id=%s direction=%s year=%s rules=%d",
            university_id,
            direction_code,
            admission_year,
            len(result),
        )
        return result

    def get_programs_for_olympiad(
        self,
        olympiad_id: OlympiadId,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        benefit_type: str | None = None,
        include_review: bool = False,
    ) -> tuple[AdmissionBenefitRule, ...]:
        rows = self._rule_models(
            university_id=university_id,
            admission_year=admission_year,
            include_review=include_review,
            olympiad_id=olympiad_id,
            benefit_type=benefit_type,
        )
        rule_scopes = self._rule_scope_rows(rows)
        rule_subjects = self._rule_subject_rows(rows)
        result = tuple(
            self._to_rule(
                row,
                scopes=rule_scopes.get(_rule_identity(row), ()),
                subjects=rule_subjects.get(_rule_identity(row), ()),
            )
            for row in rows
        )
        logger.debug(
            "admission_benefits_olympiad_reverse_read university_id=%s olympiad_id=%s year=%s rules=%d",
            university_id,
            olympiad_id,
            admission_year,
            len(result),
        )
        return result

    def get_olympiad_catalog(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
    ) -> tuple[Olympiad, ...]:
        rows = self._rule_models(
            university_id=university_id,
            admission_year=admission_year,
            include_review=False,
        )
        ids = {row.olympiad_id for row in rows if row.olympiad_id is not None}
        return tuple(
            _to_olympiad(row) for row in self._olympiad_models(admission_year, ids)
        )

    def get_individual_achievement_policy(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None = None,
        *,
        include_review: bool = False,
    ) -> IndividualAchievementPolicy | None:
        model = self._policy_model(
            university_id,
            admission_year,
            education_level,
            include_review=include_review,
        )
        if model is None:
            return None
        return _to_policy(
            model,
            self._achievement_rule_models(
                model.id, model.source_snapshot_hash, include_review=include_review
            ),
        )

    def _rule_models(
        self,
        *,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None = None,
        include_review: bool,
        olympiad_id: OlympiadId | None = None,
        benefit_type: str | None = None,
    ) -> tuple[AdmissionBenefitRuleModel, ...]:
        query = select(AdmissionBenefitRuleModel).where(
            AdmissionBenefitRuleModel.university_id == university_id,
            AdmissionBenefitRuleModel.admission_year == admission_year,
        )
        if education_level is not None:
            level_value = _education_level_value(education_level)
            query = query.where(
                or_(
                    AdmissionBenefitRuleModel.education_level == level_value,
                    AdmissionBenefitRuleModel.education_level.is_(None),
                )
            )
        if not include_review:
            query = query.where(AdmissionBenefitRuleModel.status.in_(_ACTIVE_STATUSES))
        else:
            query = query.where(
                AdmissionBenefitRuleModel.status.in_(_NON_STALE_STATUSES)
            )
        if olympiad_id is not None:
            query = query.where(AdmissionBenefitRuleModel.olympiad_id == olympiad_id)
        if benefit_type is not None:
            query = query.where(AdmissionBenefitRuleModel.benefit_type == benefit_type)
        return tuple(
            self._session.scalars(
                query.order_by(
                    AdmissionBenefitRuleModel.id,
                    AdmissionBenefitRuleModel.admission_year,
                )
            ).all()
        )

    def _policy_model(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None,
        *,
        include_review: bool,
    ) -> IndividualAchievementPolicyModel | None:
        query = select(IndividualAchievementPolicyModel).where(
            IndividualAchievementPolicyModel.university_id == university_id,
            IndividualAchievementPolicyModel.admission_year == admission_year,
        )
        if education_level is None:
            query = query.where(
                IndividualAchievementPolicyModel.education_level == "unknown"
            )
        else:
            query = query.where(
                IndividualAchievementPolicyModel.education_level.in_(
                    (education_level.value, "unknown")
                )
            )
        if not include_review:
            query = query.where(
                IndividualAchievementPolicyModel.status == RuleDataStatus.ACTIVE.value
            )
        else:
            query = query.where(
                IndividualAchievementPolicyModel.status.in_(_NON_STALE_STATUSES)
            )
        return self._session.scalar(
            query.order_by(IndividualAchievementPolicyModel.education_level.desc())
        )

    def _coverage_model(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
    ) -> AdmissionBenefitIngestionCoverageModel | None:
        query = (
            select(AdmissionBenefitIngestionCoverageModel)
            .where(
                AdmissionBenefitIngestionCoverageModel.university_id == university_id,
                AdmissionBenefitIngestionCoverageModel.admission_year == admission_year,
            )
            .order_by(
                AdmissionBenefitIngestionCoverageModel.recorded_at.desc(),
                AdmissionBenefitIngestionCoverageModel.source_run_id.desc(),
            )
            .limit(1)
        )
        return self._session.scalar(query)

    def _achievement_rule_models(
        self,
        policy_id: str,
        policy_source_snapshot_hash: str | None = None,
        *,
        include_review: bool = True,
    ) -> tuple[IndividualAchievementRuleModel, ...]:
        query = select(IndividualAchievementRuleModel).where(
            IndividualAchievementRuleModel.policy_id == policy_id
        )
        if policy_source_snapshot_hash is not None:
            query = query.where(
                IndividualAchievementRuleModel.policy_source_snapshot_hash
                == policy_source_snapshot_hash
            )
        if not include_review:
            query = query.where(
                IndividualAchievementRuleModel.status == RuleDataStatus.ACTIVE.value
            )
        else:
            query = query.where(
                IndividualAchievementRuleModel.status.in_(_NON_STALE_STATUSES)
            )
        return tuple(
            self._session.scalars(
                query.order_by(
                    IndividualAchievementRuleModel.id,
                    IndividualAchievementRuleModel.admission_year,
                )
            ).all()
        )

    def _profile_models(
        self, admission_year: int, ids: Iterable[str | None]
    ) -> tuple[AdmissionBenefitOlympiadProfileModel, ...]:
        profile_ids = tuple(sorted(item for item in ids if item is not None))
        if not profile_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(AdmissionBenefitOlympiadProfileModel)
                .where(
                    AdmissionBenefitOlympiadProfileModel.admission_year
                    == admission_year,
                    AdmissionBenefitOlympiadProfileModel.id.in_(profile_ids),
                    AdmissionBenefitOlympiadProfileModel.status.in_(
                        _NON_STALE_STATUSES
                    ),
                )
                .order_by(AdmissionBenefitOlympiadProfileModel.id)
            ).all()
        )

    def _profile_subject_rows(
        self,
        rows: tuple[AdmissionBenefitOlympiadProfileModel, ...],
    ) -> dict[tuple[str, int, str], tuple[AdmissionBenefitProfileSubjectModel, ...]]:
        if not rows:
            return {}
        profile_ids = tuple(row.id for row in rows)
        values = self._session.scalars(
            select(AdmissionBenefitProfileSubjectModel)
            .where(
                AdmissionBenefitProfileSubjectModel.profile_id.in_(profile_ids),
                AdmissionBenefitProfileSubjectModel.admission_year.in_(
                    tuple(row.admission_year for row in rows)
                ),
            )
            .order_by(
                AdmissionBenefitProfileSubjectModel.profile_id,
                AdmissionBenefitProfileSubjectModel.subject_index,
            )
        ).all()
        by_identity: dict[
            tuple[str, int, str], list[AdmissionBenefitProfileSubjectModel]
        ] = {}
        for value in values:
            by_identity.setdefault(
                (
                    value.profile_id,
                    value.admission_year,
                    value.profile_source_snapshot_hash,
                ),
                [],
            ).append(value)
        return {key: tuple(items) for key, items in by_identity.items()}

    def _olympiad_models(
        self, admission_year: int, ids: Iterable[str | None]
    ) -> tuple[AdmissionBenefitOlympiadModel, ...]:
        olympiad_ids = tuple(sorted(item for item in ids if item is not None))
        if not olympiad_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(AdmissionBenefitOlympiadModel)
                .where(
                    AdmissionBenefitOlympiadModel.admission_year == admission_year,
                    AdmissionBenefitOlympiadModel.id.in_(olympiad_ids),
                    AdmissionBenefitOlympiadModel.status.in_(_NON_STALE_STATUSES),
                )
                .order_by(AdmissionBenefitOlympiadModel.id)
            ).all()
        )

    def _scope_matches(
        self,
        row: AdmissionBenefitRuleModel,
        *,
        direction_code: str | None = None,
        program_id: str | None = None,
        education_level: EducationLevel | str | None = None,
        campus_id: AdmissionCampusId | None = None,
        scope_rows: tuple[AdmissionBenefitRuleScopeModel, ...] | None = None,
    ) -> bool:
        if scope_rows is None:
            scope_rows = tuple(
                self._session.scalars(
                    select(AdmissionBenefitRuleScopeModel)
                    .where(
                        AdmissionBenefitRuleScopeModel.rule_id == row.id,
                        AdmissionBenefitRuleScopeModel.admission_year
                        == row.admission_year,
                        AdmissionBenefitRuleScopeModel.rule_source_snapshot_hash
                        == row.source_snapshot_hash,
                    )
                    .order_by(AdmissionBenefitRuleScopeModel.target_index)
                ).all()
            )
        targets = tuple(
            BenefitTarget(
                kind=BenefitTargetKind(scope.target_kind),
                value=scope.target_value,
                original_text=scope.original_text,
                resolution=TargetResolutionStatus(scope.resolution),
            )
            for scope in scope_rows
            if not scope.excluded
        )
        excluded = tuple(
            BenefitTarget(
                kind=BenefitTargetKind(scope.target_kind),
                value=scope.target_value,
                original_text=scope.original_text,
                resolution=TargetResolutionStatus(scope.resolution),
            )
            for scope in scope_rows
            if scope.excluded
        )
        if row.scope_mode == BenefitScopeMode.ALL_EXCEPT.value:
            targets = tuple(_to_target(scope) for scope in scope_rows)
            excluded = ()
        try:
            scope = BenefitScope(
                mode=BenefitScopeMode(row.scope_mode),
                targets=targets,
                excluded_targets=excluded
                if row.scope_mode == BenefitScopeMode.ALL.value
                else (),
                original_text=row.scope_original_text,
            )
        except ValueError:
            logger.warning(
                "admission_benefits_scope_invalid rule_id=%s year=%s",
                row.id,
                row.admission_year,
            )
            return False
        applicability = scope.applies_to(
                direction_code=direction_code,
                program_id=program_id,
                education_level=education_level,
                campus_id=campus_id,
            )
        if applicability.status.value == "applicable":
            return True
        return (
            campus_id is None
            and applicability.status.value == "insufficient_data"
            and any(target.kind is BenefitTargetKind.CAMPUS for target in (*scope.targets, *scope.excluded_targets))
        )

    def _rule_scope_rows(
        self,
        rows: tuple[AdmissionBenefitRuleModel, ...],
    ) -> dict[tuple[str, int, str], tuple[AdmissionBenefitRuleScopeModel, ...]]:
        if not rows:
            return {}
        values = self._session.scalars(
            select(AdmissionBenefitRuleScopeModel)
            .where(
                AdmissionBenefitRuleScopeModel.rule_id.in_(
                    tuple(row.id for row in rows)
                ),
                AdmissionBenefitRuleScopeModel.admission_year.in_(
                    tuple(row.admission_year for row in rows)
                ),
            )
            .order_by(
                AdmissionBenefitRuleScopeModel.rule_id,
                AdmissionBenefitRuleScopeModel.target_index,
            )
        ).all()
        by_identity: dict[
            tuple[str, int, str], list[AdmissionBenefitRuleScopeModel]
        ] = {}
        for value in values:
            by_identity.setdefault(
                (value.rule_id, value.admission_year, value.rule_source_snapshot_hash),
                [],
            ).append(value)
        return {key: tuple(items) for key, items in by_identity.items()}

    def _rule_subject_rows(
        self,
        rows: tuple[AdmissionBenefitRuleModel, ...],
    ) -> dict[tuple[str, int, str], tuple[AdmissionBenefitRuleSubjectModel, ...]]:
        if not rows:
            return {}
        values = self._session.scalars(
            select(AdmissionBenefitRuleSubjectModel)
            .where(
                AdmissionBenefitRuleSubjectModel.rule_id.in_(
                    tuple(row.id for row in rows)
                ),
                AdmissionBenefitRuleSubjectModel.admission_year.in_(
                    tuple(row.admission_year for row in rows)
                ),
            )
            .order_by(
                AdmissionBenefitRuleSubjectModel.rule_id,
                AdmissionBenefitRuleSubjectModel.subject_index,
            )
        ).all()
        by_identity: dict[
            tuple[str, int, str], list[AdmissionBenefitRuleSubjectModel]
        ] = {}
        for value in values:
            by_identity.setdefault(
                (value.rule_id, value.admission_year, value.rule_source_snapshot_hash),
                [],
            ).append(value)
        return {key: tuple(items) for key, items in by_identity.items()}

    def _to_rule(
        self,
        row: AdmissionBenefitRuleModel,
        *,
        scopes: tuple[AdmissionBenefitRuleScopeModel, ...] | None = None,
        subjects: tuple[AdmissionBenefitRuleSubjectModel, ...] | None = None,
    ) -> AdmissionBenefitRule:
        if scopes is None:
            scopes = tuple(
                self._session.scalars(
                    select(AdmissionBenefitRuleScopeModel)
                    .where(
                        AdmissionBenefitRuleScopeModel.rule_id == row.id,
                        AdmissionBenefitRuleScopeModel.admission_year
                        == row.admission_year,
                        AdmissionBenefitRuleScopeModel.rule_source_snapshot_hash
                        == row.source_snapshot_hash,
                    )
                    .order_by(AdmissionBenefitRuleScopeModel.target_index)
                ).all()
            )
        excluded = tuple(_to_target(item) for item in scopes if item.excluded)
        targets = tuple(_to_target(item) for item in scopes if not item.excluded)
        if row.scope_mode == BenefitScopeMode.ALL_EXCEPT.value:
            targets = tuple(_to_target(item) for item in scopes)
            excluded = ()
        if subjects is None:
            subjects = tuple(
                self._session.scalars(
                    select(AdmissionBenefitRuleSubjectModel)
                    .where(
                        AdmissionBenefitRuleSubjectModel.rule_id == row.id,
                        AdmissionBenefitRuleSubjectModel.admission_year
                        == row.admission_year,
                        AdmissionBenefitRuleSubjectModel.rule_source_snapshot_hash
                        == row.source_snapshot_hash,
                    )
                    .order_by(AdmissionBenefitRuleSubjectModel.subject_index)
                ).all()
            )
        return AdmissionBenefitRule(
            id=row.id,
            university_id=row.university_id,
            admission_year=row.admission_year,
            education_level=_education_level(row.education_level),
            route=AdmissionRoute(row.route),
            benefit_type=BenefitType(row.benefit_type),
            olympiad_id=row.olympiad_id,
            olympiad_profile_id=row.olympiad_profile_id,
            result_type=OlympiadResultType(row.result_type)
            if row.result_type
            else None,
            scope=BenefitScope(
                mode=BenefitScopeMode(row.scope_mode),
                targets=targets,
                excluded_targets=excluded,
                original_text=row.scope_original_text,
            ),
            confirmation_requirement=ConfirmationRequirement(
                row.confirmation_requirement
            ),
            confirmation_subjects=tuple(
                ConfirmationSubjectRule(
                    subject=item.subject,
                    minimum_score=item.minimum_score,
                    exam_kind=ConfirmationExamKind(item.exam_kind),
                    applicant_category=(
                        ConfirmationApplicantCategory(item.applicant_category)
                        if item.applicant_category
                        else None
                    ),
                    source_text=item.source_text,
                )
                for item in subjects
            ),
            validity=ValidityPolicy(
                valid_from_result_year=row.valid_from_result_year,
                valid_until_result_year=row.valid_until_result_year,
                max_age_years=row.max_age_years,
                source_text=row.validity_source_text,
            ),
            target_subject=row.target_subject,
            points=row.points,
            conditions=tuple(
                BenefitCondition.model_validate(item, strict=False)
                for item in _json_list(row.conditions_json)
            ),
            source_text=row.source_text,
            status=RuleDataStatus(row.status),
            policy_version=_policy_version(row),
            provenance=_provenance(row),
        )

    def _to_profile(
        self,
        row: AdmissionBenefitOlympiadProfileModel,
        *,
        subjects: tuple[AdmissionBenefitProfileSubjectModel, ...] | None = None,
    ) -> OlympiadProfile:
        if subjects is None:
            subjects = tuple(
                self._session.scalars(
                    select(AdmissionBenefitProfileSubjectModel)
                    .where(
                        AdmissionBenefitProfileSubjectModel.profile_id == row.id,
                        AdmissionBenefitProfileSubjectModel.admission_year
                        == row.admission_year,
                        AdmissionBenefitProfileSubjectModel.profile_source_snapshot_hash
                        == row.source_snapshot_hash,
                    )
                    .order_by(AdmissionBenefitProfileSubjectModel.subject_index)
                ).all()
            )
        return OlympiadProfile(
            id=row.id,
            olympiad_id=row.olympiad_id,
            profile_name=row.profile_name,
            corresponding_subjects=tuple(
                OlympiadProfileSubject(
                    subject=item.subject, source_text=item.source_text
                )
                for item in subjects
            ),
            admission_year=row.admission_year,
            provenance=(_provenance(row),),
        )

    def _upsert_olympiad(self, value: Olympiad) -> str:
        provenance = value.provenance[0]
        identity = (value.id, value.admission_year, provenance.source_snapshot_hash)
        row = self._session.get(AdmissionBenefitOlympiadModel, identity)
        values = {
            "id": value.id,
            "admission_year": value.admission_year,
            "official_name": value.official_name,
            "organizer": value.organizer,
            "rsosh_level": value.rsosh_level,
            "status": RuleDataStatus.ACTIVE.value,
            **_evidence_values(provenance),
            "created_at": _created_at(row),
        }
        return _apply_values(
            row, self._session, AdmissionBenefitOlympiadModel, values, identity
        )

    def _upsert_coverage(
        self,
        snapshot: AdmissionBenefitsSnapshot,
        *,
        university_id: UniversityId,
        source_run_id: IngestRunId,
    ) -> None:
        identity = (university_id, snapshot.admission_year, source_run_id)
        row = self._session.get(AdmissionBenefitIngestionCoverageModel, identity)
        values: dict[str, object] = {
            "university_id": university_id,
            "admission_year": snapshot.admission_year,
            "source_run_id": source_run_id,
            "manifest_hash": snapshot.coverage.manifest_hash,
            "status": snapshot.coverage.status.value,
            "documents_discovered": snapshot.coverage.documents_discovered,
            "documents_selected": snapshot.coverage.documents_selected,
            "documents_captured": snapshot.coverage.documents_captured,
            "documents_parsed": snapshot.coverage.documents_parsed,
            "required_documents_expected": snapshot.coverage.required_documents_expected,
            "required_documents_discovered": snapshot.coverage.required_documents_discovered,
            "required_documents_captured": snapshot.coverage.required_documents_captured,
            "records_normalized": snapshot.coverage.records_normalized,
            "targets_resolved": snapshot.coverage.targets_resolved,
            "unresolved_targets": snapshot.coverage.unresolved_targets,
            "conflicts": snapshot.coverage.conflicts,
            "review_required_rows": snapshot.coverage.review_required_rows,
            "source_hashes_json": list(snapshot.coverage.source_hashes),
            "source_gaps_json": [
                item.model_dump(mode="json") for item in snapshot.source_gaps
            ],
            "sources_json": [item.model_dump(mode="json") for item in snapshot.sources],
        }
        if row is None:
            self._session.add(
                AdmissionBenefitIngestionCoverageModel(
                    **values,
                    recorded_at=datetime.now(UTC),
                )
            )
            return
        changed = any(getattr(row, key) != value for key, value in values.items())
        if changed:
            for key, value in values.items():
                setattr(row, key, value)
            row.recorded_at = datetime.now(UTC)

    def _upsert_profile(self, value: OlympiadProfile) -> str:
        provenance = value.provenance[0]
        identity = (value.id, value.admission_year, provenance.source_snapshot_hash)
        row = self._session.get(AdmissionBenefitOlympiadProfileModel, identity)
        olympiad_source_hash = self._session.scalar(
            select(AdmissionBenefitOlympiadModel.source_snapshot_hash)
            .where(
                AdmissionBenefitOlympiadModel.id == value.olympiad_id,
                AdmissionBenefitOlympiadModel.admission_year == value.admission_year,
            )
            .order_by(AdmissionBenefitOlympiadModel.source_snapshot_hash)
            .limit(1)
        )
        if olympiad_source_hash is None:
            raise ValueError(
                "olympiad profile cannot be persisted without its source-backed parent"
            )
        values = {
            "id": value.id,
            "olympiad_id": value.olympiad_id,
            "olympiad_source_snapshot_hash": olympiad_source_hash,
            "admission_year": value.admission_year,
            "profile_name": value.profile_name,
            "status": RuleDataStatus.ACTIVE.value,
            **_evidence_values(provenance),
            "created_at": _created_at(row),
        }
        return _apply_values(
            row, self._session, AdmissionBenefitOlympiadProfileModel, values, identity
        )

    def _upsert_benefit_rule(self, value: AdmissionBenefitRule) -> str:
        identity = (
            value.id,
            value.admission_year,
            value.provenance.source_snapshot_hash,
        )
        row = self._session.get(AdmissionBenefitRuleModel, identity)
        values = {
            "id": value.id,
            "admission_year": value.admission_year,
            "university_id": value.university_id,
            "education_level": value.education_level.value
            if value.education_level
            else None,
            "route": value.route.value,
            "benefit_type": value.benefit_type.value,
            "olympiad_id": value.olympiad_id,
            "olympiad_profile_id": value.olympiad_profile_id,
            "result_type": value.result_type.value if value.result_type else None,
            "scope_mode": value.scope.mode.value,
            "scope_original_text": value.scope.original_text,
            "confirmation_requirement": value.confirmation_requirement.value,
            "valid_from_result_year": value.validity.valid_from_result_year,
            "valid_until_result_year": value.validity.valid_until_result_year,
            "max_age_years": value.validity.max_age_years,
            "validity_source_text": value.validity.source_text,
            "target_subject": value.target_subject,
            "points": value.points,
            "conditions_json": [
                item.model_dump(mode="json") for item in value.conditions
            ],
            "source_text": value.source_text,
            "status": value.status.value,
            "conflict_group": None,
            **_evidence_values(value.provenance, value.policy_version),
            "created_at": _created_at(row),
        }
        return _apply_values(
            row, self._session, AdmissionBenefitRuleModel, values, identity
        )

    def _upsert_achievement_policy(
        self, value: IndividualAchievementPolicy
    ) -> tuple[str, str]:
        identity = (_policy_id(value), value.provenance.source_snapshot_hash)
        row = self._session.get(IndividualAchievementPolicyModel, identity)
        values = {
            "id": _policy_id(value),
            "university_id": value.university_id,
            "admission_year": value.admission_year,
            "education_level": _education_level_value(value.education_level),
            "global_max_points": value.global_max_points,
            "default_combination_policy": value.default_combination_policy.value,
            "source_text": value.source_text,
            "status": value.status.value,
            "conflict_group": None,
            **_evidence_values(value.provenance, value.policy_version),
            "created_at": _created_at(row),
        }
        _apply_values(
            row, self._session, IndividualAchievementPolicyModel, values, identity
        )
        return identity

    def _upsert_achievement_rule(
        self, policy: IndividualAchievementPolicy, value: IndividualAchievementRule
    ) -> str:
        identity = (
            value.id,
            value.admission_year,
            value.provenance.source_snapshot_hash,
        )
        row = self._session.get(IndividualAchievementRuleModel, identity)
        values = {
            "id": value.id,
            "admission_year": value.admission_year,
            "policy_id": _policy_id(policy),
            "policy_source_snapshot_hash": policy.provenance.source_snapshot_hash,
            "university_id": value.university_id,
            "education_level": value.education_level.value
            if value.education_level
            else None,
            "achievement_code": value.achievement_code,
            "category": value.category,
            "official_name": value.official_name,
            "description": value.description,
            "points": value.points,
            "category_cap": value.category_cap,
            "combination_group": value.combination_group,
            "combination_policy": value.combination_policy.value,
            "required_document": value.required_document,
            "conditions_json": [
                item.model_dump(mode="json") for item in value.conditions
            ],
            "source_text": value.source_text,
            "status": value.status.value,
            "conflict_group": None,
            **_evidence_values(value.provenance, value.policy_version),
            "created_at": _created_at(row),
        }
        return _apply_values(
            row, self._session, IndividualAchievementRuleModel, values, identity
        )

    def _replace_profile_subjects(self, value: OlympiadProfile) -> None:
        self._session.execute(
            delete(AdmissionBenefitProfileSubjectModel).where(
                AdmissionBenefitProfileSubjectModel.profile_id == value.id,
                AdmissionBenefitProfileSubjectModel.admission_year
                == value.admission_year,
                AdmissionBenefitProfileSubjectModel.profile_source_snapshot_hash
                == value.provenance[0].source_snapshot_hash,
            )
        )
        self._session.add_all(
            AdmissionBenefitProfileSubjectModel(
                profile_id=value.id,
                admission_year=value.admission_year,
                profile_source_snapshot_hash=value.provenance[0].source_snapshot_hash,
                subject_index=index,
                subject=subject.subject,
                source_text=subject.source_text,
            )
            for index, subject in enumerate(value.corresponding_subjects)
        )

    def _replace_rule_children(self, value: AdmissionBenefitRule) -> None:
        self._session.execute(
            delete(AdmissionBenefitRuleScopeModel).where(
                AdmissionBenefitRuleScopeModel.rule_id == value.id,
                AdmissionBenefitRuleScopeModel.admission_year == value.admission_year,
                AdmissionBenefitRuleScopeModel.rule_source_snapshot_hash
                == value.provenance.source_snapshot_hash,
            )
        )
        self._session.execute(
            delete(AdmissionBenefitRuleSubjectModel).where(
                AdmissionBenefitRuleSubjectModel.rule_id == value.id,
                AdmissionBenefitRuleSubjectModel.admission_year == value.admission_year,
                AdmissionBenefitRuleSubjectModel.rule_source_snapshot_hash
                == value.provenance.source_snapshot_hash,
            )
        )
        targets: list[tuple[BenefitTarget, bool]] = []
        if value.scope.mode is BenefitScopeMode.ALL_EXCEPT:
            targets.extend((target, True) for target in value.scope.targets)
        else:
            targets.extend((target, False) for target in value.scope.targets)
            targets.extend((target, True) for target in value.scope.excluded_targets)
        self._session.add_all(
            AdmissionBenefitRuleScopeModel(
                rule_id=value.id,
                admission_year=value.admission_year,
                rule_source_snapshot_hash=value.provenance.source_snapshot_hash,
                target_index=index,
                target_kind=target.kind.value,
                target_value=target.value,
                original_text=target.original_text,
                resolution=target.resolution.value,
                excluded=excluded,
            )
            for index, (target, excluded) in enumerate(targets)
        )
        self._session.add_all(
            AdmissionBenefitRuleSubjectModel(
                rule_id=value.id,
                admission_year=value.admission_year,
                rule_source_snapshot_hash=value.provenance.source_snapshot_hash,
                subject_index=index,
                subject=subject.subject,
                minimum_score=subject.minimum_score,
                exam_kind=subject.exam_kind.value,
                applicant_category=(subject.applicant_category.value if subject.applicant_category else None),
                source_text=subject.source_text,
            )
            for index, subject in enumerate(value.confirmation_subjects)
        )

    def _stale_snapshot_sources(
        self, snapshot: AdmissionBenefitsSnapshot, university_id: UniversityId | None
    ) -> int:
        count = 0
        for source in snapshot.sources:
            count += self.mark_stale_for_source_revision(
                university_id=university_id or "university:unknown",
                admission_year=snapshot.admission_year,
                source_kind=source.kind.value,
                source_url=str(source.url),
                current_hash=source.content_sha256,
            )
        return count

    @staticmethod
    def _validate_source_run(
        snapshot: AdmissionBenefitsSnapshot, source_run_id: IngestRunId
    ) -> None:
        for source in snapshot.sources:
            if source.run_id != source_run_id:
                raise ValueError(
                    "admission benefit source run does not match ingestion run"
                )
        for provenance in _all_provenance(snapshot):
            if provenance.source_run_id != source_run_id:
                raise ValueError(
                    "admission benefit provenance run does not match ingestion run"
                )


_SOURCE_MODELS = (
    AdmissionBenefitOlympiadModel,
    AdmissionBenefitOlympiadProfileModel,
    AdmissionBenefitRuleModel,
    IndividualAchievementPolicyModel,
    IndividualAchievementRuleModel,
)


def _apply_values(
    row: Any,
    session: Session,
    model: type[Any],
    values: dict[str, object],
    identity: object,
) -> str:
    if row is None:
        session.add(model(**values))
        return "inserted"
    changed = any(
        getattr(row, key) != value
        for key, value in values.items()
        if key != "created_at"
    )
    if changed:
        for key, value in values.items():
            if key != "created_at":
                setattr(row, key, value)
        return "updated"
    return "unchanged"


def _outcome_index(outcome: str) -> int:
    return 0 if outcome == "inserted" else 1


def _created_at(row: Any) -> datetime:
    return row.created_at if row is not None else datetime.now(UTC)


def _evidence_values(
    provenance: Any, policy_version: Any | None = None
) -> dict[str, object]:
    source = provenance.source
    schema_version = (
        policy_version.schema_version
        if policy_version is not None
        else ADMISSION_BENEFITS_SCHEMA_VERSION
    )
    parser_version = (
        policy_version.parser_version
        if policy_version is not None
        else ADMISSION_BENEFITS_PARSER_VERSION
    )
    rule_policy_version = (
        policy_version.policy_version
        if policy_version is not None
        else ADMISSION_BENEFITS_POLICY_VERSION
    )
    return {
        "source_kind": source.kind.value,
        "source_url": str(source.url),
        "source_snapshot_hash": provenance.source_snapshot_hash,
        "source_run_id": provenance.source_run_id,
        "captured_at": source.captured_at,
        "document_title": provenance.document_title,
        "document_kind": provenance.document_kind,
        "appendix_number": provenance.appendix_number,
        "source_page": provenance.page,
        "source_table": provenance.table,
        "source_row": provenance.row,
        "source_section": provenance.section,
        "source_locator": source.locator,
        "parser_version": parser_version,
        "schema_version": schema_version,
        "policy_version": rule_policy_version,
    }


def _source_attribution(row: Any) -> SourceAttribution:
    return SourceAttribution(
        kind=SourceKind(row.source_kind),
        url=row.source_url,
        captured_at=row.captured_at,
        content_sha256=row.source_snapshot_hash,
        locator=row.source_locator,
        run_id=row.source_run_id,
        university_id=getattr(row, "university_id", None),
    )


def _provenance(row: Any) -> Any:
    from andromeda.modules.admission_benefits.contracts.provenance import (
        BenefitProvenance,
    )

    return BenefitProvenance(
        source=_source_attribution(row),
        source_snapshot_hash=row.source_snapshot_hash,
        source_run_id=row.source_run_id,
        admission_year=row.admission_year,
        document_title=row.document_title,
        document_kind=row.document_kind,
        appendix_number=row.appendix_number,
        page=row.source_page,
        table=row.source_table,
        row=row.source_row,
        section=row.source_section,
        parser_version=row.parser_version,
    )


def _policy_version(row: Any) -> Any:
    from andromeda.modules.admission_benefits.contracts.status import (
        BenefitPolicyVersion,
    )

    return BenefitPolicyVersion(
        schema_version=row.schema_version,
        parser_version=row.parser_version,
        policy_version=row.policy_version,
    )


def _to_target(row: AdmissionBenefitRuleScopeModel) -> BenefitTarget:
    return BenefitTarget(
        kind=BenefitTargetKind(row.target_kind),
        value=row.target_value,
        original_text=row.original_text,
        resolution=TargetResolutionStatus(row.resolution),
    )


def _to_olympiad(row: AdmissionBenefitOlympiadModel) -> Olympiad:
    return Olympiad(
        id=row.id,
        official_name=row.official_name,
        organizer=row.organizer,
        rsosh_level=row.rsosh_level,
        admission_year=row.admission_year,
        provenance=(_provenance(row),),
    )


def _to_policy(
    row: IndividualAchievementPolicyModel,
    rules: Iterable[IndividualAchievementRuleModel],
) -> IndividualAchievementPolicy:
    return IndividualAchievementPolicy(
        university_id=row.university_id,
        admission_year=row.admission_year,
        education_level=_education_level(row.education_level),
        global_max_points=row.global_max_points,
        default_combination_policy=AchievementCombinationPolicy(
            row.default_combination_policy
        ),
        rules=tuple(_to_achievement_rule(item) for item in rules),
        source_text=row.source_text,
        status=RuleDataStatus(row.status),
        policy_version=_policy_version(row),
        provenance=_provenance(row),
    )


def _to_achievement_rule(
    row: IndividualAchievementRuleModel,
) -> IndividualAchievementRule:
    return IndividualAchievementRule(
        id=row.id,
        university_id=row.university_id,
        admission_year=row.admission_year,
        education_level=_education_level(row.education_level),
        achievement_code=row.achievement_code,
        category=row.category,
        official_name=row.official_name,
        description=row.description,
        points=row.points,
        category_cap=row.category_cap,
        combination_group=row.combination_group,
        combination_policy=AchievementCombinationPolicy(row.combination_policy),
        required_document=row.required_document,
        conditions=tuple(
            BenefitCondition.model_validate(item, strict=False)
            for item in _json_list(row.conditions_json)
        ),
        source_text=row.source_text,
        status=RuleDataStatus(row.status),
        policy_version=_policy_version(row),
        provenance=_provenance(row),
    )


def _json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _education_level(value: str | None) -> EducationLevel | None:
    if value is None or value == "unknown":
        return None
    return EducationLevel(value)


def _education_level_value(value: EducationLevel | str | None) -> str:
    if value is None:
        return "unknown"
    return value.value if isinstance(value, EducationLevel) else value


def _policy_id(policy: IndividualAchievementPolicy) -> str:
    education_level = _education_level_value(policy.education_level)
    return f"individual-achievement-policy:{policy.university_id.removeprefix('university:')}:{policy.admission_year}:{education_level}"


def _snapshot_university_id(snapshot: AdmissionBenefitsSnapshot) -> UniversityId | None:
    if snapshot.university_id is not None:
        return snapshot.university_id
    if snapshot.benefit_rules:
        return snapshot.benefit_rules[0].university_id
    if snapshot.individual_achievement_policy is not None:
        return snapshot.individual_achievement_policy.university_id
    return None


def _university_from_direction(direction: DirectionModel) -> UniversityId:
    return direction.university_id


def _all_provenance(snapshot: AdmissionBenefitsSnapshot) -> Iterable[Any]:
    for olympiad in snapshot.olympiads:
        yield from olympiad.provenance
    for profile in snapshot.olympiad_profiles:
        yield from profile.provenance
    for benefit_rule in snapshot.benefit_rules:
        yield benefit_rule.provenance
        for condition in benefit_rule.conditions:
            if condition.provenance is not None:
                yield condition.provenance
    if snapshot.individual_achievement_policy is not None:
        yield snapshot.individual_achievement_policy.provenance
        for achievement_rule in snapshot.individual_achievement_policy.rules:
            yield achievement_rule.provenance


def _deduplicate_sources(rows: Iterable[Any]) -> tuple[SourceAttribution, ...]:
    values: dict[tuple[str, str, str], SourceAttribution] = {}
    for row in rows:
        attribution = _source_attribution(row)
        values[
            (attribution.kind.value, str(attribution.url), attribution.content_sha256)
        ] = attribution
    return tuple(values[key] for key in sorted(values))


def _deduplicate_attributions(
    sources: Iterable[SourceAttribution],
) -> tuple[SourceAttribution, ...]:
    values = {
        (source.kind.value, str(source.url), source.content_sha256): source
        for source in sources
    }
    return tuple(values[key] for key in sorted(values))


def _legacy_coverage_from_rows(
    rows: Iterable[Any], sources: tuple[SourceAttribution, ...]
) -> Any:
    from andromeda.modules.admission_benefits.contracts.coverage import (
        AdmissionBenefitCoverage,
    )

    rows_tuple = tuple(rows)
    return AdmissionBenefitCoverage(
        status=AdmissionBenefitCoverageStatus.PARTIAL,
        documents_discovered=len(sources),
        documents_selected=len(sources),
        documents_captured=len(sources),
        documents_parsed=len(sources),
        records_normalized=len(rows_tuple),
        conflicts=sum(
            getattr(row, "status", None) == RuleDataStatus.CONFLICT.value
            for row in rows_tuple
        ),
        source_hashes=tuple(source.content_sha256 for source in sources),
    )


def _coverage_from_model(row: AdmissionBenefitIngestionCoverageModel) -> Any:
    from andromeda.modules.admission_benefits.contracts.coverage import (
        AdmissionBenefitCoverage,
    )

    return AdmissionBenefitCoverage(
        status=AdmissionBenefitCoverageStatus(row.status),
        documents_discovered=row.documents_discovered,
        documents_selected=row.documents_selected,
        documents_captured=row.documents_captured,
        documents_parsed=row.documents_parsed,
        required_documents_expected=row.required_documents_expected,
        required_documents_discovered=row.required_documents_discovered,
        required_documents_captured=row.required_documents_captured,
        records_normalized=row.records_normalized,
        targets_resolved=row.targets_resolved,
        unresolved_targets=row.unresolved_targets,
        conflicts=row.conflicts,
        review_required_rows=row.review_required_rows,
        manifest_hash=row.manifest_hash,
        source_hashes=tuple(str(value) for value in _json_list(row.source_hashes_json)),
    )


def _persisted_sources(
    row: AdmissionBenefitIngestionCoverageModel,
) -> tuple[SourceAttribution, ...]:
    result: list[SourceAttribution] = []
    for value in _json_list(row.sources_json):
        if not isinstance(value, dict):
            continue
        try:
            result.append(SourceAttribution.model_validate(value, strict=False))
        except (TypeError, ValueError):
            logger.warning(
                "admission_benefit_coverage_source_invalid university_id=%s year=%d run_id=%s",
                row.university_id,
                row.admission_year,
                row.source_run_id,
            )
    return tuple(result)


def _persisted_source_gaps(
    row: AdmissionBenefitIngestionCoverageModel,
) -> tuple[SourceGapReference, ...]:
    result: list[SourceGapReference] = []
    for value in _json_list(row.source_gaps_json):
        if not isinstance(value, dict):
            continue
        try:
            result.append(SourceGapReference.model_validate(value, strict=False))
        except (TypeError, ValueError):
            logger.warning(
                "admission_benefit_coverage_gap_invalid university_id=%s year=%d run_id=%s",
                row.university_id,
                row.admission_year,
                row.source_run_id,
            )
    return tuple(result)


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _rule_identity(row: AdmissionBenefitRuleModel) -> tuple[str, int, str]:
    return row.id, row.admission_year, row.source_snapshot_hash


def _profile_identity(
    row: AdmissionBenefitOlympiadProfileModel,
) -> tuple[str, int, str]:
    return row.id, row.admission_year, row.source_snapshot_hash


from andromeda.modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverageStatus,
)

__all__ = ["SqlAlchemyAdmissionBenefitsRepository"]
