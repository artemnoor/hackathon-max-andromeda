"""SQLAlchemy persistence models for source-backed admission rights."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class _BenefitEvidenceMixin:
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source_snapshots.content_sha256"),
        nullable=False,
        primary_key=True,
    )
    source_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ingest_runs.id"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    document_title: Mapped[str] = mapped_column(String(512), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    appendix_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_table: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)


class AdmissionBenefitOlympiadModel(_BenefitEvidenceMixin, Base):
    __tablename__ = "admission_benefit_olympiads"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    official_name: Mapped[str] = mapped_column(String(512), nullable=False)
    organizer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rsosh_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_benefit_olympiad_year",
        ),
        CheckConstraint(
            "rsosh_level IS NULL OR rsosh_level BETWEEN 1 AND 3",
            name="ck_benefit_olympiad_rsosh_level",
        ),
        CheckConstraint(
            "status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')",
            name="ck_benefit_olympiad_status",
        ),
        CheckConstraint("length(official_name) > 0", name="ck_benefit_olympiad_name"),
        Index("ix_benefit_olympiads_name_year", "official_name", "admission_year"),
        Index("ix_benefit_olympiads_source_hash", "source_snapshot_hash", "status"),
    )


class AdmissionBenefitOlympiadProfileModel(_BenefitEvidenceMixin, Base):
    __tablename__ = "admission_benefit_olympiad_profiles"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    olympiad_id: Mapped[str] = mapped_column(String(160), nullable=False)
    olympiad_source_snapshot_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["olympiad_id", "admission_year", "olympiad_source_snapshot_hash"],
            [
                "admission_benefit_olympiads.id",
                "admission_benefit_olympiads.admission_year",
                "admission_benefit_olympiads.source_snapshot_hash",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "olympiad_id",
            "admission_year",
            "profile_name",
            "source_snapshot_hash",
            name="uq_benefit_profile_name",
        ),
        CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_benefit_profile_year",
        ),
        CheckConstraint(
            "status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')",
            name="ck_benefit_profile_status",
        ),
        Index(
            "ix_benefit_profiles_olympiad_year",
            "olympiad_id",
            "admission_year",
            "status",
        ),
    )


class AdmissionBenefitProfileSubjectModel(Base):
    __tablename__ = "admission_benefit_profile_subjects"

    profile_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_source_snapshot_hash: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )
    subject_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    source_text: Mapped[str] = mapped_column(String(512), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "admission_year", "profile_source_snapshot_hash"],
            [
                "admission_benefit_olympiad_profiles.id",
                "admission_benefit_olympiad_profiles.admission_year",
                "admission_benefit_olympiad_profiles.source_snapshot_hash",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint("subject_index >= 0", name="ck_benefit_profile_subject_index"),
        Index("ix_benefit_profile_subjects_subject", "subject", "admission_year"),
    )


class AdmissionBenefitRuleModel(_BenefitEvidenceMixin, Base):
    __tablename__ = "admission_benefit_rules"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universities.id"), nullable=False
    )
    education_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    benefit_type: Mapped[str] = mapped_column(String(40), nullable=False)
    olympiad_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    olympiad_profile_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    result_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_original_text: Mapped[str] = mapped_column(String(2_000), nullable=False)
    confirmation_requirement: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from_result_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_until_result_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validity_source_text: Mapped[str] = mapped_column(String(512), nullable=False)
    target_subject: Mapped[str | None] = mapped_column(String(256), nullable=True)
    points: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    conditions_json: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    source_text: Mapped[str] = mapped_column(String(10_000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    conflict_group: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_benefit_rule_year",
        ),
        CheckConstraint(
            "route IN ('olympiad', 'vosh', 'international', 'special_right', 'preferential_right', 'special_quota', 'separate_quota', 'targeted', 'other')",
            name="ck_benefit_rule_route",
        ),
        CheckConstraint(
            "scope_mode IN ('all', 'only', 'all_except')",
            name="ck_benefit_rule_scope_mode",
        ),
        CheckConstraint(
            "confirmation_requirement IN ('required', 'not_required', 'unknown')",
            name="ck_benefit_rule_confirmation",
        ),
        CheckConstraint(
            "result_type IS NULL OR result_type IN ('winner', 'prize_winner', 'team_member')",
            name="ck_benefit_rule_result_type",
        ),
        CheckConstraint(
            "points IS NULL OR (points >= 0 AND points <= 100)",
            name="ck_benefit_rule_points",
        ),
        CheckConstraint(
            "max_age_years IS NULL OR max_age_years >= 0",
            name="ck_benefit_rule_max_age",
        ),
        CheckConstraint(
            "status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')",
            name="ck_benefit_rule_status",
        ),
        Index(
            "ix_benefit_rules_university_year_active",
            "university_id",
            "admission_year",
            "education_level",
            "benefit_type",
            "status",
        ),
        Index(
            "ix_benefit_rules_olympiad_result",
            "olympiad_id",
            "olympiad_profile_id",
            "result_type",
            "admission_year",
            "status",
        ),
        Index(
            "ix_benefit_rules_source_refresh",
            "source_snapshot_hash",
            "source_run_id",
            "status",
        ),
        Index("ix_benefit_rules_conflict_group", "conflict_group", "status"),
    )


class AdmissionBenefitRuleScopeModel(Base):
    __tablename__ = "admission_benefit_rule_scopes"

    rule_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_source_snapshot_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_value: Mapped[str] = mapped_column(String(256), nullable=False)
    original_text: Mapped[str] = mapped_column(String(512), nullable=False)
    resolution: Mapped[str] = mapped_column(String(32), nullable=False)
    excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "admission_year", "rule_source_snapshot_hash"],
            [
                "admission_benefit_rules.id",
                "admission_benefit_rules.admission_year",
                "admission_benefit_rules.source_snapshot_hash",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint("target_index >= 0", name="ck_benefit_scope_target_index"),
        CheckConstraint(
            "target_kind IN ('direction', 'program', 'nps', 'education_level', 'campus')",
            name="ck_benefit_scope_target_kind",
        ),
        CheckConstraint(
            "resolution IN ('resolved', 'unresolved')",
            name="ck_benefit_scope_resolution",
        ),
        Index(
            "ix_benefit_scope_target_lookup",
            "target_kind",
            "target_value",
            "admission_year",
            "excluded",
        ),
    )


class AdmissionBenefitRuleSubjectModel(Base):
    __tablename__ = "admission_benefit_rule_subjects"

    rule_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_source_snapshot_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    minimum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    exam_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    applicant_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_text: Mapped[str] = mapped_column(String(512), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "admission_year", "rule_source_snapshot_hash"],
            [
                "admission_benefit_rules.id",
                "admission_benefit_rules.admission_year",
                "admission_benefit_rules.source_snapshot_hash",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint("subject_index >= 0", name="ck_benefit_rule_subject_index"),
        CheckConstraint(
            "minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 100)",
            name="ck_benefit_rule_subject_minimum",
        ),
        CheckConstraint(
            "exam_kind IN ('ege', 'internal_exam', 'other', 'unknown')",
            name="ck_benefit_rule_subject_exam_kind",
        ),
        CheckConstraint(
            "applicant_category IS NULL OR applicant_category IN ('standard', 'territorial_exception', 'unknown')",
            name="ck_benefit_rule_subject_applicant_category",
        ),
        Index("ix_benefit_rule_subjects_subject", "subject", "admission_year"),
    )


class IndividualAchievementPolicyModel(_BenefitEvidenceMixin, Base):
    __tablename__ = "individual_achievement_policies"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    university_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universities.id"), nullable=False
    )
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    education_level: Mapped[str] = mapped_column(String(32), nullable=False)
    global_max_points: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    default_combination_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    source_text: Mapped[str] = mapped_column(String(10_000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    conflict_group: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "university_id",
            "admission_year",
            "education_level",
            "source_snapshot_hash",
            name="uq_individual_achievement_policy_scope",
        ),
        CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_achievement_policy_year",
        ),
        CheckConstraint(
            "global_max_points IS NULL OR (global_max_points >= 0 AND global_max_points <= 100)",
            name="ck_achievement_policy_global_max",
        ),
        CheckConstraint(
            "default_combination_policy IN ('additive', 'max_only', 'mutually_exclusive', 'not_combinable', 'unknown')",
            name="ck_achievement_policy_combination",
        ),
        CheckConstraint(
            "status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')",
            name="ck_achievement_policy_status",
        ),
        Index(
            "ix_achievement_policies_university_year",
            "university_id",
            "admission_year",
            "education_level",
            "status",
        ),
    )


class IndividualAchievementRuleModel(_BenefitEvidenceMixin, Base):
    __tablename__ = "individual_achievement_rules"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(256), nullable=False)
    policy_source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    university_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universities.id"), nullable=False
    )
    education_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    achievement_code: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(256), nullable=False)
    official_name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(String(10_000), nullable=True)
    points: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    category_cap: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    combination_group: Mapped[str | None] = mapped_column(String(256), nullable=True)
    combination_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    required_document: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    conditions_json: Mapped[list[object]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    source_text: Mapped[str] = mapped_column(String(10_000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    conflict_group: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["policy_id", "policy_source_snapshot_hash"],
            [
                "individual_achievement_policies.id",
                "individual_achievement_policies.source_snapshot_hash",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_achievement_rule_year",
        ),
        CheckConstraint(
            "points >= 0 AND points <= 100", name="ck_achievement_rule_points"
        ),
        CheckConstraint(
            "category_cap IS NULL OR (category_cap >= 0 AND category_cap <= 100)",
            name="ck_achievement_rule_category_cap",
        ),
        CheckConstraint(
            "combination_policy IN ('additive', 'max_only', 'mutually_exclusive', 'not_combinable', 'unknown')",
            name="ck_achievement_rule_combination",
        ),
        CheckConstraint(
            "status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')",
            name="ck_achievement_rule_status",
        ),
        Index(
            "ix_achievement_rules_lookup",
            "university_id",
            "admission_year",
            "education_level",
            "achievement_code",
            "status",
        ),
        Index(
            "ix_achievement_rules_source_refresh",
            "source_snapshot_hash",
            "source_run_id",
            "status",
        ),
        Index(
            "ix_achievement_rules_combination",
            "combination_group",
            "combination_policy",
            "admission_year",
        ),
    )


class AdmissionBenefitIngestionCoverageModel(Base):
    """One idempotent coverage record for a university/year/ingestion run."""

    __tablename__ = "admission_benefit_ingestion_coverage"

    university_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universities.id", ondelete="CASCADE"), primary_key=True
    )
    admission_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ingest_runs.id", ondelete="CASCADE"), primary_key=True
    )
    manifest_hash: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("source_snapshots.content_sha256"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    documents_discovered: Mapped[int] = mapped_column(Integer, nullable=False)
    documents_selected: Mapped[int] = mapped_column(Integer, nullable=False)
    documents_captured: Mapped[int] = mapped_column(Integer, nullable=False)
    documents_parsed: Mapped[int] = mapped_column(Integer, nullable=False)
    required_documents_expected: Mapped[int] = mapped_column(Integer, nullable=False)
    required_documents_discovered: Mapped[int] = mapped_column(Integer, nullable=False)
    required_documents_captured: Mapped[int] = mapped_column(Integer, nullable=False)
    records_normalized: Mapped[int] = mapped_column(Integer, nullable=False)
    targets_resolved: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_targets: Mapped[int] = mapped_column(Integer, nullable=False)
    conflicts: Mapped[int] = mapped_column(Integer, nullable=False)
    review_required_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hashes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_gaps_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
    sources_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_benefit_coverage_year",
        ),
        CheckConstraint(
            "status IN ('complete', 'partial', 'review_required', 'unavailable')",
            name="ck_benefit_coverage_status",
        ),
        CheckConstraint(
            "documents_discovered >= 0 AND documents_selected >= 0 AND documents_captured >= 0 AND documents_parsed >= 0",
            name="ck_benefit_coverage_documents_nonnegative",
        ),
        CheckConstraint(
            "documents_selected <= documents_discovered AND documents_captured <= documents_selected AND documents_parsed <= documents_captured",
            name="ck_benefit_coverage_document_order",
        ),
        CheckConstraint(
            "required_documents_expected >= 0 AND required_documents_discovered >= 0 AND required_documents_captured >= 0",
            name="ck_benefit_coverage_required_nonnegative",
        ),
        CheckConstraint(
            "required_documents_captured <= required_documents_discovered AND required_documents_discovered <= required_documents_expected",
            name="ck_benefit_coverage_required_order",
        ),
        CheckConstraint(
            "records_normalized >= 0 AND targets_resolved >= 0 AND unresolved_targets >= 0 AND conflicts >= 0 AND review_required_rows >= 0",
            name="ck_benefit_coverage_counts_nonnegative",
        ),
        Index(
            "ix_benefit_coverage_university_year_recorded",
            "university_id",
            "admission_year",
            "recorded_at",
        ),
        Index("ix_benefit_coverage_run", "source_run_id"),
    )


__all__ = [
    "AdmissionBenefitIngestionCoverageModel",
    "AdmissionBenefitOlympiadModel",
    "AdmissionBenefitOlympiadProfileModel",
    "AdmissionBenefitProfileSubjectModel",
    "AdmissionBenefitRuleModel",
    "AdmissionBenefitRuleScopeModel",
    "AdmissionBenefitRuleSubjectModel",
    "IndividualAchievementPolicyModel",
    "IndividualAchievementRuleModel",
]
