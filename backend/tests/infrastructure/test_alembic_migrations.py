from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from alembic import command

BACKEND_ROOT = Path(__file__).parents[2]
STAGE2_HEAD = "0038_admission_offering_scope_and_exam_choices"
CURRENT_HEAD = "0056_exact_conflict_participant_uniqueness"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_empty_sqlite_database_reaches_head_and_preserves_constraints(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)

    command.upgrade(_alembic_config("sqlite:///ignored-by-environment.db"), "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        version_column = next(
            column
            for column in inspector.get_columns("alembic_version")
            if column["name"] == "version_num"
        )
        assert version_column["type"].length >= len(
            "0052_policy_approval_preview_fingerprint"
        )
        assert "educational_programs" in inspector.get_table_names()
        assert "discipline_areas" in inspector.get_table_names()
        assert "user_profiles" in inspector.get_table_names()
        assert "decision_contexts" in inspector.get_table_names()
        assert "decision_analytics_events" in inspector.get_table_names()
        assert "venue_university_links" in inspector.get_table_names()
        assert "venue_department_links" in inspector.get_table_names()
        assert "venue_program_links" in inspector.get_table_names()
        assert "university_admin_memberships" in inspector.get_table_names()
        assert {
            "admission_benefit_olympiads",
            "admission_benefit_olympiad_profiles",
            "admission_benefit_profile_subjects",
            "admission_benefit_rules",
            "admission_benefit_rule_scopes",
            "admission_benefit_rule_subjects",
            "individual_achievement_policies",
            "individual_achievement_rules",
            "admission_benefit_ingestion_coverage",
        }.issubset(set(inspector.get_table_names()))
        benefit_rule_columns = {
            column["name"]
            for column in inspector.get_columns("admission_benefit_rules")
        }
        assert {
            "university_id",
            "admission_year",
            "benefit_type",
            "scope_mode",
            "source_snapshot_hash",
            "source_run_id",
        }.issubset(benefit_rule_columns)
        assert "ix_benefit_rules_olympiad_result" in {
            index["name"] for index in inspector.get_indexes("admission_benefit_rules")
        }
        confirmation_subject_columns = {
            column["name"]
            for column in inspector.get_columns("admission_benefit_rule_subjects")
        }
        assert "applicant_category" in confirmation_subject_columns
        assert "ix_achievement_rules_source_refresh" in {
            index["name"]
            for index in inspector.get_indexes("individual_achievement_rules")
        }
        assert {
            "university_units",
            "university_categories",
            "university_program_editorials",
            "university_discipline_editorials",
            "university_category_program_links",
            "university_category_discipline_links",
            "university_unit_program_links",
            "university_unit_discipline_links",
            "university_editorial_events",
            "university_editorial_agenda_items",
            "university_editorial_event_unit_links",
            "university_editorial_event_program_links",
            "university_editorial_event_category_links",
        }.issubset(set(inspector.get_table_names()))
        assert {
            "knowledge_sources",
            "knowledge_source_registry_revisions",
            "knowledge_source_allowlist",
            "knowledge_source_observations",
        }.issubset(set(inspector.get_table_names()))
        assert {"admission_cycles", "admission_cycle_evidence"}.issubset(
            set(inspector.get_table_names())
        )
        assert {
            "knowledge_claims",
            "knowledge_claim_evidence",
            "knowledge_change_events",
            "knowledge_change_event_claims",
            "knowledge_change_event_evidence",
        }.issubset(set(inspector.get_table_names()))
        assert "knowledge_source_poll_attempts" in set(inspector.get_table_names())
        assert {
            "policy_projection_refresh_state",
            "policy_projection_refresh_attempts",
        }.issubset(set(inspector.get_table_names()))
        assert "ix_policy_projection_refresh_pending" in {
            index["name"] for index in inspector.get_indexes("policy_projection_refresh_state")
        }
        assert {
            "knowledge_claim_candidate_clusters",
            "knowledge_claim_candidate_cluster_members",
        }.issubset(set(inspector.get_table_names()))
        assert {
            "policy_rule_revisions",
            "policy_rule_relations",
            "policy_rule_revision_claims",
            "policy_rule_revision_evidence",
            "policy_approval_events",
        }.issubset(set(inspector.get_table_names()))
        assert "owner_revision_hash" in {
            column["name"] for column in inspector.get_columns("policy_rule_revisions")
        }
        assert {
            "knowledge_conflict_groups",
            "knowledge_conflict_participants",
            "knowledge_conflict_evidence",
            "knowledge_conflict_events",
        }.issubset(set(inspector.get_table_names()))
        participant_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("knowledge_conflict_participants")
        }
        assert {
            name
            for name, index in participant_indexes.items()
            if index["unique"]
        } >= {
            "uq_knowledge_conflict_participant_claim_ref",
            "uq_knowledge_conflict_participant_change_event_ref",
            "uq_knowledge_conflict_participant_policy_ref",
        }
        for table_name in (
            "knowledge_conflict_events",
            "knowledge_review_actions",
            "knowledge_manual_submissions",
        ):
            actor_column = next(
                column
                for column in inspector.get_columns(table_name)
                if column["name"] == "actor_account_id"
            )
            assert actor_column["type"].length == 128
        manual_university_column = next(
            column
            for column in inspector.get_columns("knowledge_manual_submissions")
            if column["name"] == "university_id"
        )
        assert manual_university_column["type"].length == 64
        assert {
            "knowledge_claim_relations",
            "knowledge_claim_relation_evidence",
        }.issubset(set(inspector.get_table_names()))
        assert "knowledge_review_actions" in set(inspector.get_table_names())
        review_action_columns = {
            column["name"] for column in inspector.get_columns("knowledge_review_actions")
        }
        assert {
            "event_id",
            "idempotency_key",
            "request_fingerprint",
            "target_kind",
            "target_id",
            "target_revision",
            "target_hash",
            "result_revision",
            "result_hash",
            "actor_account_id",
            "capability",
            "reason",
            "recorded_at",
        }.issubset(review_action_columns)
        relation_columns = {
            column["name"] for column in inspector.get_columns("knowledge_claim_relations")
        }
        assert {
            "relation_id",
            "revision",
            "content_hash",
            "relation_kind",
            "source_claim_id",
            "source_claim_revision",
            "target_claim_id",
            "target_claim_revision",
            "valid_start",
            "valid_end",
            "review_state",
            "recorded_at",
        }.issubset(relation_columns)
        conflict_group_columns = {
            column["name"] for column in inspector.get_columns("knowledge_conflict_groups")
        }
        assert {
            "conflict_id",
            "revision",
            "content_hash",
            "conflict_kind",
            "scope_level",
            "scope_id",
            "valid_start",
            "valid_end",
            "recorded_at",
        }.issubset(conflict_group_columns)
        conflict_event_columns = {
            column["name"] for column in inspector.get_columns("knowledge_conflict_events")
        }
        assert {
            "event_id",
            "conflict_id",
            "group_revision",
            "group_hash",
            "sequence",
            "event_kind",
            "actor_account_id",
            "resolution_participant_ordinal",
        }.issubset(conflict_event_columns)
        policy_rule_columns = {
            column["name"] for column in inspector.get_columns("policy_rule_revisions")
        }
        assert {
            "rule_id",
            "revision",
            "content_hash",
            "schema_version",
            "family_id",
            "authority_level",
            "selector_json",
            "scope_level",
            "scope_id",
            "owner_module",
            "owner_rule_id",
            "lifecycle",
            "valid_start",
            "valid_end",
            "effective_start",
            "effective_end",
            "captured_at",
            "recorded_at",
        }.issubset(policy_rule_columns)
        approval_columns = {
            column["name"] for column in inspector.get_columns("policy_approval_events")
        }
        assert {
            "event_id",
            "rule_id",
            "revision",
            "sequence",
            "revision_hash",
            "kind",
            "actor_account_id",
            "capability",
            "reason",
            "recorded_at",
            "preview_fingerprint",
        }.issubset(approval_columns)
        cluster_columns = {
            column["name"]
            for column in inspector.get_columns("knowledge_claim_candidate_clusters")
        }
        assert {"cluster_id", "fingerprint", "fingerprint_version", "created_at"}.issubset(
            cluster_columns
        )
        cluster_member_indexes = {
            index["name"]
            for index in inspector.get_indexes("knowledge_claim_candidate_cluster_members")
        }
        assert "ix_knowledge_claim_cluster_members_claim" in cluster_member_indexes
        poll_attempt_columns = {
            column["name"]
            for column in inspector.get_columns("knowledge_source_poll_attempts")
        }
        assert {
            "source_id",
            "registry_revision",
            "outcome",
            "parser_version",
            "previous_snapshot_sha256",
            "last_successful_snapshot_sha256",
            "source_observation_id",
            "retry_count",
            "next_retry_at",
        }.issubset(poll_attempt_columns)
        assert {
            index["name"]
            for index in inspector.get_indexes("knowledge_source_poll_attempts")
        } >= {
            "ix_knowledge_poll_attempt_source_time",
            "ix_knowledge_poll_attempt_next_retry",
        }
        cycle_columns = {
            column["name"] for column in inspector.get_columns("admission_cycles")
        }
        assert {
            "cycle_id",
            "revision",
            "university_id",
            "admission_year",
            "academic_year",
            "application_start",
            "enrollment_start",
            "approved_by_account_id",
            "recorded_at",
        }.issubset(cycle_columns)
        membership_columns = {
            column["name"]
            for column in inspector.get_columns("university_admin_memberships")
        }
        assert {
            "membership_id",
            "account_id",
            "university_id",
            "role",
            "status",
            "revision",
            "created_at",
            "updated_at",
            "granted_by_account_id",
            "revoked_at",
        }.issubset(membership_columns)
        assert "ix_university_admin_memberships_university_status" in {
            index["name"]
            for index in inspector.get_indexes("university_admin_memberships")
        }
        profile_columns = {
            column["name"] for column in inspector.get_columns("user_profiles")
        }
        assert {
            "profile_id",
            "session_key_hash",
            "profile_json",
            "revision",
            "expires_at",
        }.issubset(profile_columns)
        decision_columns = {
            column["name"] for column in inspector.get_columns("decision_contexts")
        }
        assert {
            "decision_id",
            "owner_key",
            "state_json",
            "revision",
            "expires_at",
        }.issubset(decision_columns)
        columns = {
            column["name"] for column in inspector.get_columns("curriculum_items")
        }
        assert {"source_name", "semester_identity"}.issubset(columns)
        assert "subject_group" not in columns
        venue_columns = {column["name"] for column in inspector.get_columns("venues")}
        assert "point_type" in venue_columns
        unique_names = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("curriculum_items")
        }
        assert "uq_curriculum_item_identity" in unique_names
        passing_columns = {
            column["name"]
            for column in inspector.get_columns("admission_passing_scores")
        }
        assert {"competition_type", "status", "score"}.issubset(passing_columns)
        passing_unique = next(
            constraint
            for constraint in inspector.get_unique_constraints(
                "admission_passing_scores"
            )
            if constraint["name"] == "uq_admission_passing_score_identity"
        )
        assert passing_unique["column_names"] == [
            "offering_id",
            "competition_type",
            "status",
            "score_type",
        ]
        program_columns = {
            column["name"] for column in inspector.get_columns("educational_programs")
        }
        assert {"provenance_json", "source_gaps_json"}.issubset(program_columns)
        curriculum_columns = {
            column["name"] for column in inspector.get_columns("curricula")
        }
        assert {"provenance_json", "source_gaps_json"}.issubset(curriculum_columns)
        admission_columns = {
            column["name"] for column in inspector.get_columns("admission_offerings")
        }
        assert {"university_id", "run_id", "field", "record_key", "inferred"}.issubset(
            admission_columns
        )
        admission_revision_columns = {
            column["name"]
            for column in inspector.get_columns("admission_offering_revisions")
        }
        assert {
            "domain_rule_id",
            "revision",
            "offering_id",
            "program_id",
            "admission_year",
            "content_hash",
            "recorded_at",
            "payload_json",
        }.issubset(admission_revision_columns)
        assert "ix_admission_offering_revisions_program_year" in {
            index["name"]
            for index in inspector.get_indexes("admission_offering_revisions")
        }
        ingest_columns = {
            column["name"] for column in inspector.get_columns("ingest_runs")
        }
        assert {
            "projection_target",
            "heartbeat_at",
            "projection_status",
            "recovery_reason",
        }.issubset(ingest_columns)
        ingest_indexes = {
            index["name"] for index in inspector.get_indexes("ingest_runs")
        }
        assert ingest_indexes >= {
            "ix_ingest_runs_status_started_at",
            "uq_ingest_runs_active_identity",
        }
        active_index = next(
            index
            for index in inspector.get_indexes("ingest_runs")
            if index["name"] == "uq_ingest_runs_active_identity"
        )
        assert active_index["column_names"] == [
            "university_id",
            "source_profile",
            "projection_target",
        ]
        source_observation_columns = {
            column["name"]
            for column in inspector.get_columns("knowledge_source_observations")
        }
        assert {
            "source_id",
            "registry_revision",
            "idempotency_key",
            "ingest_run_id",
            "snapshot_sha256",
            "requested_url",
            "final_url",
            "captured_at",
            "observed_at",
        }.issubset(source_observation_columns)
        observation_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "knowledge_source_observations"
            )
        }
        assert "uq_knowledge_source_observation_idempotency" in observation_uniques
        assert {
            index["name"] for index in inspector.get_indexes("source_snapshots")
        } >= {"ix_source_snapshots_ingest_run_id"}
    finally:
        engine.dispose()


