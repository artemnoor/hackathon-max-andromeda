"""Persist exact, review-only claim candidate clusters."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0043_knowledge_exact_claim_clusters"
down_revision = "0042_knowledge_source_poll_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_claim_candidate_clusters",
        sa.Column("cluster_id", sa.String(length=78), nullable=False),
        sa.Column("fingerprint", sa.String(length=83), nullable=False),
        sa.Column("fingerprint_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cluster_id LIKE 'claim-cluster:%'", name="ck_knowledge_claim_cluster_id_prefix"
        ),
        sa.CheckConstraint(
            "fingerprint LIKE 'claim-fingerprint:%'",
            name="ck_knowledge_claim_cluster_fingerprint_prefix",
        ),
        sa.CheckConstraint(
            "length(fingerprint_version) > 0", name="ck_knowledge_claim_cluster_version"
        ),
        sa.PrimaryKeyConstraint("cluster_id"),
        sa.UniqueConstraint("fingerprint", name="uq_knowledge_claim_cluster_fingerprint"),
    )
    op.create_index(
        "ix_knowledge_claim_clusters_created",
        "knowledge_claim_candidate_clusters",
        ["created_at"],
    )
    op.create_table(
        "knowledge_claim_candidate_cluster_members",
        sa.Column("cluster_id", sa.String(length=78), nullable=False),
        sa.Column("claim_id", sa.String(length=70), nullable=False),
        sa.Column("claim_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "claim_revision >= 1", name="ck_knowledge_claim_cluster_member_revision"
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            name="fk_knowledge_claim_cluster_member_claim",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["knowledge_claim_candidate_clusters.cluster_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("cluster_id", "claim_id", "claim_revision"),
    )
    op.create_index(
        "ix_knowledge_claim_cluster_members_claim",
        "knowledge_claim_candidate_cluster_members",
        ["claim_id", "claim_revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_claim_cluster_members_claim",
        table_name="knowledge_claim_candidate_cluster_members",
    )
    op.drop_table("knowledge_claim_candidate_cluster_members")
    op.drop_index(
        "ix_knowledge_claim_clusters_created",
        table_name="knowledge_claim_candidate_clusters",
    )
    op.drop_table("knowledge_claim_candidate_clusters")
