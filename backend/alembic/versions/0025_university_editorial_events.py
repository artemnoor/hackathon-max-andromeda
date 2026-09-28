"""Persist university-owned editorial events and agendas."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0025_uni_events"
down_revision = "0024_uni_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "university_editorial_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("university_id", sa.String(length=64), sa.ForeignKey("universities.id"), nullable=False),
        sa.Column("slug", sa.String(length=96), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("registration_url", sa.Text(), nullable=True),
        sa.Column("venue_id", sa.String(length=128), sa.ForeignKey("venues.id"), nullable=True),
        sa.Column("location_label", sa.String(length=512), nullable=True),
        sa.Column("location_address", sa.String(length=1024), nullable=True),
        sa.Column("online_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("audience_mode", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by_account_id", sa.String(length=128), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("updated_by_account_id", sa.String(length=128), sa.ForeignKey("accounts.account_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("university_id", "slug", name="uq_university_editorial_event_slug"),
        sa.CheckConstraint("event_id LIKE 'university-event:%:%'", name="ck_university_editorial_event_id"),
        sa.CheckConstraint("kind IN ('additional_education', 'open_day', 'lecture', 'competition', 'career', 'other')", name="ck_university_editorial_event_kind"),
        sa.CheckConstraint("format IN ('offline', 'online', 'hybrid')", name="ck_university_editorial_event_format"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_university_editorial_event_status"),
        sa.CheckConstraint("audience_mode IN ('all_university', 'selected_units', 'selected_programs', 'unaffiliated')", name="ck_university_editorial_event_audience"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_university_editorial_event_time_window"),
        sa.CheckConstraint("revision >= 1", name="ck_university_editorial_event_revision"),
    )
    op.create_index("ix_university_editorial_events_public", "university_editorial_events", ["university_id", "status", "starts_at"])
    op.create_table(
        "university_editorial_agenda_items",
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.String(length=128), sa.ForeignKey("university_editorial_events.event_id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location_label", sa.String(length=512), nullable=True),
        sa.Column("speaker_label", sa.String(length=512), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("item_id"),
        sa.UniqueConstraint("event_id", "position", name="uq_university_editorial_agenda_position"),
        sa.CheckConstraint("position >= 1", name="ck_university_editorial_agenda_position"),
        sa.CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="ck_university_editorial_agenda_time_window"),
    )
    link_specs = (
        ("university_editorial_event_unit_links", "unit_id", "university_units.unit_id", 128),
        ("university_editorial_event_program_links", "program_id", None, 96),
        ("university_editorial_event_category_links", "category_id", "university_categories.category_id", 128),
    )
    for table, target_column, target_fk, length in link_specs:
        target = sa.Column(target_column, sa.String(length=length), nullable=False)
        if target_fk is not None:
            target = sa.Column(target_column, sa.String(length=length), sa.ForeignKey(target_fk), nullable=False)
        op.create_table(
            table,
            sa.Column("event_id", sa.String(length=128), sa.ForeignKey("university_editorial_events.event_id", ondelete="CASCADE"), nullable=False),
            target,
            sa.PrimaryKeyConstraint("event_id", target_column),
        )
        op.create_index(f"ix_{table}_{target_column}", table, [target_column])


def downgrade() -> None:
    for table, target_column in (
        ("university_editorial_event_category_links", "category_id"),
        ("university_editorial_event_program_links", "program_id"),
        ("university_editorial_event_unit_links", "unit_id"),
    ):
        op.drop_index(f"ix_{table}_{target_column}", table_name=table)
        op.drop_table(table)
    op.drop_table("university_editorial_agenda_items")
    op.drop_index("ix_university_editorial_events_public", table_name="university_editorial_events")
    op.drop_table("university_editorial_events")
