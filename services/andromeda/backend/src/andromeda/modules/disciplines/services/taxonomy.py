from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
from hashlib import sha256

from ..contracts.classification import ClassificationOutcome
from ..contracts.overrides import TaxonomyOverride, TaxonomyOverrideArtifact, TaxonomyRegressionCase, UnknownClassification
from ..domain.areas import AreaVector
from ..domain.identity import normalize_classification_name


class TaxonomyOverrideError(ValueError):
    """Raised when an adapter override artifact is unsafe to apply."""


class TaxonomyOverrideRegistry:
    """Validate and materialize reviewed adapter-owned taxonomy overrides."""

    def __init__(self, overrides: Sequence[TaxonomyOverride]) -> None:
        self._overrides = tuple(overrides)
        self._validate()

    @property
    def overrides(self) -> tuple[TaxonomyOverride, ...]:
        return self._overrides

    def mapping_for(self, university_id: str) -> dict[str, AreaVector]:
        return self._resolved_mapping(university_id)

    def aliases_for(self, university_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for override in self._approved_for(university_id):
            if override.source_alias is not None:
                result[normalize_classification_name(override.source_alias)] = self._resolve_alias(
                    university_id,
                    normalize_classification_name(override.normalized_key),
                )
        return result

    def artifact_for(self, university_id: str) -> TaxonomyOverrideArtifact:
        selected = tuple(self._approved_for(university_id))
        cases = tuple(
            TaxonomyRegressionCase(
                normalized_name=override.normalized_key,
                area_weights=override.area_weights,
            )
            for override in selected
        )
        payload = [
            {
                "normalized_key": override.normalized_key,
                "source_alias": override.source_alias,
                "university_id": override.university_id,
                "area_weights": [
                    {"area": weight.area.value, "weight": str(weight.weight)}
                    for weight in override.area_weights
                ],
                "reason": override.reason,
                "owner": override.owner,
                "created_at": override.created_at.isoformat(),
                "taxonomy_version": override.taxonomy_version,
                "review_state": override.review_state,
                "reviewed_by": override.reviewed_by,
                "reviewed_at": override.reviewed_at.isoformat() if override.reviewed_at else None,
                "affected_source_count": override.affected_source_count,
                "blocking": override.blocking,
            }
            for override in selected
        ]
        content_sha256 = sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        taxonomy_version = selected[0].taxonomy_version if selected else "taxonomy-22.v1"
        return TaxonomyOverrideArtifact(
            university_id=university_id,
            taxonomy_version=taxonomy_version,
            content_sha256=content_sha256,
            overrides=selected,
            regression_cases=cases,
        )

    def _approved_for(self, university_id: str) -> tuple[TaxonomyOverride, ...]:
        return tuple(
            override
            for override in self._overrides
            if override.university_id == university_id and override.review_state == "approved"
        )

    def _resolved_mapping(self, university_id: str) -> dict[str, AreaVector]:
        selected = self._approved_for(university_id)
        by_key = {normalize_classification_name(item.normalized_key): item for item in selected}
        result: dict[str, AreaVector] = {key: _area_vector(item) for key, item in by_key.items()}
        return result

    def _resolve_alias(self, university_id: str, key: str) -> str:
        aliases = {
            normalize_classification_name(item.source_alias): normalize_classification_name(item.normalized_key)
            for item in self._approved_for(university_id)
            if item.source_alias is not None
        }
        current = key
        visited: set[str] = set()
        while current in aliases:
            if current in visited:
                raise TaxonomyOverrideError(f"taxonomy alias cycle detected at {current}")
            visited.add(current)
            current = aliases[current]
        return current

    def _validate(self) -> None:
        by_scope: dict[tuple[str, str], TaxonomyOverride] = {}
        aliases: dict[tuple[str, str], str] = {}
        for override in self._overrides:
            key = (override.university_id, normalize_classification_name(override.normalized_key))
            if key in by_scope:
                raise TaxonomyOverrideError(f"duplicate taxonomy override: {key[0]}/{key[1]}")
            by_scope[key] = override
            if override.source_alias is not None:
                alias = (override.university_id, normalize_classification_name(override.source_alias))
                target = normalize_classification_name(override.normalized_key)
                previous = aliases.get(alias)
                if previous is not None and previous != target:
                    raise TaxonomyOverrideError(f"conflicting taxonomy alias: {alias[0]}/{alias[1]}")
                if alias in by_scope:
                    raise TaxonomyOverrideError(f"taxonomy alias collides with canonical key: {alias[0]}/{alias[1]}")
                aliases[alias] = target
        for alias_key, target in aliases.items():
            university_id, alias_name = alias_key
            if alias_key in by_scope:
                raise TaxonomyOverrideError(f"taxonomy alias collides with canonical key: {university_id}/{alias_name}")
            current = alias_name
            visited: set[str] = set()
            while (university_id, current) in aliases:
                if current in visited:
                    raise TaxonomyOverrideError(f"taxonomy alias cycle detected at {university_id}/{current}")
                visited.add(current)
                current = aliases[(university_id, current)]
            if (university_id, current) not in by_scope:
                raise TaxonomyOverrideError(f"taxonomy alias target is not canonical: {university_id}/{alias_name} -> {current}")


def build_unknown_queue(
    outcomes: Iterable[ClassificationOutcome],
    *,
    university_id: str,
    run_id: str,
    affected_programs: Mapping[str, Sequence[str]] | None = None,
    observed_counts: Mapping[str, int] | None = None,
) -> tuple[UnknownClassification, ...]:
    """Group unresolved outcomes into a stable operator-facing queue."""

    affected = affected_programs or {}
    counts = observed_counts or {}
    grouped: dict[str, UnknownClassification] = {}
    for outcome in outcomes:
        if outcome.method not in {"unresolved", "fallback"}:
            continue
        key = normalize_classification_name(outcome.normalized_name)
        previous = grouped.get(key)
        source_count = counts.get(key, 1)
        programs = tuple(sorted(set(affected.get(key, ()))))
        if previous is None:
            grouped[key] = UnknownClassification(
                normalized_name=key,
                university_id=university_id,
                source_count=max(1, source_count),
                affected_programs=programs,
                first_seen_run_id=run_id,
                last_seen_run_id=run_id,
            )
        else:
            grouped[key] = previous.model_copy(
                update={
                    "source_count": previous.source_count + max(1, source_count),
                    "affected_programs": tuple(sorted(set(previous.affected_programs) | set(programs))),
                    "last_seen_run_id": run_id,
                }
            )
    return tuple(grouped[key] for key in sorted(grouped))


def _area_vector(value: TaxonomyOverride) -> AreaVector:
    return tuple((weight.area, weight.weight) for weight in value.area_weights)


__all__ = ["TaxonomyOverrideError", "TaxonomyOverrideRegistry", "build_unknown_queue"]
