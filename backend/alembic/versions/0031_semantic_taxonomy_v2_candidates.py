"""Add the reviewed candidate features for the extensible semantic registry."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0031_sem_candidates"
down_revision = "0030_sem_changes"
branch_labels = None
depends_on = None


_FEATURES = (
    ("algorithms", "Алгоритмы", "Алгоритмы и алгоритмическое мышление", "subject"),
    ("databases", "Базы данных", "Проектирование и использование баз данных", "subject"),
    ("information_systems", "Информационные системы", "Анализ и проектирование информационных систем", "subject"),
    ("data_analysis", "Анализ данных", "Подготовка, исследование и интерпретация данных", "skill"),
    ("cybersecurity", "Кибербезопасность", "Защита информации и компьютерных систем", "subject"),
    ("calculus", "Математический анализ", "Пределы, производные, интегралы и calculus", "subject"),
    ("linear_algebra", "Линейная алгебра", "Векторы, матрицы и линейные преобразования", "subject"),
    ("discrete_math", "Дискретная математика", "Дискретные структуры и методы", "subject"),
    ("probability", "Теория вероятностей", "Вероятностные модели и случайные процессы", "subject"),
    ("optimization", "Оптимизация", "Методы оптимизации и принятия решений", "subject"),
    ("mechanics", "Механика", "Механические системы и движение", "subject"),
    ("electronics", "Электроника", "Электронные компоненты и схемы", "subject"),
    ("law", "Право", "Правовые нормы и юридические основы", "subject"),
    ("theoretical", "Теоретичность", "Степень теоретической направленности", "learning_style"),
    ("practical", "Практичность", "Степень практической направленности", "learning_style"),
)


def upgrade() -> None:
    feature_table = sa.table(
        "semantic_features",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("feature_group", sa.String),
        sa.column("value_type", sa.String),
        sa.column("semantic_version", sa.String),
    )
    existing = op.get_bind().execute(sa.select(feature_table.c.code)).scalars().all()
    existing_codes = set(existing)
    op.bulk_insert(
        feature_table,
        [
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
            if code not in existing_codes
        ],
    )


def downgrade() -> None:
    codes = tuple(f"semantic-feature:{code}" for code, *_ in _FEATURES)
    statement = sa.delete(sa.table("semantic_features", sa.column("id", sa.String))).where(
        sa.column("id", sa.String).in_(codes)
    )
    op.get_bind().execute(statement)
