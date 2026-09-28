"""Persist university-owned catalog editorial overlays."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0024_uni_catalog"
down_revision = "0023_uni_admin"
branch_labels = None
depends_on = None


def _editor_fields(table: str, *, include_created: bool = True) -> list[sa.Column]:
    fields = [
        sa.Column("university_id", sa.String(length=64), sa.ForeignKey("universities.id"), nullable=False),
    ]
    if include_created:
        fields.extend(
            [
                sa.Column("created_by_account_id", sa.String(length=128), sa.ForeignKey("accounts.account_id"), nullable=False),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            ]
        )
    fields.extend(
        [
            sa.Column("updated_by_account_id", sa.String(length=128), sa.ForeignKey("accounts.account_id"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        ]
    )
    return fields


def upgrade() -> None:
    op.create_table(
        "university_units",
        sa.Column("unit_id", sa.String(length=128), nullable=False),
        *_editor_fields("university_units"),
        sa.Column("unit_type", sa.String(length=16), nullable=False),
        sa.Column("parent_unit_id", sa.String(length=128), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(["parent_unit_id"], ["university_units.unit_id"]),
        sa.PrimaryKeyConstraint("unit_id"),
        sa.UniqueConstraint("university_id", "slug", name="uq_university_unit_slug"),
        sa.CheckConstraint("unit_id LIKE 'unit:%:%'", name="ck_university_unit_id"),
        sa.CheckConstraint("unit_type IN ('faculty', 'department')", name="ck_university_unit_type"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_university_unit_status"),
        sa.CheckConstraint("sort_order >= 0", name="ck_university_unit_sort_order"),
        sa.CheckConstraint("revision >= 1", name="ck_university_unit_revision"),
        sa.CheckConstraint("length(slug) > 0 AND length(name) > 0", name="ck_university_unit_text"),
    )
    op.create_table(
        "university_categories",
        sa.Column("category_id", sa.String(length=128), nullable=False),
        *_editor_fields("university_categories"),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("category_id"),
        sa.UniqueConstraint("university_id", "slug", name="uq_university_category_slug"),
        sa.CheckConstraint("category_id LIKE 'category:%:%'", name="ck_university_category_id"),
        sa.CheckConstraint("category_kind IN ('subject', 'program', 'event', 'general')", name="ck_university_category_kind"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_university_category_status"),
        sa.CheckConstraint("sort_order >= 0", name="ck_university_category_sort_order"),
        sa.CheckConstraint("revision >= 1", name="ck_university_category_revision"),
        sa.CheckConstraint("length(slug) > 0 AND length(name) > 0", name="ck_university_category_text"),
    )
    op.create_table(
        "university_program_editorials",
        *_editor_fields("university_program_editorials", include_created=False),
        sa.Column("program_id", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=True),
        sa.Column("public_summary", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default=sa.text("'visible'")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("university_id", "program_id"),
        sa.CheckConstraint("visibility IN ('visible', 'hidden')", name="ck_university_program_editorial_visibility"),
        sa.CheckConstraint("revision >= 1", name="ck_university_program_editorial_revision"),
    )
    op.create_table(
        "university_discipline_editorials",
        *_editor_fields("university_discipline_editorials", include_created=False),
        sa.Column("discipline_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("public_summary", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default=sa.text("'visible'")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("university_id", "discipline_id"),
        sa.CheckConstraint("visibility IN ('visible', 'hidden')", name="ck_university_discipline_editorial_visibility"),
        sa.CheckConstraint("revision >= 1", name="ck_university_discipline_editorial_revision"),
    )
    link_specs = (
        ("university_category_program_links", "category_id", "university_categories.category_id", "program_id", 96),
        ("university_category_discipline_links", "category_id", "university_categories.category_id", "discipline_id", 64),
        ("university_unit_program_links", "unit_id", "university_units.unit_id", "program_id", 96),
        ("university_unit_discipline_links", "unit_id", "university_units.unit_id", "discipline_id", 64),
    )
    for table, owner_column, owner_target, target_column, target_length in link_specs:
        op.create_table(
            table,
            sa.Column("university_id", sa.String(length=64), sa.ForeignKey("universities.id"), nullable=False),
            sa.Column(owner_column, sa.String(length=128), sa.ForeignKey(owner_target), nullable=False),
            sa.Column(target_column, sa.String(length=target_length), nullable=False),
            sa.PrimaryKeyConstraint("university_id", owner_column, target_column),
        )
        op.create_index(f"ix_{table}_university_id", table, ["university_id"])
    op.create_index("ix_university_units_public", "university_units", ["university_id", "status", "sort_order"])
    op.create_index("ix_university_categories_public", "university_categories", ["university_id", "status", "sort_order"])


def downgrade() -> None:
    for table in (
        "university_unit_discipline_links",
        "university_unit_program_links",
        "university_category_discipline_links",
        "university_category_program_links",
    ):
        op.drop_index(f"ix_{table}_university_id", table_name=table)
        op.drop_table(table)
    op.drop_table("university_discipline_editorials")
    op.drop_table("university_program_editorials")
    op.drop_index("ix_university_categories_public", table_name="university_categories")
    op.drop_table("university_categories")
    op.drop_index("ix_university_units_public", table_name="university_units")
    op.drop_table("university_units")
