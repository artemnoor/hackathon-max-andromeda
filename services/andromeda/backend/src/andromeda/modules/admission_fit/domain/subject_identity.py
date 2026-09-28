"""Compatibility exports for admission-fit callers.

The identity policy is owned by the shared admissions domain so that legal
eligibility and Admission Fit cannot drift into separate subject vocabularies.
"""

from andromeda.modules.admissions.contracts.subject_identity import (
    SubjectResolution,
    SubjectResolutionStatus,
    canonical_subject_key,
    is_known_exam_subject,
    normalize_subject_name,
    resolve_subject,
)

__all__ = [
    "SubjectResolution",
    "SubjectResolutionStatus",
    "canonical_subject_key",
    "is_known_exam_subject",
    "normalize_subject_name",
    "resolve_subject",
]
