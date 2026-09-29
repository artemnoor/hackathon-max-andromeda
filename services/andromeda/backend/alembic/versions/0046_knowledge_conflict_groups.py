"""Store typed conflict groups and append-only resolution events."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0046_knowledge_conflict_groups"
down_revision = "0045_policy_authority_relations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_conflict_groups",
        sa.Column("conflict_id", sa.String(96), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("conflict_kind", sa.String(48), nullable=False),
        sa.Column("scope_level", sa.String(40), nullable=True),
        sa.Column("scope_id", sa.String(320), nullable=True),
        sa.Column("valid_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("conflict_id LIKE 'knowledge-conflict:%'", name="ck_knowledge_conflict_id_prefix"),
        sa.CheckConstraint("revision >= 1", name="ck_knowledge_conflict_revision_positive"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_knowledge_conflict_content_hash"),
        sa.CheckConstraint(
            "conflict_kind IN ('contradictory_claims', 'policy_precedence', 'stale_source_disagreement', "
            "'same_issuer_amendment', 'overlapping_scope_time')",
            name="ck_knowledge_conflict_kind",
        ),
        sa.CheckConstraint(
            "(scope_level IS NULL AND scope_id IS NULL) OR "
            "(scope_level = 'federal' AND scope_id IS NULL) OR "
            "(scope_level = 'unknown' AND scope_id IS NULL) OR "
            "(scope_level NOT IN ('federal', 'unknown') AND scope_id IS NOT NULL AND length(scope_id) > 0)",
            name="ck_knowledge_conflict_scope",
        ),
        sa.CheckConstraint(
            "scope_level IS NULL OR scope_level IN ('federal', 'ministry', 'university', 'campus', 'faculty', "
            "'department', 'education_level', 'direction', 'program', 'admission_route', 'competition_type', "
            "'applicant_category', 'olympiad', 'olympiad_profile', 'subject', 'unknown')",
            name="ck_knowledge_conflict_scope_level",
        ),
        sa.CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR valid_start IS NULL OR "
            "valid_end IS NULL OR valid_start < valid_end",
            name="ck_knowledge_conflict_valid_period",
        ),
        sa.PrimaryKeyConstraint("conflict_id", "revision", name="pk_knowledge_conflict_groups"),
        sa.UniqueConstraint("conflict_id", "revision", "content_hash", name="uq_knowledge_conflict_revision_hash"),
    )
    op.create_index("ix_knowledge_conflict_latest", "knowledge_conflict_groups", ["conflict_id", "revision"])
    op.create_index(
        "ix_knowledge_conflict_scope_time",
        "knowledge_conflict_groups",
        ["conflict_kind", "scope_level", "scope_id", "valid_start", "valid_end"],
    )
    op.create_table(
        "knowledge_conflict_participants",
        sa.Column("conflict_id", sa.String(96), nullable=False),
        sa.Column("group_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("participant_kind", sa.String(32), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("claim_id", sa.String(70), nullable=True),
        sa.Column("claim_revision", sa.Integer(), nullable=True),
        sa.Column("claim_hash", sa.String(64), nullable=True),
        sa.Column("change_event_id", sa.String(78), nullable=True),
        sa.Column("change_event_revision", sa.Integer(), nullable=True),
        sa.Column("policy_rule_id", sa.String(140), nullable=True),
        sa.Column("policy_revision", sa.Integer(), nullable=True),
        sa.Column("policy_hash", sa.String(64), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_conflict_participant_ordinal"),
        sa.CheckConstraint("role IN ('competing', 'prior', 'successor')", name="ck_knowledge_conflict_participant_role"),
        sa.CheckConstraint(
            "(participant_kind = 'claim_revision' AND claim_id IS NOT NULL AND claim_revision IS NOT NULL AND claim_hash IS NOT NULL "
            "AND change_event_id IS NULL AND change_event_revision IS NULL AND policy_rule_id IS NULL AND policy_revision IS NULL AND policy_hash IS NULL) OR "
            "(participant_kind = 'change_event_revision' AND claim_id IS NULL AND claim_revision IS NULL AND claim_hash IS NULL "
            "AND change_event_id IS NOT NULL AND change_event_revision IS NOT NULL AND policy_rule_id IS NULL AND policy_revision IS NULL AND policy_hash IS NULL) OR "
            "(participant_kind = 'policy_rule_revision' AND claim_id IS NULL AND claim_revision IS NULL AND claim_hash IS NULL "
            "AND change_event_id IS NULL AND change_event_revision IS NULL AND policy_rule_id IS NOT NULL AND policy_revision IS NOT NULL AND policy_hash IS NOT NULL)",
            name="ck_knowledge_conflict_participant_reference_shape",
        ),
        sa.CheckConstraint("claim_revision IS NULL OR claim_revision >= 1", name="ck_knowledge_conflict_claim_revision"),
        sa.CheckConstraint("change_event_revision IS NULL OR change_event_revision >= 1", name="ck_knowledge_conflict_event_revision"),
        sa.CheckConstraint("policy_revision IS NULL OR policy_revision >= 1", name="ck_knowledge_conflict_policy_revision"),
        sa.CheckConstraint("claim_hash IS NULL OR length(claim_hash) = 64", name="ck_knowledge_conflict_claim_hash"),
        sa.CheckConstraint("policy_hash IS NULL OR length(policy_hash) = 64", name="ck_knowledge_conflict_policy_hash"),
        sa.ForeignKeyConstraint(["conflict_id", "group_revision"], ["knowledge_conflict_groups.conflict_id", "knowledge_conflict_groups.revision"], ondelete="RESTRICT", name="fk_knowledge_conflict_participant_group"),
        sa.ForeignKeyConstraint(["claim_id", "claim_revision"], ["knowledge_claims.claim_id", "knowledge_claims.revision"], ondelete="RESTRICT", name="fk_knowledge_conflict_claim_participant"),
        sa.ForeignKeyConstraint(["change_event_id", "change_event_revision"], ["knowledge_change_events.change_event_id", "knowledge_change_events.revision"], ondelete="RESTRICT", name="fk_knowledge_conflict_event_participant"),
        sa.ForeignKeyConstraint(["policy_rule_id", "policy_revision", "policy_hash"], ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision", "policy_rule_revisions.content_hash"], ondelete="RESTRICT", name="fk_knowledge_conflict_policy_participant"),
        sa.PrimaryKeyConstraint("conflict_id", "group_revision", "ordinal", name="pk_knowledge_conflict_participants"),
    )
    op.create_index("ix_knowledge_conflict_participant_claim", "knowledge_conflict_participants", ["claim_id", "claim_revision"])
    op.create_index("ix_knowledge_conflict_participant_policy", "knowledge_conflict_participants", ["policy_rule_id", "policy_revision"])
    op.create_table(
        "knowledge_conflict_evidence",
        sa.Column("conflict_id", sa.String(96), nullable=False),
        sa.Column("group_revision", sa.Integer(), nullable=False),
        sa.Column("participant_ordinal", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_observation_id", sa.String(64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("locator_page", sa.Integer(), nullable=True),
        sa.Column("locator_table", sa.String(256), nullable=True),
        sa.Column("locator_row", sa.Integer(), nullable=True),
        sa.Column("locator_section", sa.String(512), nullable=True),
        sa.Column("locator_field", sa.String(128), nullable=True),
        sa.Column("locator_record_key", sa.String(256), nullable=True),
        sa.Column("inferred", sa.Boolean(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_conflict_evidence_ordinal"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_knowledge_conflict_evidence_url"),
        sa.CheckConstraint("length(snapshot_sha256) = 64", name="ck_knowledge_conflict_evidence_snapshot_hash"),
        sa.CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_knowledge_conflict_evidence_page"),
        sa.CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_knowledge_conflict_evidence_row"),
        sa.ForeignKeyConstraint(["conflict_id", "group_revision", "participant_ordinal"], ["knowledge_conflict_participants.conflict_id", "knowledge_conflict_participants.group_revision", "knowledge_conflict_participants.ordinal"], ondelete="RESTRICT", name="fk_knowledge_conflict_evidence_participant"),
        sa.ForeignKeyConstraint(["source_observation_id"], ["knowledge_source_observations.source_observation_id"], ondelete="RESTRICT", name="fk_knowledge_conflict_evidence_observation"),
        sa.ForeignKeyConstraint(["snapshot_sha256"], ["source_snapshots.content_sha256"], ondelete="RESTRICT", name="fk_knowledge_conflict_evidence_snapshot"),
        sa.PrimaryKeyConstraint("conflict_id", "group_revision", "participant_ordinal", "ordinal", name="pk_knowledge_conflict_evidence"),
    )
    op.create_index("ix_knowledge_conflict_evidence_observation", "knowledge_conflict_evidence", ["source_observation_id"])
    op.create_table(
        "knowledge_conflict_events",
        sa.Column("event_id", sa.String(96), nullable=False),
        sa.Column("conflict_id", sa.String(96), nullable=False),
        sa.Column("group_revision", sa.Integer(), nullable=False),
        sa.Column("group_hash", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(40), nullable=False),
        sa.Column("actor_account_id", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("resolution_participant_ordinal", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_id LIKE 'knowledge-conflict-event:%'", name="ck_knowledge_conflict_event_id_prefix"),
        sa.CheckConstraint("sequence >= 1", name="ck_knowledge_conflict_event_sequence"),
        sa.CheckConstraint("length(group_hash) = 64", name="ck_knowledge_conflict_event_group_hash"),
        sa.CheckConstraint("length(reason) > 0", name="ck_knowledge_conflict_event_reason"),
        sa.CheckConstraint(
            "(event_kind = 'opened' AND sequence = 1 AND actor_account_id IS NULL AND resolution_participant_ordinal IS NULL) OR "
            "(event_kind = 'resolved_by_supersession' AND sequence > 1 AND actor_account_id IS NULL AND resolution_participant_ordinal IS NOT NULL) OR "
            "(event_kind = 'resolved_by_human_review' AND sequence > 1 AND actor_account_id IS NOT NULL AND resolution_participant_ordinal IS NOT NULL) OR "
            "(event_kind IN ('dismissed', 'reopened') AND sequence > 1 AND actor_account_id IS NOT NULL AND resolution_participant_ordinal IS NULL)",
            name="ck_knowledge_conflict_event_shape",
        ),
        sa.ForeignKeyConstraint(["conflict_id", "group_revision", "group_hash"], ["knowledge_conflict_groups.conflict_id", "knowledge_conflict_groups.revision", "knowledge_conflict_groups.content_hash"], ondelete="RESTRICT", name="fk_knowledge_conflict_event_group_hash"),
        sa.ForeignKeyConstraint(["conflict_id", "group_revision", "resolution_participant_ordinal"], ["knowledge_conflict_participants.conflict_id", "knowledge_conflict_participants.group_revision", "knowledge_conflict_participants.ordinal"], ondelete="RESTRICT", name="fk_knowledge_conflict_event_resolution_participant"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.account_id"], ondelete="RESTRICT", name="fk_knowledge_conflict_event_actor"),
        sa.PrimaryKeyConstraint("event_id", name="pk_knowledge_conflict_events"),
        sa.UniqueConstraint("conflict_id", "group_revision", "sequence", name="uq_knowledge_conflict_event_sequence"),
    )
    op.create_index("ix_knowledge_conflict_events_actor_time", "knowledge_conflict_events", ["actor_account_id", "recorded_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM knowledge_conflict_groups) + "
            "(SELECT count(*) FROM knowledge_conflict_events)"
        )
    ).scalar_one():
        raise RuntimeError("Cannot downgrade persisted conflict groups without discarding resolution audit")
    op.drop_index("ix_knowledge_conflict_events_actor_time", table_name="knowledge_conflict_events")
    op.drop_table("knowledge_conflict_events")
    op.drop_index("ix_knowledge_conflict_evidence_observation", table_name="knowledge_conflict_evidence")
    op.drop_table("knowledge_conflict_evidence")
    op.drop_index("ix_knowledge_conflict_participant_policy", table_name="knowledge_conflict_participants")
    op.drop_index("ix_knowledge_conflict_participant_claim", table_name="knowledge_conflict_participants")
    op.drop_table("knowledge_conflict_participants")
    op.drop_index("ix_knowledge_conflict_scope_time", table_name="knowledge_conflict_groups")
    op.drop_index("ix_knowledge_conflict_latest", table_name="knowledge_conflict_groups")
    op.drop_table("knowledge_conflict_groups")
