"""Persist versioned semantic signals and curriculum item source links."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0026_semantic"
down_revision = "0025_uni_events"
branch_labels = None
depends_on = None


_FEATURES = (
    ("mathematics", "Математика", "Математический аппарат и математические методы", "subject"),
    ("statistics", "Статистика", "Статистика, вероятность и количественный анализ", "subject"),
    ("programming", "Программирование", "Разработка программного обеспечения и алгоритмов", "subject"),
    ("computer_science", "Компьютерные науки", "Основы computer science и вычислительных систем", "subject"),
    ("data", "Данные", "Работа с данными, базами и data-процессами", "subject"),
    ("ai_ml", "AI и машинное обучение", "Искусственный интеллект и machine learning", "subject"),
    ("physics", "Физика", "Физические явления и модели", "subject"),
    ("engineering", "Инженерия", "Инженерные методы и проектирование систем", "subject"),
    ("business", "Бизнес", "Бизнес-процессы и предпринимательство", "subject"),
    ("management", "Менеджмент", "Управление организациями и командами", "subject"),
    ("economics", "Экономика", "Экономические модели и анализ", "subject"),
    ("finance", "Финансы", "Финансовые инструменты и управление финансами", "subject"),
    ("linguistics", "Лингвистика", "Язык и лингвистический анализ", "subject"),
    ("design", "Дизайн", "Проектирование визуальных и пользовательских решений", "subject"),
    ("research", "Исследования", "Исследовательская и научная деятельность", "activity"),
    ("analytics", "Аналитика", "Аналитическая деятельность и интерпретация данных", "skill"),
    ("theory", "Теория", "Теоретическая направленность обучения", "learning_style"),
    ("practice", "Практика", "Практическая направленность обучения", "learning_style"),
    ("project_work", "Проектная работа", "Проектная и командная работа", "activity"),
    ("communication", "Коммуникация", "Коммуникационные и презентационные навыки", "skill"),
)


def upgrade() -> None:
    with op.batch_alter_table("curriculum_items", recreate="auto") as batch:
        batch.add_column(sa.Column("lecture_hours", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("practice_hours", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("lab_hours", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("self_study_hours", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("is_elective", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("course_block", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("practice_type", sa.String(length=128), nullable=True))
        batch.create_check_constraint("ck_item_lecture_hours", "lecture_hours IS NULL OR (lecture_hours >= 0 AND lecture_hours <= 2000)")
        batch.create_check_constraint("ck_item_practice_hours", "practice_hours IS NULL OR (practice_hours >= 0 AND practice_hours <= 2000)")
        batch.create_check_constraint("ck_item_lab_hours", "lab_hours IS NULL OR (lab_hours >= 0 AND lab_hours <= 2000)")
        batch.create_check_constraint("ck_item_self_study_hours", "self_study_hours IS NULL OR (self_study_hours >= 0 AND self_study_hours <= 2000)")

    op.create_table(
        "curriculum_item_source_links",
        sa.Column("link_id", sa.String(length=128), nullable=False),
        sa.Column("curriculum_item_id", sa.String(length=256), sa.ForeignKey("curriculum_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), sa.ForeignKey("source_snapshots.content_sha256"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(length=512), nullable=True),
        sa.Column("university_id", sa.String(length=128), nullable=True),
        sa.Column("field", sa.String(length=128), nullable=True),
        sa.Column("record_key", sa.String(length=256), nullable=True),
        sa.Column("inferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ingest_run_id", sa.String(length=64), sa.ForeignKey("ingest_runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("link_id"),
        sa.UniqueConstraint(
            "curriculum_item_id",
            "source_sha256",
            "source_url",
            "locator",
            "field",
            "record_key",
            name="uq_curriculum_item_source_link",
        ),
    )
    op.create_index("ix_curriculum_item_source_links_item", "curriculum_item_source_links", ["curriculum_item_id"])
    op.create_index("ix_curriculum_item_source_links_source", "curriculum_item_source_links", ["source_sha256"])

    op.create_table(
        "semantic_features",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("feature_group", sa.String(length=32), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("semantic_version", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.CheckConstraint("id LIKE 'semantic-feature:%'", name="ck_semantic_feature_id"),
        sa.CheckConstraint("length(code) > 0", name="ck_semantic_feature_code"),
    )
    op.create_index("ix_semantic_features_code_version", "semantic_features", ["code", "semantic_version"])

    _create_semantic_assignment_table(
        "discipline_semantic_features",
        "discipline_id",
        "disciplines.id",
        "ix_discipline_semantic_feature_lookup",
        "discipline_id",
    )
    _create_semantic_assignment_table(
        "curriculum_item_semantic_features",
        "curriculum_item_id",
        "curriculum_items.id",
        "ix_curriculum_item_semantic_feature_lookup",
        "curriculum_item_id",
    )

    semantic_features = [
        {
            "id": f"semantic-feature:{code}",
            "code": code,
            "name": name,
            "description": description,
            "feature_group": group,
            "value_type": "intensity",
            "semantic_version": "semantic-taxonomy.v1",
        }
        for code, name, description, group in _FEATURES
    ]
    op.bulk_insert(
        sa.table(
            "semantic_features",
            sa.column("id", sa.String),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("description", sa.Text),
            sa.column("feature_group", sa.String),
            sa.column("value_type", sa.String),
            sa.column("semantic_version", sa.String),
        ),
        semantic_features,
    )


def _create_semantic_assignment_table(table: str, owner_column: str, owner_fk: str, lookup_index: str, owner_index_column: str) -> None:
    op.create_table(
        table,
        sa.Column(owner_column, sa.String(length=256), sa.ForeignKey(owner_fk, ondelete="CASCADE"), nullable=False),
        sa.Column("feature_id", sa.String(length=96), sa.ForeignKey("semantic_features.id"), nullable=False),
        sa.Column("semantic_version", sa.String(length=64), nullable=False),
        sa.Column("classifier_version", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Numeric(5, 4), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'available'")),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("classification_method", sa.String(length=16), nullable=False),
        sa.Column("source_hash", sa.String(length=64), sa.ForeignKey("source_snapshots.content_sha256"), nullable=True),
        sa.Column("source_run_id", sa.String(length=64), sa.ForeignKey("ingest_runs.id"), nullable=True),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(owner_column, "feature_id", "semantic_version", "classifier_version"),
        sa.CheckConstraint("value IS NULL OR (value >= 0 AND value <= 1)", name=f"ck_{table}_value"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=f"ck_{table}_confidence"),
        sa.CheckConstraint(f"status IN ('available', 'unknown', 'unavailable')", name=f"ck_{table}_status"),
        sa.CheckConstraint(f"(status = 'available' AND value IS NOT NULL) OR (status <> 'available' AND value IS NULL)", name=f"ck_{table}_status_value"),
    )
    op.create_index(lookup_index, table, ["feature_id", "semantic_version", owner_index_column])


def downgrade() -> None:
    op.drop_index("ix_curriculum_item_semantic_feature_lookup", table_name="curriculum_item_semantic_features")
    op.drop_table("curriculum_item_semantic_features")
    op.drop_index("ix_discipline_semantic_feature_lookup", table_name="discipline_semantic_features")
    op.drop_table("discipline_semantic_features")
    op.drop_index("ix_semantic_features_code_version", table_name="semantic_features")
    op.drop_table("semantic_features")
    op.drop_index("ix_curriculum_item_source_links_source", table_name="curriculum_item_source_links")
    op.drop_index("ix_curriculum_item_source_links_item", table_name="curriculum_item_source_links")
    op.drop_table("curriculum_item_source_links")
    with op.batch_alter_table("curriculum_items", recreate="auto") as batch:
        batch.drop_constraint("ck_item_self_study_hours", type_="check")
        batch.drop_constraint("ck_item_lab_hours", type_="check")
        batch.drop_constraint("ck_item_practice_hours", type_="check")
        batch.drop_constraint("ck_item_lecture_hours", type_="check")
        batch.drop_column("practice_type")
        batch.drop_column("course_block")
        batch.drop_column("is_elective")
        batch.drop_column("self_study_hours")
        batch.drop_column("lab_hours")
        batch.drop_column("practice_hours")
        batch.drop_column("lecture_hours")
