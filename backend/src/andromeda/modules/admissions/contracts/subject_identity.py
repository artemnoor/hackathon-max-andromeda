"""Exact canonicalization shared through the public admissions contract."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger("andromeda.modules.admissions.subject_identity")


class SubjectResolutionStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SubjectResolution:
    input_subject: str
    normalized_subject: str
    status: SubjectResolutionStatus
    matched_subject: str | None = None
    candidates: tuple[str, ...] = ()


# Explicit spelling aliases only; unknown labels never receive fuzzy matching.
_ALIASES: dict[str, str] = {
    "русский": "русский язык",
    "математика профильная": "математика",
    "профильная математика": "математика",
    "математика профиль": "математика",
    "математика профильный уровень": "математика",
    "иностранный": "иностранный язык",
    "английский": "иностранный язык",
    "информатика": "информатика и информационно коммуникационные технологии",
    "информатика и икт": "информатика и информационно коммуникационные технологии",
}
_CANONICAL_EXAM_SUBJECTS = frozenset(
    {
        "русский язык",
        "математика",
        "физика",
        "химия",
        "информатика и информационно коммуникационные технологии",
        "биология",
        "история",
        "география",
        "обществознание",
        "иностранный язык",
        "литература",
    }
)


def normalize_subject_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def canonical_subject_key(value: str) -> str:
    normalized = normalize_subject_name(value)
    return _ALIASES.get(normalized, normalized)


def is_known_exam_subject(value: str) -> bool:
    """Whether an exact normalized label maps to a supported school exam subject."""

    return canonical_subject_key(value) in _CANONICAL_EXAM_SUBJECTS


def resolve_subject(
    input_subject: str, available_subjects: tuple[str, ...]
) -> SubjectResolution:
    key = canonical_subject_key(input_subject)
    candidates = tuple(
        subject
        for subject in available_subjects
        if canonical_subject_key(subject) == key
    )
    if len(candidates) == 1:
        logger.debug(
            "subject_identity_resolved normalized_key=%s candidate_count=1", key
        )
        return SubjectResolution(
            input_subject, key, SubjectResolutionStatus.MATCHED, candidates[0]
        )
    if not candidates:
        logger.warning("subject_identity_missing normalized_key=%s", key)
        return SubjectResolution(input_subject, key, SubjectResolutionStatus.MISSING)
    logger.warning(
        "subject_identity_ambiguous normalized_key=%s candidate_count=%d",
        key,
        len(candidates),
    )
    return SubjectResolution(
        input_subject, key, SubjectResolutionStatus.AMBIGUOUS, candidates=candidates
    )


__all__ = [
    "SubjectResolution",
    "SubjectResolutionStatus",
    "canonical_subject_key",
    "is_known_exam_subject",
    "normalize_subject_name",
    "resolve_subject",
]
