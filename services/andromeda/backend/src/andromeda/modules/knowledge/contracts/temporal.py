"""Reusable time contracts for immutable, source-backed knowledge revisions."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel


class TemporalInterval(ContractModel):
    """A half-open valid-time interval [start, end), with optional open bounds."""

    start: datetime | None = None
    end: datetime | None = None

    @field_validator("start", "end")
    @classmethod
    def normalize_bounds(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            _require_aware(value, "temporal bound")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def validate_bounds(self) -> TemporalInterval:
        if self.start is None and self.end is None:
            raise ValueError("a temporal interval must have at least one bound")
        for value in (self.start, self.end):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("temporal interval bounds must be timezone-aware")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("temporal intervals must have start < end")
        return self

    def contains(self, instant: datetime) -> bool:
        _require_aware(instant, "instant")
        normalized = instant.astimezone(UTC)
        return (self.start is None or self.start.astimezone(UTC) <= normalized) and (
            self.end is None or normalized < self.end.astimezone(UTC)
        )


class BitemporalRevision(ContractModel):
    """Immutable revision clock: valid time plus when this revision was recorded."""

    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    valid_time: TemporalInterval | None = None
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, value: datetime) -> datetime:
        _require_aware(value, "recorded_at")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_aware_recorded_at(self) -> BitemporalRevision:
        _require_aware(self.recorded_at, "recorded_at")
        return self

    def is_known_at(self, instant: datetime) -> bool:
        _require_aware(instant, "as_known_at")
        return self.recorded_at.astimezone(UTC) <= instant.astimezone(UTC)

    def is_valid_at(self, instant: datetime) -> bool | None:
        _require_aware(instant, "instant")
        return self.valid_time.contains(instant) if self.valid_time is not None else None


class SourceMilestones(ContractModel):
    """Source dates; unknown milestones remain absent instead of being inferred."""

    published_at: datetime | None = None
    announced_at: datetime | None = None
    adopted_at: datetime | None = None
    effective_time: TemporalInterval | None = None
    captured_at: datetime | None = None

    @field_validator("published_at", "announced_at", "adopted_at", "captured_at")
    @classmethod
    def normalize_milestone(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            _require_aware(value, "source milestone")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def validate_times(self) -> SourceMilestones:
        for name in (
            "published_at",
            "announced_at",
            "adopted_at",
            "captured_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        return self


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


__all__ = ["BitemporalRevision", "SourceMilestones", "TemporalInterval"]
