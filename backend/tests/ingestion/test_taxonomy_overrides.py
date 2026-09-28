from datetime import datetime, timezone
from decimal import Decimal

import pytest

from andromeda.modules.disciplines.contracts.overrides import TaxonomyOverride
from andromeda.modules.disciplines.domain.areas import DisciplineAreaCode, DisciplineAreaWeight, area_vector
from andromeda.modules.disciplines.services.taxonomy import TaxonomyOverrideError, TaxonomyOverrideRegistry


def _override(
    key: str,
    *,
    alias: str | None = None,
    university: str = "university:third",
    state: str = "approved",
    vector: tuple[tuple[DisciplineAreaCode, str], ...] | None = None,
    count: int = 1,
    blocking: bool = False,
    reviewed: bool = True,
) -> TaxonomyOverride:
    return TaxonomyOverride(
        normalized_key=key,
        university_id=university,
        source_alias=alias,
        area_weights=tuple(
            DisciplineAreaWeight(area=area, weight=Decimal(str(weight)))
            for area, weight in (vector or area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1.00")))
        ),
        reason="reviewed source correction",
        owner="data-team",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        taxonomy_version="taxonomy-22.v1",
        review_state=state,  # type: ignore[arg-type]
        reviewed_by="reviewer" if reviewed else None,
        reviewed_at=datetime(2026, 1, 2, tzinfo=timezone.utc) if reviewed else None,
        affected_source_count=count,
        blocking=blocking,
    )


def test_registry_materializes_only_approved_overrides_and_stable_artifact() -> None:
    registry = TaxonomyOverrideRegistry(
        (
            _override("canonical name", alias="old name"),
            _override("draft name", state="draft", reviewed=False),
        )
    )

    mapping = registry.mapping_for("university:third")
    aliases = registry.aliases_for("university:third")
    artifact = registry.artifact_for("university:third")
    repeated = registry.artifact_for("university:third")

    assert set(mapping) == {"canonical name"}
    assert aliases == {"old name": "canonical name"}
    assert artifact.content_sha256 == repeated.content_sha256
    assert tuple(case.normalized_name for case in artifact.regression_cases) == ("canonical name",)


def test_registry_rejects_duplicate_conflicting_and_colliding_overrides() -> None:
    with pytest.raises(TaxonomyOverrideError, match="duplicate"):
        TaxonomyOverrideRegistry((_override("same"), _override("same")))

    with pytest.raises(TaxonomyOverrideError, match="collides"):
        TaxonomyOverrideRegistry((_override("canonical"), _override("other", alias="canonical")))


def test_high_volume_or_blocking_override_requires_review_identity() -> None:
    with pytest.raises(ValueError, match="review metadata"):
        _override("high-volume", count=100, reviewed=False)

    with pytest.raises(ValueError, match="review metadata"):
        _override("blocking", blocking=True, reviewed=False)


def test_reviewed_vector_is_positive_and_normalized() -> None:
    item = _override(
        "mixed",
        vector=(
            (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.60"),
            (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.40"),
        ),
    )
    assert sum((weight.weight for weight in item.area_weights), Decimal("0")) == Decimal("1.0000")
