from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    SourceMilestones,
    TemporalInterval,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision

PUBLISHED = datetime(2027, 12, 1, tzinfo=UTC)
CAPTURED = datetime(2027, 12, 15, tzinfo=UTC)
EFFECTIVE = datetime(2028, 9, 1, tzinfo=UTC)


def test_source_milestones_keep_publication_capture_recording_and_effect_separate() -> None:
    milestones = SourceMilestones(
        published_at=PUBLISHED,
        captured_at=CAPTURED,
        effective_time=TemporalInterval(start=EFFECTIVE),
    )

    policy_revision = PolicyTemporalRevision(
        clock=BitemporalRevision(
            revision=1,
            valid_time=milestones.effective_time,
            recorded_at=CAPTURED,
        ),
        source_milestones=milestones,
    )

    assert policy_revision.source_milestones.published_at == PUBLISHED
    assert policy_revision.source_milestones.captured_at == CAPTURED
    assert policy_revision.clock.recorded_at == CAPTURED
    assert policy_revision.clock.valid_time is not None
    assert policy_revision.clock.valid_time.contains(EFFECTIVE)
    assert not policy_revision.clock.valid_time.contains(
        datetime(2027, 12, 15, tzinfo=UTC)
    )
    assert not policy_revision.clock.valid_time.contains(
        datetime(2028, 8, 31, 23, 59, tzinfo=UTC)
    )


def test_revision_supports_as_known_at_and_half_open_valid_time() -> None:
    effective = TemporalInterval(
        start=EFFECTIVE,
        end=datetime(2029, 9, 1, tzinfo=UTC),
    )
    revision = BitemporalRevision(revision=1, valid_time=effective, recorded_at=CAPTURED)

    assert not revision.is_known_at(datetime(2027, 12, 14, tzinfo=UTC))
    assert revision.is_known_at(CAPTURED)
    assert not revision.is_valid_at(datetime(2028, 8, 31, 23, 59, tzinfo=UTC))
    assert revision.is_valid_at(EFFECTIVE)
    assert not revision.is_valid_at(datetime(2029, 9, 1, tzinfo=UTC))


def test_temporal_contracts_reject_naive_and_invalid_intervals() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TemporalInterval(start=EFFECTIVE.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="start < end"):
        TemporalInterval(start=EFFECTIVE, end=EFFECTIVE)
    with pytest.raises(ValidationError, match="at least one bound"):
        TemporalInterval()
    with pytest.raises(ValidationError, match="cannot precede source capture"):
        PolicyTemporalRevision(
            clock=BitemporalRevision(revision=1, recorded_at=PUBLISHED),
            source_milestones=SourceMilestones(captured_at=CAPTURED),
        )


def test_missing_valid_time_remains_unknown() -> None:
    revision = BitemporalRevision(revision=1, recorded_at=CAPTURED)

    assert revision.is_valid_at(EFFECTIVE) is None
