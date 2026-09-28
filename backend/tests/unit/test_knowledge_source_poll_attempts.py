from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from andromeda.modules.knowledge.contracts.public import (
    SourcePollAttempt,
    SourcePollOutcome,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
SOURCE_ID = "source:bmstu-admission"
SNAPSHOT_HASH = "a" * 64


def test_failed_attempt_preserves_last_successful_hash_and_bounded_retry() -> None:
    attempt = SourcePollAttempt(
        attempt_id="poll-attempt:" + "b" * 32,
        source_id=SOURCE_ID,
        registry_revision=2,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        outcome=SourcePollOutcome.UNAVAILABLE,
        parser_version="policy_text_lines:v1",
        previous_snapshot_sha256=SNAPSHOT_HASH,
        snapshot_sha256=None,
        last_successful_snapshot_sha256=SNAPSHOT_HASH,
        source_observation_id=None,
        retry_count=3,
        next_retry_at=NOW + timedelta(minutes=15),
        failure_code="http_503",
        extracted_candidate_count=0,
    )

    assert attempt.last_successful_snapshot_sha256 == SNAPSHOT_HASH
    assert attempt.next_retry_at > attempt.completed_at


def test_unavailable_attempt_cannot_claim_an_observation_or_extracted_claims() -> None:
    with pytest.raises(ValidationError, match="cannot claim a successful snapshot observation"):
        SourcePollAttempt(
            attempt_id="poll-attempt:" + "c" * 32,
            source_id=SOURCE_ID,
            registry_revision=1,
            started_at=NOW,
            completed_at=NOW,
            outcome=SourcePollOutcome.UNAVAILABLE,
            parser_version="policy_text_lines:v1",
            snapshot_sha256=SNAPSHOT_HASH,
            retry_count=1,
            next_retry_at=NOW + timedelta(minutes=5),
            failure_code="http_503",
            extracted_candidate_count=1,
        )