def test_current_0016_database_reaches_current_head(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'from-0016.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    command.upgrade(config, "0016_ingestion_source_health")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "provenance_json" in {
            column["name"] for column in inspector.get_columns("educational_programs")
        }
        assert "university_id" in {
            column["name"] for column in inspector.get_columns("admission_offerings")
        }
        assert "uq_ingest_runs_active_identity" in {
            index["name"] for index in inspector.get_indexes("ingest_runs")
        }
    finally:
        engine.dispose()


def test_clean_stage2_head_upgrades_additively_to_one_current_head(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'stage2-to-current.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [CURRENT_HEAD]
    revision = script.get_revision(CURRENT_HEAD)
    seen: set[str] = set()
    while revision.revision != STAGE2_HEAD:
        assert revision.revision not in seen
        seen.add(revision.revision)
        assert isinstance(revision.down_revision, str)
        revision = script.get_revision(revision.down_revision)
    assert revision.revision == STAGE2_HEAD

    command.upgrade(config, STAGE2_HEAD)
    engine = create_engine(database_url)
    source_hash = hashlib.sha256(b"preserved Stage 2 snapshot").hexdigest()
    try:
        with engine.begin() as connection:
            version = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert version == STAGE2_HEAD
            connection.execute(
                text(
                    "INSERT INTO ingest_runs "
                    "(id, started_at, status, university_id, heartbeat_at) "
                    "VALUES (:id, :started_at, 'completed', :university_id, :started_at)"
                ),
                {
                    "id": "ingest:" + "a" * 32,
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "university_id": "university:legacy",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO source_snapshots "
                    "(content_sha256, ingest_run_id, source_kind, requested_url, final_url, "
                    "status_code, content_type, captured_at, body) "
                    "VALUES (:digest, :run_id, 'official_fixture', :url, :url, 200, "
                    "'text/plain', :captured_at, :body)"
                ),
                {
                    "digest": source_hash,
                    "run_id": "ingest:" + "a" * 32,
                    "url": "https://official.example/stage2-fixture.txt",
                    "captured_at": "2026-01-01T00:00:00+00:00",
                    "body": b"preserved Stage 2 snapshot",
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == CURRENT_HEAD
            assert connection.scalar(
                text("SELECT content_sha256 FROM source_snapshots WHERE content_sha256 = :digest"),
                {"digest": source_hash},
            ) == source_hash
        table_names = set(inspect(engine).get_table_names())
        assert {
            "source_snapshots",
            "knowledge_source_observations",
            "policy_rule_revisions",
            "policy_approval_events",
        }.issubset(table_names)
    finally:
        engine.dispose()


def test_admission_owner_revision_migration_refuses_to_drop_persisted_history(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'admission-owner-history.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    domain_rule_id = "admission:offering:" + "a" * 64
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO admission_offering_revisions "
                    "(domain_rule_id, revision, offering_id, program_id, admission_year, "
                    "content_hash, recorded_at, payload_json) "
                    "VALUES (:domain_rule_id, 1, 'admission-offering:test', "
                    "'program:bmstu:09.03.01-02', 2028, :content_hash, "
                    "'2027-12-15 00:00:00', '{}')"
                ),
                {"domain_rule_id": domain_rule_id, "content_hash": "b" * 64},
            )
        with pytest.raises(RuntimeError, match="persisted admission owner revisions"):
            command.downgrade(config, "0052_policy_approval_preview_fingerprint")
        assert "admission_offering_revisions" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_admission_benefit_coverage_migration_round_trips_from_0035(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'benefit-coverage.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    command.upgrade(config, "0035_benefit_team_member")
    engine = create_engine(database_url)
    try:
        assert (
            "admission_benefit_ingestion_coverage"
            not in inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()

    command.upgrade(config, "0036_admission_benefit_coverage")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {
            column["name"]
            for column in inspector.get_columns("admission_benefit_ingestion_coverage")
        }
        assert {
            "university_id",
            "admission_year",
            "source_run_id",
            "manifest_hash",
            "status",
            "source_gaps_json",
            "source_hashes_json",
            "sources_json",
        }.issubset(columns)
    finally:
        engine.dispose()

    command.downgrade(config, "0035_benefit_team_member")
    engine = create_engine(database_url)
    try:
        assert (
            "admission_benefit_ingestion_coverage"
            not in inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert (
            "admission_benefit_ingestion_coverage" in inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()


def test_confirmation_category_migration_is_reversible_from_0036(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'confirmation-category.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    command.upgrade(config, "0036_admission_benefit_coverage")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert "applicant_category" in {
            column["name"]
            for column in inspect(engine).get_columns("admission_benefit_rule_subjects")
        }
    finally:
        engine.dispose()

    command.downgrade(config, "0036_admission_benefit_coverage")
    engine = create_engine(database_url)
    try:
        assert "applicant_category" not in {
            column["name"]
            for column in inspect(engine).get_columns("admission_benefit_rule_subjects")
        }
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert "applicant_category" in {
            column["name"]
            for column in inspect(engine).get_columns("admission_benefit_rule_subjects")
        }
    finally:
        engine.dispose()


def test_neutral_curriculum_migration_removes_legacy_category_column(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'neutral-curriculum.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    command.upgrade(config, "0011_proftest_sessions")
    engine = create_engine(database_url)
    try:
        assert "subject_group" in {
            column["name"] for column in inspect(engine).get_columns("curriculum_items")
        }
    finally:
        engine.dispose()


def test_decision_context_migration_round_trip_is_reversible(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'decision-migration.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    command.upgrade(config, "0012_neutral_curriculum_items")
    command.upgrade(config, "0013_decision_context")
    engine = create_engine(database_url)
    try:
        assert "decision_contexts" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.downgrade(config, "0012_neutral_curriculum_items")
    engine = create_engine(database_url)
    try:
        assert "decision_contexts" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert "decision_contexts" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert "subject_group" not in {
            column["name"] for column in inspect(engine).get_columns("curriculum_items")
        }
    finally:
        engine.dispose()


def test_decision_analytics_migration_round_trip_is_reversible(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = (
        f"sqlite:///{(tmp_path / 'decision-analytics-migration.db').as_posix()}"
    )
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    command.upgrade(config, "0013_decision_context")
    command.upgrade(config, "0014_decision_analytics")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "decision_analytics_events" in inspector.get_table_names()
        primary_key = inspector.get_pk_constraint("decision_analytics_events")
        assert primary_key["constrained_columns"] == ["owner_key", "event_id"]
    finally:
        engine.dispose()

    command.downgrade(config, "0013_decision_context")
    engine = create_engine(database_url)
    try:
        assert "decision_analytics_events" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert "decision_analytics_events" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_auth_downgrade_refuses_account_owned_profile(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'auth-downgrade.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user_profiles (profile_id, session_key_hash, account_id, profile_json, revision, created_at, updated_at, expires_at) "
                    "VALUES (:profile_id, NULL, :account_id, :profile_json, 1, :created_at, :updated_at, :expires_at)"
                ),
                {
                    "profile_id": "profile:" + "a" * 32,
                    "account_id": "account:" + "b" * 32,
                    "profile_json": "{}",
                    "created_at": "2026-01-01 00:00:00",
                    "updated_at": "2026-01-01 00:00:00",
                    "expires_at": "2027-01-01 00:00:00",
                },
            )
        with pytest.raises(RuntimeError, match="account-owned profiles"):
            command.downgrade(config, "0008_admin_ops_ingest_audit")
    finally:
        engine.dispose()


def test_sqlite_migration_chain_can_downgrade_to_base(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'migration-round-trip.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)

    config = _alembic_config("sqlite:///ignored-by-environment.db")
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(database_url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()


def test_route_migration_backfills_existing_numeric_scores(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'route-backfill.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    command.upgrade(config, "0009_auth_profile_binding")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO education_levels (id) VALUES ('bachelor')")
            )
            connection.execute(
                text(
                    "INSERT INTO universities (id, name, city, official_site, address) VALUES ('university:bmstu', 'BMSTU', 'Москва', 'https://bmstu.ru/', 'Москва')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO directions (id, university_id, code, name, education_level) VALUES ('direction:09.03.01', 'university:bmstu', '09.03.01', 'Информатика', 'bachelor')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO educational_programs (id, direction_id, code, name, education_year, study_plan_url, source_url) VALUES ('program:09.03.01-02', 'direction:09.03.01', '09.03.01-02', 'Профиль', 2026, 'https://bmstu.ru/plan.pdf', 'https://bmstu.ru/program')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO admission_offerings (id, program_id, admission_year, study_form, funding_type, scope, source_kind, source_url, captured_at, content_sha256) VALUES ('admission-offering:legacy', 'program:09.03.01-02', 2026, 'full_time', 'budget', 'direction', 'detail', 'https://bmstu.ru/admissions', '2026-01-01 00:00:00', :digest)"
                ),
                {"digest": "a" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO admission_passing_scores (id, offering_id, score_type, score, source_kind, source_url, captured_at, content_sha256) VALUES ('passing:legacy', 'admission-offering:legacy', 'budget', 231, 'detail', 'https://bmstu.ru/admissions', '2026-01-01 00:00:00', :digest)"
                ),
                {"digest": "b" * 64},
            )
        command.upgrade(config, "head")
        row = (
            engine.connect()
            .execute(
                text(
                    "SELECT competition_type, status, score FROM admission_passing_scores WHERE id = 'passing:legacy'"
                )
            )
            .one()
        )
        assert tuple(row) == ("general", "numeric", 231)
    finally:
        engine.dispose()


def test_university_scoped_identity_migrates_bmstu_and_allows_hse_collision_free(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'scoped-identity.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    command.upgrade(config, "0014_decision_analytics")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO education_levels (id) VALUES ('bachelor')")
            )
            connection.execute(
                text(
                    "INSERT INTO universities (id, name, city, official_site, address) VALUES ('university:bmstu', 'BMSTU', 'Москва', 'https://bmstu.ru/', 'Москва')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO universities (id, name, city, official_site, address) VALUES ('university:hse', 'HSE', 'Москва', 'https://hse.ru/', 'Москва')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO directions (id, university_id, code, name, education_level) VALUES ('direction:09.03.01', 'university:bmstu', '09.03.01', 'Информатика', 'bachelor')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO educational_programs (id, direction_id, code, name, education_year, study_plan_url, source_url) VALUES ('program:09.03.01-02', 'direction:09.03.01', '09.03.01-02', 'Профиль', 2026, 'https://bmstu.ru/plan.pdf', 'https://bmstu.ru/program')"
                )
            )

        command.upgrade(config, "head")
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT id FROM directions WHERE university_id = 'university:bmstu'"
                    )
                ).scalar_one()
                == "direction:bmstu:09.03.01"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT id FROM educational_programs WHERE direction_id = 'direction:bmstu:09.03.01'"
                    )
                ).scalar_one()
                == "program:bmstu:09.03.01-02"
            )
            connection.execute(
                text(
                    "INSERT INTO directions (id, university_id, code, name, education_level) VALUES ('direction:hse:09.03.01', 'university:hse', '09.03.01', 'Информатика', 'bachelor')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO educational_programs (id, direction_id, code, name, education_year, study_plan_url, source_url) VALUES ('program:hse:09.03.01-02', 'direction:hse:09.03.01', '09.03.01-02', 'Профиль HSE', 2026, 'https://hse.ru/plan.pdf', 'https://hse.ru/program')"
                )
            )
            rows = (
                connection.execute(
                    text("SELECT id FROM educational_programs ORDER BY id")
                )
                .scalars()
                .all()
            )
            assert rows == ["program:bmstu:09.03.01-02", "program:hse:09.03.01-02"]
    finally:
        engine.dispose()


def test_environment_url_is_used_for_alembic_even_when_ini_differs(
    tmp_path: Path, monkeypatch
) -> None:
    target_url = f"sqlite:///{(tmp_path / 'environment-target.db').as_posix()}"
    ignored_url = f"sqlite:///{(tmp_path / 'ini-target.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", target_url)

    command.upgrade(_alembic_config(ignored_url), "head")

    target_engine = create_engine(target_url)
    ignored_engine = create_engine(ignored_url)
    try:
        assert "alembic_version" in inspect(target_engine).get_table_names()
        assert "alembic_version" not in inspect(ignored_engine).get_table_names()
    finally:
        target_engine.dispose()
        ignored_engine.dispose()


def test_alembic_uses_config_url_when_environment_url_is_unset(
    tmp_path: Path, monkeypatch
) -> None:
    configured_url = f"sqlite:///{(tmp_path / 'configured-target.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.delenv("BMSTU_DATABASE_URL", raising=False)

    command.upgrade(_alembic_config(configured_url), "head")

    engine = create_engine(configured_url)
    try:
        assert "alembic_version" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_admission_offering_scope_migration_adds_and_downgrades_optional_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'admission-offering-scope.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    command.upgrade(config, "0037_confirmation_applicant_category")
    command.upgrade(config, "0038_admission_offering_scope_and_exam_choices")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        offering_columns = {column["name"] for column in inspector.get_columns("admission_offerings")}
        exam_columns = {column["name"] for column in inspector.get_columns("admission_exam_requirements")}
        assert "campus_id" in offering_columns
        assert {"choice_group_id", "choice_group_min", "choice_group_max"}.issubset(exam_columns)
        assert {
            "uq_admission_offering_identity_without_campus",
            "uq_admission_offering_identity_by_campus",
            "ix_admission_offerings_campus_year",
        }.issubset({index["name"] for index in inspector.get_indexes("admission_offerings")})
        assert "ix_admission_exams_choice_group" in {
            index["name"] for index in inspector.get_indexes("admission_exam_requirements")
        }
        assert {
            "ck_admission_exam_choice_group_id",
            "ck_admission_exam_choice_group_min",
            "ck_admission_exam_choice_group_max",
            "ck_admission_exam_choice_group_order",
            "ck_admission_exam_choice_group_flag",
        }.issubset({constraint["name"] for constraint in inspector.get_check_constraints("admission_exam_requirements")})
    finally:
        engine.dispose()

    command.downgrade(config, "0037_confirmation_applicant_category")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "campus_id" not in {column["name"] for column in inspector.get_columns("admission_offerings")}
        assert not {"choice_group_id", "choice_group_min", "choice_group_max"}.intersection(
            column["name"] for column in inspector.get_columns("admission_exam_requirements")
        )
        assert "uq_admission_offering_identity" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("admission_offerings")
        }
    finally:
        engine.dispose()
