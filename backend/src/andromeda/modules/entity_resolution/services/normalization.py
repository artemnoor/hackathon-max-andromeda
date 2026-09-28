"""Stable query normalization and curated aliases.

Aliases are deliberately kept as versioned code configuration for the MVP.
They are not a hidden source of truth and can later move to an audited table.
"""

from __future__ import annotations

import re

from andromeda.shared.contracts.versions import SEMANTIC_TAXONOMY_VERSION

ALIAS_POLICY_VERSION = "resolver-aliases.v1"

UNIVERSITY_ALIASES: dict[str, tuple[str, ...]] = {
    "university:bmstu": (
        "мгту",
        "мгту баумана",
        "мгту им баумана",
        "мгту им н э баумана",
        "бауманка",
    ),
    "university:hse": (
        "вшэ",
        "вышка",
        "высшая школа экономики",
        "hse",
    ),
    "university:mephi": (
        "мифи",
        "нИЯУ мифи",
        "мефи",
    ),
}

DIRECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "09.03.03": ("пи", "прикладная информатика"),
    "09.03.01": ("информатика и вычислительная техника", "ивт"),
}

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "math_share": ("матан", "математика", "математическая нагрузка", "математике"),
    "programming_share": ("программирование", "программированию", "кодинг"),
    "ai_share": ("ai", "ии", "искусственный интеллект", "машинное обучение"),
    "physics_share": ("физика", "физике"),
    "business_share": ("бизнес", "бизнесу"),
}


def normalize_text(value: str) -> str:
    """Normalize Cyrillic spelling and punctuation without changing IDs."""

    normalized = value.replace("ё", "е").replace("Ё", "Е").casefold()
    normalized = re.sub(r"[^\w:.-]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def tokens(value: str) -> frozenset[str]:
    return frozenset(normalize_text(value).replace(":", " ").replace(".", " ").replace("-", " ").split())


def aliases_for(*, entity_id: str, code: str | None = None, entity_name: str | None = None) -> tuple[str, ...]:
    normalized_id = normalize_text(entity_id)
    if normalized_id in UNIVERSITY_ALIASES:
        return UNIVERSITY_ALIASES[normalized_id]
    if code and normalize_text(code) in DIRECTION_ALIASES:
        return DIRECTION_ALIASES[normalize_text(code)]
    if normalized_id.startswith("metric:"):
        return METRIC_ALIASES.get(normalized_id.removeprefix("metric:"), ())
    if entity_name and "математический анализ" in normalize_text(entity_name):
        return ("матан",)
    return ()


def direction_university_id(direction_id: str) -> str | None:
    parts = direction_id.split(":")
    if len(parts) == 3:
        return f"university:{parts[1]}"
    return None


def program_university_id(program_id: str) -> str | None:
    parts = program_id.split(":")
    if len(parts) == 3:
        return f"university:{parts[1]}"
    return None


__all__ = [
    "ALIAS_POLICY_VERSION",
    "SEMANTIC_TAXONOMY_VERSION",
    "aliases_for",
    "direction_university_id",
    "normalize_text",
    "program_university_id",
    "tokens",
]
