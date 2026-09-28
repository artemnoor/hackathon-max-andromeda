"""Content identities for exact admission-benefit owner revisions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from andromeda.shared.contracts.ids import SourceHash

from .public import AdmissionBenefitRule, IndividualAchievementPolicy


def admission_benefit_revision_hash(
    revision: AdmissionBenefitRule | IndividualAchievementPolicy,
) -> SourceHash:
    """Hash normalized owner data while excluding mutable review/staleness state."""

    payload = revision.model_dump(mode="python")
    payload.pop("status", None)
    if isinstance(revision, IndividualAchievementPolicy):
        payload["rules"] = [
            {key: value for key, value in rule.items() if key != "status"}
            for rule in payload["rules"]
        ]
    canonical = json.dumps(
        _canonical_value(payload),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def individual_achievement_domain_rule_id(
    policy: IndividualAchievementPolicy,
) -> str:
    university_slug = policy.university_id.removeprefix("university:")
    level = policy.education_level.value if policy.education_level else "unknown"
    return (
        f"individual-achievement:{university_slug}:"
        f"{policy.admission_year}:{level}"
    )


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return format(normalized, "f") if normalized else "0"
    if isinstance(value, datetime):
        normalized_datetime = (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None or value.utcoffset() is None
            else value.astimezone(UTC)
        )
        return normalized_datetime.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


__all__ = [
    "admission_benefit_revision_hash",
    "individual_achievement_domain_rule_id",
]
