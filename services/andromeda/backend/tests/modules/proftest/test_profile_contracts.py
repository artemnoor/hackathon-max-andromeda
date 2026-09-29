from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from andromeda.modules.proftest.contracts.public import ProfileScope, UserProfile, UserProfileSnapshot


def _timestamps() -> tuple[datetime, datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now, now, now + timedelta(days=30)


def test_profile_scope_accepts_only_a_sha256_session_reference() -> None:
    scope = ProfileScope(session_key_hash="a" * 64)

    assert scope.session_key_hash == "a" * 64
    assert scope.owner_key == "anonymous:" + "a" * 64
    assert scope.owner_kind == "anonymous"

    account_scope = ProfileScope(session_key_hash="a" * 64, account_id="account:" + "b" * 32)
    assert account_scope.owner_key == "account:" + "b" * 32
    assert account_scope.owner_kind == "account"

    with pytest.raises(ValidationError):
        ProfileScope(session_key_hash="raw-cookie-token")


def test_snapshot_is_strict_and_keeps_profile_storage_metadata_separate() -> None:
    created_at, updated_at, expires_at = _timestamps()
    snapshot = UserProfileSnapshot(
        profile_id="profile:" + "b" * 32,
        profile=UserProfile(),
        revision=1,
        created_at=created_at,
        updated_at=updated_at,
        expires_at=expires_at,
    )

    assert snapshot.profile.version == 1
    assert "revision" not in snapshot.profile.model_dump()

    with pytest.raises(ValidationError):
        UserProfileSnapshot(
            profile_id="profile:" + "b" * 32,
            profile=UserProfile(),
            revision=1,
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            unexpected="value",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision", 0),
        ("created_at", datetime.now()),
        ("expires_at", datetime.now(timezone.utc) - timedelta(seconds=1)),
    ],
)
def test_snapshot_rejects_invalid_revision_or_timestamp(field: str, value: object) -> None:
    created_at, updated_at, expires_at = _timestamps()
    values: dict[str, object] = {
        "profile_id": "profile:" + "c" * 32,
        "profile": UserProfile(),
        "revision": 1,
        "created_at": created_at,
        "updated_at": updated_at,
        "expires_at": expires_at,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        UserProfileSnapshot(**values)
